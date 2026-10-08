"""Latency log for stage 7 measurements.

One JSON line per event in <log_dir>/latency-YYYYMMDD.jsonl:
  segment   a final transcript segment: client, receive, detect-done and send times
  rendered  when a screen drew the state caused by that segment
Interim segments are logged only when they change the screen, with
"interim": true; a final and its interims share a sequence number.

Times are seconds since the epoch. Client times are on the client clock;
clock_offset (server minus client, from pings) converts them. No transcript
text is written, only times, sequence numbers and references.
"""

from __future__ import annotations

import json
import statistics
import time
from datetime import date
from pathlib import Path


def _pct(values: list[float], q: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


class LatencyLog:
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)

    def path(self, day: date | None = None) -> Path:
        return self.log_dir / f"latency-{(day or date.today()).strftime('%Y%m%d')}.jsonl"

    def _write(self, record: dict) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with self.path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def segment(self, conn: str, seq: int, **fields) -> None:
        self._write({"event": "segment", "conn": conn, "seq": seq, "t": time.time(), **fields})

    def rendered(
        self,
        conn: str,
        seq: int,
        t_render: float | None,
        clock_offset: float | None,
        interim: bool = False,
    ):
        self._write(
            {
                "event": "rendered",
                "conn": conn,
                "seq": seq,
                "t": time.time(),
                "t_render": t_render,
                "clock_offset": clock_offset,
                "interim": interim,
            }
        )

    def summary(self, day: date | None = None) -> dict:
        """p50 / p95 / max in milliseconds per hop."""
        path = self.path(day)
        records = (
            [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
            if path.exists()
            else []
        )
        segments = {
            (r["conn"], r["seq"], r.get("interim", False)): r
            for r in records
            if r["event"] == "segment"
        }
        hops: dict[str, list[float]] = {
            "client_to_server": [],
            "detect": [],
            "detect_to_send": [],
            "send_to_render": [],
            "speech_to_render": [],
        }
        for s in segments.values():
            hops["detect"].append(s["t_detect_done"] - s["t_recv"])
            if s.get("t_sent"):
                hops["detect_to_send"].append(s["t_sent"] - s["t_detect_done"])
            if s.get("t_client") is not None and s.get("clock_offset") is not None:
                hops["client_to_server"].append(s["t_recv"] - (s["t_client"] + s["clock_offset"]))
        for r in records:
            if r["event"] != "rendered" or r.get("t_render") is None:
                continue
            s = segments.get((r["conn"], r["seq"], r.get("interim", False)))
            if s is None or not s.get("t_sent"):
                continue
            if r.get("clock_offset") is not None:
                hops["send_to_render"].append(r["t_render"] + r["clock_offset"] - s["t_sent"])
            if s.get("t_client") is not None:
                hops["speech_to_render"].append(r["t_render"] - s["t_client"])
        out = {"file": path.name, "segments": len(segments)}
        for name, values in hops.items():
            ms = sorted(v * 1000 for v in values)
            out[name] = (
                {
                    "n": len(ms),
                    "p50": round(_pct(ms, 50), 1),
                    "p95": round(_pct(ms, 95), 1),
                    "max": round(ms[-1], 1),
                }
                if ms
                else {"n": 0}
            )
        return out
