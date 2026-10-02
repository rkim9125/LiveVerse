# Bible Verse Lookup (성경 구절 조회)

This is a lookup page for Korean–English parallel Bible verses. It is one HTML file and runs offline, with no server or build step.

You can type references in Korean or English. For example: `요 3:16`, `John 3:16`, `Jn 3:16`, `시 23`, `Ps 23:1-6` or `롬 8:28`.

## Quick start (demo)

```sh
git clone <this repo>
cd <repo>
git config core.hooksPath .githooks   # enable the copyright-safety pre-commit hook
open index.html
```

The repo includes only the public-domain **King James Version**, in [data/sample/kjv.js](data/sample/kjv.js). The demo therefore shows a single English column and a **DEMO** badge in the header.

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

Book abbreviations (`gn`, `ex`, … `re`) are listed in [scripts/books.py](scripts/books.py).

## Project layout

```
index.html                        the app (no Bible text embedded)
data/bible_data.js                your local data (gitignored)
data/sample/kjv.js                public-domain KJV
data/sample/SOURCE.md             KJV source and license
scripts/build_data.py             your JSON → data/bible_data.js
scripts/build_sample.py           eBible.org KJV → data/sample/kjv.js
scripts/check_no_copyrighted.sh   blocks copyrighted Bible text from commits
.githooks/pre-commit              runs the check above before each commit
```

The page loads data with a `<script>` tag rather than `fetch()`. That way it also works when you open it directly from disk (`file://`).

## Pre-commit hook

Enable it once after cloning:

```sh
git config core.hooksPath .githooks
```

The hook rejects a commit if any staged file:

- has a local-data file name (`nkjv*`, `bible_data*`, `*.bak`, …)
- contains signature phrases from NKJV or Korean Bible text
- is larger than 1MB (files under `data/sample/` are exempt)

You can also run the check on any files directly:

```sh
scripts/check_no_copyrighted.sh path/to/file ...
```

## License

The code is under the [MIT License](LICENSE). The KJV text is in the public domain; see [data/sample/SOURCE.md](data/sample/SOURCE.md).
