from functools import cache

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core import bible_text
from app.core.store import BibleStore
from app.main import create_app


@cache
def kjv_store() -> BibleStore:
    """The public-domain KJV sample, so tests never need copyrighted text."""
    return BibleStore.load(bible_text.SAMPLE)


@pytest.fixture
def store() -> BibleStore:
    return kjv_store()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(bible_text_path=bible_text.SAMPLE, log_dir=tmp_path / "logs")


@pytest.fixture
def client(settings, store) -> TestClient:
    return TestClient(create_app(settings, store))
