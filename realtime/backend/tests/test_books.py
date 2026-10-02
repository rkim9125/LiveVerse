import importlib.util
import re
from pathlib import Path

import pytest

from app.detect import versification
from app.detect.books import BOOKS, TYPED_ALIASES, book_regex, lookup

REPO = Path(__file__).resolve().parents[3]


def _load_scripts_books():
    spec = importlib.util.spec_from_file_location("repo_books", REPO / "scripts" / "books.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BOOKS


def _index_html_lookup() -> dict[str, str]:
    html = (REPO / "index.html").read_text(encoding="utf-8")
    body = html[html.index("const BOOK_LOOKUP = {") :]
    body = body[: body.index("\n};")]
    return dict(re.findall(r"'([^']+)':'([^']+)'", body))


def test_canon_matches_scripts_books():
    expected = [(a, en, ko) for a, en, ko, _ in _load_scripts_books()]
    assert [(b.abbrev, b.en, b.ko) for b in BOOKS] == expected


def test_typed_aliases_match_index_html():
    assert TYPED_ALIASES == _index_html_lookup()


@pytest.mark.parametrize("alias, abbrev", sorted(_index_html_lookup().items()))
def test_every_static_demo_alias_resolves_in_typed_mode(alias, abbrev):
    assert lookup(alias, "typed") == abbrev
    m = book_regex("typed").search(f"{alias} 1:1")
    assert m and lookup(m.group(0), "typed") == abbrev


@pytest.mark.parametrize(
    "alias, abbrev",
    [
        ("요한복음", "jo"),
        ("요한 복음", "jo"),
        ("요한일서", "1jo"),
        ("요한 1서", "1jo"),
        ("요한 일 서", "1jo"),
        ("요한삼서", "3jo"),
        ("고린도 전서", "1co"),
        ("예레미야애가", "lm"),
        ("요한 계시록", "re"),
        ("계시록", "re"),
        ("psalm", "ps"),
        ("song of songs", "so"),
        ("revelations", "re"),
        ("1th corinthians", "1co"),
        ("2nd kings", "2kgs"),
        ("1 john", "1jo"),
    ],
)
def test_spoken_variants(alias, abbrev):
    assert lookup(alias, "spoken") == abbrev
    m = book_regex("spoken").search(f"{alias} 1")
    assert m and lookup(m.group(0), "spoken") == abbrev


@pytest.mark.parametrize("alias", ["요", "시", "창", "요일", "고전", "대상", "말", "jn", "rom"])
def test_short_forms_are_typed_only(alias):
    assert lookup(alias, "spoken") is None
    assert lookup(alias, "typed") is not None


@pytest.mark.parametrize(
    "text, found",
    [
        ("예레미야애가 3장", "예레미야애가"),
        ("1th john 1 9", "1th john"),
        ("john 1 9", "john"),
        ("요일마다 모입니다", None),
        ("고전 음악을 좋아합니다", None),
        ("remarkable 3", None),
    ],
)
def test_book_regex_spoken(text, found):
    m = book_regex("spoken").search(text)
    assert (m.group(0) if m else None) == found


def test_versification_totals():
    books = versification.books()
    assert books == [b.abbrev for b in BOOKS]
    assert sum(versification.chapter_count(b) for b in books) == 1189
    total = sum(
        versification.verse_count(b, c)
        for b in books
        for c in range(1, versification.chapter_count(b) + 1)
    )
    assert total == 31102


@pytest.mark.parametrize(
    "book, chapter, verses",
    [("ps", 119, 176), ("ps", 23, 6), ("jo", 3, 36), ("ps", 1, 6), ("3jo", 1, 14)],
)
def test_verse_counts(book, chapter, verses):
    assert versification.verse_count(book, chapter) == verses


def test_out_of_range():
    assert versification.verse_count("jo", 22) is None
    assert versification.verse_count("xx", 1) is None
    assert versification.chapter_count("xx") == 0
