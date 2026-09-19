# The Vanished Blue Grid

Reconstructs a city's lost water bodies from the satellite record, then flags the
buildings sitting on them and the low ground that floods as a result.

Not a flood predictor. An evidence tool: it says which structures are on former
water, ranks them by how much catchment they block, checks any plot before it
gets built on, and answers questions about that plot from a corpus where every
number carries the source it came from.

---

## Run order

**1. Extract (Earth Engine, browser, ~2 min)**

Paste `gee_blue_grid.js` into <https://code.earthengine.google.com> and Run.
The console prints ten `PNG <name>: https://...` lines and six figures.

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

**5. Build the corpus**

```
./build_corpus.py && ./check_corpus.py
```

The first compiles `corpus/**/*.md` into `data/corpus.json`. The second checks
it against the code it describes and refuses to pass if the two have drifted.
`data/corpus.json` is committed, so this is only needed after editing a chunk.

**6. Serve**

```
python3 server.py                          # answers stay local
ANTHROPIC_API_KEY=... python3 server.py    # answers get a model
GEMINI_API_KEY=... python3 server.py       # or Gemini
GROQ_API_KEY=... python3 server.py         # or Groq
```

`file://` will not work — the browser blocks local image sources over CORS.
`python3 -m http.server 8000` still serves everything except `/ask`, in which
case answers are composed locally and say so.

**7. Second city**

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

Any plot or flagged structure can then be asked about in plain language —
*what happens if a construction occurs here*, *should this be allowed*, *will it
affect the flooding level*. See **Asking** below.

### What the plot check decides

Four outcomes, and deliberately none of them is *approve* — this screens, it
does not grant permission.

| | Meaning |
|---|---|
| **REJECT** | Inside live water, on a former water body with ≥ 50% occurrence, on a former bed that already carries construction, or confidently inside a buffer. |
| **REFER TO GROUND SURVEY** | The measurement cannot resolve the question at ±20 m, or the two shorelines disagree. |
| **CONDITIONS REQUIRED** | Low ground: retention and a plinth condition. |
| **NO RECORDED OBJECTION** | Nothing found — which at 30 m is not the same as nothing there. |

Occurrence deliberately does not carry that branch on its own. JRC occurrence
is the share of observations that were water across 1984–2021, so a tank drained
and built over part-way through the window scores *low* precisely because it was
destroyed — the more completely a bed was encroached, the weaker the only signal
that would have rejected it. A bed lost in 2017 came back at 16% and screened as
an unresolved wet season. Two corroborating signals now settle it: construction
already standing on the mapped bed, which is a rejection, and a bed still at the
level of the channel it drained into, which is a referral naming the reason.

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
- `hydro.png` — R: upstream drainage area, **log-packed** as
  `255·log10(1+km²)/log10(1001)`, ceiling 1000 km² · G: metres to the nearest
  trunk channel (> 10 km²) · B: metres above the lowest ground in the study
  area. The only layer not read as a straight byte, so the decode law is
  printed on the certificate. Optional: without it every answer says upstream
  catchment is unavailable rather than guessing at it.

The distance transform runs at **10 m**, which must stay coarser than the
6.36 m/px export or the thumbnail downsamples and averages adjacent byte codes
into distances that never existed. Do not "optimise" it finer.

The plot check reads the same PNGs the map draws, pixel by pixel, in an
offscreen canvas. No server, no API, no network. It cannot fail on stage.

---

## Asking

The ask box is docked at the bottom of the window, in the same slot the
timeline occupies in timeline mode — one place to look for the control you drive
the tool with, and one that never moves as the answer grows. The answer opens
upward from it, so the input stays under the cursor.

Click a plot or a flagged structure, then ask. Three chips cover the questions
this was built for; the box takes anything.

The answer is **retrieved, not recalled**. Two channels feed it:

- **The site record.** Everything `readSite` already measured, plus what can be
  derived from it: runoff displacement, the exposure class, the shoreline
  retreat, the catchment draining through the point.
- **The corpus.** About seventy short chunks under `corpus/`, one idea each,
  every one carrying its source. Chunks declare numeric *triggers* over the
  site record — `distHistoric == 0`, `ruleId == ngt`, `handM <= 1` — and those
  triggers are the dominant retrieval signal. Wording similarity is the other
  35%, scored with BM25 over postings built at compile time.

### Why the corpus holds the numbers

Design rainfall, runoff coefficients, buffer distances, the ±20 m budget and
the exposure bands are all declared in `asserts:` on the chunk that cites their
source. `index.html` keeps a bootstrap copy so the plot check runs before
`corpus.json` lands, and `check_corpus.py` fails if the two ever disagree.

