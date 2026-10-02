"""66-book canon table shared by the build scripts.

Each entry: (app abbrev, English name, Korean name, eBible/USFM-style code).
The app abbrev is what index.html's BOOK_LOOKUP resolves to.
"""

BOOKS = [
    ("gn", "Genesis", "창세기", "GEN"),
    ("ex", "Exodus", "출애굽기", "EXO"),
    ("lv", "Leviticus", "레위기", "LEV"),
    ("nm", "Numbers", "민수기", "NUM"),
    ("dt", "Deuteronomy", "신명기", "DEU"),
    ("js", "Joshua", "여호수아", "JOS"),
    ("jud", "Judges", "사사기", "JDG"),
    ("rt", "Ruth", "룻기", "RUT"),
    ("1sm", "1 Samuel", "사무엘상", "1SA"),
    ("2sm", "2 Samuel", "사무엘하", "2SA"),
    ("1kgs", "1 Kings", "열왕기상", "1KI"),
    ("2kgs", "2 Kings", "열왕기하", "2KI"),
    ("1ch", "1 Chronicles", "역대상", "1CH"),
    ("2ch", "2 Chronicles", "역대하", "2CH"),
    ("ezr", "Ezra", "에스라", "EZR"),
    ("ne", "Nehemiah", "느헤미야", "NEH"),
    ("et", "Esther", "에스더", "EST"),
    ("job", "Job", "욥기", "JOB"),
    ("ps", "Psalms", "시편", "PSA"),
    ("prv", "Proverbs", "잠언", "PRO"),
    ("ec", "Ecclesiastes", "전도서", "ECC"),
    ("so", "Song of Solomon", "아가", "SOL"),
    ("is", "Isaiah", "이사야", "ISA"),
    ("jr", "Jeremiah", "예레미야", "JER"),
    ("lm", "Lamentations", "예레미야애가", "LAM"),
    ("ez", "Ezekiel", "에스겔", "EZE"),
    ("dn", "Daniel", "다니엘", "DAN"),
    ("ho", "Hosea", "호세아", "HOS"),
    ("jl", "Joel", "요엘", "JOE"),
    ("am", "Amos", "아모스", "AMO"),
    ("ob", "Obadiah", "오바댜", "OBA"),
    ("jn", "Jonah", "요나", "JON"),
    ("mi", "Micah", "미가", "MIC"),
    ("na", "Nahum", "나훔", "NAH"),
    ("hk", "Habakkuk", "하박국", "HAB"),
    ("zp", "Zephaniah", "스바냐", "ZEP"),
    ("hg", "Haggai", "학개", "HAG"),
    ("zc", "Zechariah", "스가랴", "ZEC"),
    ("ml", "Malachi", "말라기", "MAL"),
    ("mt", "Matthew", "마태복음", "MAT"),
    ("mk", "Mark", "마가복음", "MAR"),
    ("lk", "Luke", "누가복음", "LUK"),
    ("jo", "John", "요한복음", "JOH"),
    ("act", "Acts", "사도행전", "ACT"),
    ("rm", "Romans", "로마서", "ROM"),
    ("1co", "1 Corinthians", "고린도전서", "1CO"),
    ("2co", "2 Corinthians", "고린도후서", "2CO"),
    ("gl", "Galatians", "갈라디아서", "GAL"),
    ("eph", "Ephesians", "에베소서", "EPH"),
    ("ph", "Philippians", "빌립보서", "PHI"),
    ("cl", "Colossians", "골로새서", "COL"),
    ("1ts", "1 Thessalonians", "데살로니가전서", "1TH"),
    ("2ts", "2 Thessalonians", "데살로니가후서", "2TH"),
    ("1tm", "1 Timothy", "디모데전서", "1TI"),
    ("2tm", "2 Timothy", "디모데후서", "2TI"),
    ("tt", "Titus", "디도서", "TIT"),
    ("phm", "Philemon", "빌레몬서", "PHM"),
    ("hb", "Hebrews", "히브리서", "HEB"),
    ("jm", "James", "야고보서", "JAM"),
    ("1pe", "1 Peter", "베드로전서", "1PE"),
    ("2pe", "2 Peter", "베드로후서", "2PE"),
    ("1jo", "1 John", "요한일서", "1JO"),
    ("2jo", "2 John", "요한이서", "2JO"),
    ("3jo", "3 John", "요한삼서", "3JO"),
    ("jd", "Jude", "유다서", "JUD"),
    ("re", "Revelation", "요한계시록", "REV"),
]


def write_data_js(path, meta, books):
    """Write window.BIBLE_DATA as a JS file (loadable via <script> from file://).

    One book per line so diffs stay readable.
    """
    import json

    def dump(x):
        return json.dumps(x, ensure_ascii=False, separators=(",", ":"))

    lines = ["window.BIBLE_DATA = {", '"meta":' + dump(meta) + ",", '"books":[']
    lines += [dump(b) + ("," if i < len(books) - 1 else "") for i, b in enumerate(books)]
    lines += ["]};", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
