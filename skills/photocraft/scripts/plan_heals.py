#!/usr/bin/env python3
"""Plan a precise skin retouch: many small Healing Brush dabs, each copying real texture from
clean nearby skin. No blur, no content-aware synthesis.

usage: plan_heals.py crop.png ref.png cropX cropY area.json [--threshold N] [--max-size 10]
                     [--bright-weight 0.7 --ref-small ref3.png] [--add X,Y[,D] …] [--heal-marks]
                     [--layer ID] [--sample current|currentAndBelow|all] [--fallback spot|skip]
                     [--steps steps.json | --dry-run] [--overlay overlay.png [--overlay-scale S]]

crop.png   the face cropped from the photo at full resolution (image.crop)
ref.png    the same crop + filter.noise.median (radius ~10): the "clean skin" reference
area.json  {"skin": polygon or [polygon, …], "exclude": [[x0, y0, x1, y1] or polygon, …]} in full-image coords
Writes a pc.py script (list of paint.healingBrush steps, after a layer.select of --layer) and an overlay (2x the crop,
1x above 800 px): red rings = dabs, blue = kept moles and freckles, yellow = no clean source.
--bright-weight > 0 also catches light bumps (closed comedones, flaky bits) that catch a rim light.
Self-calibrating: the threshold is --noise-mult (4.3) x the score's robust spread on the skin around each spot, per
64 px tile (at least 6), unless --threshold is given; the source speck limit is 5 x the skin's own spread (at least 6)
unless --source-max-speck is. Both are printed. A fixed threshold of 7 flagged nearly every pore of a sharp 18 MP
portrait (3060 dabs); the automatic one planned 106 there, and on an acne crop it kept to the acne. Spots that look
like moles, freckles or dark pores (brown, well defined) are kept unless --heal-marks, and listed.
On the High layer of frequency separation (freqsep.py): --layer <High> --hardness 95 --fallback skip, and keep
--sample current. Sampling below it reads the visible photo into a Linear Light layer (a spot 57-66 levels too
light, measured), and a Spot Healing fallback on High smooths the texture (to 0.37 of the skin's around it).
Spots with no clean source nearby that aren't planned are printed with their positions, written to
<steps>_skipped.json and drawn yellow on the overlay: heal those by hand. With --sample currentAndBelow (healing on
an empty layer) there is no Spot Healing fallback at all: it would sample the visible layers above too.
"""
import argparse
import json
import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import imgops
import pngio

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("crop"); ap.add_argument("ref"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
ap.add_argument("area")
ap.add_argument("--threshold", type=float,
                help="blemish score a spot must reach. Default: --noise-mult x the score's robust spread on the skin "
                     "around it (at least 6), measured per 64 px tile: pores and grain on sharp skin set their own floor")
ap.add_argument("--noise-mult", type=float, default=4.3, help="the automatic threshold, in units of the local spread")
ap.add_argument("--max-size", type=int, default=10)
ap.add_argument("--min-size", type=int, default=5)
ap.add_argument("--hardness", type=int, default=80)
ap.add_argument("--dark-weight", type=float, default=0.5, help="weight of darkness vs redness (pores/stubble are dark, acne is red)")
ap.add_argument("--bright-weight", type=float, default=0, help="weight of light bumps (try 0.7, with --ref-small, on rim-lit skin)")
ap.add_argument("--ref-small", help="the crop + median radius 3: light bumps are measured against it, so the edge "
                                    "of a highlight (which a radius-10 median lags behind) doesn't count as a bump")
ap.add_argument("--min-area", type=int, default=6, help="px; 2 to catch tiny whiteheads")
ap.add_argument("--source-max-speck", type=float,
                help="with --ref-small: a source may not contain any pixel this many levels lighter or darker than "
                     "its radius-3 median, so a whitehead or dark pore is never copied onto a healed spot. Default: 5 x "
                     "the skin's own robust spread there (at least 6), about its 99.8th percentile")
ap.add_argument("--max-gradient", type=float, default=2.0,
                help="levels/px: skip skin where the clean reference itself changes this fast (edge of a highlight "
                     "or shadow, which a median lags behind and would read as a 'blemish')")
ap.add_argument("--add", action="append", default=[], metavar="X,Y[,D]",
                help="also heal this spot (full-image coords, diameter D, default 8): a blemish you can see that the "
                     "detector misses, e.g. a scab that is half light, half dark. Repeatable")
ap.add_argument("--layer", type=int)
ap.add_argument("--sample", choices=["current", "currentAndBelow", "all"], default="current",
                help="what the dabs copy from: the layer itself (a duplicate of the photo, or FS High), or the layers "
                     "below too (healing on an empty layer)")
ap.add_argument("--fallback", choices=["spot", "skip"], default="spot",
                help="where no clean source is near: a small Spot Healing dab, or nothing (on FS High). Nothing with "
                     "--sample currentAndBelow either; skipped spots are listed and drawn yellow, --add spots always kept")
ap.add_argument("--heal-marks", action="store_true",
                help="also heal spots that look like moles or freckles (brown, well defined); by default they are "
                     "left out, listed and drawn blue")
ap.add_argument("--steps", default="steps.json")
ap.add_argument("--dry-run", action="store_true", help="plan and report (and draw --overlay) but write no steps file")
ap.add_argument("--overlay")
ap.add_argument("--overlay-scale", type=int, help="overlay size: x the crop (default 2, or 1 for crops over 800 px)")
a = ap.parse_args()

w, h, P = pngio.read(a.crop)
_, _, M = pngio.read(a.ref)
M3 = pngio.read(a.ref_small)[2] if a.ref_small else M
cfg = json.load(open(a.area))
POLYS = cfg["skin"] if isinstance(cfg["skin"][0][0], list) else [cfg["skin"]]
EXCL = [tuple(b) for b in cfg.get("exclude", []) if not isinstance(b[0], list)]
EXCL_POLYS = [b for b in cfg.get("exclude", []) if isinstance(b[0], list)]


def in_poly(x, y, poly):
    c, j = False, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def in_area(x, y):
    return (any(in_poly(x, y, p) for p in POLYS) and not any(in_poly(x, y, p) for p in EXCL_POLYS)
            and not any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in EXCL))


