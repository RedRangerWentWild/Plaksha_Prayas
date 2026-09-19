#!/usr/bin/env python3
"""Prove the byte-packed measurement layers decoded losslessly.

The distance fields and the history layer smuggle real quantities through an
8-bit PNG channel. If Earth Engine's visualize() stretched them, or the
thumbnail resampled them, every distance the tool reports would be wrong and
entirely plausible. Nothing else in the pipeline would notice.

The decisive test is cross-consistency rather than eyeballing: distance to a
feature must be zero wherever that feature's own mask is set. Two layers built
by separate code paths have to agree, or something moved.

    ./verify_encoding.py bengaluru
"""
import sys
import numpy as np
from PIL import Image

city = sys.argv[1] if len(sys.argv) > 1 else 'bengaluru'
fails = []


def load(name, required=True):
    try:
        return np.asarray(Image.open(f'data/{city}/{name}.png').convert('RGBA'))
    except (FileNotFoundError, OSError):
        if required:
            sys.exit(f'missing or unreadable data/{city}/{name}.png')
        return None


def check(ok, msg):
    print(('  PASS  ' if ok else '  FAIL  ') + msg)
    if not ok:
        fails.append(msg)


buf = load('buffers')
hist = load('history', required=False)
present, historic, flowpath = load('present'), load('historic'), load('flowpath')

print(f"\nbuffers.png {buf.shape[1]}x{buf.shape[0]}"
      + (f"   history.png {hist.shape[1]}x{hist.shape[0]}" if hist is not None
         else "   history.png ABSENT") + "\n")

# Every layer is georeferenced by stretching it across the same AOI rectangle,
# so a layer with different pixel dimensions is on a different grid and every
# lookup into it lands on the wrong ground. This is silent: the numbers stay
# plausible. Check it before anything else.
ref_shape = historic.shape[:2]
for nm, im in [('buffers', buf), ('present', present), ('flowpath', flowpath)] + \
              ([('history', hist)] if hist is not None else []):
    check(im.shape[:2] == ref_shape,
          f'{nm} is {im.shape[1]}x{im.shape[0]}, historic is {ref_shape[1]}x{ref_shape[0]}')
if fails:
    print('\nGeometry mismatch - layers are on different grids. Fix the export '
          'before trusting anything below.')
    sys.exit(1)

inside = buf[..., 3] == 255          # alpha 255 marks the study area
print(f'study area covers {100 * inside.mean():.1f}% of the frame\n')

# 1. A distance field is graded. A mask is not. Telling them apart catches a
#    visualize() call that collapsed the range.
for ch, name in [(0, 'R  distance to water today'),
                 (1, 'G  distance to 1984-99 water'),
                 (2, 'B  distance to drainage line')]:
    v = buf[..., ch][inside]
    uniq = len(np.unique(v))
    check(uniq > 30, f'{name}: {uniq} distinct values, range {v.min()}-{v.max()}'
          + ('' if uniq > 30 else '   <-- looks like a mask, not a distance'))

# 2. The decisive one. Distance must read zero exactly where the feature's own
#    mask is set, and those two layers were produced by different code paths.
for ch, mask, name in [(0, present, 'present water'),
                       (1, historic, '1984-99 water'),
                       (2, flowpath, 'drainage line')]:
    on = (mask[..., 3] > 128) & inside
    if not on.any():
        check(False, f'{name}: mask is empty, cannot cross-check')
        continue
    d = buf[..., ch][on]
    frac = float((d <= 10).mean())
    check(frac > 0.95, f'{name}: {100*frac:.1f}% of mask pixels read <= 10 m '
                       f'(median {np.median(d):.0f} m)')

# 3. Distance has to grow with distance.
on = (historic[..., 3] > 128) & inside
off = (historic[..., 3] <= 128) & inside
if on.any() and off.any():
    check(buf[..., 1][off].mean() > buf[..., 1][on].mean(),
          f'G rises outside the 1984-99 mask ({buf[...,1][off].mean():.0f} m) '
          f'versus inside it ({buf[...,1][on].mean():.0f} m)')

if hist is None:
    print('\n  history layer absent - skipping year and occurrence checks')
else:
    yc = hist[..., 0][inside]
    yrs = yc[yc > 0]
    if yrs.size:
        lo, hi = 1983 + int(yrs.min()), 1983 + int(yrs.max())
        check(1984 <= lo and hi <= 2021,
              f'last-water year decodes to {lo}-{hi} (expected inside 1984-2021)')
        print(f'          {100*(yc>0).mean():.1f}% of the study area held water at some point')
    else:
        check(False, 'no non-zero year codes at all')

    occ = hist[..., 1][inside]
    check(occ.max() <= 100, f'JRC occurrence peaks at {occ.max()} (must not exceed 100)')

    if on.any():
        med = float(np.median(hist[..., 1][on]))
        check(med > 20, f'median occurrence inside the 1984-99 mask is {med:.0f}%')

print()
if fails:
    print(f'{len(fails)} CHECK(S) FAILED - do not trust any distance the tool reports.')
    sys.exit(1)
print('All checks passed. The bytes survived the round trip; distances are metres.')
