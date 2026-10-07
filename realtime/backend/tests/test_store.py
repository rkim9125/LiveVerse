import pytest

from app.core.models import Reference
from app.detect.typed import parse_query


def test_info_has_no_verse_text(store):
    info = store.info()
    assert info["file"] == "kjv.js"
    assert info["korean"] is False
    assert info["books"] == 66
    assert info["verses"] == 31102
    assert "God so loved" not in str(info)


def test_single_verse(store):
    [v] = store.verses(Reference.parse("jo 3:16"))
    assert v.num == 16 and v.ko == "" and v.en.startswith("For God so loved")


@pytest.mark.parametrize(
    "ref, nums",
    [("jo 3:16-18", [16, 17, 18]), ("ps 23", [1, 2, 3, 4, 5, 6]), ("jo 3:35+", [35, 36])],
)
def test_ranges(store, ref, nums):
    assert [v.num for v in store.verses(Reference.parse(ref))] == nums


def test_unknown_chapter(store):
    with pytest.raises(KeyError):
        store.verses(Reference.parse("jo 22"))


def test_label(store):
    assert store.label(Reference.parse("1co 13:4-7")) == {
        "en": "1 Corinthians 13:4-7",
        "ko": "고린도전서 13:4-7",
    }


@pytest.mark.parametrize(
    "text, ref",
    [
        ("mt 22:1-14", "mt 22:1-14"),
        ("Matthew 22:1-14", "mt 22:1-14"),
        ("마태복음 22:1-14", "mt 22:1-14"),
        ("마 22:1-14", "mt 22:1-14"),
        ("마태복음 22장 1절부터 14절까지", "mt 22:1-14"),
        ("요 3:16", "jo 3:16"),
        ("1 Corinthians 13", "1co 13"),
        ("시편 23", "ps 23"),
    ],
)
def test_parse_query(text, ref):
    assert str(parse_query(text)) == ref


@pytest.mark.parametrize("text", ["", "abc 1:1", "matthew 29:1", "mt 22:50"])
def test_parse_query_errors(text):
    with pytest.raises(ValueError):
        parse_query(text)
