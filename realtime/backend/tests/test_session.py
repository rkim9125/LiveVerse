from dataclasses import replace

import pytest

from app.core.models import Reference
from app.core.session import Session
from app.detect.quotes import QuoteIndex
from app.llm.base import Guess
from tests.conftest import kjv_store


@pytest.fixture
def session(settings, store):
    return Session(store, settings)


def shown(s: Session) -> str | None:
    return str(s.shown.candidate.ref) if s.shown else None


def source(s: Session) -> str | None:
    return s.shown.candidate.source if s.shown else None


def test_absolute_mention_is_shown_at_once(session):
    assert session.process_final("요한복음 3장 16절 말씀입니다", now=0)
    assert (shown(session), source(session)) == ("jo 3:16", "rule")
    state = session.state()
    assert state["shown"]["verses"][0]["num"] == 16
    assert state["shown"]["label"]["en"] == "John 3:16"


def test_relative_mention_has_context_source(session):
    session.process_final("요한복음 3장 16절", now=0)
    session.process_final("17절", now=5)
    assert (shown(session), source(session)) == ("jo 3:17", "context")


def test_chapter_in_passing_moves_spoken_but_not_the_screen(session):
    session.process_final("요한복음 3장 16절", now=0)
    session.process_final("이제 4장에 보면 그런 이야기가 나옵니다", now=20)
    assert shown(session) == "jo 3:16"
    assert str(session.spoken) == "jo 4"
    alt = session.state()["alternatives"][0]
    assert (alt["ref"], alt["dimmed"]) == ("jo 4", True)
    # the next relative verse follows the spoken position, not the screen
    session.process_final("5절에 보면", now=25)
    assert shown(session) == "jo 4:5"


def test_dimmed_chapter_is_promoted_by_an_announcement(session):
    session.process_final("로마서 8장에 보면", now=0)
    assert shown(session) is None
    session.process_final("같이 읽겠습니다", now=6)
    assert shown(session) == "rm 8"


def test_dimmed_chapter_expires(session):
    session.process_final("로마서 8장에 보면", now=0)
    session.process_final("같이 읽겠습니다", now=11)
    assert shown(session) is None
    assert session.state()["alternatives"][0]["dimmed"] is True


def test_announcement_before_the_chapter_counts(session):
    session.process_final("성경을 펴시기 바랍니다", now=0)
    session.process_final("로마서 8장", now=4)
    assert shown(session) == "rm 8"


def test_chapter_with_copula_is_shown(session):
    session.process_final("이사야 40장입니다", now=0)
    assert shown(session) == "is 40"


def test_chapter_then_verse_shows_the_verse(session):
    session.process_final("이사야 40장입니다. 이사야 40장 27절", now=0)
    assert shown(session) == "is 40:27"
    refs = [a["ref"] for a in session.state()["alternatives"]]
    assert "is 40" not in refs  # superseded


def test_repeating_the_chapter_on_screen_changes_nothing(session):
    session.process_final("이사야 40장 27절", now=0)
    session.process_final("이사야 40장", now=10)
    assert shown(session) == "is 40:27"


def test_hymns_are_ignored(session):
    assert not session.process_final("찬송가 305장을 부르겠습니다", now=0)
    assert shown(session) is None


def test_threshold_is_configurable(settings, store):
    low = Session(store, replace(settings, show_threshold=0.5))
    low.process_final("요한복음 3장 16절", now=0)
    low.process_final("4장으로 넘어가서", now=5)  # chapter from context: confidence 0.6
    assert shown(low) == "jo 4"
    default = Session(store, settings)
    default.process_final("요한복음 3장 16절", now=0)
    default.process_final("4장으로 넘어가서", now=5)
    assert shown(default) == "jo 3:16"


