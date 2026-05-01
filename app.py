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
import psycopg2
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "frontend" / "dist"

load_dotenv(BASE_DIR / ".env")

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from agent_service import build_agent, last_assistant_text
from chat_store import (
    delete_session,
    list_sessions_meta,
    load_messages,
    messages_for_ui,
    new_session_id,
    save_messages,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(db_url)

def init_doc_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Create table with session-scoped schema
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS document_files (
                        id SERIAL PRIMARY KEY,
                        session_id TEXT,
                        filename TEXT,
                        content BYTEA,
                        uploaded_at TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE(session_id, filename)
                    )
                """)
                # Migration: add session_id if table existed without it
                cur.execute("""
                    ALTER TABLE document_files
                    ADD COLUMN IF NOT EXISTS session_id TEXT
                """)
                # Migration: drop old unique constraint on filename alone if exists
                cur.execute("""
                    ALTER TABLE document_files
                    DROP CONSTRAINT IF EXISTS document_files_filename_key
                """)
                # Migration: add new composite unique constraint if not exists
                cur.execute("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'document_files_session_id_filename_key'
                        ) THEN
                            ALTER TABLE document_files
                            ADD CONSTRAINT document_files_session_id_filename_key
                            UNIQUE (session_id, filename);
                        END IF;
                    END $$;
                """)
            conn.commit()
    except Exception as e:
        print(f"Failed to init document DB: {e}")

init_doc_db()

app = FastAPI(title="Personal RAG Researcher", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ingest_lock = threading.Lock()

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "80")) * 1024 * 1024


def get_agent(session_id: str | None = None):
    """Build a fresh agent scoped to the session (no caching — fast enough)."""
    return build_agent(session_id=session_id)


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
    db_ok = True
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception:
        db_ok = False
        
    return {
        "status": "ok" if db_ok else "degraded",
        "chroma_ready": db_ok, # keep name for frontend compat
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
    lc = load_messages(sid)
    if not lc:
        # Just return empty if not found
        return SessionOut(session_id=sid, messages=[])
    return SessionOut(session_id=sid, messages=messages_for_ui(lc))


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    delete_session(sid)
    return {"ok": True}


@app.post("/api/session/reset")
def reset_session(session_id: str = Query(..., description="Session to clear")):
    """Remove persisted session."""
    sid = _normalize_session_id(session_id)
    assert sid is not None
    delete_session(sid)
    return {"ok": True}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest):
    sid = _normalize_session_id(body.session_id) if body.session_id else str(uuid.uuid4())

    messages = load_messages(sid)
    messages.append(HumanMessage(content=body.message.strip()))

    try:
        agent = get_agent(session_id=sid)
        result = agent.invoke({"messages": messages})
    except Exception as e:
        logger.exception("Agent invoke failed")
        messages.pop()
        raise HTTPException(status_code=500, detail=str(e)) from e

    messages[:] = list(result.get("messages", messages))
    save_messages(sid, messages)

    reply = last_assistant_text(messages) or "(No text response.)"
    return ChatResponse(reply=reply, session_id=sid)


# Allowed upload extensions (must stay in sync with ingest.py ALLOWED_EXTENSIONS)
_ALLOWED_UPLOAD_EXTS = {
    ".pdf", ".docx", ".doc",
    ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".webp",
}


@app.post("/api/upload")
async def upload_document(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    raw = file.filename.replace("\\", "/")
    name = Path(raw).name
    if name != file.filename and "/" in raw:
        raise HTTPException(status_code=400, detail="Invalid file name.")

    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_UPLOAD_EXTS))}"
            ),
        )

    # session_id is required for scoped uploads
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required for document upload.")
    sid = _normalize_session_id(session_id)
    assert sid is not None

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO document_files (session_id, filename, content)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id, filename) DO UPDATE
                        SET content = EXCLUDED.content, uploaded_at = NOW()
                """, (sid, name, psycopg2.Binary(body)))
            conn.commit()
    except Exception as e:
        logger.exception("Failed to save document to database")
        raise HTTPException(status_code=500, detail=str(e)) from e

    try:
        with _ingest_lock:
            from ingest import rebuild_vector_index
            stats = rebuild_vector_index(session_id=sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Ingest failed after upload")
        raise HTTPException(status_code=500, detail=f"Indexing failed: {e}") from e

    return {
        "ok": True,
        "saved_as": name,
        "session_id": sid,
        "file_count": stats["pdf_count"],  # renamed internally but keep compat key
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
