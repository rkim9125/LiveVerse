"""REST endpoints: health, verse lookup, and debugging helpers."""

from __future__ import annotations

import subprocess
from functools import cache

from fastapi import APIRouter, HTTPException, Query, Request

from app.config import BACKEND
from app.detect.typed import parse_query

router = APIRouter(prefix="/api")


@cache
def detector_version() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(BACKEND), "describe", "--tags", "--always", "--dirty"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


@router.get("/health")
def health(request: Request) -> dict:
    app = request.app
    return {
        "status": "ok",
        "data": app.state.store.info(),
        "quote_search": app.state.settings.quote_search,
        "show_threshold": app.state.settings.show_threshold,
        "detector": detector_version(),
    }


@router.get("/verses")
def verses(request: Request, ref: str = Query(..., description="e.g. John 3:16-18 or 요 3:16")):
    try:
        parsed = parse_query(ref)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store = request.app.state.store
    return {
        "ref": str(parsed),
        "label": store.label(parsed),
        "names": store.names,
        "verses": [v.__dict__ for v in store.verses(parsed)],
    }
