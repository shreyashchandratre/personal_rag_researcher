"""
Load PDFs from the local `data` directory, chunk them, embed, and persist to Chroma.
Replaces any existing `chroma_db` on each run (full rebuild).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from embeddings_factory import get_embeddings

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = BASE_DIR / "chroma_db"


def _load_pdf(path: Path) -> list[Document]:
    """Prefer PyMuPDF (handles many academic PDFs better); fall back to PyPDFLoader."""
    try:
        from langchain_community.document_loaders import PyMuPDFLoader
    except ImportError:
        return PyPDFLoader(str(path)).load()
    try:
        return PyMuPDFLoader(str(path)).load()
    except Exception:
        return PyPDFLoader(str(path)).load()


def rebuild_vector_index() -> dict[str, int]:
    """
    Full rebuild of Chroma from all `data/*.pdf`.
    Raises ValueError if no PDFs or no extractable text.
    """
    load_dotenv(BASE_DIR / ".env")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    pdf_paths = sorted(DATA_DIR.glob("*.pdf"))
    if not pdf_paths:
        raise ValueError("No PDF files in the data folder. Add at least one .pdf file.")

    docs: list[Document] = []
    for path in pdf_paths:
        try:
            docs.extend(_load_pdf(path))
        except Exception as e:
            print(f"Warning: could not load {path.name}: {e}", file=sys.stderr)

    if not docs:
        raise ValueError("No text could be extracted from any PDF. Check that files are valid.")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    splits = splitter.split_documents(docs)
    embeddings = get_embeddings()

    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory=str(CHROMA_DIR),
    )
    return {"pdf_count": len(pdf_paths), "chunk_count": len(splits)}


def main() -> None:
    try:
        out = rebuild_vector_index()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    print(
        f"Ingested {out['chunk_count']} chunks from {out['pdf_count']} PDF(s) into {CHROMA_DIR}"
    )


if __name__ == "__main__":
    main()
