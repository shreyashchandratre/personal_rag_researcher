"""
FastAPI server: chat API, session history, PDF upload, static SPA.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from agent_service import build_agent, last_assistant_text
from chat_store import (
    CHAT_DIR,
    delete_session,
    list_sessions_meta,
    load_messages,
    messages_for_ui,
    new_session_id,
    save_messages,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "frontend" / "dist"
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="Personal RAG Researcher", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_agent = None
_agent_lock = threading.Lock()
_ingest_lock = threading.Lock()

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "80")) * 1024 * 1024


def invalidate_agent():
    global _agent
    with _agent_lock:
        _agent = None


def get_agent():
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = build_agent()
        return _agent


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _normalize_session_id(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    sid = session_id.strip()
    if not _UUID_RE.match(sid):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    return sid.lower()


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=16000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


@app.get("/api/health")
def health():
    chroma_ok = (BASE_DIR / "chroma_db").exists()
    return {
        "status": "ok" if chroma_ok else "degraded",
        "chroma_ready": chroma_ok,
        "frontend_built": DIST_DIR.joinpath("index.html").is_file(),
    }


@app.get("/api/sessions")
def api_list_sessions():
    return {"sessions": list_sessions_meta()}


@app.post("/api/sessions")
def api_create_session():
    sid = new_session_id()
    save_messages(sid, [])
    return {"session_id": sid}


class SessionOut(BaseModel):
    session_id: str
    messages: list[dict[str, str]]


@app.get("/api/sessions/{session_id}", response_model=SessionOut)
def api_get_session(session_id: str):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    if not (CHAT_DIR / f"{sid}.json").is_file():
        raise HTTPException(status_code=404, detail="Session not found")
    lc = load_messages(sid)
    return SessionOut(session_id=sid, messages=messages_for_ui(lc))


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    if not (CHAT_DIR / f"{sid}.json").is_file():
        raise HTTPException(status_code=404, detail="Session not found")
    delete_session(sid)
    return {"ok": True}


@app.post("/api/session/reset")
def reset_session(session_id: str = Query(..., description="Session to clear")):
    """Remove persisted session (same as DELETE /api/sessions/{id})."""
    sid = _normalize_session_id(session_id)
    assert sid is not None
    if not (CHAT_DIR / f"{sid}.json").is_file():
        raise HTTPException(status_code=404, detail="Session not found")
    delete_session(sid)
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    if not (BASE_DIR / "chroma_db").exists():
        raise HTTPException(
            status_code=503,
            detail="Vector store missing. Upload a PDF here or run python ingest.py.",
        )

    sid = _normalize_session_id(body.session_id) if body.session_id else str(uuid.uuid4())

    messages = load_messages(sid)
    messages.append(HumanMessage(content=body.message.strip()))

    try:
        agent = get_agent()
        result = agent.invoke({"messages": messages})
    except Exception as e:
        logger.exception("Agent invoke failed")
        messages.pop()
        raise HTTPException(status_code=500, detail=str(e)) from e

    messages[:] = list(result.get("messages", messages))
    save_messages(sid, messages)

    reply = last_assistant_text(messages) or "(No text response.)"
    return ChatResponse(reply=reply, session_id=sid)


@app.post("/api/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    raw = file.filename.replace("\\", "/")
    name = Path(raw).name
    if name != file.filename and "/" in raw:
        raise HTTPException(status_code=400, detail="Invalid file name.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    dest = DATA_DIR / name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        dest = DATA_DIR / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )

    dest.write_bytes(body)

    try:
        with _ingest_lock:
            from ingest import rebuild_vector_index

            stats = rebuild_vector_index()
        invalidate_agent()
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Ingest failed after upload")
        raise HTTPException(status_code=500, detail=f"Indexing failed: {e}") from e

    return {
        "ok": True,
        "saved_as": dest.name,
        "pdf_count": stats["pdf_count"],
        "chunk_count": stats["chunk_count"],
    }


# --- Static frontend ---
assets_dir = DIST_DIR / "assets"
if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/")
async def spa_root():
    index = DIST_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Frontend not built. Run: cd frontend && npm install && npm run build",
            },
        )
    return FileResponse(index)


@app.get("/favicon.svg")
async def favicon_svg():
    p = DIST_DIR / "favicon.svg"
    if p.is_file():
        return FileResponse(p)
    return JSONResponse(status_code=404, content={})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
