"""
FastAPI server: chat API, session history, document upload/management, static SPA.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
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
                cur.execute("""
                    ALTER TABLE document_files
                    ADD COLUMN IF NOT EXISTS session_id TEXT
                """)
                cur.execute("""
                    ALTER TABLE document_files
                    DROP CONSTRAINT IF EXISTS document_files_filename_key
                """)
                # Document registry — tracks each upload with status + chunk count
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS document_registry (
                        id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        file_size INTEGER NOT NULL DEFAULT 0,
                        chunk_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'processing',
                        uploaded_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_doc_registry_session
                    ON document_registry (session_id)
                """)
            conn.commit()
    except Exception as e:
        print(f"Failed to init document DB: {e}")


init_doc_db()

app = FastAPI(title="Personal RAG Researcher", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ingest_lock = threading.Lock()

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "80")) * 1024 * 1024

_ALLOWED_UPLOAD_EXTS = {
    ".pdf", ".docx", ".doc",
    ".txt", ".md",
    ".png", ".jpg", ".jpeg", ".webp",
}

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


def get_agent(session_id: str | None = None):
    return build_agent(session_id=session_id)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=16000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


class DocumentOut(BaseModel):
    id: str
    session_id: str
    filename: str
    file_size: int
    chunk_count: int
    status: str
    uploaded_at: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

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
        "chroma_ready": db_ok,
        "frontend_built": DIST_DIR.joinpath("index.html").is_file(),
    }


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

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
        return SessionOut(session_id=sid, messages=[])
    return SessionOut(session_id=sid, messages=messages_for_ui(lc))


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    delete_session(sid)
    return {"ok": True}


@app.post("/api/session/reset")
def reset_session(session_id: str = Query(...)):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    delete_session(sid)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Document registry endpoints
# ---------------------------------------------------------------------------

@app.get("/api/documents", response_model=list[DocumentOut])
def list_documents(session_id: str = Query(...)):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, session_id, filename, file_size, chunk_count, status,
                           uploaded_at
                    FROM document_registry
                    WHERE session_id = %s
                    ORDER BY uploaded_at DESC
                    """,
                    (sid,),
                )
                rows = cur.fetchall()
        return [
            DocumentOut(
                id=r["id"],
                session_id=r["session_id"],
                filename=r["filename"],
                file_size=r["file_size"],
                chunk_count=r["chunk_count"],
                status=r["status"],
                uploaded_at=r["uploaded_at"].isoformat(),
            )
            for r in rows
        ]
    except Exception as e:
        logger.exception("Failed to list documents")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/documents/{doc_id}/status")
def get_document_status(doc_id: str, session_id: str = Query(...)):
    sid = _normalize_session_id(session_id)
    assert sid is not None
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, status, chunk_count FROM document_registry WHERE id = %s AND session_id = %s",
                    (doc_id, sid),
                )
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"id": row["id"], "status": row["status"], "chunk_count": row["chunk_count"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, session_id: str = Query(...)):
    """Remove a document's vectors from PGVector and its registry entry."""
    sid = _normalize_session_id(session_id)
    assert sid is not None

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise HTTPException(status_code=500, detail="DATABASE_URL not set")

    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT id, filename FROM document_registry WHERE id = %s AND session_id = %s",
                    (doc_id, sid),
                )
                row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found")

        # Delete vectors tagged with this doc_id from PGVector
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM langchain_pg_embedding
                    WHERE collection_id IN (
                        SELECT uuid FROM langchain_pg_collection WHERE name = 'rag_docs'
                    )
                    AND cmetadata->>'doc_id' = %s
                    """,
                    (doc_id,),
                )
                deleted_vectors = cur.rowcount

            # Remove from document_files
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_files WHERE session_id = %s AND filename = %s",
                    (sid, row["filename"]),
                )
            # Remove registry entry
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM document_registry WHERE id = %s",
                    (doc_id,),
                )
            conn.commit()

        logger.info("Deleted doc %s (%s vectors removed)", doc_id, deleted_vectors)
        return {"ok": True, "vectors_removed": deleted_vectors}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete document %s", doc_id)
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Upload (single or multi-file)
# ---------------------------------------------------------------------------

async def _ingest_one(
    file: UploadFile,
    sid: str,
) -> dict:
    """Process one file: save to DB, ingest to vector store, update registry."""
    if not file.filename:
        return {"filename": "", "ok": False, "error": "No filename"}

    raw = file.filename.replace("\\", "/")
    name = Path(raw).name
    ext = Path(name).suffix.lower()

    if ext not in _ALLOWED_UPLOAD_EXTS:
        return {
            "filename": name,
            "ok": False,
            "error": f"Unsupported type '{ext}'",
        }

    body = await file.read()
    if len(body) > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return {"filename": name, "ok": False, "error": f"File too large (max {max_mb} MB)"}

    doc_id = str(uuid.uuid4())

    # Write registry entry (status=processing)
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_registry (id, session_id, filename, file_size, status)
                    VALUES (%s, %s, %s, %s, 'processing')
                    ON CONFLICT DO NOTHING
                    """,
                    (doc_id, sid, name, len(body)),
                )
            conn.commit()
    except Exception as e:
        return {"filename": name, "ok": False, "error": f"Registry write failed: {e}"}

    # Store raw file in document_files
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO document_files (session_id, filename, content)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (session_id, filename) DO UPDATE
                        SET content = EXCLUDED.content, uploaded_at = NOW()
                    """,
                    (sid, name, psycopg2.Binary(body)),
                )
            conn.commit()
    except Exception as e:
        _mark_registry(doc_id, "failed", 0)
        return {"filename": name, "ok": False, "error": f"Storage failed: {e}"}

    # Ingest into vector store (tagged with doc_id for future deletion)
    try:
        with _ingest_lock:
            from ingest import ingest_document_bytes
            chunk_count = ingest_document_bytes(
                file_bytes=body,
                filename=name,
                session_id=sid,
                doc_id=doc_id,
            )
        _mark_registry(doc_id, "ready", chunk_count)
        return {"filename": name, "ok": True, "doc_id": doc_id, "chunk_count": chunk_count}
    except Exception as e:
        logger.exception("Ingest failed for %s", name)
        _mark_registry(doc_id, "failed", 0)
        return {"filename": name, "ok": False, "error": f"Indexing failed: {e}"}


def _mark_registry(doc_id: str, status: str, chunk_count: int) -> None:
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE document_registry SET status = %s, chunk_count = %s WHERE id = %s",
                    (status, chunk_count, doc_id),
                )
            conn.commit()
    except Exception as e:
        logger.warning("Could not update registry for %s: %s", doc_id, e)


@app.post("/api/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    session_id: str | None = Form(None),
):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required.")
    sid = _normalize_session_id(session_id)
    assert sid is not None

    results = []
    for f in files:
        result = await _ingest_one(f, sid)
        results.append(result)

    any_ok = any(r["ok"] for r in results)
    return {"ok": any_ok, "results": results}


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------

assets_dir = DIST_DIR / "assets"
if assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/")
async def spa_root():
    index = DIST_DIR / "index.html"
    if not index.is_file():
        return JSONResponse(
            status_code=503,
            content={"detail": "Frontend not built. Run: cd frontend && npm install && npm run build"},
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
