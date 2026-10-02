import pytest

from app.core.models import HIGH_CONFIDENCE
from app.detect.normalize import normalize
from app.detect.parser import parse
from tests.fixtures import load_cases

ABSOLUTE_CASES = [c for c in load_cases() if c["context"] is None and "relative" not in c["tags"]]


@pytest.mark.parametrize("case", ABSOLUTE_CASES, ids=lambda c: c["id"])
def test_absolute_fixture(case):
    norm = normalize(case["input"])
    raws = [m for m in parse(norm, case["mode"]).mentions if m.op == "abs"]
    assert [str(m.ref) for m in raws] == [e["ref"] for e in case["expect"]]
    for raw, exp in zip(raws, case["expect"], strict=True):
        if "matched" in exp:
            assert norm.original_text(raw.start, raw.end) == exp["matched"]
        if "confidence" in exp:
            assert (raw.confidence >= HIGH_CONFIDENCE) == (exp["confidence"] == "high")


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
