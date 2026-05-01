"""Persistent chat sessions (PostgreSQL)."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from langchain_core.messages import (
    BaseMessage,
    messages_from_dict,
    messages_to_dict,
)

from agent_service import _message_text, last_assistant_text

def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    return psycopg2.connect(db_url)

def init_db():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                        session_id UUID PRIMARY KEY,
                        title TEXT,
                        updated_at TIMESTAMPTZ DEFAULT NOW(),
                        messages JSONB DEFAULT '[]'::jsonb
                    )
                """)
            conn.commit()
    except Exception as e:
        print(f"Failed to init chat DB: {e}")

# Initialize DB tables on import
init_db()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_messages(session_id: str) -> list[BaseMessage]:
    if not re.match(r"^[a-f0-9-]{36}$", session_id):
        return []
        
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT messages FROM chat_sessions WHERE session_id = %s", (session_id,))
                row = cur.fetchone()
                if row and row[0]:
                    return messages_from_dict(row[0])
    except Exception as e:
        print(f"Error loading messages: {e}")
    return []

def save_messages(session_id: str, messages: list[BaseMessage]) -> None:
    if not re.match(r"^[a-f0-9-]{36}$", session_id):
        return
        
    msgs_dict = messages_to_dict(messages)
    title = session_title(messages)
    
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chat_sessions (session_id, title, updated_at, messages)
                    VALUES (%s, %s, NOW(), %s)
                    ON CONFLICT (session_id) 
                    DO UPDATE SET title = EXCLUDED.title, updated_at = NOW(), messages = EXCLUDED.messages
                """, (session_id, title, json.dumps(msgs_dict)))
            conn.commit()
    except Exception as e:
        print(f"Error saving messages: {e}")

def delete_session(session_id: str) -> None:
    if not re.match(r"^[a-f0-9-]{36}$", session_id):
        return
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_sessions WHERE session_id = %s", (session_id,))
            conn.commit()
    except Exception as e:
        print(f"Error deleting session: {e}")

def session_title(messages: list[BaseMessage]) -> str:
    for m in messages:
        if getattr(m, "type", None) == "human":
            t = _message_text(m).strip()
            if t:
                return (t[:72] + "…") if len(t) > 72 else t
    return "New chat"

def messages_for_ui(lc_messages: list[BaseMessage]) -> list[dict[str, str]]:
    """Pairs of user/assistant bubbles; skips tool/system noise for display."""
    out: list[dict[str, str]] = []
    for m in lc_messages:
        role = getattr(m, "type", None)
        if role == "human":
            out.append({"role": "user", "content": _message_text(m)})
        elif role == "ai":
            txt = last_assistant_text([m])
            if txt and str(txt).strip():
                out.append({"role": "assistant", "content": txt})
    return out

def list_sessions_meta() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT session_id, title, updated_at FROM chat_sessions ORDER BY updated_at DESC")
                for row in cur.fetchall():
                    sid = str(row['session_id'])
                    title = row['title'] or "New chat"
                    updated_at = row['updated_at'].isoformat() if row['updated_at'] else _now_iso()
                    
                    rows.append({
                        "session_id": sid,
                        "title": title,
                        "updated_at": updated_at,
                        "preview": title,
                    })
    except Exception as e:
        print(f"Error listing sessions: {e}")
    return rows

def new_session_id() -> str:
    return str(uuid.uuid4())
