from app.detect.announce import WINDOW_S, TimedSegment, dimmed_chapters
from app.detect.pipeline import detect


def seg(start, text, context=None):
    s = TimedSegment(start, start + 5, text)
    for m in detect(text, context=context):
        s.mentions.append((m, start, start + 2))
    return s


def dims(*segments):
    timeline = list(segments)
    return {str(timeline[i].mentions[j][0].ref) for i, j in dimmed_chapters(timeline)}


def test_chapter_in_passing_is_dimmed():
    assert dims(seg(0, "로마서 8장에 보면 그런 이야기가 나옵니다")) == {"rm 8"}


def test_announced_chapter_is_kept():
    assert dims(seg(0, "로마서 8장을 보시겠습니다")) == set()


def test_announcement_in_the_next_segment_counts():
    assert dims(seg(0, "로마서 8장"), seg(6, "같이 읽겠습니다")) == set()


def test_announcement_outside_the_window_does_not_count():
    later = 5 + WINDOW_S + 1
    assert dims(seg(0, "로마서 8장"), seg(later, "같이 읽겠습니다")) == {"rm 8"}


def test_chapter_followed_by_its_verse_is_kept():
    assert dims(seg(0, "로마서 8장"), seg(6, "28절", context="rm 8")) == set()


def test_chapter_with_copula_is_kept():
    assert dims(seg(0, "이사야 40장입니다")) == set()


def test_verses_are_never_dimmed():
    assert dims(seg(0, "로마서 8장 28절에 보면 그런 이야기가 나옵니다")) == set()


def test_chapter_repeated_while_its_verse_is_displayed_is_dropped():
    assert detect("이사야 40장", context="is 40:27") == []
    assert [str(m.ref) for m in detect("이사야 41장", context="is 40:27")] == ["is 41"]
    assert [str(m.ref) for m in detect("이사야 40장", context="is 40")] == ["is 40"]
