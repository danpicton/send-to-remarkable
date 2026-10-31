FROM ghcr.io/astral-sh/uv:0.6.9 AS uv
FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 reader \
    && useradd --uid 10001 --gid reader --no-create-home reader \
    && mkdir -p /tmp/send-to-remarkable && chown reader:reader /tmp/send-to-remarkable
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY app /app/app
COPY LICENSE README.md pyproject.toml uv.lock /app/
LABEL org.opencontainers.image.title="Send to reMarkable" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/tmp/send-to-remarkable
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read()"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "16"]
