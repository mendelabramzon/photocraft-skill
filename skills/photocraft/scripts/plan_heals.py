#!/usr/bin/env python3
"""Plan a precise skin retouch: many small Healing Brush dabs, each copying real texture from
clean nearby skin. No blur, no content-aware synthesis.

usage: plan_heals.py crop.png ref.png cropX cropY area.json [--threshold 7] [--max-size 10]
                     [--bright-weight 0.7 --ref-small ref3.png] [--add X,Y[,D] …]
                     [--layer ID] [--steps steps.json] [--overlay overlay.png]

crop.png   the face cropped from the photo at full resolution (image.crop)
ref.png    the same crop + filter.noise.median (radius ~10): the "clean skin" reference
area.json  {"skin": [[x, y], …polygon], "exclude": [[x0, y0, x1, y1] or [[x, y], …polygon], …]} in full-image coords
Writes a pc.py script (list of paint.healingBrush steps) and a 2x overlay: red rings = dabs.
--bright-weight > 0 also catches light bumps (closed comedones, flaky bits) that catch a rim light.
"""
import argparse
import json
import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pngio

ap = argparse.ArgumentParser()
ap.add_argument("crop"); ap.add_argument("ref"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
ap.add_argument("area")
ap.add_argument("--threshold", type=float, default=7)
ap.add_argument("--max-size", type=int, default=10)
ap.add_argument("--min-size", type=int, default=5)
ap.add_argument("--hardness", type=int, default=80)
ap.add_argument("--dark-weight", type=float, default=0.5, help="weight of darkness vs redness (pores/stubble are dark, acne is red)")
ap.add_argument("--bright-weight", type=float, default=0, help="weight of light bumps (try 0.7, with --ref-small, on rim-lit skin)")
ap.add_argument("--ref-small", help="the crop + median radius 3: light bumps are measured against it, so the edge "
                                    "of a highlight (which a radius-10 median lags behind) doesn't count as a bump")
ap.add_argument("--min-area", type=int, default=6, help="px; 2 to catch tiny whiteheads")
ap.add_argument("--source-max-speck", type=float, default=6,
                help="with --ref-small: a source may not contain any pixel this many levels lighter or darker than "
                     "its radius-3 median, so a whitehead or dark pore is never copied onto a healed spot")
ap.add_argument("--max-gradient", type=float, default=2.0,
                help="levels/px: skip skin where the clean reference itself changes this fast (edge of a highlight "
                     "or shadow, which a median lags behind and would read as a 'blemish')")
ap.add_argument("--add", action="append", default=[], metavar="X,Y[,D]",
                help="also heal this spot (full-image coords, diameter D, default 8): a blemish you can see that the "
                     "detector misses, e.g. a scab that is half light, half dark. Repeatable")
ap.add_argument("--layer", type=int)
ap.add_argument("--steps", default="steps.json")
ap.add_argument("--overlay")
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
L = [[lum(M[y][x]) for x in range(w)] for y in range(h)]
# specks (whiteheads, dark pores) relative to a small median: never use them as healing sources
speck = [[a.ref_small is not None and abs(lum(P[y][x]) - lum(M3[y][x])) > a.source_max_speck for x in range(w)]
         for y in range(h)]
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
        bright = lum(o) - lum(M3[y][x]) if a.bright_weight else 0
        score[y][x] = a.dark_weight * max(dark, 0) + 1.5 * max(red, 0) + a.bright_weight * max(bright, 0)

# blemish components
T = a.threshold
seen = [[False] * w for _ in range(h)]
comps = []
for y in range(h):
    for x in range(w):
        if score[y][x] >= T and not seen[y][x]:
            st, pix = [(x, y)], []
            seen[y][x] = True
            while st:
                cx, cy = st.pop(); pix.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and score[ny][nx] >= T * 0.6:
                            seen[ny][nx] = True; st.append((nx, ny))
            n = len(pix)
            if n < a.min_area or n > 1500:
                continue
            xs = [p[0] for p in pix]; ys = [p[1] for p in pix]
            span = max(max(xs) - min(xs), max(ys) - min(ys)) + 1
            if span > 3.5 * math.sqrt(n) + 4:  # a line: crease, hair, edge
                continue
            comps.append((pix, span))

for spec in a.add:
    v = [int(float(t)) for t in spec.split(",")]
    cx, cy, d = v[0] - a.ox, v[1] - a.oy, (v[2] if len(v) > 2 else 8)
    pix = [(cx + dx, cy + dy) for dy in range(-(d // 2), d // 2 + 1) for dx in range(-(d // 2), d // 2 + 1)
           if dx * dx + dy * dy <= (d / 2) ** 2 and 0 <= cx + dx < w and 0 <= cy + dy < h]
    for x, y in pix:  # strongest at the centre, so the first dab lands there
        score[y][x] = max(score[y][x], T + 1 - math.hypot(x - cx, y - cy) / d)
    comps.append((pix, d - 3))


def disk(cx, cy, r):
    ri = int(math.ceil(r))
    for dy in range(-ri, ri + 1):
        for dx in range(-ri, ri + 1):
            if dx * dx + dy * dy <= r * r:
                yield cx + dx, cy + dy


blemish = [[False] * w for _ in range(h)]
for pix, _ in comps:
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
for pix, span in comps:
    d = max(a.min_size, min(a.max_size, span + 3))
    left = set(pix)
    cover = d / 2 * 0.75
    while left:
        cx, cy = max(left, key=lambda p: score[p[1]][p[0]])
        src = source_for(cx, cy, d)
        dabs.append((cx, cy, d, src))
        left = {p for p in left if (p[0] - cx) ** 2 + (p[1] - cy) ** 2 > cover * cover}

steps = []
for cx, cy, d, src in dabs:
    p = {"points": [[cx + a.ox, cy + a.oy]], "size": d, "hardness": a.hardness, "target": "pixels"}
    if a.layer is not None:
        p["layer"] = a.layer
    if src:
        p.update({"offset": list(src), "aligned": True, "sampleLayer": "current"})
        steps.append({"command": "paint.healingBrush", "params": p})
    else:  # no clean source nearby: a small content-aware dab instead
        p["type"] = "proximityMatch"
        steps.append({"command": "paint.spotHealing", "params": p})
json.dump(steps, open(a.steps, "w"))
nsrc = sum(1 for d in dabs if d[3])
print(f"{len(comps)} blemishes, {len(dabs)} dabs ({nsrc} healing brush, {len(dabs) - nsrc} spot heal), "
      f"sizes {sorted(set(d[2] for d in dabs))}")

if a.overlay:
    S = 2
    img = [[P[y // S][x // S] for x in range(w * S)] for y in range(h * S)]
    for cx, cy, d, src in dabs:
        r = d / 2 * S
        for t in range(0, 360, 6):
            px, py = int(cx * S + r * math.cos(math.radians(t))), int(cy * S + r * math.sin(math.radians(t)))
            if 0 <= px < w * S and 0 <= py < h * S:
                img[py][px] = (255, 40, 40)
    pngio.write(a.overlay, w * S, h * S, img)
