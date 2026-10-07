"""FastAPI app for the realtime sermon assistant.

Run (from realtime/backend):
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import rest
from app.config import Settings
from app.core.store import BibleStore

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def create_app(settings: Settings | None = None, store: BibleStore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="LiveVerse realtime", version="0.2.0")
    app.state.settings = settings
    app.state.store = store or BibleStore.load(settings.bible_text_path)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.client.host if request.client else ""
        if not settings.allow_remote and host not in LOCAL_HOSTS:
            return JSONResponse({"detail": "localhost only"}, status_code=403)
        return await call_next(request)

    app.include_router(rest.router)
    return app


def __getattr__(name: str):
    # `uvicorn app.main:app` builds the app on first access, so importing this
    # module in tests does not load Bible text.
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
