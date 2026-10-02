import statistics
import time

from app.detect.pipeline import detect
from tests.fixtures import load_cases

ROUNDS = 20
P95_BUDGET_MS = 5.0


def test_detect_p95_under_budget():
    cases = load_cases()
    for case in cases:  # warm up compiled regexes and caches
        detect(case["input"], mode=case["mode"], context=case["context"])

    timings = []
    for _ in range(ROUNDS):
        for case in cases:
            t0 = time.perf_counter()
            detect(case["input"], mode=case["mode"], context=case["context"])
            timings.append((time.perf_counter() - t0) * 1000)

    p95 = statistics.quantiles(timings, n=100)[94]
    median = statistics.median(timings)
    print(f"\ndetect(): {len(timings)} calls, median {median:.3f} ms, p95 {p95:.3f} ms")
    assert p95 < P95_BUDGET_MS
