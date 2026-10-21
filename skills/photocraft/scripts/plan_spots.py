#!/usr/bin/env python3
"""Plan sensor-dust and speck removal: find soft spots on smooth background (sky, studio backdrop, wall) and heal each
with one Healing Brush dab that copies clean, tone-matched background from nearby. No blur, no fill.

Sensor dust is the soft shadow of a particle: round, a few percent darker, the same in every frame, most visible at
small apertures in bright, even areas. A shadow darkens R, G and B by the same fraction, which tells it apart from
birds, planes and cloud texture (those change colour too). A spot is planned only if it is
  - darker (--polarity light: lighter) than a large median of the image by more than --threshold x the noise,
  - round and compact, --min-size to --max-size px across (not a wire, branch or cloud edge),
  - neutral: R, G and B fall by about the same fraction (--max-tint; --any-colour also takes coloured specks),
  - on smooth background (the median changes by less than --max-gradient levels/px there).
Each dab is a little bigger than the spot's soft edge and copies background with the same tone and texture from the
nearest clean place (left and right first: sky gradients run up and down). A spot with no clean source nearby gets a
small Spot Healing dab instead.

usage: plan_spots.py crop.png ref.png cropX cropY [--area area.json] [--layer ID] [--steps steps.json]
                     [--overlay overlay.png] [--check check.png]
crop.png  the region at full resolution (image.crop); ref.png the same crop + filter.noise.median, radius a little
          over the largest spot's radius (25 for spots up to ~40 px)
area.json optional {"skin": [[x, y], ...] (where to look), "exclude": [...]} in full-image coords, as for skin
Writes steps.json (paint.healingBrush dabs for pc.py script), overlay.png (red = dab, cyan = its source, yellow =
spot heal), check.png (the dust-check view: local contrast x --gain, how retouchers make dust visible).
plan_lines.py imports the helpers below.
"""
import argparse
import json
import math
import os
import sys
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pngio


# ---------------------------------------------------------------- helpers shared with plan_lines.py

def gradient(Y, w, h):
    """Central-difference gradient magnitude (levels/px), 0 on the border."""
    g = [0.0] * (w * h)
    for y in range(1, h - 1):
        r = y * w
        for x in range(1, w - 1):
            i = r + x
            gx = Y[i + 1] - Y[i - 1]; gy = Y[i + w] - Y[i - w]
            g[i] = 0.5 * math.sqrt(gx * gx + gy * gy)
    return g


def robust_sigma(vals):
    """1.4826 x median absolute deviation from the median."""
    if not vals:
        return 1.0
    m = imgops.percentile(vals, 50)
    return 1.4826 * imgops.percentile([abs(v - m) for v in vals], 50)


def smooth_background(Yr, w, h, max_gradient, area):
    """1 where the background (the median reference) is smooth enough to heal from: no edges, no structure."""
    g = gradient(imgops.gauss(Yr, w, h, 1.5), w, h)
    return bytearray(1 if area[i] and g[i] < max_gradient and Yr[i] > 12 else 0 for i in range(w * h))


def tile_noise(v, ok, w, h, tile=64):
    """Local level and noise of v: median and robust sigma per tile (from the `ok` pixels; tiles with too few borrow
    the whole image's), spread to every pixel by bilinear interpolation between tile centres."""
    tw, th = (w + tile - 1) // tile, (h + tile - 1) // tile
    allv = [v[i] for i in range(0, w * h, 7) if ok[i]]
    gm, gs = (imgops.percentile(allv, 50), robust_sigma(allv)) if allv else (0.0, 1.0)
    med, sig = [gm] * (tw * th), [gs] * (tw * th)
    for ty in range(th):
        for tx in range(tw):
            vals = [v[y * w + x] for y in range(ty * tile, min(h, ty * tile + tile), 2)
                    for x in range(tx * tile, min(w, tx * tile + tile), 2) if ok[y * w + x]]
            if len(vals) > tile * tile // 16:
                med[ty * tw + tx] = imgops.percentile(vals, 50)
                sig[ty * tw + tx] = max(robust_sigma(vals), 0.25 * gs)
    base, noise = [0.0] * (w * h), [0.0] * (w * h)
    for y in range(h):
        fy = min(max((y + 0.5) / tile - 0.5, 0), th - 1); y0 = int(fy); y1 = min(y0 + 1, th - 1); ty = fy - y0
        for x in range(w):
            fx = min(max((x + 0.5) / tile - 0.5, 0), tw - 1); x0 = int(fx); x1 = min(x0 + 1, tw - 1); tx = fx - x0
            k00, k01, k10, k11 = y0 * tw + x0, y0 * tw + x1, y1 * tw + x0, y1 * tw + x1
            wa, wb, wc, wd = (1 - tx) * (1 - ty), tx * (1 - ty), (1 - tx) * ty, tx * ty
            base[y * w + x] = wa * med[k00] + wb * med[k01] + wc * med[k10] + wd * med[k11]
            noise[y * w + x] = max(1e-3, wa * sig[k00] + wb * sig[k01] + wc * sig[k10] + wd * sig[k11])
    return base, noise