def test_switch_search_clear(session):
    session.process_final("로마서 8장 28절과 요한복음 3장 16절", now=0)
    assert shown(session) == "jo 3:16"
    other = next(a for a in session.state()["alternatives"] if a["ref"] == "rm 8:28")
    assert session.switch(other["id"], now=2)
    assert (shown(session), session.shown.manual) == ("rm 8:28", True)
    assert session.search("요 1:1", now=3)
    assert (shown(session), source(session)) == ("jo 1:1", "manual")
    assert str(session.spoken) == "jo 1:1"
    assert session.clear(now=4)
    assert session.state()["shown"] is None
    with pytest.raises(KeyError):
        session.switch("nope", now=5)


def test_new_mention_replaces_a_manual_choice(session):
    session.search("요 1:1", now=0)
    session.process_final("로마서 8장 28절", now=5)
    assert (shown(session), session.shown.manual) == ("rm 8:28", False)


def test_preview_changes_nothing(session):
    preview = session.preview("요한복음 3장 16절", now=0)
    assert [p["ref"] for p in preview] == ["jo 3:16"]
    assert session.shown is None and session.spoken is None and not session.candidates


def test_quote_source(settings):
    store = kjv_store()
    s = Session(store, settings, quotes=QuoteIndex(store.text))
    s.process_final("for God so loved the world, that he gave his only begotten Son", now=0)
    assert (shown(s), source(s)) == ("jo 3:16", "quote")


def test_llm_hook_is_called_only_when_ambiguous(settings, store):
    class Fake:
        calls = 0

        def resolve(self, text, spoken):
            Fake.calls += 1
            return [Guess(Reference.parse("rt 2:7"), 0.75)]

    s = Session(store, settings, resolver=Fake())
    s.process_final("오늘 날씨가 좋습니다", now=0)
    assert Fake.calls == 0
    s.process_final("루키 2장 7절", now=1)  # looks like a book name, not confirmed
    assert Fake.calls == 1
    assert (shown(s), source(s)) == ("rt 2:7", "llm")
    assert s.state()["shown"]["tentative"] is True


def test_reset(session):
    session.process_final("요한복음 3장 16절", now=0)
    session.reset()
    assert session.state()["shown"] is None and session.spoken is None


# A book said with a chapter it does not have ("로마서 17장"; Romans has 16).


@pytest.mark.parametrize(
    "text", ["로마서 17장입니다", "로마서 17장 1절", "로마서 17장 1절 말씀입니다"]
)
def test_out_of_range_chapter_keeps_the_screen_and_moves_spoken_to_the_book(session, text):
    session.process_final("요한복음 3장 16절 말씀입니다", now=0)
    session.process_final(text, now=5)
    assert shown(session) == "jo 3:16"  # the bug showed jo 17 or jo 17:1 here
    assert session.spoken is None and session.spoken_book == "rm"
    assert session.state()["spoken"] == {"ref": None, "book": "rm"}


def test_out_of_range_guess_is_a_low_confidence_alternative(session):
    session.process_final("요한복음 3장 16절", now=0)
    session.process_final("로마서 17장 1절", now=5)
    alt = session.state()["alternatives"][0]
    assert (alt["ref"], alt["guess"]) == ("rm 7:1", True)
    assert alt["confidence"] < session.settings.show_threshold
    assert shown(session) == "jo 3:16"
    assert session.switch(alt["id"], now=6)  # one click shows it
    assert shown(session) == "rm 7:1"


def test_relative_mentions_after_out_of_range_use_the_book(session):
    session.process_final("요한복음 3장 16절", now=0)
    session.process_final("로마서 17장 1절", now=5)
    session.process_final("2절을 보면", now=8)  # no chapter known: nothing, never jo 3:2
    assert shown(session) == "jo 3:16"
    assert session.spoken_book == "rm"
    session.process_final("8장 28절을 보면", now=10)
    assert shown(session) == "rm 8:28"
    assert str(session.spoken) == "rm 8:28" and session.spoken_book is None
    session.process_final("29절", now=12)
    assert shown(session) == "rm 8:29"


def test_search_clears_book_only_position(session):
    session.process_final("로마서 17장", now=0)
    session.search("요 3:16", now=1)
    assert session.spoken_book is None and str(session.spoken) == "jo 3:16"
