"""Shared RAG agent construction for CLI and web API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langgraph.prebuilt import create_react_agent
from langchain_postgres.vectorstores import PGVector
from langchain_classic.chains import RetrievalQA
from langchain_cerebras import ChatCerebras
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from embeddings_factory import get_embeddings

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _message_text(message: AIMessage | object) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            # skip tool_use blocks entirely
        return "".join(parts)
    return str(content)


def _has_tool_calls(message: object) -> bool:
    """Return True if this AI message is a pure tool-call with no text."""
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        text = _message_text(message).strip()
        return not text
    return False


def build_chat_llm():
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    primary = ChatOllama(
        model="mistral",
        base_url=base_url,
        temperature=0,
    )
    key = (os.environ.get("CEREBRAS_API_KEY") or "").strip()
    if not key:
        print(
            "[warn] CEREBRAS_API_KEY is empty. Set it in .env for Cerebras fallback when Ollama fails.",
            file=sys.stderr,
        )
        return primary

    fallback = ChatCerebras(
        model="llama3.1-8b",
        temperature=0,
        api_key=key,
    )
    return primary.with_fallbacks([fallback])


def load_vectorstore(session_id: str | None = None) -> PGVector:
    """Load the PGVector store, optionally filtering by session_id."""
    embeddings = get_embeddings()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL must be set in .env")

    vs = PGVector(
        embeddings=embeddings,
        collection_name="rag_docs",
        connection=db_url,
        use_jsonb=True,
    )
    return vs


def build_agent(session_id: str | None = None):
    """Create LangGraph ReAct agent scoped to a session's PDFs + web search."""
    vs = load_vectorstore(session_id)

    # Build metadata filter so retriever only sees this session's chunks
    search_kwargs: dict = {"k": 4}
    if session_id:
        search_kwargs["filter"] = {"session_id": session_id}

    retriever = vs.as_retriever(search_kwargs=search_kwargs)
    llm = build_chat_llm()
    qa = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=False,
    )

    @tool
    def search_documents(query: str) -> str:
        """Search the PDFs uploaded in this chat session for relevant information. Prefer this for questions about your uploaded documents."""
        result = qa.invoke({"query": query})
        return str(result.get("result", result))

    ddg = DuckDuckGoSearchRun()

    @tool
    def web_search(query: str) -> str:
        """Search the public web for recent or general knowledge when documents are insufficient or the question is outside local files."""
        return str(ddg.invoke(query))

    system_prompt = (
        "You are a powerful personal research assistant. "
        "You have access to documents uploaded in this chat session (PDFs, Word docs, images, text files) via 'search_documents'. "
        "You have access to the public internet via 'web_search'. "
        "ALWAYS use 'search_documents' when the user asks about something from an uploaded file. "
        "ALWAYS use 'web_search' when you need current facts, news, or information not in the documents. "
        "After using a tool, synthesize the results into a clear, well-structured, human-friendly answer. "
        "Cite whether information came from the uploaded documents or the web. "
        "Be thorough and precise — this is a research tool."
    )

    return create_react_agent(
        model=llm,
        tools=[search_documents, web_search],
        prompt=system_prompt,
    )


def last_assistant_text(messages: list) -> str | None:
    """Return the last AI text message, skipping pure tool-call messages."""
    for m in reversed(messages):
        is_ai = isinstance(m, AIMessage) or getattr(m, "type", None) == "ai"
        if is_ai and not _has_tool_calls(m):
            text = _message_text(m).strip()
            if text:
                return text
    return None


def ensure_env_loaded() -> None:
    load_dotenv(BASE_DIR / ".env")
