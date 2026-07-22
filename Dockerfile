# WisdomAI MVP — container image for Google Cloud Run (or any container host).
#
# Base is python:3.12-slim (stable, well-supported by every pinned dep; the app
# uses no 3.13/3.14-only syntax). Local dev may be on 3.14 — the container is the
# source of truth for what actually ships, so pin it here, not on the dev machine.
FROM python:3.12-slim

# Fail fast, no .pyc, unbuffered logs (so Cloud Run captures stdout immediately).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Install dependencies first (separate layer → cached across code-only changes).
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the application. .dockerignore keeps out .venv/.git/caches/scratch.
COPY . .

# Run as a non-root user (Cloud Run best practice; also avoids root-owned volumes).
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Cloud Run injects $PORT (default 8080). Shell form so ${PORT} expands at runtime.
# Single worker: the app's background jobs + on-disk job store assume one process;
# scale out with Cloud Run instances, not in-container workers.
EXPOSE 8080
CMD exec uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}
