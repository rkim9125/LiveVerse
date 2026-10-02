#!/usr/bin/env python3
"""Build data/bible_data.js from Bible data you are licensed to use.

The output is gitignored and must never be committed.

Usage:
    # From a combined file in the app schema: [{a, en, ko, c: [[ko[], en[]], ...]}, ...]
    python3 scripts/build_data.py --combined bible_data.json

    # From two separate files: [{abbrev, chapters: [[verse, ...], ...]}, ...]
    python3 scripts/build_data.py --ko ko_ko.json --en nkjv.json

Options:
    --ko-name NAME   Korean column label (default: 개역한글)
    --en-name NAME   English column label (default: NKJV)
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from books import BOOKS, write_data_js  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "bible_data.js")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def from_separate(ko_path, en_path):
    ko = {b["abbrev"]: b["chapters"] for b in load(ko_path)}
    en = {b["abbrev"]: b["chapters"] for b in load(en_path)}
    books = []
    for a, en_name, ko_name, _ in BOOKS:
        kc, ec = ko.get(a, []), en.get(a, [])
        n = max(len(kc), len(ec))
        c = [[kc[i] if i < len(kc) else [], ec[i] if i < len(ec) else []] for i in range(n)]
        books.append({"a": a, "en": en_name, "ko": ko_name, "c": c})
    return books


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--combined")
    p.add_argument("--ko")
    p.add_argument("--en")
    p.add_argument("--ko-name", default="개역한글")
    p.add_argument("--en-name", default="NKJV")
    args = p.parse_args()

    if args.combined:
        books = load(args.combined)
    elif args.ko and args.en:
        books = from_separate(args.ko, args.en)
    else:
        p.error("give --combined FILE, or both --ko FILE and --en FILE")

    meta = {
        "title": f"{args.ko_name} + {args.en_name}",
        "langs": ["ko", "en"],
        "names": {"ko": args.ko_name, "en": args.en_name},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    write_data_js(OUT, meta, books)
    print(f"Wrote {OUT}: {len(books)} books (local only — gitignored)")


if __name__ == "__main__":
    main()
