# kjv.js — source

- **Text**: King James Version (Authorized Version), standardized text of 1769
- **Source**: eBible.org, `eng-kjv` — https://ebible.org/Scriptures/eng-kjv_vpl.zip
- **License**: Public Domain (as stated by eBible.org).
  Outside the UK the KJV is in the public domain. In the UK, printing rights are
  held under Crown letters patent (Cambridge University Press and others).
- **Changes**, made by `scripts/build_sample.py`:
  - Only the 66-book Protestant canon is kept. The Apocrypha books in the source are skipped.
  - Translator-supplied words marked `[like this]` keep the word and lose the brackets.
  - Paragraph markers (`¶`) are removed.
- **Counts**: 66 books, 1,189 chapters, 31,102 verses

To regenerate:

```sh
python3 scripts/build_sample.py
```
