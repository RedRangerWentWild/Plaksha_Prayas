# The Vanished Blue Grid

Reconstructs a city's lost water bodies from the satellite record, then flags the
buildings sitting on them and the low ground that floods as a result.

Not a flood predictor. An evidence tool: it says which structures are on former
water, ranks them by how much catchment they block, and checks any plot before
it gets built on.

---

## Run order

**1. Extract (Earth Engine, browser, ~2 min)**

Paste `gee_blue_grid.js` into <https://code.earthengine.google.com> and Run.
The console prints seven `PNG <name>: https://...` lines and six figures.

**2. Pull the layers down**

Copy every `PNG ...` line into `urls/bengaluru.txt`, then:

```
./fetch_layers.sh bengaluru
```

Earth Engine thumbnail URLs expire. If a download reports `BAD`, re-Run the
script and copy fresh links.

**3. Pull the buildings**

In Earth Engine, open the **Tasks** tab and run `blue_grid_flagged_buildings`.
It lands in Drive. Rename and move it:

```
data/bengaluru/flagged_buildings.geojson
```

This unlocks the ranked list, the per-building evidence panel and CSV export.
Everything else works without it.

**4. Update the numbers**

Put the printed hectare figures into `data/bengaluru/stats.json`.

**5. Serve**

```
python3 -m http.server 8000
```

`file://` will not work — the browser blocks local image sources over CORS.

**6. Second city**

In `gee_blue_grid.js` set `var CITY = CITIES.chennai`, Run, repeat steps 2–4
with `chennai`, then:

```
./hotspots.py chennai
```

Paste the printed block into the `CITIES` table in `index.html`.

---

## The three modes

| Mode | Question it answers |
|---|---|
| **Timeline** | What was here, and what happened to it? Scrub 2005 → 2025, real imagery underneath. Space bar plays it. |
| **Plot check** | Can this plot be built on? Click anywhere for an instant verdict. |
| **Downstream** | Who pays? Low ground receiving the runoff the lost tanks used to hold. |

The plot check reads the same PNGs the map draws, pixel by pixel, in an
offscreen canvas. No server, no API, no network. It cannot fail on stage.

---

## Method, and where it is weak

Both eras of water come from **one** source: the JRC Global Surface Water
`transition` band, which compares 1984–1999 against 2000–2021 across the whole
Landsat archive with a single method. Hand-differencing a Landsat composite
against a Sentinel-2 one cannot be made symmetric — the finer sensor finds more
water whatever is on the ground, and that shows up as water appearing.

Terrain comes from **MERIT Hydro**: `upa` (upstream drainage area) and `hnd`
(height above nearest drainage), both precomputed, so there is no flow
accumulation to calculate.

Buildings come from **Google Open Buildings v3**, filtered to confidence ≥ 0.70
and area ≥ 40 m².

Known limits, stated up front:

- JRC is 30 m. Tanks under roughly half a hectare are invisible.
- MERIT Hydro is 90 m. It resolves catchment drainage, not individual rajakaluves.
- Dynamic World's `built` class is conservative under tree canopy, so the
  built-on-water hectare figure understates. The building intersection is the
  stronger number.
- Hyacinth-covered lakes read as vegetation in every water index. Dynamic World
  class 3 is treated as surviving water specifically so Bellandur and Varthur
  are not reported as destroyed.

Every flag is a lead for ground verification, not a finding of fact.

---

## Files

```
gee_blue_grid.js   extraction — the only thing that touches Earth Engine
index.html         the whole app, single file, no build step
fetch_layers.sh    downloads exported PNGs into data/<city>/
hotspots.py        finds where encroachment concentrates, prints coordinates
data/<city>/       layers, stats.json, flagged_buildings.geojson
urls/<city>.txt    pasted Earth Engine console links
```
