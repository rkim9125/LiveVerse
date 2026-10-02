#!/usr/bin/env python3
"""Build data/sample/kjv.js from the public-domain eBible.org KJV.

Usage:
    python3 scripts/build_sample.py                     # downloads eng-kjv_vpl.zip
    python3 scripts/build_sample.py path/to/eng-kjv_vpl.zip

Source: https://ebible.org/Scriptures/eng-kjv_vpl.zip (KJV 1769, Public Domain).
Apocrypha books in the source are skipped; only the 66-book canon is kept.
"""

import io
import os
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from books import BOOKS, write_data_js  # noqa: E402

SOURCE_URL = "https://ebible.org/Scriptures/eng-kjv_vpl.zip"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "sample", "kjv.js")

LINE_RE = re.compile(r"^(\w{3}) (\d+):(\d+) (.*)$")


def clean(text):
    # [word] marks words supplied by the translators (printed in italics);
    # keep the word, drop the brackets. ¶ is a paragraph marker.
    text = text.replace("[", "").replace("]", "").replace("¶", "")
    return re.sub(r"\s+", " ", text).strip()


def read_vpl(src):
    if src is None:
        print("Downloading", SOURCE_URL)
        data = urllib.request.urlopen(SOURCE_URL).read()
    else:
        with open(src, "rb") as f:
            data = f.read()
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = next(n for n in z.namelist() if n.endswith("_vpl.txt"))
            data = z.read(name)
    return data.decode("utf-8-sig").splitlines()


def main():
    lines = read_vpl(sys.argv[1] if len(sys.argv) > 1 else None)
    code_to_book = {code: (a, en, ko) for a, en, ko, code in BOOKS}
    chapters = {a: [] for a, _, _, _ in BOOKS}

    for line in lines:
        m = LINE_RE.match(line)
        if not m:
            continue
        code, ch, v, text = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
        if code not in code_to_book:
            continue  # apocrypha
        chs = chapters[code_to_book[code][0]]
        while len(chs) < ch:
            chs.append([])
        verses = chs[ch - 1]
        if len(verses) != v - 1:
            raise SystemExit(f"Unexpected verse order at {code} {ch}:{v}")
        verses.append(clean(text))

    books = []
    for a, en, ko, _ in BOOKS:
        if not chapters[a]:
            raise SystemExit(f"Missing book {en}")
        # Same schema as the local data: each chapter is [ko_verses, en_verses].
        books.append({"a": a, "en": en, "ko": ko, "c": [[[], vs] for vs in chapters[a]]})

    meta = {
        "title": "KJV",
        "langs": ["en"],
        "names": {"en": "KJV"},
        "demo": True,
        "source": "eBible.org eng-kjv (KJV 1769), Public Domain",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    write_data_js(OUT, meta, books)
    n_ch = sum(len(b["c"]) for b in books)
    n_v = sum(len(c[1]) for b in books for c in b["c"])
    print(f"Wrote {OUT}: {len(books)} books, {n_ch} chapters, {n_v} verses")


if __name__ == "__main__":
    main()
