FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg is required by faster-whisper for decoding.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --upgrade pip && pip install .

# Run as a non-root user; the data dir must be writable by it.
RUN useradd --create-home --uid 10001 sada \
    && mkdir -p /app/data/uploads \
    && chown -R sada:sada /app
USER sada

ENV UPLOAD_DIR=/app/data/uploads \
    DATABASE_URL=sqlite:////app/data/sada.db \
    HF_HOME=/home/sada/.cache/huggingface

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
