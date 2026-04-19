# Build frontend, then run API + serve static assets.
# Build: docker build -t personal-rag .
# Run:  docker run --env-file .env -p 8000:8000 -v ./chroma_db:/app/chroma_db personal-rag

FROM node:22-bookworm-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY embeddings_factory.py agent_service.py app.py ingest.py main.py ./
COPY --from=frontend /fe/dist ./frontend/dist

ENV HOST=0.0.0.0
ENV PORT=8000
EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
