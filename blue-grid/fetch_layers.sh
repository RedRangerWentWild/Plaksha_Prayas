#!/usr/bin/env bash
# Download the PNG layers Earth Engine printed, into data/<city>/.
#
#   1. Run gee_blue_grid.js, copy every "PNG <name>: https://..." console line
#      into urls/<city>.txt (one per line, any surrounding text is tolerated).
#   2. ./fetch_layers.sh <city>
#
# Earth Engine thumbnail URLs expire, so re-copy them if a download 404s.
set -u
CITY="${1:-bengaluru}"
SRC="urls/${CITY}.txt"
DEST="data/${CITY}"

[ -f "$SRC" ] || { echo "missing $SRC — paste the PNG lines from the Earth Engine console into it"; exit 1; }
mkdir -p "$DEST"

ok=0; fail=0
while IFS= read -r line; do
  url=$(printf '%s' "$line" | grep -oE 'https://[^ "]+' | head -1)
  [ -z "$url" ] && continue
  # Layer name is the word just before the colon, e.g. "PNG rgb2005: https://..."
  name=$(printf '%s' "$line" | sed -E 's/[[:space:]]*:[[:space:]]*https.*$//' | awk '{print $NF}')
  [ -z "$name" ] && continue
  # Staged through a part file, because the normal way to use this script is
  # to re-run it after ONE new layer was added, with every other URL in the
  # list long expired. Downloading straight onto the destination meant a 404
  # truncated a layer that was already on disk and correct: the fetch reported
  # a failure and silently destroyed the evidence at the same time.
  part="$DEST/.$name.png.part"
  if curl -sSfL -o "$part" "$url" && file "$part" | grep -q 'PNG image'; then
    mv -f "$part" "$DEST/$name.png"
    printf '  ok    %-12s %s\n' "$name" "$(du -h "$DEST/$name.png" | cut -f1)"
    ok=$((ok+1))
  else
    rm -f "$part"
    if [ -f "$DEST/$name.png" ]; then
      printf '  skip  %-12s URL expired; kept the copy already on disk\n' "$name"
    else
      printf '  FAIL  %-12s download failed and nothing on disk\n' "$name"
    fi
    fail=$((fail+1))
  fi
done < "$SRC"
echo "$ok downloaded, $fail failed -> $DEST"

# Earth Engine writes a fractional alpha wherever a layer mixes source scales,
# and a browser's canvas quantisation-damages every channel underneath it.
# Flattening here means a freshly fetched layer is never briefly wrong.
if [ -x ./flatten_alpha.py ]; then ./flatten_alpha.py "$CITY"; fi
