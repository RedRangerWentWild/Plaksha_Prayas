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
  if curl -sSfL -o "$DEST/$name.png" "$url"; then
    if file "$DEST/$name.png" | grep -q 'PNG image'; then
      printf '  ok    %-12s %s\n' "$name" "$(du -h "$DEST/$name.png" | cut -f1)"
      ok=$((ok+1))
    else
      printf '  BAD   %-12s not a PNG (URL expired?)\n' "$name"
      rm -f "$DEST/$name.png"; fail=$((fail+1))
    fi
  else
    printf '  FAIL  %-12s download error\n' "$name"
    fail=$((fail+1))
  fi
done < "$SRC"
echo "$ok downloaded, $fail failed -> $DEST"

# Earth Engine writes a fractional alpha wherever a layer mixes source scales,
# and a browser's canvas quantisation-damages every channel underneath it.
# Flattening here means a freshly fetched layer is never briefly wrong.
if [ -x ./flatten_alpha.py ]; then ./flatten_alpha.py "$CITY"; fi
