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
The console prints nine `PNG <name>: https://...` lines and six figures.

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
| **Timeline** | What was here, and what happened to it? Scrub the 2003–07 composite to the 2023–25 one. Space bar plays it. |
| **Plot check** | May this plot be built on? Click anywhere for a screening decision against a selectable buffer regime. |
| **Downstream** | Who pays? Low ground receiving the runoff the lost tanks used to hold. |

### What the plot check decides

Four outcomes, and deliberately none of them is *approve* — this screens, it
does not grant permission.

| | Meaning |
|---|---|
| **REJECT** | Inside live water, on a former water body with ≥ 50% occurrence, or confidently inside a buffer. |
| **REFER TO GROUND SURVEY** | The measurement cannot resolve the question at ±20 m, or the two shorelines disagree. |
| **CONDITIONS REQUIRED** | Low ground: retention and a plinth condition. |
| **NO RECORDED OBJECTION** | Nothing found — which at 30 m is not the same as nothing there. |

The finding worth demonstrating is the shoreline disagreement. An applicant
measures their buffer from the water's edge *as it stands today*. Where the
lake has already shrunk, that edge is one encroachment produced, so the buffer
measured from the 1984–99 edge lands somewhere else entirely. When the two
distances differ by more than one JRC pixel the tool says so.

Buffer distances are **operator configuration**, not a legal determination:

| Ruleset | Lake | Drain |
|---|---|---|
| State revision | 30 m | 25 m |
| NGT, upheld by the Supreme Court | 75 m | 50 m |

A consequence worth knowing before anyone asks: at ±20 m measurement
uncertainty, the 30 m buffer is barely outside the error bar, so under that
ruleset most near-lake plots return REFER rather than REJECT. The 75 m buffer
is confidently testable. That is a fact about the rule, not a defect in the
tool.

### Layer channels

Two exports carry measurements rather than colour and are never drawn:

- `buffers.png` — R: metres to today's water edge · G: metres to the 1984–99
  edge · B: metres to the nearest drainage line. 255 means "beyond the ceiling".
- `history.png` — R: last year water was recorded, as `year − 1983`, 0 = never
  · G: JRC occurrence percent · B: height above nearest drainage, metres.

The distance transform runs at **10 m**, which must stay coarser than the
6.36 m/px export or the thumbnail downsamples and averages adjacent byte codes
into distances that never existed. Do not "optimise" it finer.

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

## Accuracy

There is no surveyed encroachment dataset for this catchment, so there is no
ground truth to score against and no honest "model accuracy" number to report.
What can be measured is whether the reference this pipeline depends on is
reproducible by an independent method.

`validate.py` scores Landsat 5 MNDWI against JRC Global Surface Water's own
per-year classification, over the same pixels in the same years (2003–2007),
on held-out spatial blocks:

```
./validate.py bengaluru --blocks 6x4 --holdout 8
```

Blocks are contiguous tiles, not random pixels. Neighbouring pixels of one
lake are not independent samples, and a pixel-wise split would inflate every
score. The Otsu threshold is fitted on training blocks only.

This pipeline contains no learned model. Every flag traces to a published
dataset and a stated threshold, which is why a judge can be handed the reason
for any individual flag rather than a confidence score.

---

## Files

```
gee_blue_grid.js   extraction — the only thing that touches Earth Engine
index.html         the whole app, single file, no build step
fetch_layers.sh    downloads exported PNGs into data/<city>/
hotspots.py        finds where encroachment concentrates, prints coordinates
validate.py        scores MNDWI against the JRC reference on held-out blocks
data/<city>/       layers, stats.json, flagged_buildings.geojson
urls/<city>.txt    pasted Earth Engine console links
```
