"""Shared RAG agent construction for CLI and web API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_chroma import Chroma
from langchain_classic.chains import RetrievalQA
from langchain_cerebras import ChatCerebras
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from embeddings_factory import get_embeddings

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"


def _message_text(message: AIMessage | object) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content)


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


def load_vectorstore() -> Chroma:
    embeddings = get_embeddings()
    if not CHROMA_DIR.exists():
        raise FileNotFoundError(
            f"Missing vector store at {CHROMA_DIR}. Run: python ingest.py "
            f"(with PDFs in {DATA_DIR} and Ollama running)."
        )
    return Chroma(
        persist_directory=str(CHROMA_DIR),
        embedding_function=embeddings,
    )


def build_agent():
    """Create LangGraph agent (retrieval QA + web search)."""
    vs = load_vectorstore()
    retriever = vs.as_retriever(search_kwargs={"k": 4})
    llm = build_chat_llm()
    qa = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=retriever,
        return_source_documents=False,
    )

    @tool
    def search_documents(query: str) -> str:
        """Search ingested local PDFs for relevant information. Prefer this for questions about your uploaded documents."""
        result = qa.invoke({"query": query})
        return str(result.get("result", result))

    ddg = DuckDuckGoSearchRun()

    @tool
    def web_search(query: str) -> str:
        """Search the public web for recent or general knowledge when documents are insufficient or the question is outside local files."""
        return str(ddg.invoke(query))

    system_prompt = (
        "You are a powerful research assistant. You DO have access to local PDF files and documents via your 'search_documents' tool. "
        "You DO have access to the public internet via your 'web_search' tool. "
        "CRITICAL INSTRUCTION: NEVER say you don't have access to files, local storage, or the internet. "
        "If the user asks about a document, PDF, or uploaded file, ALWAYS use the 'search_documents' tool to read it. "
        "If you need outside facts, ALWAYS use the 'web_search' tool. "
        "Cite whether information came from documents or the web when it matters."
    )

    return create_agent(
        model=llm,
        tools=[search_documents, web_search],
        system_prompt=system_prompt,
    )


def last_assistant_text(messages: list) -> str | None:
    for m in reversed(messages):
        if isinstance(m, AIMessage) or getattr(m, "type", None) == "ai":
            return _message_text(m)
    return None


def ensure_env_loaded() -> None:
    load_dotenv(BASE_DIR / ".env")
