# LiveVerse realtime backend.
# Bible text is never copied into the image: mount the repo's data/ folder at
# /srv/data (read only). The app finds data/bible_data.js there, or falls back
# to data/sample/kjv.js.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/venv \
    PATH="/srv/venv/bin:$PATH"

WORKDIR /srv/realtime/backend
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app

ARG VERSION=unknown
ENV LIVEVERSE_VERSION=${VERSION} \
    LIVEVERSE_LOG_DIR=/srv/logs

RUN useradd --system --uid 10001 liveverse \
    && mkdir -p /srv/logs /srv/data \
    && chown liveverse /srv/logs
USER liveverse

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
