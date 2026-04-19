"""Shared embedding setup: defaults to local Hugging Face models so ingest works without Ollama embed models."""

from __future__ import annotations

import os

from langchain_core.embeddings import Embeddings


def get_embeddings() -> Embeddings:
    use_ollama = os.environ.get("USE_OLLAMA_EMBEDDINGS", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if use_ollama:
        from langchain_ollama import OllamaEmbeddings

        return OllamaEmbeddings(
            model=os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        )

    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name=os.environ.get(
            "HF_EMBED_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ),
        model_kwargs={"device": os.environ.get("HF_EMBED_DEVICE", "cpu")},
        encode_kwargs={"normalize_embeddings": True},
    )
