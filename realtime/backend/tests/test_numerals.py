import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.detect.numerals import (
    find_english_numbers,
    find_korean_numbers,
    int_to_english,
    int_to_sino,
    sino_to_int,
)


def apply(text, repls):
    for start, end, rep in sorted(repls, reverse=True):
        text = text[:start] + rep + text[end:]
    return text


@pytest.mark.parametrize(
    "s, n",
    [
        ("일", 1),
        ("십", 10),
        ("십일", 11),
        ("이십", 20),
        ("이십삼", 23),
        ("백", 100),
        ("백십구", 119),
        ("백오십", 150),
        ("백칠십육", 176),
        ("이백", 200),
        ("십육", 16),
    ],
)
def test_sino_to_int(s, n):
    assert sino_to_int(s) == n


@pytest.mark.parametrize("s", ["", "삼일", "일십", "십십", "백백", "칠팔"])
def test_sino_rejects_malformed(s):
    assert sino_to_int(s) is None


@given(st.integers(min_value=1, max_value=200))
def test_sino_round_trip(n):
    assert sino_to_int(int_to_sino(n)) == n


@given(st.integers(min_value=1, max_value=200))
def test_english_round_trip(n):
    text = int_to_english(n)
    assert apply(text, find_english_numbers(text)) == str(n)


@given(st.integers(min_value=1, max_value=200))
def test_korean_with_counter_round_trip(n):
    text = f"{int_to_sino(n)} 장"
    expected = text if n == 2 else f"{n} 장"  # "이 장" means "this chapter"
    assert apply(text, find_korean_numbers(text)) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("삼 장 십육 절", "3 장 16 절"),
        ("삼장 십육절", "3장 16절"),
        ("백십구 편 백오 절", "119 편 105 절"),
        ("이십삼편", "23편"),
        # ordinary words that must stay as they are
        ("이 장에서", "이 장에서"),
        ("이 절을 보면", "이 절을 보면"),
        ("이 구절을", "이 구절을"),
        ("일절 없다", "일절 없다"),
        ("사장님", "사장님"),
        ("삼일절", "삼일절"),
        ("교회 장로님", "교회 장로님"),
        ("삼 장로", "삼 장로"),
        ("이 편지를", "이 편지를"),
        ("삼 장짜리", "삼 장짜리"),
        ("회사장", "회사장"),
    ],
)
def test_find_korean_numbers(text, expected):
    assert apply(text, find_korean_numbers(text)) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("john three sixteen", "john 3 16"),
        ("romans eight twenty eight", "romans 8 28"),
        ("psalm one hundred nineteen", "psalm 119"),
        ("psalm a hundred and nineteen", "psalm 119"),
        ("twenty-one", "21"),
        ("the twenty third psalm", "the 23th psalm"),
        ("the twenty-third psalm", "the 23th psalm"),
        ("the third chapter", "the 3th chapter"),
        ("first john", "1th john"),
        ("psalm one nineteen", "psalm 1 19"),
        ("verses sixteen and seventeen", "verses 16 and 17"),
        ("three sons and sixteen grandchildren", "3 sons and 16 grandchildren"),
        ("a man and a woman", "a man and a woman"),
        ("one hundredth", "100th"),
    ],
)
def test_find_english_numbers(text, expected):
    assert apply(text, find_english_numbers(text)) == expected


def test_converters_reject_out_of_range():
    with pytest.raises(ValueError):
        int_to_sino(0)
    with pytest.raises(ValueError):
        int_to_english(1000)
