import pytest

from app.core import bible_text
from app.core.models import Reference
from app.detect.quotes import QuoteIndex


@pytest.fixture(scope="module")
def kjv():
    return QuoteIndex(bible_text.load(bible_text.SAMPLE))


def test_sample_has_english_only():
    text = bible_text.load(bible_text.SAMPLE)
    assert text.has_english and not text.has_korean


def test_finds_quoted_verse(kjv):
    said = (
        "as it is written, for God so loved the world, that he gave his only begotten "
        "Son, that whosoever believeth in him should not perish, and that is our hope"
    )
    assert str(kjv.find(said).ref) == "jo 3:16"


def test_reading_the_passage_on_screen_is_not_a_quote(kjv):
    said = "for God so loved the world, that he gave his only begotten Son"
    assert kjv.find(said, spoken=Reference.parse("jo 3:14-18")) is None


def test_chapter_context_still_finds_the_verse(kjv):
    said = "for God so loved the world, that he gave his only begotten Son"
    assert str(kjv.find(said, spoken=Reference.parse("jo 3")).ref) == "jo 3:16"


def test_reading_an_announced_chapter_is_not_a_quote(kjv):
    said = "for God so loved the world, that he gave his only begotten Son"
    assert kjv.find(said, spoken=Reference.parse("jo 3"), announced=True) is None


def test_short_common_phrase_is_not_a_quote(kjv):
    assert kjv.find("and he said unto them, go") is None


def test_env_path(monkeypatch):
    monkeypatch.setenv("BIBLE_TEXT_PATH", str(bible_text.SAMPLE))
    assert bible_text.default_path() == bible_text.SAMPLE


def test_rejects_other_files(tmp_path):
    bad = tmp_path / "x.js"
    bad.write_text("var x = 1;", encoding="utf-8")
    with pytest.raises(ValueError):
        bible_text.load(bad)


@pytest.mark.skipif(not bible_text.LOCAL.exists(), reason="local Korean text not present")
def test_korean_quote_with_local_text():
    """Uses a verse from the local file at run time, so no Korean text is in the repo."""
    local = bible_text.load(bible_text.LOCAL)
    if not local.has_korean:
        pytest.skip("local file has no Korean text")
    index = QuoteIndex(local)
    verse = local.books["rt"][0][0][15]  # Ruth 1:16
    assert str(index.find(f"말씀에 보면 {verse} 라고 되어 있습니다").ref) == "rt 1:16"
