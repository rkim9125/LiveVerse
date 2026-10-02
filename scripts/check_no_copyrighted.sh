#!/usr/bin/env bash
# Blocks copyrighted Bible text (NKJV, Korean translations) from being committed.
#
#   scripts/check_no_copyrighted.sh            # check staged files (pre-commit)
#   scripts/check_no_copyrighted.sh FILE...    # check files on disk
#
# Checks:
#   1. Forbidden file names (local data / source files)
#   2. Signature phrases that appear in NKJV or Korean Bible text but not in the KJV
#   3. Files over 1MB, except under data/sample/ (the public-domain KJV)

set -u

MAX_BYTES=1048576

# Signatures are kept base64-encoded (and not quoted in comments) so this
# script and docs about it do not match themselves. In order:
#   NKJV Gen 1:1     (plural "heavens"; the KJV has singular "heaven")
#   NKJV John 3:16   (capitalised divine pronouns; the KJV uses lowercase)
#   Korean Gen 1:1
#   Korean John 3:16
SIGNATURES_B64=(
  "Y3JlYXRlZCB0aGUgaGVhdmVucyBhbmQgdGhlIGVhcnRo"
  "dGhhdCBIZSBnYXZlIEhpcyBvbmx5IGJlZ290dGVuIFNvbg=="
  "7YOc7LSI7JeQIO2VmOuCmOuLmOydtCDsspzsp4Drpbw="
  "7ZWY64KY64uY7J20IOyEuOyDgeydhCDsnbTsspjrn7wg7IKs656R7ZWY7IKs"
)

FORBIDDEN_NAME_RE='(^|/)(nkjv[^/]*|NKJV[^/]*|ko_ko[^/]*|bible_data[^/]*|b_25\.html|[^/]*\.bak)$'

if [ "$#" -gt 0 ]; then
  MODE=disk
  FILES=("$@")
else
  MODE=staged
  FILES=()
  while IFS= read -r f; do FILES+=("$f"); done < <(git diff --cached --name-only --diff-filter=ACMR)
fi

content() {
  if [ "$MODE" = staged ]; then git show ":$1"; else cat -- "$1"; fi
}

size() {
  if [ "$MODE" = staged ]; then git cat-file -s ":$1"; else wc -c < "$1" | tr -d ' '; fi
}

decode() { printf '%s' "$1" | base64 --decode 2>/dev/null || printf '%s' "$1" | base64 -D; }

SIGS=()
for s in "${SIGNATURES_B64[@]}"; do SIGS+=("$(decode "$s")"); done

fail=0
for f in "${FILES[@]+"${FILES[@]}"}"; do
  if [[ "$f" =~ $FORBIDDEN_NAME_RE ]]; then
    echo "BLOCKED  $f: forbidden file name (local Bible data)"
    fail=1
    continue
  fi

  for sig in "${SIGS[@]}"; do
    if content "$f" | grep -qF -- "$sig"; then
      echo "BLOCKED  $f: contains copyrighted Bible text (\"$sig\")"
      fail=1
    fi
  done

  case "$f" in
    data/sample/*) ;;
    *)
      bytes=$(size "$f")
      if [ "$bytes" -gt "$MAX_BYTES" ]; then
        echo "BLOCKED  $f: $bytes bytes > 1MB (only data/sample/ may exceed this)"
        fail=1
      fi
      ;;
  esac
done

if [ "$fail" -ne 0 ]; then
  echo
  echo "Commit aborted: copyrighted Bible data must not be committed. See README.md."
  exit 1
fi
echo "check_no_copyrighted: OK (${#FILES[@]} file(s) checked)"
