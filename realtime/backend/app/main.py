"""FastAPI app for the realtime sermon assistant.

Run (from realtime/backend):
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from functools import cache

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import rest, ws
from app.config import BACKEND, Settings
from app.core.latency import LatencyLog
from app.core.session import Session
from app.core.store import BibleStore
from app.detect.quotes import QuoteIndex

FRONTEND = BACKEND.parent / "frontend"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


@cache
def _quote_index(store: BibleStore) -> QuoteIndex:
    """Built once per loaded text (a second or two for the whole Bible)."""
    return QuoteIndex(store.text)


def create_app(settings: Settings | None = None, store: BibleStore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="LiveVerse realtime", version="0.2.0")
    app.state.settings = settings
    app.state.store = store or BibleStore.load(settings.bible_text_path)
    quotes = _quote_index(app.state.store) if settings.quote_search else None
    app.state.session = Session(app.state.store, settings, quotes=quotes)
    app.state.hub = ws.Hub()
    app.state.latency = LatencyLog(settings.log_dir)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.client.host if request.client else ""
        if not settings.allow_remote and host not in LOCAL_HOSTS:
            return JSONResponse({"detail": "localhost only"}, status_code=403)
        return await call_next(request)

    app.include_router(rest.router)
    app.include_router(ws.router)
    if FRONTEND.is_dir():
        # Same origin as the API, so the page counts as a secure context on localhost
        # (needed for the microphone) and can open the WebSocket without CORS.
        app.mount("/ui", StaticFiles(directory=FRONTEND, html=True), name="ui")
    return app


def __getattr__(name: str):
    # `uvicorn app.main:app` builds the app on first access, so importing this
    # module in tests does not load Bible text.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
