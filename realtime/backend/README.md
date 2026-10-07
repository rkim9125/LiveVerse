# LiveVerse realtime backend

This folder holds the backend for the realtime sermon assistant. The design is in [docs/realtime-design.md](../../docs/realtime-design.md).

Done so far:

- **Stage 1:** the reference detector. It takes one transcript segment and returns the Bible references mentioned in it.
- **Stage 2:** the server. It provides a FastAPI app with REST and WebSocket endpoints and one in-memory session for the interpreter screen, packaged with Docker.
- **Stage 3:** speech input. Chrome's Web Speech API transcribes Korean in the browser, and a minimal STT check page at `/ui/stt-check/` sends the segments to the server. Testing it, BlackHole setup and the evaluation procedure are in [docs/stt-testing.md](../../docs/stt-testing.md).

The interpreter screen, reading confirmation and the LLM come in later stages.

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

## Running the server

```sh
cd realtime/backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
curl 127.0.0.1:8000/api/health
curl "127.0.0.1:8000/api/verses?ref=John+3:16"
```

- **Bible text:** the server loads `data/bible_data.js` if it exists. That file is your local NKJV and 개역한글, gitignored. Otherwise it uses the public-domain KJV sample.
- **Settings:** set them with environment variables. They are listed in [app/config.py](app/config.py) and include the display threshold, quote search, the pending window and the log folder.
- **Protocol:** the WebSocket protocol (`/ws`) and the REST endpoints are described in the design document, section 3.14.

The frontend in `realtime/frontend` is served at `http://127.0.0.1:8000/ui/`. The STT check page is `http://127.0.0.1:8000/ui/stt-check/`. It is not in the Docker image yet; that comes in stage 4.

To replay a recorded transcript into a running server and print every screen change, with no transcript text:

```sh
uv run python eval/replay.py ~/liveverse-corpus/sermon-01/whisper.prompted.json
curl 127.0.0.1:8000/api/metrics/latency
```

## Docker

```sh
cd realtime
VERSION=$(git describe --tags --always) docker compose up --build
curl 127.0.0.1:8000/api/health
backend/scripts/check_image.sh liveverse-backend:dev   # the image holds no Bible text
```

- **Data:** the image contains only the backend code. The repo's `data/` folder is mounted read only at `/srv/data`. The server uses `data/bible_data.js` if it is there, and the KJV sample otherwise.
- **Network:** the port is published on the host's `127.0.0.1` only. Inside the container, requests arrive from the Docker network, so compose turns off the app's own localhost check (`LIVEVERSE_ALLOW_REMOTE=on`). Without that setting the app refuses every request with 403.
- **Logs:** latency logs go to the `liveverse-logs` volume.
- **User:** the container runs as an unprivileged user, and a health check calls `/api/health`.

## Reproducing the evaluation

The detector can change after the evaluation. To score exactly what was evaluated, check out the frozen tag in a separate worktree:

```sh
git worktree add ../liveverse-eval eval-freeze-v1
cd ../liveverse-eval/realtime/backend
uv sync
uv run python eval/score.py sermon-01 sermon-02 --transcript whisper.prompted.json --name repro --quotes
```

## Using the detector directly

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
app/stt/base.py             Segment, SpeechSource, SegmentSink: where speech sources plug in
eval/play_to_device.py      plays part of a dev sermon into an audio device (needs consent)
eval/capture_to_segments.py puts a browser capture on the recording timeline
eval/stt_latency.py         speech end to screen latency for one replay
../frontend/shared/         Web Speech source, WebSocket client, capture (ES modules)
../frontend/stt-check/      the STT check page
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
- **Versification:** the detector checks chapter and verse numbers against KJV counts. In the local Korean (개역한글) and NKJV data used with this project, every chapter has the same number of verses as the KJV (1,189 chapters checked). A different translation with other verse divisions would need its own counts.
