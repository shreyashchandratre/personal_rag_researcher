"""Persistent chat sessions (LangChain message JSON on disk)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    BaseMessage,
    messages_from_dict,
    messages_to_dict,
)

from agent_service import _message_text, last_assistant_text

_BASE = Path(__file__).resolve().parent
CHAT_DIR = _BASE / "chat_history"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _session_path(session_id: str) -> Path:
    if not re.match(r"^[a-f0-9-]{36}$", session_id):
        raise ValueError("Invalid session id")
    return CHAT_DIR / f"{session_id}.json"


def load_messages(session_id: str) -> list[BaseMessage]:
    try:
        path = _session_path(session_id)
    except ValueError:
        return []
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("messages")
    if raw is None:
        return []
    return messages_from_dict(raw)


def save_messages(session_id: str, messages: list[BaseMessage]) -> None:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    path = _session_path(session_id)
    payload = {
        "version": 1,
        "session_id": session_id,
        "updated_at": _now_iso(),
        "messages": messages_to_dict(messages),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_session(session_id: str) -> None:
    try:
        path = _session_path(session_id)
    except ValueError:
        return
    if path.is_file():
        path.unlink()


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
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for path in sorted(CHAT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        sid = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        msgs_raw = data.get("messages") or []
        try:
            msgs = messages_from_dict(msgs_raw)
        except Exception:
            continue
        rows.append(
            {
                "session_id": sid,
                "title": session_title(msgs),
                "updated_at": data.get("updated_at") or _now_iso(),
                "preview": session_title(msgs),
            }
        )
    return rows


def new_session_id() -> str:
    return str(uuid.uuid4())
