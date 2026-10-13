# syntax=docker/dockerfile:1.7
FROM pandoc/core:3.12.1-debian AS pandoc
FROM ghcr.io/astral-sh/uv:0.12.24 AS uv
FROM python:3.13.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PAPER_QA_ROOT=/data/papers \
    PAPER_QA_HOST=0.0.0.0 \
    PAPER_QA_PORT=8010 \
    PAPER_QA_TRANSPORT=http

COPY --from=uv /uv /uvx /bin/
COPY --from=pandoc /usr/local/bin/pandoc /usr/local/bin/pandoc

RUN groupadd --system --gid 10001 paperqa \
    && useradd --system --uid 10001 --gid paperqa --home-dir /app paperqa \
    && mkdir -p /app /data/papers \
    && chown -R paperqa:paperqa /app /data/papers

WORKDIR /app
COPY --chown=paperqa:paperqa pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=paperqa:paperqa src ./src
RUN uv sync --frozen --no-dev

USER 10001:10001
EXPOSE 8010
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import socket; s=socket.create_connection(('127.0.0.1',8010),3); s.close()"]
CMD ["/app/.venv/bin/paper-qa-mcp"]

