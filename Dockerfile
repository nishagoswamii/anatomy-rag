# Backend image. Builds the search index and downloads model weights at build
# time, so the container starts with no network downloads.
#
#   docker build -t anatomy-rag .
#   docker run -p 7860:7860 -e ANTHROPIC_API_KEY=... anatomy-rag

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# Hugging Face Spaces runs containers as uid 1000.
RUN useradd -m -u 1000 user
WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock backend/
RUN cd backend && uv sync --frozen --no-default-groups

COPY backend/app backend/app
COPY data/chunks.jsonl data/chunks.jsonl
RUN cd backend && .venv/bin/python -m app.index && chown -R user:user /app

USER user
ENV RAG_TRUST_PROXY_HEADERS=true \
    HF_HUB_OFFLINE=1
EXPOSE 7860
WORKDIR /app/backend
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers"]
