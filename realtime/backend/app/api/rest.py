"""REST endpoints: health, verse lookup, and debugging helpers."""

from __future__ import annotations

import os
import subprocess
import time
from functools import cache

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import BACKEND
from app.core.models import Reference
from app.detect.pipeline import detect
from app.detect.typed import parse_query

router = APIRouter(prefix="/api")


@cache
def detector_version() -> str:
    """LIVEVERSE_VERSION (set when the Docker image is built), else git describe."""
    if os.environ.get("LIVEVERSE_VERSION"):
        return os.environ["LIVEVERSE_VERSION"]
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


class DetectRequest(BaseModel):
    text: str
    mode: str = "spoken"
    spoken: str | None = None  # e.g. "jo 3:16"; context for relative mentions
    known_books: list[str] = []


@router.post("/detect")
def detect_text(request: Request, body: DetectRequest) -> dict:
    """Run detection on one text. For tests and debugging; the session is not touched."""
    if body.mode not in ("spoken", "typed"):
        raise HTTPException(status_code=400, detail="mode must be spoken or typed")
    try:
        spoken = Reference.parse(body.spoken) if body.spoken else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    mentions = detect(body.text, mode=body.mode, context=spoken, known_books=set(body.known_books))
    quotes = request.app.state.session.quotes
    quoted = quotes.find(body.text, spoken=spoken) if quotes else None
    return {
        "mentions": [
            {
                "ref": str(m.ref),
                "kind": m.kind,
                "source": "rule" if m.kind == "absolute" else "context",
                "confidence": m.confidence,
                "matched_text": m.matched_text,
                "span": list(m.span),
                "fuzzy_from": m.fuzzy_from,
                "superseded": m.superseded,
            }
            for m in mentions
        ],
        "quote": {"ref": str(quoted.ref), "source": "quote", "confidence": quoted.confidence}
        if quoted
        else None,
    }


@router.get("/session")
def session_state(request: Request) -> dict:
    return request.app.state.session.state()


@router.post("/session/reset")
def session_reset(request: Request) -> dict:
    request.app.state.session.reset()
    return {"status": "reset", "t": time.time()}


@router.get("/metrics/latency")
def latency_summary(request: Request) -> dict:
    """Today's latency per hop in milliseconds (p50, p95, max)."""
    return request.app.state.latency.summary()
