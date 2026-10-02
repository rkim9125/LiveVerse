"""Bible book names and aliases.

CANON mirrors scripts/books.py (the 66-book table used by the static demo build).
TYPED_ALIASES mirrors BOOK_LOOKUP in index.html, so typed lookups behave the same
in the static demo and the backend. tests/test_books.py checks both.

Spoken mode uses full names and spoken variants only. Short forms such as 요, 시,
요일, 고전 are ordinary Korean words, so they are accepted in typed mode only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

from app.core.models import Mode


@dataclass(frozen=True)
class Book:
    abbrev: str
    en: str
    ko: str


CANON = [
    ("gn", "Genesis", "창세기"),
    ("ex", "Exodus", "출애굽기"),
    ("lv", "Leviticus", "레위기"),
    ("nm", "Numbers", "민수기"),
    ("dt", "Deuteronomy", "신명기"),
    ("js", "Joshua", "여호수아"),
    ("jud", "Judges", "사사기"),
    ("rt", "Ruth", "룻기"),
    ("1sm", "1 Samuel", "사무엘상"),
    ("2sm", "2 Samuel", "사무엘하"),
    ("1kgs", "1 Kings", "열왕기상"),
    ("2kgs", "2 Kings", "열왕기하"),
    ("1ch", "1 Chronicles", "역대상"),
    ("2ch", "2 Chronicles", "역대하"),
    ("ezr", "Ezra", "에스라"),
    ("ne", "Nehemiah", "느헤미야"),
    ("et", "Esther", "에스더"),
    ("job", "Job", "욥기"),
    ("ps", "Psalms", "시편"),
    ("prv", "Proverbs", "잠언"),
    ("ec", "Ecclesiastes", "전도서"),
    ("so", "Song of Solomon", "아가"),
    ("is", "Isaiah", "이사야"),
    ("jr", "Jeremiah", "예레미야"),
    ("lm", "Lamentations", "예레미야애가"),
    ("ez", "Ezekiel", "에스겔"),
    ("dn", "Daniel", "다니엘"),
    ("ho", "Hosea", "호세아"),
    ("jl", "Joel", "요엘"),
    ("am", "Amos", "아모스"),
    ("ob", "Obadiah", "오바댜"),
    ("jn", "Jonah", "요나"),
    ("mi", "Micah", "미가"),
    ("na", "Nahum", "나훔"),
    ("hk", "Habakkuk", "하박국"),
    ("zp", "Zephaniah", "스바냐"),
    ("hg", "Haggai", "학개"),
    ("zc", "Zechariah", "스가랴"),
    ("ml", "Malachi", "말라기"),
    ("mt", "Matthew", "마태복음"),
    ("mk", "Mark", "마가복음"),
    ("lk", "Luke", "누가복음"),
    ("jo", "John", "요한복음"),
    ("act", "Acts", "사도행전"),
    ("rm", "Romans", "로마서"),
    ("1co", "1 Corinthians", "고린도전서"),
    ("2co", "2 Corinthians", "고린도후서"),
    ("gl", "Galatians", "갈라디아서"),
    ("eph", "Ephesians", "에베소서"),
    ("ph", "Philippians", "빌립보서"),
    ("cl", "Colossians", "골로새서"),
    ("1ts", "1 Thessalonians", "데살로니가전서"),
    ("2ts", "2 Thessalonians", "데살로니가후서"),
    ("1tm", "1 Timothy", "디모데전서"),
    ("2tm", "2 Timothy", "디모데후서"),
    ("tt", "Titus", "디도서"),
    ("phm", "Philemon", "빌레몬서"),
    ("hb", "Hebrews", "히브리서"),
    ("jm", "James", "야고보서"),
    ("1pe", "1 Peter", "베드로전서"),
    ("2pe", "2 Peter", "베드로후서"),
    ("1jo", "1 John", "요한일서"),
    ("2jo", "2 John", "요한이서"),
    ("3jo", "3 John", "요한삼서"),
    ("jd", "Jude", "유다서"),
    ("re", "Revelation", "요한계시록"),
]

BOOKS = [Book(*row) for row in CANON]
BY_ABBREV = {b.abbrev: b for b in BOOKS}

# Keys are normalized the way index.html's resolveBook() does it: lowercase,
# spaces, dots and hyphens removed for English; Korean as written.
TYPED_ALIASES = {
    "genesis": "gn",
    "exodus": "ex",
    "leviticus": "lv",
    "numbers": "nm",
    "deuteronomy": "dt",
    "joshua": "js",
    "judges": "jud",
    "ruth": "rt",
    "1samuel": "1sm",
    "2samuel": "2sm",
    "1kings": "1kgs",
    "2kings": "2kgs",
    "1chronicles": "1ch",
    "2chronicles": "2ch",
    "ezra": "ezr",
    "nehemiah": "ne",
    "esther": "et",
    "job": "job",
    "psalms": "ps",
    "psalm": "ps",
    "proverbs": "prv",
    "ecclesiastes": "ec",
    "songofsolomon": "so",
    "songofsongs": "so",
    "songs": "so",
    "isaiah": "is",
    "jeremiah": "jr",
    "lamentations": "lm",
    "ezekiel": "ez",
    "daniel": "dn",
    "hosea": "ho",
    "joel": "jl",
    "amos": "am",
    "obadiah": "ob",
    "jonah": "jn",
    "micah": "mi",
    "nahum": "na",
    "habakkuk": "hk",
    "zephaniah": "zp",
    "haggai": "hg",
    "zechariah": "zc",
    "malachi": "ml",
    "matthew": "mt",
    "mark": "mk",
    "luke": "lk",
    "john": "jo",
    "acts": "act",
    "actoftheapostles": "act",
    "actsoftheapostles": "act",
    "romans": "rm",
    "1corinthians": "1co",
    "2corinthians": "2co",
    "galatians": "gl",
    "ephesians": "eph",
    "philippians": "ph",
    "colossians": "cl",
    "1thessalonians": "1ts",
    "2thessalonians": "2ts",
    "1timothy": "1tm",
    "2timothy": "2tm",
    "titus": "tt",
    "philemon": "phm",
    "hebrews": "hb",
    "james": "jm",
    "1peter": "1pe",
    "2peter": "2pe",
    "1john": "1jo",
    "2john": "2jo",
    "3john": "3jo",
    "jude": "jd",
    "revelation": "re",
    "gen": "gn",
    "exo": "ex",
    "ex": "ex",
    "lev": "lv",
    "lv": "lv",
    "num": "nm",
    "numb": "nm",
    "nm": "nm",
    "deu": "dt",
    "deut": "dt",
    "dt": "dt",
    "josh": "js",
    "jos": "js",
    "jsh": "js",
    "js": "js",
    "judg": "jud",
    "jdg": "jud",
    "jdgs": "jud",
    "rut": "rt",
    "rt": "rt",
    "1sa": "1sm",
    "1sam": "1sm",
    "1sm": "1sm",
    "2sa": "2sm",
    "2sam": "2sm",
    "2sm": "2sm",
    "1ki": "1kgs",
    "1kgs": "1kgs",
    "1kin": "1kgs",
    "1kg": "1kgs",
    "2ki": "2kgs",
    "2kgs": "2kgs",
    "2kin": "2kgs",
    "2kg": "2kgs",
    "1ch": "1ch",
    "1chr": "1ch",
    "1chron": "1ch",
    "2ch": "2ch",
    "2chr": "2ch",
    "2chron": "2ch",
    "ezr": "ezr",
    "neh": "ne",
    "ne": "ne",
    "est": "et",
    "esth": "et",
    "et": "et",
    "psa": "ps",
    "pss": "ps",
    "ps": "ps",
    "pro": "prv",
    "prov": "prv",
    "prv": "prv",
    "ecc": "ec",
    "eccl": "ec",
    "ec": "ec",
    "qoh": "ec",
    "sos": "so",
    "sol": "so",
    "son": "so",
    "so": "so",
    "isa": "is",
    "is": "is",
    "jer": "jr",
    "jr": "jr",
    "lam": "lm",
    "lm": "lm",
    "eze": "ez",
    "ezek": "ez",
    "ez": "ez",
    "dan": "dn",
    "dn": "dn",
    "hos": "ho",
    "ho": "ho",
    "joe": "jl",
    "jl": "jl",
    "amo": "am",
    "am": "am",
    "oba": "ob",
    "obad": "ob",
    "ob": "ob",
    "jon": "jn",
    "mic": "mi",
    "mi": "mi",
    "nah": "na",
    "hab": "hk",
    "hk": "hk",
    "zep": "zp",
    "zeph": "zp",
    "zp": "zp",
    "hag": "hg",
    "hg": "hg",
    "zec": "zc",
    "zech": "zc",
    "zc": "zc",
    "mal": "ml",
    "ml": "ml",
    "mat": "mt",
    "matt": "mt",
    "mt": "mt",
    "mar": "mk",
    "mrk": "mk",
    "mk": "mk",
    "luk": "lk",
    "lk": "lk",
    "joh": "jo",
    "jhn": "jo",
    "jn": "jo",
    "act": "act",
    "rom": "rm",
    "ro": "rm",
    "rm": "rm",
    "1co": "1co",
    "1cor": "1co",
    "2co": "2co",
    "2cor": "2co",
    "gal": "gl",
    "gl": "gl",
    "eph": "eph",
    "phi": "ph",
    "phil": "ph",
    "php": "ph",
    "ph": "ph",
    "col": "cl",
    "cl": "cl",
    "1th": "1ts",
    "1the": "1ts",
    "1thes": "1ts",
    "1ths": "1ts",
    "1thess": "1ts",
    "1ts": "1ts",
    "2th": "2ts",
    "2the": "2ts",
    "2thes": "2ts",
    "2ths": "2ts",
    "2thess": "2ts",
    "2ts": "2ts",
    "1ti": "1tm",
    "1tim": "1tm",
    "1tm": "1tm",
    "2ti": "2tm",
    "2tim": "2tm",
    "2tm": "2tm",
    "tit": "tt",
    "tt": "tt",
    "phm": "phm",
    "phlm": "phm",
    "heb": "hb",
    "hb": "hb",
    "jam": "jm",
    "jas": "jm",
    "jm": "jm",
    "1pe": "1pe",
    "1pet": "1pe",
    "2pe": "2pe",
    "2pet": "2pe",
    "1jn": "1jo",
    "1jo": "1jo",
    "2jn": "2jo",
    "2jo": "2jo",
    "3jn": "3jo",
    "3jo": "3jo",
    "jud": "jd",
    "jd": "jd",
    "rev": "re",
    "re": "re",
    "apoc": "re",
    "창": "gn",
    "출": "ex",
    "레": "lv",
    "민": "nm",
    "신": "dt",
    "수": "js",
    "삿": "jud",
    "룻": "rt",
    "삼상": "1sm",
    "삼하": "2sm",
    "왕상": "1kgs",
    "왕하": "2kgs",
    "대상": "1ch",
    "대하": "2ch",
    "스": "ezr",
    "느": "ne",
    "에": "et",
    "욥": "job",
    "시": "ps",
    "잠": "prv",
    "전": "ec",
    "아": "so",
    "사": "is",
    "렘": "jr",
    "애": "lm",
    "겔": "ez",
    "단": "dn",
    "호": "ho",
    "욜": "jl",
    "암": "am",
    "옵": "ob",
    "욘": "jn",
    "미": "mi",
    "나": "na",
    "합": "hk",
    "습": "zp",
    "학": "hg",
    "슥": "zc",
    "말": "ml",
    "마": "mt",
    "막": "mk",
    "눅": "lk",
    "요": "jo",
    "행": "act",
    "롬": "rm",
    "고전": "1co",
    "고후": "2co",
    "갈": "gl",
    "엡": "eph",
    "빌": "ph",
    "골": "cl",
    "살전": "1ts",
    "살후": "2ts",
    "딤전": "1tm",
    "딤후": "2tm",
    "딛": "tt",
    "몬": "phm",
    "히": "hb",
    "약": "jm",
    "벧전": "1pe",
    "벧후": "2pe",
    "요일": "1jo",
    "요이": "2jo",
    "요삼": "3jo",
    "유": "jd",
    "계": "re",
    "창세기": "gn",
    "출애굽기": "ex",
    "레위기": "lv",
    "민수기": "nm",
    "신명기": "dt",
    "여호수아": "js",
    "사사기": "jud",
    "룻기": "rt",
    "사무엘상": "1sm",
    "사무엘하": "2sm",
    "열왕기상": "1kgs",
    "열왕기하": "2kgs",
    "역대상": "1ch",
    "역대하": "2ch",
    "에스라": "ezr",
    "느헤미야": "ne",
    "에스더": "et",
    "욥기": "job",
    "시편": "ps",
    "잠언": "prv",
    "전도서": "ec",
    "아가": "so",
    "이사야": "is",
    "예레미야": "jr",
    "예레미야애가": "lm",
    "에스겔": "ez",
    "다니엘": "dn",
    "호세아": "ho",
    "요엘": "jl",
    "아모스": "am",
    "오바댜": "ob",
    "요나": "jn",
    "미가": "mi",
    "나훔": "na",
    "하박국": "hk",
    "스바냐": "zp",
    "학개": "hg",
    "스가랴": "zc",
    "말라기": "ml",
    "마태복음": "mt",
    "마가복음": "mk",
    "누가복음": "lk",
    "요한복음": "jo",
    "사도행전": "act",
    "로마서": "rm",
    "고린도전서": "1co",
    "고린도후서": "2co",
    "갈라디아서": "gl",
    "에베소서": "eph",
    "빌립보서": "ph",
    "골로새서": "cl",
    "데살로니가전서": "1ts",
    "데살로니가후서": "2ts",
    "디모데전서": "1tm",
    "디모데후서": "2tm",
    "디도서": "tt",
    "빌레몬서": "phm",
    "히브리서": "hb",
    "야고보서": "jm",
    "베드로전서": "1pe",
    "베드로후서": "2pe",
    "요한일서": "1jo",
    "요한이서": "2jo",
    "요한삼서": "3jo",
    "유다서": "jd",
    "요한계시록": "re",
}

# Spoken variants beyond the canonical names.
_SPOKEN_EXTRA_EN = {
    "ps": ["psalm", "psalms"],
    "so": ["song of solomon", "song of songs", "songs of solomon"],
    "act": ["acts", "acts of the apostles"],
    "re": ["revelation", "revelations"],
}
_SPOKEN_EXTRA_KO = {
    "re": ["계시록"],
    "so": ["아가서"],
}

_ORDINAL_PREFIX = {"1": "1", "2": "2", "3": "3"}
_KO_NUMERAL = {"일": "1", "이": "2", "삼": "3"}


def _key_en(s: str) -> str:
    return re.sub(r"[\s.\-]+", "", s.lower())


def _strip_ordinal(key: str) -> str:
    # "1thjohn", "2ndkings" -> "1john", "2kings"
    return re.sub(r"^([123])(?:th|st|nd|rd)", r"\1", key)


def _key_ko(s: str) -> str:
    s = re.sub(r"\s+", "", s)
    # 요한1서 -> 요한일서
    return re.sub(r"([123])서$", lambda m: "일이삼"[int(m.group(1)) - 1] + "서", s)


@cache
def _spoken_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for b in BOOKS:
        keys[_key_ko(b.ko)] = b.abbrev
        keys[_key_en(b.en)] = b.abbrev
        for alias in _SPOKEN_EXTRA_EN.get(b.abbrev, []):
            keys[_key_en(alias)] = b.abbrev
        for alias in _SPOKEN_EXTRA_KO.get(b.abbrev, []):
            keys[_key_ko(alias)] = b.abbrev
    return keys


def lookup(alias: str, mode: Mode = "spoken") -> str | None:
    """Resolve a book name as written or spoken to its abbrev, or None."""
    if re.search(r"[가-힣]", alias):
        keys = [_key_ko(alias)]
    else:
        # Try the key as written first: "1thes" is a typed alias, not "1" + "th" + "es".
        key = _key_en(alias)
        keys = [key, _strip_ordinal(key)]
    for key in keys:
        found = _spoken_keys().get(key)
        if found is None and mode == "typed":
            found = TYPED_ALIASES.get(key)
        if found is not None:
            return found
    return None


def _ko_pattern(name: str) -> str:
    chars = []
    for i, ch in enumerate(name):
        is_numbered = ch in _KO_NUMERAL and name[i + 1 : i + 2] == "서" and i == len(name) - 2
        chars.append(f"[{ch}{_KO_NUMERAL[ch]}]" if is_numbered else re.escape(ch))
    return r"\s*".join(chars)


def _en_pattern(name: str) -> str:
    words = name.lower().split()
    if words[0] in _ORDINAL_PREFIX:
        n = words[0]
        head = rf"{n}(?:th|st|nd|rd)?\s*"
        words = words[1:]
    else:
        head = ""
    return head + r"\s+".join(re.escape(w) for w in words)


def _typed_pattern(key: str) -> str:
    # Typed keys have no spaces; allow spaces or dots between characters ("1 Cor.").
    return r"[\s.]*".join(re.escape(c) for c in key) + r"\.?"


@cache
def book_regex(mode: Mode) -> re.Pattern[str]:
    """One regex that finds any book name in normalized (lowercased) text.

    Alternatives are ordered longest first so 예레미야애가 wins over 예레미야 and
    1 john wins over john.
    """
    ko_names: set[str] = set()
    en_names: set[str] = set()
    for b in BOOKS:
        ko_names.add(b.ko)
        en_names.add(b.en)
        ko_names.update(_SPOKEN_EXTRA_KO.get(b.abbrev, []))
        en_names.update(_SPOKEN_EXTRA_EN.get(b.abbrev, []))

    alts: list[tuple[int, str]] = []
    for name in ko_names:
        alts.append((len(name), _ko_pattern(name)))
    for name in en_names:
        alts.append((len(name), rf"(?<![a-z0-9]){_en_pattern(name)}(?![a-z])"))
    if mode == "typed":
        for key in TYPED_ALIASES:
            if key in ko_names:
                continue
            if re.search(r"[가-힣]", key):
                pat = rf"(?<![가-힣]){re.escape(key)}(?=\s*\d)"
            else:
                pat = rf"(?<![a-z0-9]){_typed_pattern(key)}(?=\s*\d)"
            alts.append((len(key), pat))
    alts.sort(key=lambda a: -a[0])
    return re.compile("|".join(p for _, p in alts))
