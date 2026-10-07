#!/usr/bin/env python3
"""Review candidate labels one at a time in the terminal.

Shows each candidate from $LIVEVERSE_CORPUS/<sermon>/candidates.jsonl with the
transcript around it, what detect() found and the suggested label, then takes
one key:

    a  agree with the suggested label
    f  fix: type the correct refs (e.g. "rt 2:1-3", several with commas)
    r  reject: no reference to display here
    u  unsure: keep for a later discussion
    p  play the audio of this window (3 s before and after)
    b  back to the previous item
    q  quit (everything is already saved)

Every judgment sets label_source to "user" and is saved immediately, so the
review can stop and resume at any time. Items suggested as fix or reject come
first, accepts last.

Usage (from realtime/backend):
    uv run python eval/review_labels.py              # all sermons in the corpus
    uv run python eval/review_labels.py sermon-02    # one sermon
    uv run python eval/review_labels.py --type quote # only quote-search candidates
    uv run python eval/review_labels.py --blind      # hide detector output and suggestions
    uv run python eval/review_labels.py sermon-03 sermon-04 sermon-05 \
        --ids ~/liveverse-corpus/test-sample-40.json   # only the fixed random sample

Blind mode is on automatically for test-set sermons (meta.json "split": "test").
It shows only the time, the transcript and the audio: no detect() result, no
suggested label, no note. There is no "a" key, items come in time order, and
n adds a mention that no candidate covers:

    n  add a missed mention: enter its time (mm:ss or h:mm:ss) and the refs
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.detect.typed import parse_query  # noqa: E402

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".webm"}
PLAY_PADDING_S = 3.0
CONTEXT_CHARS = 160
ORDER = {"fix": 0, "reject": 1, "accept": 2}

RULES = [
    "1. Correct = what the interpreter would want on the display at that moment.",
    "2. Not correct: bookmarks, 'read the whole book', a book name alone, hymns.",
    "3. Consecutive verses = one range (rt 2:19-20). Chapter + verse said = both.",
]

BOLD, DIM, CYAN, YELLOW, RESET = "\033[1m", "\033[2m", "\033[36m", "\033[33m", "\033[0m"


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


# ── data ──


class Sermon:
    def __init__(self, path: Path):
        self.dir = path
        self.name = path.name
        self.labels_path = path / "candidates.jsonl"
        with self.labels_path.open(encoding="utf-8") as f:
            self.items = [json.loads(line) for line in f if line.strip()]
        self.segments = self._load_segments("whisper.json")
        self.prompted = self._load_segments("whisper.prompted.json")
        meta_path = path / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        self.split = meta.get("split", "")

    def _load_segments(self, name: str) -> list[dict]:
        path = self.dir / name
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))["segments"]

    def save(self) -> None:
        """Write atomically so an interrupted save never truncates the file."""
        tmp = self.labels_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for item in self.items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        tmp.replace(self.labels_path)

    def audio(self) -> Path | None:
        sources = [
            p
            for p in self.dir.iterdir()
            if p.suffix.lower() in AUDIO_EXTS and not p.name.startswith(("audio", "sample"))
        ]
        return sources[0] if len(sources) == 1 else None


def is_done(item: dict) -> bool:
    return item.get("label_source") == "user"


def review_order(
    sermons: list[Sermon], only_type: str | None = None, blind: bool = False
) -> list[tuple[Sermon, dict]]:
    queue = [
        (s, item)
        for s in sermons
        for item in s.items
        if only_type is None or item.get("type") == only_type
    ]
    if blind:
        queue.sort(key=lambda p: (p[0].name, p[1]["t_start"]))
    else:
        queue.sort(key=lambda p: (ORDER.get(p[1].get("decision"), 3), p[0].name, p[1]["t_start"]))
    return queue


def parse_time(text: str) -> float:
    """'12:34' or '1:02:03' or '754' -> seconds."""
    parts = [float(p) for p in text.strip().split(":")]
    if not parts or len(parts) > 3:
        raise ValueError(f"bad time {text!r}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def missed_item(sermon: Sermon, at: float, refs: list[str]) -> dict:
    """A window for a mention that no candidate covered, added by the reviewer."""
    n = 1 + sum(it["id"].startswith(f"{sermon.name}-m") for it in sermon.items)
    m, s = divmod(int(at), 60)
    h, m = divmod(m, 60)
    return {
        "id": f"{sermon.name}-m{n:02d}",
        "sermon": sermon.name,
        "t_start": round(max(0.0, at - 3), 1),
        "t_end": round(at + 5, 1),
        "time": f"{h}:{m:02d}:{s:02d}",
        "source": "manual",
        "decision": "fix",
        "correct_refs": refs,
        "label_source": "user",
        "review_status": "added",
        "notes": "",
    }


def parse_refs(text: str) -> list[str]:
    """Validate 'rt 2:1-3, 마태복음 22:1-14' against the versification. Raises ValueError."""
    refs = []
    for part in text.split(","):
        if part.strip():
            refs.append(str(parse_query(part)))
    if not refs:
        raise ValueError("no reference given")
    return refs


def apply(item: dict, key: str, refs: list[str] | None = None) -> None:
    detected = [d["ref"] for d in item.get("detected", [])]
    if key == "a":
        item["review_status"] = "agreed"
    elif key == "f":
        item["correct_refs"] = refs
        item["decision"] = "accept" if refs == detected else "fix"
        item["review_status"] = "fixed"
    elif key == "r":
        item["correct_refs"] = []
        item["decision"] = "reject"
        item["review_status"] = "rejected"
    elif key == "u":
        item["review_status"] = "unsure"
    else:
        raise ValueError(key)
    item["label_source"] = "user"


# ── display ──


def text_around(segments: list[dict], start: float, end: float) -> tuple[str, str, str]:
    before = " ".join(
        s["text"].strip() for s in segments if s["end"] <= start and s["end"] > start - 30
    )
    inside = " ".join(s["text"].strip() for s in segments if s["start"] < end and s["end"] > start)
    after = " ".join(
        s["text"].strip() for s in segments if s["start"] >= end and s["start"] < end + 30
    )
    return before[-CONTEXT_CHARS:], inside, after[:CONTEXT_CHARS]


def show(
    sermon: Sermon, item: dict, pos: int, total: int, done: int, message: str, blind: bool
) -> None:
    print("\033[2J\033[H", end="")
    for line in RULES:
        print(f"{DIM}{line}{RESET}")
    print(f"{DIM}{'─' * 78}{RESET}")
    status = item.get("review_status", "")
    mark = f"  {YELLOW}[{status}]{RESET}" if is_done(item) else ""
    print(
        f"{BOLD}{pos + 1}/{total}{RESET}  done {done}/{total}   "
        f"{BOLD}{item['id']}{RESET}  {item['time']}  ({item['t_start']} to {item['t_end']} s){mark}"
    )
    print()
    before, inside, after = text_around(sermon.segments, item["t_start"], item["t_end"])
    print(f"{DIM}... {before}{RESET}")
    print(f"{BOLD}{inside or item.get('text', '')}{RESET}")
    print(f"{DIM}{after} ...{RESET}")
    if sermon.prompted:
        _, p_inside, _ = text_around(sermon.prompted, item["t_start"], item["t_end"])
        if p_inside and p_inside != inside:
            print(f"{CYAN}prompted transcript:{RESET} {p_inside}")
    print()
    if blind:
        if is_done(item):
            print(f"your label:      {item.get('decision')}  {item.get('correct_refs')}")
        print()
        print(f"{DIM}f refs  r no reference  u unsure  n add missed  p play  b back  q quit{RESET}")
        if message:
            print(f"{YELLOW}{message}{RESET}")
        return
    detected = ", ".join(
        f"{d['ref']} ({d['kind'][0]}, {d['confidence']})" for d in item["detected"]
    )
    print(f"detect():        {detected or 'none'}")
    print(f"suggested:       {BOLD}{item.get('decision')}{RESET}  {item.get('correct_refs')}")
    if item.get("claude_note"):
        print(f"note:            {item['claude_note']}")
    if item.get("error_types"):
        print(f"error types:     {', '.join(item['error_types'])}")
    print()
    print(f"{DIM}a agree  f fix  r reject  u unsure  p play  b back  q quit{RESET}")
    if message:
        print(f"{YELLOW}{message}{RESET}")


# ── input and audio ──


def read_key() -> str:
    if not sys.stdin.isatty():
        line = sys.stdin.readline()
        return line.strip()[:1] if line else "q"
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return "q" if ch in ("\x03", "\x04") else ch.lower()


def play(sermon: Sermon, item: dict) -> str:
    src = sermon.audio()
    if src is None:
        return "no single source recording found in the sermon folder"
    start = max(0.0, item["t_start"] - PLAY_PADDING_S)
    duration = item["t_end"] - item["t_start"] + 2 * PLAY_PADDING_S
    if shutil.which("ffplay"):
        cmd = [
            "ffplay",
            "-v",
            "error",
            "-nodisp",
            "-autoexit",
            "-ss",
            str(start),
            "-t",
            str(duration),
            str(src),
        ]
        subprocess.run(cmd, check=False)
        return ""
    with tempfile.NamedTemporaryFile(suffix=".wav") as clip:
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-ss",
                str(start),
                "-t",
                str(duration),
                "-i",
                str(src),
                clip.name,
            ],
            check=True,
        )
        subprocess.run(["afplay", clip.name], check=False)
    return ""


# ── main loop ──


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("sermons", nargs="*", help="default: every folder with a candidates.jsonl")
    p.add_argument("--type", help="review only candidates of this type, e.g. quote")
    p.add_argument("--blind", action="store_true", help="hide detector output and suggestions")
    p.add_argument("--ids", help="JSON file with an 'ids' list: review only those candidates")
    args = p.parse_args()

    root = corpus_dir()
    names = args.sermons or sorted(
        d.name for d in root.iterdir() if (d / "candidates.jsonl").exists()
    )
    sermons = [Sermon(root / n) for n in names]
    blind = args.blind or any(s.split == "test" for s in sermons)
    if blind and any(s.split != "test" for s in sermons) and not args.blind:
        raise SystemExit("do not review test and dev sermons together; name the sermons")
    queue = review_order(sermons, args.type, blind)
    if args.ids:
        wanted = set(json.loads(Path(args.ids).expanduser().read_text(encoding="utf-8"))["ids"])
        queue = [(s, it) for s, it in queue if it["id"] in wanted]
    total = len(queue)
    if not total:
        raise SystemExit(f"no candidates found under {root}")

    done = sum(is_done(item) for _, item in queue)
    print(f"{done}/{total} done ({', '.join(names)}){' [blind]' if blind else ''}")
    pos = next((i for i, (_, item) in enumerate(queue) if not is_done(item)), None)
    if pos is None:
        print("Everything is reviewed. Showing the first item; press q to quit.")
        pos = 0

    message = ""
    while True:
        sermon, item = queue[pos]
        done = sum(is_done(it) for _, it in queue)
        show(sermon, item, pos, total, done, message, blind)
        message = ""
        key = read_key()
        if key == "q":
            break
        if key == "b":
            pos = max(0, pos - 1)
            continue
        if key == "p":
            message = play(sermon, item) or "played"
            continue
        if key == "a" and blind:
            message = "a is off in blind mode: type the refs with f, or r for no reference"
            continue
        if key == "n" and blind:
            try:
                at = parse_time(input("time of the missed mention (mm:ss): "))
                refs = parse_refs(input("correct refs (comma separated): "))
            except (ValueError, EOFError) as e:
                message = f"not added: {e}"
                continue
            new = missed_item(sermon, at, refs)
            sermon.items.append(new)
            sermon.save()
            queue.insert(pos + 1, (sermon, new))
            total = len(queue)
            message = f"added {new['id']} at {new['time']}"
            continue
        if key not in ("a", "f", "r", "u"):
            message = f"unknown key {key!r}"
            continue
        refs = None
        if key == "f":
            try:
                refs = parse_refs(input("correct refs (comma separated): "))
            except (ValueError, EOFError) as e:
                message = f"not saved: {e}"
                continue
        apply(item, key, refs)
        sermon.save()
        if pos + 1 >= total:
            message = "last item reached; press q to quit or b to go back"
        else:
            pos += 1

    done = sum(is_done(it) for _, it in queue)
    unsure = sum(it.get("review_status") == "unsure" for _, it in queue)
    print(f"\nsaved. {done}/{total} done, {unsure} marked unsure.")


if __name__ == "__main__":
    main()
