# CLAUDE.md

## Project

LiveVerse is a Korean/English Bible verse lookup for church interpreters. The static app is `index.html`, and it loads `data/bible_data.js` (local only) or the public-domain KJV in `data/sample/kjv.js`.

## Rules

- **Realtime work:**
  - Before planning or changing anything in the realtime sermon assistant (`realtime/`, speech input, reference detection, backend, interpreter screen), read [docs/realtime-design.md](docs/realtime-design.md) and follow it.
  - If a change departs from the design, update the design document in the same change and say why.
- **Copyrighted Bible text:**
  - Never commit copyrighted Bible text (NKJV, 개역한글, 개역개정), never bake it into Docker images, and never put it in test fixtures.
  - Tests and CI use the KJV only.
  - Run `scripts/check_no_copyrighted.sh` on changed files before committing.
- **Static demo:** keep `index.html` and the static demo working on their own. New realtime code lives under `realtime/` on the `feature/realtime` branch.
- **Writing style:** write public docs in English, plainly, without em dashes or en dashes.
