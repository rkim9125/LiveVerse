import pytest

from app.core.models import Reference
from app.detect.context import CONF_BOUNDARY, CONF_DISPLAYED, resolve
from app.detect.parser import RawMention
from app.detect.pipeline import detect


def raw(op, **kw):
    return RawMention(op, 0, 1, **kw)


def refs(raws, displayed):
    return [str(r[1]) for r in resolve(raws, Reference.parse(displayed) if displayed else None)]


@pytest.mark.parametrize(
    "op, displayed, expected",
    [
        ("next_verse", "jo 3:16", ["jo 3:17"]),
        ("next_verse", "jo 3:16-18", ["jo 3:19"]),  # after a range, continue from its end
        ("next_verse", "jo 3:36", ["jo 4:1"]),
        ("next_verse", "re 22:21", []),  # last verse of the Bible
        ("next_verse", "jo 3", []),  # a whole chapter has no "next verse"
        ("prev_verse", "jo 3:16", ["jo 3:15"]),
        ("prev_verse", "jo 3:1", ["jo 2:25"]),
        ("prev_verse", "gn 1:1", []),
        ("prev_verse", "gn 1", []),
        ("next_chapter", "jo 3:16", ["jo 4"]),
        ("next_chapter", "jo 21:25", []),
        ("last_verse", "ps 23:1", ["ps 23:6"]),
    ],
)
def test_navigation(op, displayed, expected):
    assert refs([raw(op)], displayed) == expected


def test_boundary_crossing_is_low_confidence():
    [(_, ref, kind, conf)] = resolve([raw("next_verse")], Reference.parse("jo 3:36"))
    assert (str(ref), kind, conf) == ("jo 4:1", "relative", CONF_BOUNDARY)


def test_displayed_context_confidence():
    [(_, _, _, conf)] = resolve([raw("verse", verse_start=17)], Reference.parse("jo 3:16"))
    assert conf == CONF_DISPLAYED


@pytest.mark.parametrize(
    "mention, displayed",
    [
        (raw("verse", verse_start=40), "jo 3:16"),  # jo 3 has 36 verses
        (raw("chapter", chapter=22), "jo 3:16"),  # jo has 21 chapters
    ],
)
def test_out_of_range_is_dropped(mention, displayed):
    assert refs([mention], displayed) == []


def test_no_context_drops_relative():
    assert refs([raw("verse", verse_start=17), raw("next_verse")], None) == []


def test_segment_context_wins_over_displayed():
    assert [str(m.ref) for m in detect("로마서 8장 28절, 그리고 29절", context="jo 3:16")] == [
        "rm 8:28",
        "rm 8:29",
    ]


def test_relative_chapter_with_verse():
    assert [str(m.ref) for m in detect("5장 1절", context="rm 3:1")] == ["rm 5:1"]


def test_unknown_op_raises():
    with pytest.raises(ValueError):
        resolve([raw("bogus")], Reference.parse("jo 3:16"))


def test_duplicate_mentions_collapse():
    assert [str(m.ref) for m in detect("요한복음 3장 16절, 요한복음 3장 16절")] == ["jo 3:16"]


def test_trigger_raises_confidence():
    plain = detect("4장으로 넘어가서", context="jo 3:16")[0].confidence
    triggered = detect("4장 말씀을 보시면", context="jo 3:16")[0].confidence
    assert triggered > plain
