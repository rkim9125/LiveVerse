#!/usr/bin/env python3
"""Generate app/detect/versification.json from the public-domain KJV sample.

Only chapter and verse counts are written, never verse text.

Usage (from realtime/backend):
    uv run python scripts/gen_versification.py
"""

import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parents[1]
SOURCE = REPO / "data" / "sample" / "kjv.js"
OUT = BACKEND / "app" / "detect" / "versification.json"
PREFIX = "window.BIBLE_DATA = "


def main() -> None:
    raw = SOURCE.read_text(encoding="utf-8").strip()
    data = json.loads(raw[len(PREFIX) :].rstrip(";"))
    counts = {book["a"]: [len(chapter[1]) for chapter in book["c"]] for book in data["books"]}
    lines = [f'  "{abbrev}": {json.dumps(verses)}' for abbrev, verses in counts.items()]
    OUT.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")
    total = sum(sum(v) for v in counts.values())
    print(f"Wrote {OUT.relative_to(REPO)}: {len(counts)} books, {total} verses")


if __name__ == "__main__":
    main()
