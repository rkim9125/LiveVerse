#!/usr/bin/env python3
"""Candidate g: decode reference-like finals again with more audio context.

Streaming decodes each utterance alone (often 2 to 4 s), which loses context
that a 30 s window has. For every final that looks like a reference (a digit,
장/절/편, or a word like a book name), this decodes the utterance again with
the CONTEXT_S seconds of audio before it, with word times, and keeps the words
of the utterance itself. Results are cached per sermon (and saved as they
go), for eval/full_eval.py's "+g" variants.

Timing: a revision is taken to arrive when its decode would finish if started
right after the final. Decoding competes with interims in a live run, so this
is optimistic by up to one decode (about 0.7 s).

Usage (from realtime/backend, dev sermons, after stream_sim has cached them):
    uv run python eval/revise_sim.py sermon-01 sermon-02
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import stream_sim as sim  # noqa: E402

from app.detect.books import looks_like_book  # noqa: E402
from stt_worker.decoder import MlxDecoder  # noqa: E402
from stt_worker.prompt import book_prompt  # noqa: E402
from stt_worker.segmenter import SR  # noqa: E402

CONTEXT_S = 20.0
FULL_S = 4200.0
_REF_LIKE = re.compile(r"\d|장|절|편")


def reference_like(text: str) -> bool:
    return bool(_REF_LIKE.search(text)) or any(looks_like_book(w) for w in text.split())


def revisions_path(sermon: str) -> Path:
    return (
        sim.corpus_dir()
        / "reports"
        / "sim-events"
        / f"{sermon}-revisions-v2-ctx{CONTEXT_S:.0f}.json"
    )


def utterance_words(words: list, start_in_piece: float) -> str:
    """The words of the utterance itself: those that end after it starts.
    Whisper's word starts drift early, so a start cut drops the first word,
    usually the book name ("룻기 2장" came back as "2장")."""
    return "".join(w for _, b, w in words if b > start_in_piece + 0.1).strip()


def revise(decoder: MlxDecoder, audio: np.ndarray, start: float, end: float) -> dict:
    begin = max(0.0, start - CONTEXT_S)
    piece = audio[int(begin * SR) : int(end * SR)]
    d = decoder.decode(piece, words=True)
    return {
        "text": utterance_words(d.words, start - begin),
        "seconds": round(d.seconds, 3),
        "start_in_piece": round(start - begin, 3),
        "words": [[round(a, 2), round(b, 2), w] for a, b, w in d.words],
    }


def main() -> None:
    from mlx_whisper.audio import load_audio

    decoder = MlxDecoder("turbo", prompt=book_prompt())
    decoder.warm_up()
    for sermon in sys.argv[1:]:
        d = sim.corpus_dir() / sermon
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta.get("split") != "dev":
            raise SystemExit(f"{sermon} is not a dev sermon")
        events = json.loads(
            sim.events_cache(sermon, 0.0, FULL_S, 0.0, sim.CONFIGS["repeat1"]).read_text()
        )
        out_path = revisions_path(sermon)
        done = json.loads(out_path.read_text()) if out_path.exists() else {}
        audio = np.array(load_audio(str(d / "audio.wav")), dtype=np.float32)
        todo = [
            e
            for e in events
            if e["final"] and reference_like(e["text"]) and str(e["seq"]) not in done
        ]
        print(f"{sermon}: {len(todo)} finals to revise ({len(done)} done)", flush=True)
        t = time.time()
        for i, e in enumerate(todo, 1):
            done[str(e["seq"])] = revise(decoder, audio, e["start"], e["end"]) | {"t_final": e["t"]}
            if i % 20 == 0 or i == len(todo):
                out_path.write_text(json.dumps(done, ensure_ascii=False))
        print(
            f"{sermon}: done in {time.time() - t:.0f} s, dropped loops {decoder.dropped}",
            flush=True,
        )


if __name__ == "__main__":
    main()
