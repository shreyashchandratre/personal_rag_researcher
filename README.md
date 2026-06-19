# Personal RAG Researcher

A full-stack AI study assistant that lets you upload documents and chat with them using Retrieval-Augmented Generation (RAG). Supports local LLMs via Ollama with Cerebras as a cloud fallback.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![React](https://img.shields.io/badge/React-18-61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-5.6-blue)

## Features

- Upload PDFs, Word docs, images, and text files
- Chat with your documents using RAG
- Web search fallback via DuckDuckGo
- Persistent chat history per session
- Document management panel — view, track, and delete uploaded files
- Multi-file upload with per-file status tracking
- Local embeddings via HuggingFace (no API key needed for embeddings)
- Ollama (local LLM) + Cerebras (cloud fallback)
- Animated neural network hero UI

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python, FastAPI, LangChain, LangGraph |
| Vector Store | PostgreSQL + pgvector (Supabase) |
| Embeddings | HuggingFace `all-MiniLM-L6-v2` |
| LLM | Ollama (Mistral) + Cerebras fallback |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Infra | Docker, uvicorn |

## Getting Started

### 1. Clone the repo

```bash
git clone https://github.com/shreyashchandratre/personal_rag_researcher.git
cd personal_rag_researcher
```

### 2. Set up environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `CEREBRAS_API_KEY` — get from [cloud.cerebras.ai](https://cloud.cerebras.ai)
- `DATABASE_URL` — your PostgreSQL connection string (Supabase recommended)

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Build the frontend

```bash
cd frontend && npm install && npm run build && cd ..
```

### 5. Run the server

```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://127.0.0.1:8000`

## Docker

```bash
docker build -t personal-rag .
docker run --rm -p 8000:8000 --env-file .env personal-rag
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `CEREBRAS_API_KEY` | Recommended | Cerebras cloud LLM fallback |
| `OLLAMA_BASE_URL` | No | Ollama host (default: `http://localhost:11434`) |
| `USE_OLLAMA_EMBEDDINGS` | No | Use Ollama for embeddings instead of HuggingFace |
| `HF_EMBED_MODEL` | No | HuggingFace embedding model name |
| `MAX_UPLOAD_MB` | No | Max upload size in MB (default: 80) |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (default: `*`) |

## Supported File Types

`PDF` `DOCX` `DOC` `TXT` `MD` `PNG` `JPG` `JPEG` `WEBP`

## Project Structure

```
├── app.py                 # FastAPI server + API endpoints
├── agent_service.py       # LangGraph RAG agent
├── ingest.py              # Document ingestion pipeline
├── embeddings_factory.py  # HuggingFace / Ollama embeddings
├── chat_store.py          # PostgreSQL chat session store
├── frontend/
│   └── src/
│       ├── App.tsx        # Main chat UI
│       ├── DocumentPanel.tsx  # File upload & management panel
│       └── NeuralAnimation.tsx # Hero animation
├── Dockerfile
└── docker-compose.yml
```

## License

MIT
