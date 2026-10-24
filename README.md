# Bible Verse Lookup (성경 구절 조회)

A single-page tool for looking up Bible verses side by side in Korean and English.

Built for church interpreters who need to find and display verses in real time during live sermons. The program our interpreters had been using did not run on Mac, so I built a replacement that works in any browser. Currently used at my church.

![KJV demo showing John 3:16](docs/screenshot.png)

**Live demo:** https://rkim9125.github.io/LiveVerse/

## Features

- Look up verses using Korean or English book names and abbreviations: `요 3:16`, `John 3:16`, `Jn 3:16`, `롬 8:28`
- Whole chapters (`시 23`) and verse ranges (`Ps 23:1-6`)
- Korean and English text in parallel columns, stacked on narrow screens
- One HTML file with no server, build step or network access needed
- Ships with the full public-domain KJV, and you can plug in your own licensed translations

## Quick start

```sh
git clone https://github.com/rkim9125/LiveVerse.git
cd LiveVerse
git config core.hooksPath .githooks   # enable the copyright-safety pre-commit hook
open index.html
```

The repo includes only the public-domain **King James Version**, in [data/sample/kjv.js](data/sample/kjv.js). The demo therefore shows a single English column and a **DEMO** badge in the header.

## Design decisions

### Loading data with a `<script>` tag instead of `fetch()`

Interpreters often open the page straight from disk, so it has to work over `file://`. Browsers block `fetch()` of local files from a `file://` page, but they allow `<script src>`. Each data file therefore sets `window.BIBLE_DATA`, and the page loads it with a script tag, so the page still runs without a server.

### Separating the app from the Bible text

The first version embedded all of the text in the HTML, as one 8.6MB line. That made the code hard to share, because the translations we use are copyrighted. The page now tries `data/bible_data.js` (local and gitignored) first, then falls back to the bundled KJV. Both files use the same schema, so the app code doesn't care which one it got.

### A pre-commit hook that blocks copyrighted text

A `.gitignore` alone isn't enough, because renaming a file or copying text into a new file gets around it. The hook checks every staged file in three ways:

- it blocks known local data file names
- it blocks signature phrases that appear in the NKJV and the Korean translations but not in the KJV
- it blocks any file over 1MB outside `data/sample/`

I ran it against the full KJV to confirm it raises no false positives, and against renamed copies of the real data to confirm it catches them.

## Using your own translations (Korean/English parallel)

Most modern translations are under copyright, including the NKJV, 개역개정 and 개역한글, so this repo does not include them.
If you are licensed to use a translation, generate a local data file from it:

```sh
# A combined JSON file in the app schema:
#   [{a, en, ko, c: [[ko_verses[], en_verses[]], ...]}, ...]
python3 scripts/build_data.py --combined bible_data.json

# Or one JSON file per translation:
#   [{abbrev, chapters: [[verse, ...], ...]}, ...]
python3 scripts/build_data.py --ko ko.json --en en.json --ko-name 개역한글 --en-name NKJV
```

This writes `data/bible_data.js`. `index.html` loads it automatically when it exists, and falls back to the KJV demo otherwise.
**`data/bible_data.js` is gitignored and must never be committed.**

Book abbreviations (`gn`, `ex`, ... `re`) are listed in [scripts/books.py](scripts/books.py).

You can also run the copyright check on any files directly:

```sh
scripts/check_no_copyrighted.sh path/to/file ...
```

### Project layout

```
index.html                        the app (no Bible text embedded)
data/bible_data.js                your local data (gitignored)
data/sample/kjv.js                public-domain KJV
data/sample/SOURCE.md             KJV source and license
scripts/build_data.py             your JSON -> data/bible_data.js
scripts/build_sample.py           eBible.org KJV -> data/sample/kjv.js
scripts/check_no_copyrighted.sh   blocks copyrighted Bible text from commits
.githooks/pre-commit              runs the check above before each commit
docs/screenshot.png               README screenshot
```

## Real-time sermon assistant

The `feature/realtime` branch adds a live assistant for the interpreter. It listens to the sermon, finds verse references as the preacher says them ("요한복음 3장 16절", "다음 절", or a verse quoted without its number), and shows the passage on the interpreter's own screen in Korean and English, with other candidates beside it. The design is in [docs/realtime-design.md](docs/realtime-design.md).

How it is put together:

- **Speech to text:** a worker on the same Mac (`realtime/backend/stt_worker`) cuts the microphone input into utterances with Silero VAD and transcribes them with Whisper (mlx-whisper, large-v3-turbo) and a prompt of Bible book names. Nothing leaves the computer. Chrome's Web Speech API is kept as a fallback (the Listen button on the screen).
- **Server:** FastAPI with one WebSocket. It detects references in each transcript segment, keeps track of where the preacher is, and decides what the screen shows.
- **Interpreter screen:** a web page served by the server, at `http://127.0.0.1:8000/`.

### Requirements

- A Mac with Apple Silicon for the Whisper worker (the server and the screen run anywhere)
- [uv](https://docs.astral.sh/uv/) and `ffmpeg` (`brew install uv ffmpeg`)
- Your licensed `data/bible_data.js` for Korean and NKJV text; without it the server uses the KJV sample

### Running it

One command starts the server and the Whisper worker on the default microphone, and opens the screen:

```sh
./run-live.sh                         # Ctrl+C stops everything
./run-live.sh --device "MacBook Pro Microphone"
./run-live.sh --list-devices
```

Or start the parts yourself:

```sh
cd realtime/backend
uv sync --group stt
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000          # server
uv run python -m stt_worker --device "MacBook Pro Microphone" \
  --ws ws://127.0.0.1:8000/ws                                     # Whisper worker
open http://127.0.0.1:8000/                                       # interpreter screen
```

On the screen, keys 1 to 3 switch to an alternative, Esc clears, / searches, + and - change the text size, and ? lists the rest.

### Docker

The server and the screen can also run in Docker. The Whisper worker cannot, because a container on macOS has no access to the Metal GPU; run it on the host and point it at the container's port.

```sh
cd realtime
docker build -f backend/Dockerfile -t liveverse-backend:dev .
VERSION=$(git describe --tags --always) docker compose up --build
```

The image holds no Bible text. The repo's `data/` folder is mounted read only.

### Tests

```sh
cd realtime/backend && uv run pytest && uv run ruff check .
cd realtime/frontend && node --test tests/ && npm install && npm run e2e
```

GitHub Actions runs these, the copyright check, and a Docker build with an image check on every push to `feature/realtime`. More on the backend, the evaluation on recorded sermons and speech testing is in [realtime/backend/README.md](realtime/backend/README.md) and [docs/stt-testing.md](docs/stt-testing.md).

## License

The code is under the [MIT License](LICENSE). The KJV text is in the public domain; see [data/sample/SOURCE.md](data/sample/SOURCE.md).
