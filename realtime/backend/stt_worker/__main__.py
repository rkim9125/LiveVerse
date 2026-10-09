"""Run the Whisper streaming worker.

From realtime/backend, with `uv sync --group stt`:

  Offline, as fast as possible, finals only (no server):
    uv run python -m stt_worker --sermon sermon-01 --start 180 --duration 600 --no-interim

  A recording at live pace into a running server, with interims:
    uv run python -m stt_worker --sermon sermon-01 --start 180 --duration 600 \\
        --realtime --ws ws://127.0.0.1:8000/ws

  A live input device into a running server:
    uv run python -m stt_worker --device "BlackHole 2ch" --ws ws://127.0.0.1:8001/ws

File input uses dev sermons only. The transcript is written next to the
Whisper transcripts as whisperstream.<time>.json (recording seconds). With
--realtime a run file is written too, for eval/stt_latency.py. A device run
writes a capture in the browser format (epoch seconds) to the corpus captures
folder, for eval/capture_to_segments.py.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stt_worker.decoder import MlxDecoder  # noqa: E402
from stt_worker.prompt import book_prompt  # noqa: E402
from stt_worker.segmenter import SegmenterConfig  # noqa: E402
from stt_worker.sinks import RecordSink, WsSink  # noqa: E402
from stt_worker.sources import DeviceSource, FileSource  # noqa: E402
from stt_worker.stream import StreamWorker, WorkerConfig  # noqa: E402
from stt_worker.vad import SileroVAD  # noqa: E402


def corpus_dir() -> Path:
    return Path(os.environ.get("LIVEVERSE_CORPUS", "~/liveverse-corpus")).expanduser()


def recording(sermon_dir: Path) -> Path:
    wav = sermon_dir / "audio.wav"
    if not wav.exists():
        raise SystemExit(f"{wav} is missing; run eval/transcribe.py first")
    return wav


async def main_async(args: argparse.Namespace) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.device:
        source = DeviceSource(args.device)
        offset = 0.0  # set to t0 once the stream starts
    else:
        d = corpus_dir() / args.sermon
        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if meta.get("split") != "dev":
            raise SystemExit(f"{args.sermon} is not a dev sermon")
        source = FileSource(recording(d), args.start, args.duration, realtime=args.realtime)
        offset = args.start

    decoder = MlxDecoder(args.model, prompt=None if args.no_prompt else book_prompt())
    decoder.warm_up()
    vad = SileroVAD()
    record = RecordSink(offset)
    config = WorkerConfig(
        segmenter=SegmenterConfig(hangover_s=args.hangover_s, max_s=args.max_s),
        interim=not args.no_interim,
        interim_s=args.interim_s,
    )

    async with contextlib.AsyncExitStack() as stack:
        ws = await stack.enter_async_context(WsSink(args.ws)) if args.ws else None

        async def sink(result) -> None:
            if ws is not None:
                await ws(result)
            await record(result)

        worker = StreamWorker(vad, _Words(decoder, args.words), sink, config)

        async def frames():
            async for f in source.frames():
                if record.t0 is None and (args.realtime or args.device):
                    record.t0 = source.t0
                    if args.device:
                        record.offset = source.t0
                    elif args.realtime:
                        write_run(args, stamp, source.t0)
                yield f

        t = time.time()
        with contextlib.suppress(KeyboardInterrupt, asyncio.CancelledError):
            await worker.run(frames())
        elapsed = time.time() - t

    out = {
        "source": "whisperstream",
        "model": args.model,
        "prompt": not args.no_prompt,
        "interim": not args.no_interim,
        "hangover_s": args.hangover_s,
        "max_s": args.max_s,
        "realtime": bool(args.realtime or args.device),
        "clip_start": None if args.device else args.start,
        "duration": None if args.device else args.duration,
        "elapsed_s": round(elapsed, 1),
        "worker": worker.stats,
        "stats": record.stats(),
        "segments": record.finals,
    }
    if args.device:
        out["time_base"] = "epoch_seconds"
        dest = corpus_dir() / "captures" / f"whisperstream-capture-{stamp}.json"
    else:
        dest = corpus_dir() / args.sermon / f"whisperstream.{args.name or stamp}.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("elapsed_s", "worker", "stats")}, indent=1))
    print(f"wrote {dest}")


def write_run(args: argparse.Namespace, stamp: str, t0: float) -> None:
    runs = corpus_dir() / args.sermon / "runs"
    runs.mkdir(exist_ok=True)
    run = {
        "sermon": args.sermon,
        "clip_start": args.start,
        "duration": args.duration,
        "device": "file (stt_worker)",
        "t0": t0,
        "created": stamp,
    }
    (runs / f"{stamp}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")


class _Words:
    """Word times only when asked for (they add about 0.6 s per final)."""

    def __init__(self, decoder: MlxDecoder, words: bool):
        self.decoder, self.words = decoder, words

    def decode(self, audio, words: bool = False):
        return self.decoder.decode(audio, words and self.words)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--sermon", help="dev sermon folder in the corpus")
    src.add_argument("--device", help="live input device name")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--duration", type=float)
    p.add_argument("--realtime", action="store_true", help="feed the file at live pace")
    p.add_argument("--ws", help="server WebSocket URL, e.g. ws://127.0.0.1:8000/ws")
    p.add_argument("--model", default="turbo", help="turbo, medium, small or a repo")
    p.add_argument("--no-prompt", action="store_true")
    p.add_argument("--no-interim", action="store_true")
    p.add_argument("--interim-s", type=float, default=1.0)
    p.add_argument("--hangover-s", type=float, default=0.4, help="silence that ends an utterance")
    p.add_argument("--max-s", type=float, default=12.0, help="longest utterance before a cut")
    p.add_argument("--words", action="store_true", help="word times in finals (slower)")
    p.add_argument("--name", help="output name instead of the time")
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