def lum(p):
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


skin = [[False] * w for _ in range(h)]
score = [[0.0] * w for _ in range(h)]
signed = [[0.0] * w for _ in range(h)]  # the score before its parts are clipped at 0: its spread is the skin's noise
resid = [[0.0] * w for _ in range(h)]   # each pixel against its radius-3 median: specks
L = [[lum(M[y][x]) for x in range(w)] for y in range(h)]
for y in range(h):
    for x in range(w):
        if not in_area(x + a.ox, y + a.oy):
            continue
        o, m = P[y][x], M[y][x]
        if L[y][x] < 70 or m[0] < m[2]:
            continue
        if 2 <= x < w - 2 and 2 <= y < h - 2 and math.hypot(L[y][x + 2] - L[y][x - 2], L[y + 2][x] - L[y - 2][x]) / 4 > a.max_gradient:
            continue
        skin[y][x] = True
        dark = L[y][x] - lum(o)
        red = (o[0] - o[1]) - (m[0] - m[1])
        resid[y][x] = lum(o) - lum(M3[y][x])
        bright = resid[y][x] if a.bright_weight else 0
        score[y][x] = a.dark_weight * max(dark, 0) + 1.5 * max(red, 0) + a.bright_weight * max(bright, 0)
        signed[y][x] = a.dark_weight * dark + 1.5 * red + a.bright_weight * bright

TILE = 64


