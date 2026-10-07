#!/usr/bin/env bash
# Check that a Docker image holds no Bible text.
#
#   scripts/check_image.sh [image]      (default: liveverse-backend:dev)
#
# Exports the image file system and looks for:
#   1. data files by name (bible_data*, kjv.js, nkjv*, ko_ko*, *.mp3 ...)
#   2. signature phrases of NKJV and Korean Bible text (same as the commit hook)
#   3. KJV text: public domain, but data belongs in the mounted folder, not the image
#   4. anything under /srv/data (must be empty; it is a mount point)

set -euo pipefail
IMAGE="${1:-liveverse-backend:dev}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"; docker rm -f "$CID" >/dev/null 2>&1 || true' EXIT

CID="$(docker create "$IMAGE")"
docker export "$CID" | tar -x -C "$WORK" 2>/dev/null || true

fail=0
names="$(find "$WORK" -type f \( -iname 'bible_data*' -o -iname 'kjv.js' -o -iname 'nkjv*' \
  -o -iname 'ko_ko*' -o -iname '*.mp3' -o -iname '*.wav' -o -iname '*.m4a' -o -iname '*djvu*' \) \
  | sed "s|$WORK||")"
if [ -n "$names" ]; then
  echo "FAIL  data files in the image:"; echo "$names"; fail=1
fi

if [ -n "$(find "$WORK/srv/data" -mindepth 1 2>/dev/null)" ]; then
  echo "FAIL  /srv/data is not empty"; fail=1
fi

decode() { printf '%s' "$1" | base64 --decode 2>/dev/null || printf '%s' "$1" | base64 -D; }
# NKJV Gen 1:1, NKJV John 3:16, Korean Gen 1:1, Korean John 3:16, then KJV Gen 1:1, KJV John 3:16
SIGNATURES=(
  "Y3JlYXRlZCB0aGUgaGVhdmVucyBhbmQgdGhlIGVhcnRo"
  "dGhhdCBIZSBnYXZlIEhpcyBvbmx5IGJlZ290dGVuIFNvbg=="
  "7YOc7LSI7JeQIO2VmOuCmOuLmOydtCDsspzsp4Drpbw="
  "7ZWY64KY64uY7J20IOyEuOyDgeydhCDsnbTsspjrn7wg7IKs656R7ZWY7IKs"
  "SW4gdGhlIGJlZ2lubmluZyBHb2QgY3JlYXRlZCB0aGUgaGVhdmVuIGFuZCB0aGUgZWFydGg="
  "dGhhdCBoZSBnYXZlIGhpcyBvbmx5IGJlZ290dGVuIFNvbg=="
)
for s in "${SIGNATURES[@]}"; do
  phrase="$(decode "$s")"
  hits="$(grep -rlF -- "$phrase" "$WORK/srv" "$WORK/app" 2>/dev/null | sed "s|$WORK||" || true)"
  if [ -n "$hits" ]; then
    echo "FAIL  Bible text found:"; echo "$hits"; fail=1
  fi
done

files="$(find "$WORK/srv" -type f | wc -l | tr -d ' ')"
if [ "$fail" -ne 0 ]; then
  exit 1
fi
echo "check_image: OK ($IMAGE, $files files under /srv, no Bible text)"