def disk(r):
    """Offsets of a disk of radius r, every pixel."""
    ri = int(math.ceil(r))
    return [(dx, dy) for dy in range(-ri, ri + 1) for dx in range(-ri, ri + 1) if dx * dx + dy * dy <= r * r]


def find_source(cx, cy, size, ok, Yr, tex, w, h, max_dist=None, prefer_horizontal=True):
    """Best healing source for a dab of diameter `size` at (cx, cy): (dx, dy) or None. Every source pixel must be
    `ok` (smooth, clean, inside the area); among those, the closest match in tone and texture wins."""
    r = size / 2 + 1.5
    pts = disk(r)
    sparse = pts[::3] if len(pts) > 60 else pts
    ring = [(dx, dy) for dx, dy in disk(r + 3) if dx * dx + dy * dy > r * r]
    def mean_at(img, x, y, offs):
        v = [img[(y + dy) * w + x + dx] for dx, dy in offs if 0 <= x + dx < w and 0 <= y + dy < h]
        return sum(v) / len(v) if v else 0.0
    t_dst, x_dst = mean_at(Yr, cx, cy, ring), mean_at(tex, cx, cy, ring)
    best = None
    max_dist = max_dist or 4 * size + 30
    d = size + 3
    while d <= max_dist:
        for k in range(24):
            ang = 2 * math.pi * k / 24
            sx, sy = round(cx + d * math.cos(ang)), round(cy + d * math.sin(ang))
            if not (r <= sx < w - r and r <= sy < h - r):
                continue
            if not all(ok[(sy + dy) * w + sx + dx] for dx, dy in sparse):
                continue
            if not all(ok[(sy + dy) * w + sx + dx] for dx, dy in pts):
                continue
            cost = (abs(mean_at(Yr, sx, sy, sparse) - t_dst) + 0.5 * abs(mean_at(tex, sx, sy, sparse) - x_dst)
                    + 0.02 * d + (0.3 * abs(math.sin(ang)) if prefer_horizontal else 0))
            if best is None or cost < best[0]:
                best = (cost, sx - cx, sy - cy)
        if best is not None and d > 2 * size + 10:
            break  # a good source close by beats a marginally better one far away
        d += max(2, size // 3)
    return None if best is None else (best[1], best[2])


def texture(Y, Yr, w, h):
    """Local grain/texture energy: mean |image - median| over ~7 px."""
    return imgops.box([abs(a - b) for a, b in zip(Y, Yr)], w, h, 3)


def overlay_image(P, w, h, scale):
    S = scale
    return [[P[y // S][x // S] for x in range(w * S)] for y in range(h * S)]


def draw_circle(img, cx, cy, r, col, scale):
    W, H = len(img[0]), len(img)
    n = max(24, int(2 * math.pi * r * scale / 2))
    for t in range(n):
        a = 2 * math.pi * t / n
        px, py = int((cx + 0.5) * scale + r * scale * math.cos(a)), int((cy + 0.5) * scale + r * scale * math.sin(a))
        if 0 <= px < W and 0 <= py < H:
            img[py][px] = col


def draw_line(img, p, q, col, scale, dash=0):
    W, H = len(img[0]), len(img)
    (x0, y0), (x1, y1) = p, q
    n = int(max(abs(x1 - x0), abs(y1 - y0)) * scale) + 1
    for i in range(n + 1):
        if dash and (i // dash) % 2:
            continue
        t = i / n
        px, py = int((x0 + 0.5 + (x1 - x0) * t) * scale), int((y0 + 0.5 + (y1 - y0) * t) * scale)
        if 0 <= px < W and 0 <= py < H:
            img[py][px] = col


def heal_step(points, size, hardness, src, layer, sample, ox, oy, zoom=1):
    """A paint.healingBrush step in full-image coords (crop coords x zoom + offset), or paint.spotHealing when
    there is no source."""
    k = zoom
    p = {"points": [[round(ox + k * x + (k - 1) / 2, 1), round(oy + k * y + (k - 1) / 2, 1)] for x, y in points],
         "size": int(round(size * k)), "hardness": hardness, "target": "pixels"}
    if layer is not None:
        p["layer"] = layer
    if src is None:
        p.update({"type": "contentAware", "sampleAllLayers": sample != "current"})
        return {"command": "paint.spotHealing", "params": p}
    p.update({"offset": [int(round(src[0] * k)), int(round(src[1] * k))], "aligned": True, "sampleLayer": sample})
    return {"command": "paint.healingBrush", "params": p}


def load_area(path, ox, oy, w, h):
    if not path:
        return [1.0] * (w * h)
    return imgops.raster(json.load(open(path)), ox, oy, w, h)


# ---------------------------------------------------------------- spots

def profile(m, w, h, cx, cy, rmax):
    """Mean of map m on rings of radius 0, 1, ... rmax around (cx, cy)."""
    out = []
    for r in range(0, rmax + 1):
        v = [m[(cy + dy) * w + cx + dx] for dx, dy in RINGS(r) if 0 <= cx + dx < w and 0 <= cy + dy < h]
        out.append(sum(v) / len(v) if v else 0.0)
    return out


_rings = {}


def RINGS(r):
    if r not in _rings:
        _rings[r] = [(dx, dy) for dx, dy in disk(r + 0.5) if dx * dx + dy * dy > (r - 0.5) ** 2] if r else [(0, 0)]
    return _rings[r]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crop"); ap.add_argument("ref"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
    ap.add_argument("--area")
    ap.add_argument("--zoom", type=int, default=1,
                    help="crop.png and ref.png are the region shrunk by this factor (big images: plan at half size)")
    ap.add_argument("--polarity", choices=["dark", "light", "both"], default="dark")
    ap.add_argument("--threshold", type=float, default=3.5, help="x noise at the spot's own scale: how far past the grain")
    ap.add_argument("--min-depth", type=float, default=0.6,
                    help="percent darker than the background for a large spot; small ones need more (x (1 + 16 / diameter))")
    ap.add_argument("--min-size", type=float, default=4, help="px across (in crop.png)")
    ap.add_argument("--max-size", type=float, default=64, help="px across (in crop.png); the median radius must exceed it")
    ap.add_argument("--max-tint", type=float, default=0.2,
                    help="chromaticity change relative to the darkening (dust ~0.1, birds and cloud gaps > 0.5)")
    ap.add_argument("--max-asym", type=float, default=0.35,
                    help="how lopsided the darkening may be around the centre (dust ~0.1-0.3, sky blotches 0.4-1)")
    ap.add_argument("--any-colour", action="store_true", help="plan coloured or lopsided specks too (pollen, litter, birds)")
    ap.add_argument("--max-gradient", type=float, default=2.5, help="levels/px: background steeper than this is left alone")
    ap.add_argument("--margin", type=float, default=2, help="px added around the spot's halo for the dab")
    ap.add_argument("--hardness", type=int, default=60)
    ap.add_argument("--layer", type=int, help="the retouch layer to paint on (an empty layer: use --sample currentAndBelow)")
    ap.add_argument("--sample", default="current", choices=["current", "currentAndBelow", "all"])
    ap.add_argument("--steps", default="steps.json")
    ap.add_argument("--overlay")
    ap.add_argument("--check", help="dust-check view: local contrast, spots circled")
    ap.add_argument("--gain", type=float, default=8)
    ap.add_argument("--debug", action="append", default=[], metavar="X,Y",
                    help="print why the spot nearest this point (full-image coords) was planned or not. Repeatable")
    a = ap.parse_args()

    w, h, R, G, B = imgops.load(a.crop)
    w2, h2, Rr, Gr, Br = imgops.load(a.ref)
    assert (w, h) == (w2, h2), "crop and ref differ in size"
    N = w * h
    Y = [imgops.lum(*v) for v in zip(R, G, B)]
    Yr = [imgops.lum(*v) for v in zip(Rr, Gr, Br)]
    zoom = a.zoom
    area = load_area(a.area, a.ox, a.oy, w * zoom, h * zoom) if zoom == 1 or not a.area else None
    if area is None:  # rasterise the area at full size, sample it down
        full = load_area(a.area, a.ox, a.oy, w * zoom, h * zoom)
        area = [full[(y * zoom + zoom // 2) * w * zoom + x * zoom + zoom // 2] for y in range(h) for x in range(w)]
    smooth = smooth_background(Yr, w, h, a.max_gradient, area)

    # percent darkening (or lightening) against the median. A soft spot shows best at its own scale, so the map is
    # smoothed at several scales and each is measured in units of its own local noise; a pixel keeps its best
    # score and the scale it came from.
    sign = -1 if a.polarity == "light" else 1
    d = [sign * 100 * (yr - y) / max(yr, 8) for y, yr in zip(Y, Yr)]
    if a.polarity == "both":
        d = [abs(v) for v in d]
    scales = [sg for sg in (1.0, 2.0, 3.5, 6.0, 10.0, 16.0) if 4 * sg <= a.max_size] or [1.0]
    maps, z, zk = [], [0.0] * N, bytearray(N)
    for k, sg in enumerate(scales):
        dk = imgops.gauss(d, w, h, sg)
        # tiles well over the spots this scale finds, so a spot doesn't raise the noise it is measured against
        base, sk = tile_noise(dk, smooth, w, h, tile=int(max(64, 12 * sg)))
        for i in range(N):
            v = (dk[i] - base[i]) / sk[i]
            if v > z[i]:
                z[i] = v; zk[i] = k
        maps.append(array("f", dk))
    sig = robust_sigma([maps[0][i] for i in range(0, N, 5) if smooth[i]])

    dbg = [((int(float(p.split(",")[0])) - a.ox) // zoom, (int(float(p.split(",")[1])) - a.oy) // zoom) for p in a.debug]

    def note(i0, verdict, **kv):
        for x, y in dbg:
            if math.hypot(i0 % w - x, i0 // w - y) < 15:
                print(f"debug {x * zoom + a.ox},{y * zoom + a.oy}: candidate at {i0 % w * zoom + a.ox},{i0 // w * zoom + a.oy} "
                      f"z={z[i0]:.1f} scale={scales[zk[i0]]} {verdict} "
                      + " ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in kv.items()), file=sys.stderr)
    for x, y in dbg:
        if 0 <= x < w and 0 <= y < h:
            near = max((j for j in range(N) if abs(j % w - x) < 12 and abs(j // w - y) < 12), key=lambda j: z[j])
            print(f"debug {x * zoom + a.ox},{y * zoom + a.oy}: best score nearby z={z[near]:.1f}, smooth={smooth[near]}, "
                  f"threshold {a.threshold}", file=sys.stderr)

    # candidates: local maxima of the score (neighbouring spots stay apart), strongest first, each measured on its
    # own: size from its radial profile (the darkest ring may sit off-centre: out-of-focus dust is a ring), then
    # shape, colour and symmetry
    zmax = imgops.maxf(z, w, h, 3)
    cands = sorted((i for i in range(N) if smooth[i] and z[i] >= a.threshold and z[i] >= zmax[i]), key=lambda i: -z[i])
    spots, rejected = [], {"faint": 0, "size": 0, "border": 0, "shape": 0, "tint": 0}
    taken = bytearray(N)
    rlim = int(a.max_size / 2) + 4
    for i0 in cands:
        if taken[i0]:
            note(i0, "inside a spot already planned")
            continue
        icx, icy = i0 % w, i0 // w
        k = zk[i0]
        m, mf = maps[k], maps[min(1, len(maps) - 1)]  # size from a fine map: blur at a coarse scale inflates it
        pf = profile(mf, w, h, icx, icy, rlim)
        rp = max(range(0, min(len(pf), int(3 * scales[k]) + 3)), key=lambda r: pf[r])
        edge = next((r for r in range(rp + 1, len(pf)) if pf[r] < 0.15 * pf[rp]), None)
        if edge:
            # the score can peak off-centre (on the darker ring of an out-of-focus spot, or where grain adds to the
            # darkening): move to the centroid of the darkening on a coarser map before measuring the spot
            mc = maps[min(len(maps) - 1, k + 1)]
            for _ in range(3):
                pts = [(dx, dy) for dx, dy in disk(edge) if 0 <= icx + dx < w and 0 <= icy + dy < h]
                wt = [max(mc[(icy + dy) * w + icx + dx], 0.0) for dx, dy in pts]
                if sum(wt) <= 0:
                    break
                icx += round(sum(dx * q for (dx, dy), q in zip(pts, wt)) / sum(wt))
                icy += round(sum(dy * q for (dx, dy), q in zip(pts, wt)) / sum(wt))
            pf = profile(mf, w, h, icx, icy, rlim)
            rp = max(range(0, min(len(pf), int(edge) + 2)), key=lambda r: pf[r])
            edge = next((r for r in range(rp + 1, len(pf)) if pf[r] < 0.15 * pf[rp]), None)
        peak = pf[rp]
        if edge is None or not a.min_size <= 2 * edge <= a.max_size:
            rejected["size"] += 1
            note(i0, "wrong size", diameter=2 * edge if edge else "> max")
            continue
        # visibility: a big soft spot shows at lower contrast than a small one; and the finest scales, with the
        # most independent samples, must clear a higher score before a grain cluster counts as a spot
        if peak < a.min_depth * (1 + 8 * zoom / edge) or z[i0] < a.threshold + max(0.0, 1.0 - 0.5 * k):
            rejected["faint"] += 1
            note(i0, "too faint", depth=peak, diameter=2 * edge)
            continue
        if not (edge <= icx < w - edge and edge <= icy < h - edge):
            rejected["border"] += 1  # the median and the blurs are unreliable at the crop edge: crop wider
            note(i0, "touches the crop border")
            continue
        inner = disk(edge)
        wt = [max(m[(icy + dy) * w + icx + dx], 0.0) for dx, dy in inner]
        ws = sum(wt) or 1.0
        mx = sum(dx * q for (dx, dy), q in zip(inner, wt)) / ws; my = sum(dy * q for (dx, dy), q in zip(inner, wt)) / ws
        sxx = sum((dx - mx) ** 2 * q for (dx, dy), q in zip(inner, wt)) / ws
        syy = sum((dy - my) ** 2 * q for (dx, dy), q in zip(inner, wt)) / ws
        sxy = sum((dx - mx) * (dy - my) * q for (dx, dy), q in zip(inner, wt)) / ws
        tr, det = sxx + syy, sxx * syy - sxy * sxy
        l1 = tr / 2 + math.sqrt(max(0.0, tr * tr / 4 - det)); l2 = max(tr / 2 - math.sqrt(max(0.0, tr * tr / 4 - det)), 1e-6)
        if l1 / l2 > 4:
            rejected["shape"] += 1
            note(i0, "elongated", ratio=l1 / l2)
            continue
        # dust is radially symmetric: about the same darkening in every direction from the centre, where a darker
        # patch of sky between clouds is lopsided
        sect = [[] for _ in range(8)]
        for dx, dy in disk(0.8 * edge):
            if dx * dx + dy * dy >= (0.25 * edge) ** 2:
                sect[int((math.atan2(dy, dx) + math.pi) / (2 * math.pi) * 8) % 8].append(m[(icy + dy) * w + icx + dx])
        ms = [sum(v) / len(v) for v in sect if v]
        mean = sum(ms) / len(ms) if ms else 0.0
        asym = math.sqrt(sum((q - mean) ** 2 for q in ms) / len(ms)) / mean if mean > 0 else 9.0
        # a shadow keeps the colour's chromaticity (each channel's share of R+G+B); per-channel ratios would be
        # dominated by noise in a dark channel (the red of a blue sky)
        core = [(icy + dy) * w + icx + dx for dx, dy in inner]
        sp = [sum(c[i] for i in core) for c in (R, G, B)]; rf = [sum(c[i] for i in core) for c in (Rr, Gr, Br)]
        depth = abs(1 - sum(sp) / max(1.0, sum(rf)))
        tint = math.hypot(sp[0] / sum(sp) - rf[0] / sum(rf), sp[1] / sum(sp) - rf[1] / sum(rf)) / max(depth, 0.002)
        if not a.any_colour:
            if tint > a.max_tint:
                rejected["tint"] += 1
                note(i0, "coloured", tint=tint, asym=asym)
                continue
            # a strong neutral spot may be lopsided because two dust shadows overlap; let it through
            if asym > min(0.7, a.max_asym + 0.05 * max(0.0, z[i0] - 5)):
                rejected["shape"] += 1
                note(i0, "lopsided", tint=tint, asym=asym, centre=f"{icx * zoom + a.ox},{icy * zoom + a.oy}", diameter=2 * edge)
                continue
        # the dab must enclose the whole soft halo: healing takes its tone from the dab's edge, so an edge inside
        # the halo leaves a dark ring. Cover out to where the darkening is down to ~5 % (or into the grain)
        cover = next((r for r in range(edge, len(pf)) if pf[r] < max(0.03 * peak, 0.5 * sig)), len(pf) - 1)
        cover = min(cover, int(2.2 * edge) + 4)
        note(i0, "PLANNED", diameter=2 * cover, depth=peak, tint=tint, asym=asym)
        spots.append({"x": icx + mx, "y": icy + my, "r": cover, "peak": peak, "z": z[i0]})
        for dx, dy in disk(cover + 2):
            if 0 <= icx + dx < w and 0 <= icy + dy < h:
                taken[(icy + dy) * w + icx + dx] = 1

    # sources: smooth, inside the area, away from every spot
    block = bytearray(N)
    for s in spots:
        for dx, dy in disk(s["r"] + a.margin + 2):
            x, y = int(round(s["x"])) + dx, int(round(s["y"])) + dy
            if 0 <= x < w and 0 <= y < h:
                block[y * w + x] = 1
    ok = bytearray(1 if smooth[i] and not block[i] else 0 for i in range(N))
    tex = texture(Y, Yr, w, h)
    steps, plan = [], []
    for s in sorted(spots, key=lambda s: -s["peak"]):
        size = max(6 / zoom, math.ceil(2 * s["r"] + 2 * a.margin / zoom))
        cx, cy = int(round(s["x"])), int(round(s["y"]))
        src = find_source(cx, cy, size, ok, Yr, tex, w, h)
        steps.append(heal_step([(cx, cy)], size, a.hardness, src, a.layer, a.sample, a.ox, a.oy, zoom))
        plan.append((cx, cy, size, src))
    json.dump(steps, open(a.steps, "w"))

    if a.overlay or a.check:
        P = pngio.read(a.crop)[2]
        if a.overlay:
            img = overlay_image(P, w, h, 1)
            for cx, cy, size, src in plan:
                draw_circle(img, cx, cy, size / 2, (255, 40, 40) if src else (255, 230, 0), 1)
                if src:
                    draw_circle(img, cx + src[0], cy + src[1], size / 2, (0, 230, 255), 1)
                    draw_line(img, (cx, cy), (cx + src[0], cy + src[1]), (0, 230, 255), 1, dash=3)
            pngio.write(a.overlay, w, h, img)
        if a.check:
            v = [max(0, min(255, int(128 + a.gain * (y - yr)))) for y, yr in zip(Y, Yr)]
            img = [[(v[y * w + x],) * 3 for x in range(w)] for y in range(h)]
            for cx, cy, size, src in plan:
                draw_circle(img, cx, cy, size / 2 + 3, (255, 40, 40), 1)
            pngio.write(a.check, w, h, img)

    print(json.dumps({"spots": len(plan), "healingBrush": sum(1 for p in plan if p[3]), "spotHealing": sum(1 for p in plan if not p[3]),
                      "noise": round(sig, 3), "rejected": rejected,
                      "sizes": sorted(int(round(p[2] * zoom)) for p in plan)}))


if __name__ == "__main__":
    main()