def local_spread(val):
    """Robust spread (1.4826 x the median absolute deviation) of val over the skin, per 64 px tile, interpolated
    between tile centres. Robust, so the blemishes in a tile (a minority of its pixels even in an acne cluster) don't
    raise it; local, because pores and grain differ across a face (the forehead of a sharp 18 MP portrait measured
    3.3, its cheeks 2.4). Returns (spread at x, y; the tiles' values)."""
    nx, ny = (w + TILE - 1) // TILE, (h + TILE - 1) // TILE
    grid = [[None] * nx for _ in range(ny)]
    for ty in range(ny):
        for tx in range(nx):
            v = [val[y][x] for y in range(ty * TILE, min(h, (ty + 1) * TILE))
                 for x in range(tx * TILE, min(w, (tx + 1) * TILE)) if skin[y][x]]
            if len(v) >= 0.25 * TILE * TILE:
                md = sorted(v)[len(v) // 2]
                grid[ty][tx] = 1.4826 * sorted(abs(t - md) for t in v)[len(v) // 2]
    vals = sorted(g for row in grid for g in row if g is not None)
    if not vals:
        return (lambda x, y: 0.0), []
    fill = vals[len(vals) // 2]
    grid = [[fill if g is None else g for g in row] for row in grid]

    def at(x, y):
        fx = min(max((x + 0.5) / TILE - 0.5, 0.0), nx - 1.0)
        fy = min(max((y + 0.5) / TILE - 0.5, 0.0), ny - 1.0)
        x0, y0 = int(fx), int(fy)
        x1, y1 = min(nx - 1, x0 + 1), min(ny - 1, y0 + 1)
        tx, ty = fx - x0, fy - y0
        return ((grid[y0][x0] * (1 - tx) + grid[y0][x1] * tx) * (1 - ty) +
                (grid[y1][x0] * (1 - tx) + grid[y1][x1] * tx) * ty)
    return at, vals


# The threshold: fixed if given, else --noise-mult x the score's local spread (at least 6). A fixed 7 sat at the noise
# floor: on a sharp, clean 18 MP face it flagged nearly every pore (3060 dabs), on an acne crop it rang plain skin too.
if a.threshold is None:
    spread_at, spreads = local_spread(signed)
    TH = [[max(6.0, a.noise_mult * spread_at(x, y)) if skin[y][x] else 1e9 for x in range(w)] for y in range(h)]
else:
    TH = [[a.threshold] * w for _ in range(h)]
ths = sorted(TH[y][x] for y in range(0, h, 4) for x in range(0, w, 4) if skin[y][x]) or [a.threshold or 0.0]
# specks (whiteheads, dark pores) never go into a source: more than --source-max-speck off the radius-3 median, by
# default 5 x the skin's own spread there (about its 99.8th percentile on four faces; a fixed 6 rejected nearly every
# source on sharp skin, where 2-26 % of clean pixels pass it, and those dabs fell back to Spot Healing)
if a.ref_small and a.source_max_speck is None:
    res_at, _ = local_spread(resid)
    LIM = [[max(6.0, 5 * res_at(x, y)) if skin[y][x] else 6.0 for x in range(w)] for y in range(h)]
else:
    LIM = [[a.source_max_speck or 6.0] * w for _ in range(h)]
speck = [[a.ref_small is not None and abs(resid[y][x]) > LIM[y][x] for x in range(w)] for y in range(h)]
lims = sorted(LIM[y][x] for y in range(0, h, 4) for x in range(0, w, 4) if skin[y][x]) or [6.0]


def mark_kind(pix):
    """Is this a mole or a freckle (permanent: keep) rather than a blemish (temporary: heal)? Melanin darkens skin and
    shifts it toward yellow-brown (it absorbs blue most), with a well-defined edge; an inflamed or healing blemish
    shifts it toward red (haemoglobin absorbs green). In Lab against the clean reference: 3+ L* darker with the colour
    shift 25 degrees or more from red toward yellow and a sharp edge, or 4+ L* darker, not red-dominant, sharp, and
    mole-sized or 6+ L* darker. On a sharp portrait it kept 8 of the 10 moles and freckles a retoucher had marked; on an acne crop it also
    kept 11 of 58 spots, the brown ones (freckles or old acne marks, which Step 3 fades): listed for review."""
    n = len(pix)
    cx, cy = sum(p[0] for p in pix) / n, sum(p[1] for p in pix) / n
    r = max(2.0, math.sqrt(n / math.pi))

    def ring(r0, r1):
        R1 = int(r1) + 1
        return [(x, y) for y in range(int(cy) - R1, int(cy) + R1 + 2) for x in range(int(cx) - R1, int(cx) + R1 + 2)
                if 0 <= x < w and 0 <= y < h and r0 * r0 <= (x - cx) ** 2 + (y - cy) ** 2 <= r1 * r1]
    core, edge = ring(0, 0.6 * r), ring(r + 1, r + 2.5)
    if not core or not edge:
        return False

    def mean(pts, img):
        return [sum(img[y][x][k] for x, y in pts) / len(pts) for k in range(3)]
    Lc, ac, bc = imgops.lab(*mean(core, P))
    Lm, am, bm = imgops.lab(*mean(core, M))
    Le = imgops.lab(*mean(edge, P))[0]
    dL, da, db = Lc - Lm, ac - am, bc - bm
    sharp = 1 - max(0.0, Lm - Le) / max(0.5, Lm - Lc)  # 1: the skin just outside is back to clean; 0: a soft halo
    brown = dL <= -3 and math.degrees(math.atan2(db, da)) >= 25 and sharp >= 0.8
    defined = dL <= -4 and da <= 0.6 * abs(dL) and (n >= 0.4 * a.max_size ** 2 or dL <= -6) and sharp >= 0.9
    return brown or defined


# blemish components: seeded at the threshold, grown down to 0.6 of it
seen = [[False] * w for _ in range(h)]
comps, marks = [], []
for y in range(h):
    for x in range(w):
        if score[y][x] >= TH[y][x] and not seen[y][x]:
            st, pix = [(x, y)], []
            seen[y][x] = True
            while st:
                cx, cy = st.pop(); pix.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and score[ny][nx] >= TH[ny][nx] * 0.6:
                            seen[ny][nx] = True; st.append((nx, ny))
            n = len(pix)
            if n < a.min_area or n > 1500:
                continue
            xs = [p[0] for p in pix]; ys = [p[1] for p in pix]
            span = max(max(xs) - min(xs), max(ys) - min(ys)) + 1
            if span > 3.5 * math.sqrt(n) + 4:  # a line: crease, hair, edge
                continue
            if not a.heal_marks and mark_kind(pix):
                marks.append((pix, span))
                continue
            comps.append((pix, span))

for spec in a.add:
    v = [int(float(t)) for t in spec.split(",")]
    cx, cy, d = v[0] - a.ox, v[1] - a.oy, (v[2] if len(v) > 2 else 8)
    pix = [(cx + dx, cy + dy) for dy in range(-(d // 2), d // 2 + 1) for dx in range(-(d // 2), d // 2 + 1)
           if dx * dx + dy * dy <= (d / 2) ** 2 and 0 <= cx + dx < w and 0 <= cy + dy < h]
    for x, y in pix:  # strongest at the centre, so the first dab lands there
        score[y][x] = max(score[y][x], 1e6 - math.hypot(x - cx, y - cy) / d)
    comps.append((pix, d - 3))


def disk(cx, cy, r):
    ri = int(math.ceil(r))
    for dy in range(-ri, ri + 1):
        for dx in range(-ri, ri + 1):
            if dx * dx + dy * dy <= r * r:
                yield cx + dx, cy + dy


blemish = [[False] * w for _ in range(h)]
for pix, _ in comps + marks:  # a mole is never a source either
    for x, y in pix:
        blemish[y][x] = True


def source_for(cx, cy, d):
    """Clean, tone-matched skin near (cx, cy) for a dab of diameter d. Returns (dx, dy) or None."""
    r = d / 2 + 1
    best = None
    for dist in range(d + 3, d + 22, 3):
        for k in range(16):
            ang = 2 * math.pi * k / 16
            sx, sy = round(cx + dist * math.cos(ang)), round(cy + dist * math.sin(ang))
            tot, ok, bad = 0.0, True, 0
            for px, py in disk(sx, sy, r):
                if not (0 <= px < w and 0 <= py < h) or not skin[py][px]:
                    ok = False; break
                if blemish[py][px] or speck[py][px]:
                    bad += 1
                tot += score[py][px]
            if not ok or bad:
                continue
            n = sum(1 for _ in disk(sx, sy, r))
            cost = tot / n + 0.6 * abs(L[sy][sx] - L[cy][cx]) + 0.05 * dist
            if best is None or cost < best[0]:
                best = (cost, sx - cx, sy - cy)
    return None if best is None else (best[1], best[2])


dabs = []
for k, (pix, span) in enumerate(comps):
    explicit = k >= len(comps) - len(a.add)  # the --add spots were appended last
    d = max(a.min_size, min(a.max_size, span + 3))
    left = set(pix)
    cover = d / 2 * 0.75
    while left:
        cx, cy = max(left, key=lambda p: score[p[1]][p[0]])
        src = source_for(cx, cy, d)
        dabs.append((cx, cy, d, src, explicit))
        left = {p for p in left if (p[0] - cx) ** 2 + (p[1] - cy) ** 2 > cover * cover}

# Dabs with no clean source nearby become small Spot Healing dabs, or are left for you. Spot Healing can't sample
# "this layer and below": with sampleAllLayers it reads every visible layer, the ones above too (an empty layer under
# a visible Invert healed 21 levels off on average), and without it an empty layer gives it nothing. So with
# --sample currentAndBelow (and --fallback skip) they are left out and listed, and drawn yellow on the overlay.
# A spot you asked for with --add is always kept.
spot_ok = a.fallback == "spot" and a.sample != "currentAndBelow"
skipped = [dd for dd in dabs if not dd[3] and not (spot_ok or dd[4])]
dabs = [dd for dd in dabs if dd[3] or spot_ok or dd[4]]
steps = []
if a.layer is not None:  # paint commands fail while a group is active (e.g. after reopening a PSD), even with "layer"
    steps.append({"command": "layer.select", "params": {"layer": a.layer}})
warn_add = []
for cx, cy, d, src, explicit in dabs:
    p = {"points": [[cx + a.ox, cy + a.oy]], "size": d, "hardness": a.hardness, "target": "pixels"}
    if a.layer is not None:
        p["layer"] = a.layer
    if src:
        p.update({"offset": list(src), "aligned": True, "sampleLayer": a.sample})
        steps.append({"command": "paint.healingBrush", "params": p})
    else:  # no clean source nearby: a small content-aware dab instead
        p["type"] = "proximityMatch"
        if a.sample != "current":
            p["sampleAllLayers"] = True
            if a.sample == "currentAndBelow":  # only an explicit --add gets here
                warn_add.append([cx + a.ox, cy + a.oy, d])
        steps.append({"command": "paint.spotHealing", "params": p})
if not a.dry_run:
    json.dump(steps, open(a.steps, "w"))
nsrc = sum(1 for d in dabs if d[3])
base = a.steps.rsplit(".", 1)[0]
q = lambda v, f: round(v[int(f * (len(v) - 1))], 1)
th = (f"threshold {a.threshold:g}" if a.threshold is not None else
      f"threshold auto {q(ths, 0)}-{q(ths, 1)} (median {q(ths, .5)}) = {a.noise_mult:g} x the score's local spread")
print(f"{len(comps)} blemishes, {len(dabs)} dabs ({nsrc} healing brush, {len(dabs) - nsrc} spot heal), "
      f"sizes {sorted(set(d[2] for d in dabs))}; {th}"
      + (f"; source speck limit {q(lims, 0)}-{q(lims, 1)} (median {q(lims, .5)})" if a.ref_small else "")
      + ("; dry run, no steps written" if a.dry_run else ""))
spot = len(dabs) - nsrc
if dabs and spot / len(dabs) > 0.2:
    print(f"note: {100 * spot / len(dabs):.0f} % of the dabs have no clean source within ~20 px and fall back to Spot "
          "Healing: widen the area so clean skin surrounds the marks, raise --source-max-speck, or on FS High use "
          "--fallback skip and heal those by hand")
if marks:
    mk = [[round(sum(p[0] for p in pix) / len(pix)) + a.ox, round(sum(p[1] for p in pix) / len(pix)) + a.oy,
           max(a.min_size, min(a.max_size, span + 3))] for pix, span in marks]
    if not a.dry_run:
        json.dump(mk, open(base + "_marks.json", "w"))
    print(f"{len(marks)} spots look like moles, freckles or dark pores (brown, well defined) and are kept, blue on the overlay "
          f"(x, y, size in full-image px{'' if a.dry_run else ', all in ' + base + '_marks.json'}): {mk[:24]}"
          + (" …" if len(mk) > 24 else "") + ". Look at each; --add X,Y,D heals one that is a blemish, --heal-marks all")
if skipped:
    where = [[cx + a.ox, cy + a.oy, d] for cx, cy, d, _, _ in skipped]
    if not a.dry_run:
        json.dump(where, open(base + "_skipped.json", "w"))
    print(f"{len(skipped)} spots have no clean source nearby and are not planned; heal them by hand from a source you "
          f"choose (yellow on the overlay; x, y, size in full-image px"
          f"{'' if a.dry_run else ', all in ' + base + '_skipped.json'}): {where[:24]}" + (" …" if len(where) > 24 else ""))
if warn_add:
    print(f"warning: {len(warn_add)} --add spot(s) have no clean source and become Spot Healing, which samples all "
          f"visible layers: hide the layers above the target before running, or they are copied in: {warn_add[:24]}")

if a.overlay:
    S = a.overlay_scale or (2 if max(w, h) <= 800 else 1)
    img = [[P[y // S][x // S] for x in range(w * S)] for y in range(h * S)]
    mark_rings = [(round(sum(p[0] for p in pix) / len(pix)), round(sum(p[1] for p in pix) / len(pix)),
                   max(a.min_size, min(a.max_size, span + 3)) + 2, None, False) for pix, span in marks]
    for ring, col in ((dabs, (255, 40, 40)), (skipped, (255, 210, 0)), (mark_rings, (40, 140, 255))):
        for cx, cy, d, src, _ in ring:
            for r in (d / 2 * S + 0.5, d / 2 * S + 1.5):  # 2 px rings, readable when the image is shown smaller
                for t in range(0, 360, 4):
                    px = int(cx * S + S / 2 + r * math.cos(math.radians(t)))
                    py = int(cy * S + S / 2 + r * math.sin(math.radians(t)))
                    if 0 <= px < w * S and 0 <= py < h * S:
                        img[py][px] = col
    pngio.write(a.overlay, w * S, h * S, img)
