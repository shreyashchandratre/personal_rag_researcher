# Deploying Personal RAG Researcher

## What you are deploying

- **FastAPI** (`app.py`) serves the **REST API** (`/api/chat`, `/api/health`) and the **built React UI** from `frontend/dist`.
- **Ollama** and **Chroma** are not inside the container by default: you point the app at Ollama with `OLLAMA_BASE_URL`, and you provide a **`chroma_db`** directory (volume or baked-in from `python ingest.py`).

## Local web (development)

Terminal 1 — API (serves UI after build):

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
uvicorn app:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — optional: edit UI with hot reload (proxies `/api` to port 8000):

```bash
cd frontend && npm run dev
```

Then open the Vite URL (e.g. `http://localhost:5173`) or `http://127.0.0.1:8000` after a production build.

## Docker

Build:

```bash
docker build -t personal-rag .
```

Run (mount your index and env; Ollama on the host at port 11434):

```bash
docker run --rm -p 8000:8000 \
  --env-file .env \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -v "%cd%\chroma_db:/app/chroma_db" \
  personal-rag
```

On Linux, replace `host.docker.internal` with your host IP or add `--add-host=host.docker.internal:host-gateway`.

Copy PDFs into `data/`, run **`python ingest.py`** on the host (or in a one-off container with the same volume layout) so `chroma_db` exists before or after the container starts.

## Cloud (Railway, Render, Fly.io, etc.)

1. Set **environment variables** from `.env`: at minimum `CEREBRAS_API_KEY` if Ollama is not reachable; embedding and Chroma paths as you use them.
2. **`OLLAMA_BASE_URL`**: must be a URL your container can reach (another service, tunnel, or omit if you rely only on Cerebras — you would still need a running vector store).
3. **Persistence**: attach a **volume** for `chroma_db` (and optionally `data`) or run **ingest** in CI / release command once models and PDFs are available.
4. **Sessions**: chat sessions are stored **in memory** on one process. For multiple replicas, use sticky sessions or add Redis-backed sessions later.
5. **Build**: use the provided **Dockerfile** (builds the frontend inside the image) or run `npm run build` in CI and copy `frontend/dist` into the Python image.

## Production checklist

- [ ] `python ingest.py` has produced `chroma_db/` for production PDFs.
- [ ] `CEREBRAS_API_KEY` set if Ollama can fail or is unavailable.
- [ ] `CORS_ORIGINS` set to your real front-end origin if the UI is on another domain (comma-separated). Default `*` is convenient for demos only.
- [ ] `PORT` / `HOST` match your platform (many set `PORT` automatically).
