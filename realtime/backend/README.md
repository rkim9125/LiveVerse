# LiveVerse realtime backend

This folder holds the backend for the realtime sermon assistant. The design is in [docs/realtime-design.md](../../docs/realtime-design.md).

Stage 1 is done: the reference detector. It takes one transcript segment and returns the Bible references mentioned in it. There is no web server, speech input or Docker yet.

## Setup and tests

You need [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 if it is missing.

```sh
cd realtime/backend
uv sync
uv run pytest                    # all tests
uv run pytest --cov=app          # with coverage
uv run pytest tests/test_perf.py -s   # print timing
uv run ruff check . && uv run ruff format --check .
```

## Usage

```python
from app.detect.pipeline import detect

detect("오늘 본문은 요한복음 3장 16절 말씀입니다")
# [Mention(ref=jo 3:16, kind='absolute', matched_text='요한복음 3장 16절', confidence=1.0, ...)]

detect("다음 절", context="jo 3:16")  # context is the verse on the display
# [Mention(ref=jo 3:17, kind='relative', ...)]

detect("요 3:16", mode="typed")  # short forms are accepted in typed mode only
```

## Layout

```
app/core/models.py          Reference, Mention
app/detect/numerals.py      Sino-Korean and English number words
app/detect/normalize.py     normalization with an offset map back to the original text
app/detect/books.py         66 books, spoken and typed aliases
app/detect/versification.*  chapter and verse counts (numbers only, from the KJV)
app/detect/parser.py        tokenizer and absolute references
app/detect/context.py       relative references ("17절", "다음 절", "next verse")
app/detect/pipeline.py      detect(): the public entry point
scripts/gen_versification.py  rebuilds versification.json from data/sample/kjv.js
tests/fixtures/parser_cases.jsonl  table of inputs and expected references
```

## Fixture format

Each line in `tests/fixtures/parser_cases.jsonl` is one case:

```json
{"id": "ko-abs-001", "lang": "ko", "mode": "spoken", "input": "요한복음 3장 16절", "context": null, "expect": [{"ref": "jo 3:16", "kind": "absolute", "matched": "요한복음 3장 16절", "confidence": "high"}], "tags": ["absolute"]}
```

- **`ref` forms:**
  - `jo 3`: a whole chapter
  - `jo 3:16`: one verse
  - `jo 3:16-18`: a verse range
  - `jo 3:16+`: a verse and the ones after it (16절 이하)
- **Book codes:** they are the app abbreviations listed in `app/detect/books.py`.
- **`context`:** the reference on the display, or `null`.
- **Empty `expect`:** an empty list means nothing should be detected.
- **Optional fields in `expect`:** `kind`, `matched` and `confidence`. `confidence` is `high` or `low`, and `high` means 0.7 or above.
- **Copyright:** inputs are sentences that name a reference. Never put Bible text in fixtures.

## Data rules

- Tests use no Bible text at all.
- `versification.json` holds counts only.
- Copyrighted translations stay in the local `data/` folder (gitignored), as described in the top-level README.
- Recordings and transcripts for evaluation go in `eval/corpus/`, which is gitignored.

## Known limits

- **Spoken short forms:** single and two syllable book abbreviations (요, 시, 요일, 고전) are off in spoken mode, because they collide with ordinary words.
- **Possible false positive:** a bare chapter such as "누가 3장을" is ignored without context. With a displayed verse, though, it resolves to that book's chapter 3. Stage 4 shows such candidates with a lower confidence, and the interpreter decides.
- **Korean versification:** the Korean versification differences from the KJV are not handled yet.
