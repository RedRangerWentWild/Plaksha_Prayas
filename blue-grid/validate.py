#!/usr/bin/env python3
"""Score water detection against the JRC reference on held-out ground.

What this measures, precisely: how well an independent spectral method
reproduces JRC Global Surface Water's own per-year classification over the
same pixels in the same years (2003-2007).

What it does NOT measure: accuracy against surveyed ground truth. There is no
labelled encroachment dataset for this catchment, so no such number exists.
Anyone reporting one has either found labels worth citing or invented them.

Threshold selection happens on training blocks only. Blocks are contiguous
tiles, not random pixels, because neighbouring pixels of the same lake are not
independent samples and a pixel-wise split would inflate every score here.

    ./validate.py bengaluru
    ./validate.py bengaluru --blocks 8x6 --holdout 13
"""
import argparse, math, sys
import numpy as np
from PIL import Image

BOUNDS = {
    'bengaluru': (77.63, 12.90, 77.75, 12.97),
    'chennai':   (80.180, 12.900, 80.280, 12.985),
}

ap = argparse.ArgumentParser()
ap.add_argument('city')
ap.add_argument('--blocks', default='6x4', help='grid of blocks, COLSxROWS')
ap.add_argument('--holdout', type=int, default=8, help='how many blocks to hold out')
ap.add_argument('--seed', type=int, default=0)
ap.add_argument('--seeds', type=int, default=1,
                help='re-run over this many held-out draws and report the spread')
ap.add_argument('--bounds', help='west,south,east,north if the city is not in the table')
a = ap.parse_args()

W, S, E, N = (tuple(float(x) for x in a.bounds.split(','))
              if a.bounds else BOUNDS.get(a.city, ()) or sys.exit(f'unknown city {a.city!r}'))

def load(name):
    try:
        return Image.open(f'data/{a.city}/{name}.png').convert('RGBA')
    except FileNotFoundError:
        sys.exit(f'missing data/{a.city}/{name}.png — add the benchmark exports from '
                 f'gee_blue_grid.js to urls/{a.city}.txt and re-run ./fetch_layers.sh {a.city}')

ref_im, mn_im = load('ref2005'), load('mndwi2005')
if ref_im.size != mn_im.size:
    sys.exit(f'size mismatch: ref {ref_im.size} vs mndwi {mn_im.size}')

ref_a = np.asarray(ref_im)
mn_a = np.asarray(mn_im)

truth = ref_a[..., 0] > 127                      # white = water in the reference
valid = mn_a[..., 3] > 0                         # cloud-masked pixels carry no evidence
mndwi = mn_a[..., 0].astype(np.float32) / 255.0 * 2.0 - 1.0   # grey ramp back to -1..1

H, Wd = truth.shape
GX, GY = (int(v) for v in a.blocks.lower().split('x'))
if a.holdout >= GX * GY:
    sys.exit(f'--holdout {a.holdout} must be fewer than the {GX*GY} blocks available')

# Ground area, for reporting how much land the held-out set actually covers.
mid = math.radians((S + N) / 2)
km2_total = (E - W) * 111.320 * math.cos(mid) * (N - S) * 110.574

ys = np.arange(H) * GY // H
xs = np.arange(Wd) * GX // Wd
block_id = ys[:, None] * GX + xs[None, :]

rng = np.random.default_rng(a.seed)
test_blocks = set(rng.choice(GX * GY, size=a.holdout, replace=False).tolist())
is_test = np.isin(block_id, list(test_blocks))

train_sel = valid & ~is_test
test_sel = valid & is_test
if not test_sel.any():
    sys.exit('no valid pixels in the held-out blocks — try a different --seed')

def otsu(x):
    """Threshold maximising between-class variance, fitted on training pixels only."""
    hist, edges = np.histogram(x, bins=256, range=(-1, 1))
    centres = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist).astype(np.float64)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centres) / np.maximum(w0, 1)
    m1 = (np.sum(hist * centres) - np.cumsum(hist * centres)) / np.maximum(w1, 1)
    between = w0 * w1 * (m0 - m1) ** 2
    return float(centres[int(np.argmax(between))])

