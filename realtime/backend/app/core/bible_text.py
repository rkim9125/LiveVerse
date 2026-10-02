"""Load Bible text at runtime from the repo's data folder.

The text is never stored in the backend package or in Docker images:
  - $BIBLE_TEXT_PATH, if set
  - else data/bible_data.js (local translations, gitignored), if present
  - else data/sample/kjv.js (public-domain KJV, committed)

Both files hold window.BIBLE_DATA = {meta, books: [{a, c: [[ko[], en[]], ...]}]}.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
LOCAL = REPO / "data" / "bible_data.js"
SAMPLE = REPO / "data" / "sample" / "kjv.js"
_PREFIX = "window.BIBLE_DATA = "


@dataclass(frozen=True)
class BibleText:
    path: Path
    meta: dict
    books: dict[str, list[tuple[list[str], list[str]]]]  # abbrev -> chapters of (ko, en)

    @property
    def has_korean(self) -> bool:
        return any(ko for chapters in self.books.values() for ko, _ in chapters)

    @property
    def has_english(self) -> bool:
        return any(en for chapters in self.books.values() for _, en in chapters)


def default_path() -> Path:
    env = os.environ.get("BIBLE_TEXT_PATH")
    if env:
        return Path(env).expanduser()
    return LOCAL if LOCAL.exists() else SAMPLE


def load(path: Path | None = None) -> BibleText:
    path = path or default_path()
    raw = path.read_text(encoding="utf-8").strip()
    if not raw.startswith(_PREFIX):
        raise ValueError(f"{path} is not a BIBLE_DATA file")
    data = json.loads(raw[len(_PREFIX) :].rstrip(";"))
    books = {b["a"]: [(c[0], c[1]) for c in b["c"]] for b in data["books"]}
    return BibleText(path, data.get("meta", {}), books)
