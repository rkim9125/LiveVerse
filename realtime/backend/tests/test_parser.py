import pytest

from app.detect.normalize import normalize
from app.detect.pipeline import analyze
from tests.fixtures import load_cases


@pytest.mark.parametrize("case", load_cases(), ids=lambda c: c["id"])
def test_fixture(case):
    found = analyze(
        case["input"],
        lang=case["lang"],
        mode=case["mode"],
        context=case["context"],
        context_book=case.get("context_book"),
    )
    mentions = found.mentions
    assert [str(m.ref) for m in mentions] == [e["ref"] for e in case["expect"]]
    for mention, exp in zip(mentions, case["expect"], strict=True):
        if "kind" in exp:
            assert mention.kind == exp["kind"]
        if "matched" in exp:
            assert mention.matched_text == exp["matched"]
        if "confidence" in exp:
            assert mention.is_high == (exp["confidence"] == "high")
    if "guesses" in case:
        assert [str(g.ref) for g in found.guesses] == case["guesses"]
        assert all(not g.is_high for g in found.guesses)
    if "spoken_book" in case:
        assert found.book == case["spoken_book"]


@pytest.mark.parametrize(
    "text, normalized",
    [
        ("요한복음 삼 장 십육 절", "요한복음 3 장 16 절"),
        ("시편 23편 첫 절", "시편 23편 1절"),
        ("John Three Sixteen", "john 3 16"),
        ("요한복음 3장 16–18절", "요한복음 3장 16-18절"),
        ("요한복음 3：16", "요한복음 3:16"),
    ],
)
def test_normalize(text, normalized):
    assert normalize(text).text == normalized


def test_offsets_map_back_to_original():
    norm = normalize("오늘은 John three sixteen 입니다")
    start = norm.text.index("john")
    end = norm.text.index("16") + 2
    assert norm.original_text(start, end) == "John three sixteen"
    assert norm.original_span(3, 3) == (3, 3)