def score(pred, sel):
    p, t = pred[sel], truth[sel]
    tp = int(np.count_nonzero(p & t))
    fp = int(np.count_nonzero(p & ~t))
    fn = int(np.count_nonzero(~p & t))
    iou = tp / (tp + fp + fn) if tp + fp + fn else float('nan')
    prec = tp / (tp + fp) if tp + fp else float('nan')
    rec = tp / (tp + fn) if tp + fn else float('nan')
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else float('nan')
    return iou, f1, prec, rec, tp, fp, fn

t_otsu = otsu(mndwi[train_sel])
methods = [('MNDWI > 0', mndwi > 0.0), (f'Otsu/MNDWI ({t_otsu:+.3f})', mndwi > t_otsu)]

km2_test = km2_total * len(test_blocks) / (GX * GY)
print(f'\ncity            {a.city}')
print(f'reference       JRC GSW YearlyHistory, waterClass >= 2, 2003-2007')
print(f'prediction      Landsat 5 MNDWI, same years, same pixels')
print(f'blocks          {GX}x{GY} = {GX*GY}, {len(test_blocks)} held out '
      f'({km2_test:.1f} km2 of {km2_total:.1f} km2)')
print(f'valid pixels    {int(np.count_nonzero(test_sel)):,} in held-out blocks, '
      f'{100*truth[test_sel].mean():.2f}% water in reference\n')

print('  ' + '-' * 62)
print(f"  {'method':<22}{'IoU':>8}{'F1':>8}{'prec':>8}{'recall':>9}")
print('  ' + '-' * 62)
for name, pred in methods:
    iou, f1, prec, rec, *_ = score(pred, test_sel)
    print(f'  {name:<22}{iou:>8.3f}{f1:>8.3f}{prec:>8.3f}{rec:>9.3f}')
print('  ' + '-' * 62)

# Per-block spread matters more than the pooled figure: one large lake can
# carry an entire catchment's score and hide that most blocks are poor.
print('\n  per held-out block, MNDWI > 0:')
ious = []
for b in sorted(test_blocks):
    sel = valid & (block_id == b)
    if np.count_nonzero(sel) < 100 or not truth[sel].any():
        continue
    iou, *_ = score(mndwi > 0.0, sel)
    ious.append(iou)
    print(f'    block {b:<4} IoU {iou:.3f}   water {100*truth[sel].mean():5.2f}%')
if ious:
    print(f'\n    median {np.median(ious):.3f}   mean {np.mean(ious):.3f}   '
          f'sd {np.std(ious):.3f}   n={len(ious)}')

# One split is one sample. With 8 blocks held out of 24, which 8 they are moves
# the per-block median across a range wider than the difference between the two
# methods being compared, so quoting a single seed reports the draw rather than
# the method. Re-running over several seeds is the only way to see that, and
# seeing it is the point: the honest summary is the spread, not the best run.
if a.seeds > 1:
    print(f'\n  across {a.seeds} held-out draws:')
    pooled, medians = [], []
    for sd in range(a.seeds):
        rng2 = np.random.default_rng(sd)
        tb = set(rng2.choice(GX * GY, size=a.holdout, replace=False).tolist())
        tsel = valid & np.isin(block_id, list(tb))
        trsel = valid & ~np.isin(block_id, list(tb))
        if not tsel.any() or not trsel.any():
            continue
        pooled.append(score(mndwi > 0.0, tsel)[0])
        per = []
        for b in sorted(tb):
            sel = valid & (block_id == b)
            if np.count_nonzero(sel) < 100 or not truth[sel].any():
                continue
            per.append(score(mndwi > 0.0, sel)[0])
        if per:
            medians.append(float(np.median(per)))
        print(f'    seed {sd:<3} pooled IoU {pooled[-1]:.3f}   '
              f'per-block median {medians[-1] if medians else float("nan"):.3f}')
    if medians:
        print(f'\n    pooled IoU      {np.min(pooled):.3f} to {np.max(pooled):.3f}'
              f'   (median {np.median(pooled):.3f})')
        print(f'    per-block median {np.min(medians):.3f} to {np.max(medians):.3f}'
              f'   (median {np.median(medians):.3f})')
        print('\n    Report the range. A single seed is one draw, and the draw'
              '\n    moves the answer more than the choice of threshold does.')

print('\n  No learned model is scored here. This pipeline contains none —')
print('  every flag traces to a published dataset and a stated threshold.')
print()