A figure therefore cannot appear in an answer without a chunk id attached,
because there is nowhere else in the system for it to have come from.

### Why the model never types a digit

It emits `{{fact.distPresent}}` placeholders and the client substitutes. Any
bare digit left in the narrative — after placeholders and bracketed citations
are stripped — is a validation failure. So is echoing a verdict other than the
one screening reached, citing a chunk that is not in the pack, or answering a
flooding question without refusing the part that cannot be answered.

A rejected answer is reported on screen, not hidden. The officer is entitled to
know the machine said something the tool would not stand behind.

### Three tiers

| | |
|---|---|
| **0** | A deterministic composer renders **first, always**, before any network call. |
| **1** | If `/ask` reaches a model, it replaces the narrative paragraph only. The verdict, the numbers table and the source list are never regenerated. |
| **2** | A validation failure reverts to tier 0 and says why. |

Pull the network cable and the page behaves identically, minus one paragraph.
Three providers are wired, and the provider follows `VBG_PROVIDER` or
whichever key is present; `VBG_MODEL` overrides the default model. Anthropic
gets the answer through a forced tool call, Gemini and Groq through a response
schema — the same contract and the same validated shape either way, because
the client validates what comes back rather than trusting how it was asked
for. On Groq the default is `openai/gpt-oss-120b`: `json_schema` output is
only honoured by some of the models Groq serves, and one that ignores it
answers in prose that the client then rejects.

Starting `server.py` with no key at all is a supported way to run it:
`/ask` answers 503 and the page stays on the answer it has already rendered.

### What it refuses

Flood depth, level, extent or probability. Damage cost. Legality. The identity
of an owner. Anything at all outside the mapped rectangle, including the runoff
arithmetic — a volume computed from assumptions alone looks exactly like a
measurement and is not one.

`refusal.no-flood-depth-model` names the four things a real depth answer would
need: the drain network, a fine elevation model, a local rainfall curve and a
hydraulic solver. Naming them is more useful than producing a number, because
it says what to go and commission.

### The corpus is not finished

Eighteen chunks carry `verify: true` — drafted from public knowledge and the
citations already in this repo, **not yet checked against the original**. They
are listed by `./check_corpus.py` on every run and marked in the source list
under every answer. The design rainfall and the runoff coefficients are stated
placeholders; every runoff figure scales linearly with the first of them.

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
./validate.py bengaluru --blocks 6x4 --holdout 8 --seeds 6
```

Blocks are contiguous tiles, not random pixels. Neighbouring pixels of one
lake are not independent samples, and a pixel-wise split would inflate every
score. The Otsu threshold is fitted on training blocks only.

**Quote the range, not a run.** With 8 blocks held out of 24, which 8 they are
moves the result more than the choice of threshold does:

| | across six draws |
|---|---|
| pooled IoU | 0.43 – 0.81 |
| per-block median IoU | 0.21 – 0.69 |

`--seeds` exists to make that visible. A single seed reports the draw. The
pooled figure is also the flattering one: one large lake carries it, and the
blocks that score worst are the ones with almost no water in them, where IoU
punishes a handful of misclassified pixels hardest. The defensible summary is
that MNDWI reproduces the JRC reference well where there is water to find and
poorly where there is barely any — which is a statement about the metric and
the terrain as much as about the method.

This pipeline contains no learned model. Every flag traces to a published
dataset and a stated threshold, which is why a judge can be handed the reason
for any individual flag rather than a confidence score.

---

## Files

```
gee_blue_grid.js   extraction — the only thing that touches Earth Engine
index.html         the whole app, single file, no build step
server.py          serves the app and holds the API key; /ask proxies to Claude
fetch_layers.sh    downloads exported PNGs into data/<city>/
hotspots.py        finds where encroachment concentrates, prints coordinates
validate.py        scores MNDWI against the JRC reference on held-out blocks
verify_encoding.py proves the byte-packed layers decoded losslessly
build_corpus.py    compiles corpus/**/*.md into data/corpus.json
check_corpus.py    checks the corpus against the code it describes
corpus/            the knowledge, one idea per file — see corpus/README.md
data/<city>/       layers, stats.json, flagged_buildings.geojson
data/corpus.json   the compiled corpus, committed
urls/<city>.txt    pasted Earth Engine console links
```

Before committing:

```
./check_corpus.py && ./verify_encoding.py bengaluru
```
