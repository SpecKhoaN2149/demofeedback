# syntax=docker/dockerfile:1

# ─── Stage 1: build the React/Vite frontend ─────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build/frontend

# Install deps first (better layer caching).
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# Build the production bundle into /build/frontend/dist.
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: python backend that also serves the built frontend ────────────
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Backend Python dependencies + the Gemini SDK used by the NLP pipeline.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir "google-genai" "python-dotenv"

# Application code. The layout is preserved so the backend can import the
# repo-root `nlp_processing` package (it adds the parent of backend/ to sys.path).
COPY backend/ ./backend/
COPY nlp_processing/ ./nlp_processing/

# Built frontend from stage 1 → served by FastAPI at runtime.
COPY --from=frontend /build/frontend/dist ./frontend/dist

# Persistent SQLite lives on a mounted disk in production (see DEPLOY.md).
ENV SUBMISSIONS_DB_PATH=/data/submissions.db

WORKDIR /app/backend
EXPOSE 8000

# Render provides $PORT; default to 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
