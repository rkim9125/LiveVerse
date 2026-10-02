import json
from pathlib import Path

CASES_PATH = Path(__file__).with_name("parser_cases.jsonl")


def load_cases() -> list[dict]:
    with CASES_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
