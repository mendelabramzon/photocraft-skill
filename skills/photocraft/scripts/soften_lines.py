#!/usr/bin/env python3
"""Plan softened (not erased) lines, folds and under-eye shadows: one masked layer per kind, at partial opacity.

How retouchers do it (Adobe's Healing Brush on an empty layer sampling Current & Below; Scott Kelby, PhLearn, Pratik
Naik): remove the line completely on its own layer, then lower that layer's opacity so part of it comes back. The
person keeps their age and expression, the light keeps the face's shape, and the client can turn it up or down later:

  Lines       crow's feet, lines under the eye, forehead and neck lines: about 50 %
  Folds       nasolabial folds, marionette lines, a deep neck crease: form shadows, so about 30 %
  Under-eye   the tear-trough shadow under a bag: about 40 % (more reads as a different, younger face)

What this does instead of hand-healing: every line is a narrow valley of tone. A grey closing (max, then min, over
the kind's radius) of a lightly smoothed copy gives the skin level on both sides of it, per channel, so the valley's
redness goes with its darkness (the same fraction, as in skin_masks.py). The layer is the photo plus that smooth
lift, so pores, stubble and grain run on through it unchanged: nothing is blurred or copied. Only valleys that are
long and thin (crow's feet networks too) count as lines; pores and blemishes are round and stay. A valley deeper than
--max-depth is not a wrinkle but a lash line, a brow, a glasses frame or hair, and is left (magenta in viz.png).
Under-eye works on the whole zone at a bigger radius, its lift faded in from the zone's edge.

area.json (full-image coordinates; draw it on grid.py): one key per kind, each a polygon or a list of them, round
the lines to treat with ~10 px of skin to spare; "exclude" as in the other planners. Keep every zone off the eye,
lashes, brows, lips, nostrils, hairline and glasses frames: lines inside a lens are fine, the frame is not.

  {"lines": [[[x, y], ...], ...], "folds": [...], "undereye": [...], "exclude": [...]}

usage: soften_lines.py crop.png X Y area.json OUTDIR [--face-width PX] [--opacity lines=0.5,folds=0.3,undereye=0.4]
crop.png   the face cropped at full resolution (image.crop), even width and height; X Y its top-left in the photo
--face-width  the face's width in px at eye level (cheek to cheek, grid.py): sets every radius
Writes OUTDIR/layers.json (one pixel layer per kind present, masked, at its opacity, in a "Soften lines" group) for
import_layers.py, preview.png (exact), viz.png (green = lines softened, cyan = under-eye lift, magenta = deep valleys
left alone, yellow = zones), lines.json. Prints the stats and warnings as one JSON line.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops

KINDS = {  # radius as a fraction of the face width, smoothing before the closing (x radius), opacity, and the depth
    # (levels below the skin beside it) past which a valley is a lash line, a brow, a frame or hair. A tear trough
    # runs deeper than a crow's foot, so its limit is higher; the lashes themselves stay outside the zone
    "lines": {"name": "Lines", "radius": 1 / 300, "pre": 0.25, "opacity": 0.5, "maxDepth": 28},
    "folds": {"name": "Folds", "radius": 1 / 90, "pre": 0.25, "opacity": 0.3, "maxDepth": 40},
    "undereye": {"name": "Under-eye", "radius": 1 / 45, "pre": 0.3, "opacity": 0.4, "maxDepth": 50},
}


def closing(src, w, h, r):
    return imgops.minf(imgops.maxf(src, w, h, r), w, h, r)


def median(vals):
    s = sorted(vals)
    return s[len(s) // 2] if s else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crop"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
    ap.add_argument("area"); ap.add_argument("outdir")
    ap.add_argument("--face-width", type=float, default=1000, help="px, cheek to cheek at eye level (default 1000)")
    ap.add_argument("--opacity", default="", help="per kind, e.g. lines=0.5,folds=0.3,undereye=0.4")
    ap.add_argument("--radius", default="", help="per kind in px, overriding --face-width, e.g. lines=5")
    ap.add_argument("--threshold", type=float, default=3.0, help="x the valley noise: fainter is texture, left alone")
    ap.add_argument("--min-depth", type=float, default=2.0, help="levels: shallower valleys are left alone")
    ap.add_argument("--max-depth", type=float,
                    help="levels: a valley this deep is a lash line, a brow, a frame or hair, never lifted "
                         "(default lines 28, folds 40, undereye 50)")
    ap.add_argument("--min-length", type=float, default=0, help="px: shorter valleys are pores (default 5 x the lines radius)")
    ap.add_argument("--max-lift", type=float, default=40.0, help="levels: no pixel is lifted more than this")
    a = ap.parse_args()

    w, h, R, G, B = imgops.load(a.crop)
    if w % 2 or h % 2:
        sys.exit("error: crop width and height must be even (import_layers centres crop-sized PNGs)")
    N = w * h
    cfg = json.load(open(a.area))
    for kv in filter(None, (a.opacity + "," + a.radius).split(",")):
        if kv.count("=") != 1 or kv.split("=")[0].strip() not in KINDS:
            sys.exit(f"error: {kv!r}: give kind=value, kind one of {', '.join(KINDS)}")
    opac = {k: v["opacity"] for k, v in KINDS.items()}
    for kv in filter(None, a.opacity.split(",")):
        k, v = kv.split("="); opac[k.strip()] = float(v)
    radius = {k: max(2, int(round(v["radius"] * a.face_width))) for k, v in KINDS.items()}
    for kv in filter(None, a.radius.split(",")):
        k, v = kv.split("="); radius[k.strip()] = max(1, int(round(float(v))))
    excl = cfg.get("exclude", [])
    Y = [imgops.lum(*v) for v in zip(R, G, B)]
    viz = [[r * 0.6, g * 0.6, b * 0.6] for r, g, b in zip(R, G, B)]
    os.makedirs(a.outdir, exist_ok=True)
    layers, stats, warnings = [], {}, []
    prev_out = [R[:], G[:], B[:]]  # the predicted result, layer by layer

    for kind in ("folds", "undereye", "lines"):  # broad first; lines on top, as a retoucher stacks them
        polys = cfg.get(kind)
        if not polys:
            continue
        r = radius[kind]
        max_depth = a.max_depth or KINDS[kind]["maxDepth"]
        zone = imgops.polygon_mask(polys if isinstance(polys[0][0], (list, tuple)) else [polys], a.ox, a.oy, w, h, excl)
        if not any(zone):
            warnings.append(f"{kind}: the zone lies outside the crop")
            continue
        pre = max(0.8, KINDS[kind]["pre"] * r)
        # work in the zone's box, plus a margin for the closing to see the skin beside a line at the zone's edge
        zx = [i % w for i in range(N) if zone[i]]; zy = [i // w for i in range(N) if zone[i]]
        mg = int(2 * r + 3 * pre) + 2
        x0, x1 = max(0, min(zx) - mg), min(w, max(zx) + mg + 1)
        y0, y1 = max(0, min(zy) - mg), min(h, max(zy) + mg + 1)
        sw, sh = x1 - x0, y1 - y0
        SN = sw * sh
        idx = [y * w + x for y in range(y0, y1) for x in range(x0, x1)]
        sz = [zone[i] for i in idx]
        sm = [imgops.gauss([ch[i] for i in idx], sw, sh, pre) for ch in (R, G, B, Y)]
        lifted = [closing(ch, sw, sh, r) for ch in sm]
        D = [[max(0.0, c - s_) for c, s_ in zip(lifted[k], sm[k])] for k in range(4)]
        zi = [i for i in range(SN) if sz[i] > 0.5]
        # the closing rides on the tops of the texture, so the whole zone reads a little "lifted": that bias is the
        # valley depth of plain skin, taken off everywhere so treated lines don't turn into light ones
        bias = [median([D[k][i] for i in zi[::3]]) for k in range(4)]
        noise = 1.4826 * median([abs(D[3][i] - bias[3]) for i in zi[::3]]) or 0.5
        thr = max(a.min_depth, a.threshold * noise)
        depth = [D[3][i] - bias[3] for i in range(SN)]
        slift = [[max(0.0, min(a.max_lift, D[k][i] - bias[k])) for i in range(SN)] for k in range(3)]
        deep_n = 0
        if kind == "undereye":
            # the whole zone, faded in from its edge over a third of the radius; deep valleys (the lash line) stay out
            deep = bytearray(1 if sz[i] > 0.5 and depth[i] > max_depth else 0 for i in range(SN))
            deep_g = imgops.maxf([float(v) for v in deep], sw, sh, max(2, r // 3))
            core = [sz[i] * (0.0 if deep_g[i] else 1.0) for i in range(SN)]
            sm_ = imgops.gauss(imgops.minf(core, sw, sh, max(1, r // 3)), sw, sh, max(1.0, r / 3))
            sm_ = [min(v, z) for v, z in zip(sm_, sz)]
            deep_n = sum(1 for c in imgops.components(deep, sw, sh) if len(c) > 4)
            n_lines = None
            score = [0.0] * SN
        else:
            # long thin valleys only: hysteresis (seeds over thr, grown down to thr/2), then extent and depth
            weak = bytearray(1 if sz[i] > 0.5 and depth[i] > 0.5 * thr else 0 for i in range(SN))
            min_len = a.min_length or 5 * radius["lines"]
            core = bytearray(SN)
            n_lines = 0
            score = [0.0] * SN  # 1 = a line softened, 2 = a deep valley left
            for pix in imgops.components(weak, sw, sh):
                if len(pix) < 6 or max(depth[i] for i in pix) < thr:
                    continue
                xs = [i % sw for i in pix]; ys = [i // sw for i in pix]
                extent = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
                pset = set(pix)
                perim = sum(1 for i in pix if any(j not in pset for j in (i - 1, i + 1, i - sw, i + sw)))
                thick = 2.0 * len(pix) / max(perim, 1)
                if median([depth[i] for i in pix]) > max_depth:
                    deep_n += 1
                    for i in pix:
                        score[i] = 2
                    continue
                n = len(pix)
                mx, my = sum(xs) / n, sum(ys) / n
                sxx = sum((x - mx) ** 2 for x in xs) / n; syy = sum((y - my) ** 2 for y in ys) / n
                sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
                tr, det = sxx + syy, sxx * syy - sxy * sxy
                l1 = tr / 2 + math.sqrt(max(0.0, tr * tr / 4 - det)); l2 = max(tr - l1, 1e-6)
                aspect = math.sqrt(l1 / l2)
                # a line, or a network of thin lines (crow's feet joined at their roots); not a pore, a blemish, a
                # patch of stubble or a blob of shadow
                if extent < min_len or thick > 1.5 * max(3.0, 1.2 * r) or not (aspect >= 2.5 or (aspect >= 1.6 and extent >= 10 * thick)):
                    continue
                n_lines += 1
                for i in pix:
                    core[i] = 1; score[i] = 1
            grown = imgops.maxf([float(v) for v in core], sw, sh, max(1, r // 2))
            sm_ = imgops.gauss(grown, sw, sh, max(0.8, r / 4))
            zf = imgops.gauss(sz, sw, sh, 2.0)
            sm_ = [min(1.0, v) * z for v, z in zip(sm_, zf)]
        m = [0.0] * N
        lift = [[0.0] * N for _ in range(3)]
        for j, i in enumerate(idx):
            m[i] = sm_[j]
            for k in range(3):
                lift[k][i] = slift[k][j]
            if score[j] == 1:
                viz[i] = [40, 230, 40]
            elif score[j] == 2:
                viz[i] = [230, 0, 230]
            elif kind == "undereye" and sm_[j] > 0.05:
                t = sm_[j]
                viz[i] = [viz[i][0] * (1 - t), viz[i][1] * (1 - t) + 230 * t, viz[i][2] * (1 - t) + 255 * t]
        treated = sum(1 for v in m if v > 0.05)
        depths = [depth[j] for j in range(SN) if sm_[j] > 0.5]  # levels below the skin beside them, at full removal
        if not treated:
            warnings.append(f"{kind}: nothing to soften found (lines fainter than {thr:.1f} levels, or the zone missed them)")
            continue
        op = opac[kind]
        name = KINDS[kind]["name"]
        px = [[min(255.0, (R, G, B)[k][i] + lift[k][i]) for i in range(N)] for k in range(3)]
        mask8 = [round(v * 255) / 255 for v in m]
        px8 = [[float(min(255, max(0, int(v + 0.5)))) for v in ch] for ch in px]
        imgops.save_rgb(os.path.join(a.outdir, f"{kind}.png"), w, h, *px)
        imgops.save_gray(os.path.join(a.outdir, f"{kind}_mask.png"), w, h, m)
        # the predicted composite of this layer over what's below (Normal, mask x opacity)
        for k in range(3):
            prev_out[k] = [b + (p - b) * mv * op for b, p, mv in zip(prev_out[k], px8[k], mask8)]
        layers.append({"name": name, "image": f"{kind}.png", "mask": f"{kind}_mask.png", "opacity": op})
        stats[kind] = {"radius": r, "noise": round(noise, 2), "threshold": round(thr, 2), "opacity": op,
                       "lines": n_lines, "deepLeft": deep_n, "pixels": treated,
                       "depthP50": round(imgops.percentile(depths, 50), 1) if depths else 0,
                       "depthP95": round(imgops.percentile(depths, 95), 1) if depths else 0}
        if kind != "undereye" and n_lines == 0:
            warnings.append(f"{kind}: no long thin valleys in the zone")

    if not layers:
        print(json.dumps({"layers": 0, "stats": stats, "warnings": warnings}))
        sys.exit(1)
    imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w, h, *prev_out)
    for kind in ("lines", "folds", "undereye"):  # zone outlines
        polys = cfg.get(kind)
        if not polys:
            continue
        zone = imgops.polygon_mask(polys if isinstance(polys[0][0], (list, tuple)) else [polys], a.ox, a.oy, w, h)
        for i in range(w + 1, N - w - 1):
            if zone[i] and not (zone[i - 1] and zone[i + 1] and zone[i - w] and zone[i + w]):
                viz[i] = [255, 230, 0]
    imgops.save_rgb(os.path.join(a.outdir, "viz.png"), w, h, *[[p[k] for p in viz] for k in range(3)])
    spec = {"center": [a.ox + w / 2, a.oy + h / 2], "crop": [a.ox, a.oy, w, h], "preview": "preview.png",
            "group": "Soften lines", "layers": layers}
    json.dump(spec, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    out = {"layers": len(layers), "stats": stats, "warnings": warnings}
    json.dump(out, open(os.path.join(a.outdir, "lines.json"), "w"), indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
