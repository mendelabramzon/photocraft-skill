#!/usr/bin/env python3
"""Eyes and teeth, the natural way: soft masks and measured Curves for teeth whitening, eye whites and irises.

Run it on a crop of the face (after the skin is healed, if you do both). From regions.json (per eye: the eye opening
drawn along the lid margins and a rough iris circle; a teeth polygon inside the lips) it builds colour-gated masks,
measures teeth and eye whites in Lab (D50, as Photoshop's Info panel) and solves Curves against targets:

  teeth.png      teeth only: light pixels inside the polygon; gums, lips, tongue (pinker) and the dark gaps fall out
  sclera.png     the eye whites: the opening minus the iris; lashes and the lid line (dark), skin and the caruncle
                 (more saturated) fall out; whites_lift.png the same, fading towards the corners for the lift
  veins.png      thin red veins in the eye whites; veins_ref.png is the clean white under them (a pixel layer)
  iris.png       the iris minus pupil and catchlight, strongest on the side away from the catchlight (light enters
                 there and leaves on the far side); limbal.png is the dark ring at the iris edge
  sharpen.png    iris and lashes only, for an Unsharp Mask stamp layer
  layers.json    for import_layers.py: the group, its layers, curves and masks, with crop + preview to verify
  preview.png    the predicted result (PhotoCraft's Curves spline and Luminosity maths; the sharpening rendered by
                 photocraft-cli); viz.png where each mask acts (teeth cyan, whites yellow, veins red, iris green,
                 limbal ring magenta, sharpen blue); regions.png the regions as drawn and the refined irises
  eyes_teeth.json  measurements before/after and the checks

Targets. Teeth: with eye whites in the crop, --whiten of the teeth's yellow (b*) ABOVE the eye whites' is taken out
(the whites carry the same light, so a warm light stays warm); without them, --whiten of their b*. Never below
--teeth-b-min, never more neutral than the corrected eye whites, L* up at most --teeth-lift and only as far as
there's yellow to take out, and never brighter than the lit eye whites (--margin). One curve per channel moves every
tooth by a smooth amount and never reorders tones, so the back teeth stay darker and the edges translucent. Eye
whites: redness (a*) down --sclera-red and yellow (b*) down --sclera-yellow, never past a slightly warm white (a
Curves layer); L* up --sclera-lift beside the iris and less towards the corners, which keeps the eyeball round (a
Luminosity layer). --light warm (golden hour, tungsten) keeps the light's colour in the whites. Veins: the red
lines are replaced by the clean white around them, by --veins. Iris: up to --iris-lift L* on the far side from the
catchlight, the limbal ring down --limbal L*. All of it on named layers the user can turn down.

usage: eyes_teeth.py crop.png cropX cropY regions.json outdir [--whiten 0.4] [--space srgb|p3] [--no-sharpen]
regions.json: {"eyes": [{"opening": [[x, y], ...], "iris": [cx, cy, r]}, ...],
               "teeth": [[x, y], ...] or [[[x, y], ...], ...], "exclude": [[x0, y0, x1, y1] or [[x, y], ...], ...]}
"""
import argparse
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc
import pngio
from imgops import components, gauss, lab, lab_to_rgb, load, lum, lut_f, maxf, minf, percentile, polygon_mask, save_gray, \
    save_rgb, set_lum, spline_lut

DODGE = [[0, 0], [128, 160], [255, 255]]
BURN = [[0, 0], [128, 96], [255, 255]]
GRAY_L = [lab(v, v, v)[0] for v in range(256)]  # L* of each grey level: luminance targets in L*


def smooth(a, b, x):
    t = 0.0 if x <= a else 1.0 if x >= b else (x - a) / (b - a)
    return t * t * (3 - 2 * t)


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def gray_l(y):
    y = clamp(y, 0, 255); i = min(254, int(y))
    return GRAY_L[i] + (GRAY_L[i + 1] - GRAY_L[i]) * (y - i)


def gray_for_l(L):
    """Grey level whose L* is L (inverse of gray_l)."""
    if L <= GRAY_L[0]:
        return 0.0
    for i in range(255):
        if GRAY_L[i + 1] >= L:
            return i + (L - GRAY_L[i]) / max(1e-9, GRAY_L[i + 1] - GRAY_L[i])
    return 255.0


def bilinear(img, w, h, x, y):
    x = clamp(x, 0, w - 1.001); y = clamp(y, 0, h - 1.001)
    i, j = int(x), int(y); fx, fy = x - i, y - j; k = j * w + i
    return (img[k] * (1 - fx) + img[k + 1] * fx) * (1 - fy) + (img[k + w] * (1 - fx) + img[k + w + 1] * fx) * fy


class Box:
    """A sub-rectangle of the crop (a region's bounding box plus margin), for working on small images."""

    def __init__(self, x0, y0, x1, y1, w, h):
        self.x0, self.y0 = max(0, int(x0)), max(0, int(y0))
        self.w, self.h = min(w, int(math.ceil(x1)) + 1) - self.x0, min(h, int(math.ceil(y1)) + 1) - self.y0
        self.W = w

    def take(self, img):
        return [v for y in range(self.y0, self.y0 + self.h) for v in img[y * self.W + self.x0:y * self.W + self.x0 + self.w]]

    def put(self, img, sub, combine=max):
        for y in range(self.h):
            for x in range(self.w):
                i = (self.y0 + y) * self.W + self.x0 + x
                img[i] = combine(img[i], sub[y * self.w + x])


def fit_circle(pts):
    """Least-squares circle (Kasa) through (x, y) points: (cx, cy, r)."""
    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts); syy = sum(p[1] * p[1] for p in pts); sxy = sum(p[0] * p[1] for p in pts)
    z = [p[0] * p[0] + p[1] * p[1] for p in pts]
    M = [[sxx, sxy, sx, -sum(p[0] * q for p, q in zip(pts, z))], [sxy, syy, sy, -sum(p[1] * q for p, q in zip(pts, z))],
         [sx, sy, n, -sum(z)]]
    for i in range(3):
        k = max(range(i, 3), key=lambda j: abs(M[j][i])); M[i], M[k] = M[k], M[i]
        for j in range(i + 1, 3):
            f = M[j][i] / M[i][i]
            M[j] = [u - f * v for u, v in zip(M[j], M[i])]
    x = [0.0] * 3
    for i in range(2, -1, -1):
        x[i] = (M[i][3] - sum(M[i][j] * x[j] for j in range(i + 1, 3))) / M[i][i]
    cx, cy = -x[0] / 2, -x[1] / 2
    return cx, cy, math.sqrt(max(0.0, cx * cx + cy * cy - x[2]))


def refine_iris(Ls, box, opening, cx, cy, r):
    """Find the iris edge along rays from the drawn centre (the steepest dark-to-light step between 0.75 r and
    1.25 r, only on rays that stay inside the eye opening: lids hide the top and bottom), then fit a circle to those
    edge points, dropping outliers (tear-film specks, lashes). Returns (cx, cy, r, edge points, refined); the drawn
    circle is kept when too few rays see the edge or the fit wanders off."""
    w, h = box.w, box.h
    inside = minf(opening, w, h, 1)
    lo, hi = 0.75 * r, 1.25 * r
    rhos = [lo - 1.5 + 0.5 * j for j in range(int((hi - lo + 3) / 0.5) + 1)]
    pts = []
    for k in range(0, 360, 3):
        c, s_ = math.cos(math.radians(k)), math.sin(math.radians(k))
        prof = []
        for rho in rhos:
            x, y = cx + rho * c, cy + rho * s_
            if not (0 <= x < w - 1 and 0 <= y < h - 1) or inside[int(y + 0.5) * w + int(x + 0.5)] < 0.5:
                prof = None
                break
            prof.append(bilinear(Ls, w, h, x, y))
        if not prof:
            continue
        grads = [(prof[j + 2] - prof[j - 2]) / 2 for j in range(3, len(prof) - 3)]  # L* per px, at rhos[3:-3]
        j = max(range(len(grads)), key=grads.__getitem__)
        if grads[j] < 2.0:
            continue
        if 0 < j < len(grads) - 1:  # parabolic peak for sub-pixel
            den = grads[j - 1] - 2 * grads[j] + grads[j + 1]
            off = 0.5 * (grads[j - 1] - grads[j + 1]) / den if den < 0 else 0.0
        else:
            off = 0.0
        rho = rhos[j + 3] + 0.5 * off
        pts.append((cx + rho * c, cy + rho * s_))
    if len(pts) < 12:
        return cx, cy, float(r), len(pts), False
    for _ in range(4):
        fx, fy, fr = fit_circle(pts)
        res = [abs(math.hypot(p[0] - fx, p[1] - fy) - fr) for p in pts]
        keep = [p for p, e in zip(pts, res) if e <= max(1.5, 2.5 * percentile(res, 50))]
        if len(keep) == len(pts) or len(keep) < 10:
            break
        pts = keep
    fx, fy, fr = fit_circle(pts)
    if math.hypot(fx - cx, fy - cy) > 0.35 * r or not 0.8 * r <= fr <= 1.2 * r:
        return cx, cy, float(r), len(pts), False
    return fx, fy, fr, len(pts), True


def solve_curves(pix, target, space, fixed_iters=3):
    """Per-channel Curves (red, green, blue) that move a region's representative colours (its L* quartiles) to
    target(L, a, b) -> (L, a, b). pix: (r, g, b) tuples. A few fixed-point passes make the region's measured median
    land on the target despite the smooth curve. Returns (curves, luts)."""
    labs_ = [lab(*p, space) for p in pix]
    order = sorted(range(len(pix)), key=lambda i: labs_[i][0])
    n = len(order); band = max(1, n // 20)
    reps = []
    for q in (25, 50, 75):
        k = int((n - 1) * q / 100)
        sel = order[max(0, k - band):k + band + 1]
        reps.append(tuple(percentile([pix[i][c] for i in sel], 50) for c in range(3)))
    goal = [target(*lab(*p, space)) for p in reps]
    want = [list(g) for g in goal]
    med = lambda vals: percentile(vals, 50)
    for _ in range(fixed_iters):
        tg = [tuple(clamp(v, 1, 254) for v in lab_to_rgb(*t, space)) for t in want]
        curves, luts = {}, []
        for c, name in enumerate(("red", "green", "blue")):
            pts = sorted((reps[j][c], tg[j][c]) for j in range(3))
            merged = []
            for x, y in pts:
                if merged and x - merged[-1][0] < 8:
                    merged[-1] = ((merged[-1][0] + x) / 2, (merged[-1][1] + y) / 2)
                else:
                    merged.append((x, y))
            cur = [[0, 0]]
            for x, y in merged:
                x, y = int(round(clamp(x, 1, 254))), int(round(clamp(y, 1, 254)))
                if x > cur[-1][0] and y >= cur[-1][1]:
                    cur.append([x, y])
            cur.append([255, 255])
            lut = spline_lut(cur)
            if any(lut[i + 1] < lut[i] for i in range(255)):  # a wiggle: fall back to the median point alone
                x, y = int(round(reps[1][c])), int(round(tg[1][c]))
                cur = [[0, 0], [x, y], [255, 255]]; lut = spline_lut(cur)
            curves[name] = cur; luts.append(lut)
        got = [lab(*(lut_f(luts[c], p[c]) for c in range(3)), space) for p in pix]
        mg = [med([g[k] for g in got]) for k in range(3)]
        mb = [med([l[k] for l in labs_]) for k in range(3)]
        mt = target(*mb)
        for t in want:  # nudge the targets by what the median missed
            for k in range(3):
                t[k] += mt[k] - mg[k]
    return curves, luts


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("crop"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
    ap.add_argument("regions"); ap.add_argument("outdir")
    ap.add_argument("--space", choices=("srgb", "p3"), default="srgb", help="the photo's RGB space, for Lab")
    ap.add_argument("--whiten", type=float, default=0.4, help="fraction of the teeth's yellow (b*) taken out")
    ap.add_argument("--teeth-b-min", type=float, default=6.0, help="teeth b* never goes below this (natural ivory)")
    ap.add_argument("--teeth-lift", type=float, default=3.0, help="max L* the teeth are lifted")
    ap.add_argument("--margin", type=float, default=2.0, help="lit teeth stay this many L* below the lit eye whites")
    ap.add_argument("--sclera-lift", type=float, default=3.0, help="L* the eye whites are lifted")
    ap.add_argument("--light", choices=("neutral", "warm"), default="neutral",
                    help="warm: golden hour, tungsten, candle light. The eye whites keep the light's colour (only veins "
                         "and a little redness go) and the teeth are whitened relative to them")
    ap.add_argument("--sclera-red", type=float, help="fraction of the eye whites' redness (a*) taken out (0.5; warm light 0.15)")
    ap.add_argument("--sclera-yellow", type=float, help="fraction of their yellow (b*) taken out (0.3; warm light 0)")
    ap.add_argument("--veins", type=float, default=0.8, help="fraction of each vein replaced by the clean white")
    ap.add_argument("--vein-threshold", type=float, default=5.0, help="levels of extra redness (R-G) that count as a vein")
    ap.add_argument("--iris-lift", type=float, default=5.0, help="L* the iris is lifted on the far side from the catchlight")
    ap.add_argument("--limbal", type=float, default=2.0, help="L* the limbal ring is darkened (0 = off)")
    ap.add_argument("--no-refine", action="store_true", help="use the iris circles as given")
    ap.add_argument("--no-sharpen", action="store_true")
    ap.add_argument("--sharpen-amount", type=float, default=80)
    ap.add_argument("--sharpen-radius", type=float, help="px (default: iris radius / 30, 0.5..1.5)")
    a = ap.parse_args()
    warm = a.light == "warm"
    if a.sclera_red is None:
        a.sclera_red = 0.15 if warm else 0.5
    if a.sclera_yellow is None:
        a.sclera_yellow = 0.0 if warm else 0.3
    os.makedirs(a.outdir, exist_ok=True)
    cfg = json.load(open(a.regions))
    w, h, R, G, B = load(a.crop)
    N = w * h
    if w % 2 or h % 2:
        print("warning: odd crop size; the masks are centred on the crop, keep width and height even", file=sys.stderr)
    excl = cfg.get("exclude", [])
    m_teeth = [0.0] * N; m_sclera = [0.0] * N; m_veins = [0.0] * N; w_iris = [0.0] * N; w_limbal = [0.0] * N
    w_wlift = [0.0] * N  # where the eye whites get lifted: full beside the iris, less towards the corners
    m_sharp = [0.0] * N
    clean = [None] * N  # the clean eye white under veins
    info = {"eyes": []}
    lut_d, lut_b = spline_lut(DODGE), spline_lut(BURN)

    def box_of(pts, extra=0, margin=6):
        xs = [p[0] - a.ox for p in pts]; ys = [p[1] - a.oy for p in pts]
        return Box(min(xs) - extra - margin, min(ys) - extra - margin, max(xs) + extra + margin, max(ys) + extra + margin, w, h)

    # ------------------------------------------------------------ eyes
    for eye in cfg.get("eyes", []):
        cx, cy, r = eye["iris"]
        bx = box_of(eye["opening"] + [[cx - r, cy - r], [cx + r, cy + r]], extra=max(4, r * 0.7))
        bw, bh = bx.w, bx.h
        sR, sG, sB = bx.take(R), bx.take(G), bx.take(B)
        sL = [lab(r_, g_, b_, a.space) for r_, g_, b_ in zip(sR, sG, sB)]
        Ls = gauss([v[0] for v in sL], bw, bh, 0.8)
        op_bin = polygon_mask([eye["opening"]], a.ox + bx.x0, a.oy + bx.y0, bw, bh, excl)
        opening = [min(v, s) for v, s in zip(gauss(op_bin, bw, bh, 0.7), maxf(op_bin, bw, bh, 1))]
        icx, icy, ir = cx - a.ox - bx.x0, cy - a.oy - bx.y0, float(r)
        fit, refined = None, False
        if not a.no_refine:
            icx, icy, ir, fit, refined = refine_iris(Ls, bx, op_bin, icx, icy, ir)
        D = [math.hypot(i % bw - icx, i // bw - icy) for i in range(bw * bh)]
        disk = [clamp(ir + 0.5 - d) for d in D]
        vis = [o * dk for o, dk in zip(opening, disk)]
        iris_px = [i for i in range(bw * bh) if vis[i] > 0.5]
        iris_med = percentile([sL[i][0] for i in iris_px], 50) if iris_px else 50.0
        # catchlights: much lighter than the iris, inside the disk (pupil included)
        cat_bin = [1.0 if D[i] <= 0.8 * ir and op_bin[i] > 0.5 and sL[i][0] > max(iris_med + 25, 55) else 0.0 for i in range(bw * bh)]
        catch = [min(1.0, 1.5 * v) for v in gauss(maxf(cat_bin, bw, bh, 1), bw, bh, 1.0)]
        cxs = [i % bw for i in range(bw * bh) if cat_bin[i]]; cys = [i // bw for i in range(bw * bh) if cat_bin[i]]
        if cxs:
            ux, uy = icx - sum(cxs) / len(cxs), icy - sum(cys) / len(cys)
        else:
            ux, uy = 0.0, 1.0  # no catchlight: light from above, glow at the bottom
        un = math.hypot(ux, uy) or 1.0; ux, uy = ux / un, uy / un
        # pupil: the dark centre of the radial profile (catchlights ignored)
        rings = [[] for _ in range(int(ir) + 1)]
        for i in range(bw * bh):
            if vis[i] > 0.5 and not cat_bin[i] and D[i] < len(rings):
                rings[int(D[i])].append(sL[i][0])
        prof = [percentile(ring, 50) if ring else None for ring in rings]
        known = [p for p in prof if p is not None]
        rp = 0.0
        if known:
            p_in = percentile([p for p in prof[:max(2, int(ir * 0.15))] if p is not None] or known[:1], 50)
            p_out = percentile([p for k, p in enumerate(prof) if p is not None and 0.55 * ir <= k <= 0.85 * ir] or known[-1:], 50)
            if p_out - p_in > 6:
                rp = next((k for k, p in enumerate(prof) if p is not None and p > (p_in + p_out) / 2), 0)
        pupil_seen = rp > 0
        if not pupil_seen:  # a very dark iris hides the pupil: keep a typical one out of the lift anyway
            rp = round(0.4 * ir)
        pupil = [clamp(rp + 1 - d) for d in D]
        sub_iris = [0.0] * (bw * bh); sub_limbal = [0.0] * (bw * bh)
        for i in range(bw * bh):
            if vis[i] <= 0:
                continue
            x, y, d = i % bw, i // bw, D[i]
            Li = sL[i][0]  # lashes over the iris and specular bits are not iris: leave them alone
            region = vis[i] * (1 - pupil[i]) * (1 - catch[i]) * smooth(iris_med - 28, iris_med - 16, Li) * \
                (1 - smooth(iris_med + 12, iris_med + 24, Li))
            t = ((x - icx) * ux + (y - icy) * uy) / ir
            wr = smooth(rp, rp + 0.3 * (ir - rp), d) * (1 - smooth(0.75 * ir, 0.92 * ir, d))
            sub_iris[i] = region * smooth(-0.4, 0.8, t) * wr
            sub_limbal[i] = opening[i] * (1 - catch[i]) * smooth(0.78 * ir, 0.94 * ir, d) * (1 - smooth(ir - 1.5, ir + 0.5, d))
        # eye whites: opening minus the iris; lashes and the lid line are dark and fall out
        raw = [o * smooth(ir + 0.5, ir + 2.5, d) for o, d in zip(opening, D)]
        core_px = [i for i in range(bw * bh) if raw[i] > 0.5]
        Lsc = percentile([sL[i][0] for i in core_px], 70) if core_px else 80.0
        sa, sb = gauss([v[1] for v in sL], bw, bh, 2.0), gauss([v[2] for v in sL], bw, bh, 2.0)
        chroma = [math.hypot(x_, y_) for x_, y_ in zip(sa, sb)]  # smoothed: thin veins don't punch holes
        Csc = percentile([chroma[i] for i in core_px], 40) if core_px else 8.0
        sub_sclera = [raw[i] * smooth(Lsc - 35, Lsc - 22, sL[i][0]) * (1 - smooth(Csc + 6, Csc + 14, chroma[i]))
                      for i in range(bw * bh)]
        sub_sclera = [min(v, o) for v, o in zip(gauss(sub_sclera, bw, bh, 0.8), maxf(raw, bw, bh, 1))]
        # veins: thin lines redder than the white around them (broad pink areas near the lids are not veins)
        core = minf([1.0 if v > 0.5 else 0.0 for v in sub_sclera], bw, bh, 2)
        red = [r_ - g_ for r_, g_ in zip(sR, sG)]
        sig = max(2.0, ir / 8)
        wv = core[:]
        for _ in range(2):
            den = gauss(wv, bw, bh, sig)
            ref = [n_ / d_ if d_ > 1e-4 else 0.0 for n_, d_ in zip(gauss([k * v for k, v in zip(wv, red)], bw, bh, sig), den)]
            dev = [v - rf for v, rf in zip(red, ref)]
            wv = [c_ * (1.0 if dv < a.vein_threshold * 0.6 else 0.0) for c_, dv in zip(core, dev)]
        broad = gauss([max(0.0, dv) for dv in dev], bw, bh, 2.5)
        vein_raw = [c_ * clamp((dv - br - a.vein_threshold) / a.vein_threshold) for c_, dv, br in zip(core, dev, broad)]
        sub_veins = [min(c_, v) for c_, v in zip(core, gauss(maxf(vein_raw, bw, bh, 1), bw, bh, 0.7))]
        den = gauss(wv, bw, bh, sig)
        cref = [[n_ / d_ if d_ > 1e-4 else src for n_, d_, src in
                 zip(gauss([k * v for k, v in zip(wv, ch)], bw, bh, sig), den, ch)] for ch in (sR, sG, sB)]
        # sharpening: the iris (with pupil and catchlight) and the lashes just outside the opening
        band = [max(0.0, b_ - o) for b_, o in zip(maxf(op_bin, bw, bh, max(2, int(ir * 0.5))), minf(op_bin, bw, bh, 1))]
        band_px = [sL[i][0] for i in range(bw * bh) if band[i] > 0.5]
        Lb = percentile(band_px, 50) if band_px else 50.0
        lashes = [band[i] * (1 - smooth(Lb - 16, Lb - 4, sL[i][0])) for i in range(bw * bh)]
        ring = maxf(cat_bin, bw, bh, 3)
        sub_sharp = gauss([max(o * dk * (1 - rg), l_) for o, dk, l_, rg in zip(opening, disk, lashes, ring)], bw, bh, 0.7)
        sub_iris = gauss(sub_iris, bw, bh, 0.8); sub_limbal = gauss(sub_limbal, bw, bh, 0.8)
        # a smooth mask times one strength per eye, set so the iris's median tone moves by the asked L*: like a
        # soft brush at a fixed opacity, the curve does the rest (per-pixel division would blow up on lashes)
        for sub_w, dl, lut in ((sub_iris, a.iris_lift, lut_d), (sub_limbal, -a.limbal, lut_b)):
            sel = [i for i in range(bw * bh) if sub_w[i] > 0.3]
            k = 0.0
            if sel and dl:
                rep_ = [percentile([ch[i] for i in sel], 50) for ch in (sR, sG, sB)]
                y0 = lum(*rep_)
                got = lum(*(lut_f(lut, v) for v in rep_)) - y0
                want = gray_for_l(gray_l(y0) + dl) - y0
                k = clamp(want / got) if abs(got) > 0.5 and want * got > 0 else 0.0
            for i in range(bw * bh):
                sub_w[i] *= k
        # lighten the whites mostly beside the iris; brightening the corners flattens the round eyeball
        sub_wlift = [v * (1 - 0.6 * smooth(0.15 * ir, 1.4 * ir, d - ir)) for v, d in zip(sub_sclera, D)]
        bx.put(w_wlift, sub_wlift)
        bx.put(m_sclera, sub_sclera); bx.put(m_veins, sub_veins); bx.put(w_iris, sub_iris)
        bx.put(w_limbal, sub_limbal); bx.put(m_sharp, sub_sharp)
        for y in range(bh):
            for x in range(bw):
                if sub_veins[y * bw + x] > 0:
                    clean[(bx.y0 + y) * w + bx.x0 + x] = (cref[0][y * bw + x], cref[1][y * bw + x], cref[2][y * bw + x])
        info["eyes"].append({
            "iris": [round(icx + bx.x0 + a.ox, 1), round(icy + bx.y0 + a.oy, 1), round(ir, 1)], "edgePoints": fit, "refined": refined,
            "pupilRadius": rp, "pupilSeen": pupil_seen, "catchlight": bool(cxs), "glowTowards": [round(ux, 2), round(uy, 2)],
            "veinPx": sum(1 for v in sub_veins if v > 0.3)})

    # ------------------------------------------------------------ teeth
    tp = cfg.get("teeth")
    t_stats = None
    if tp:
        polys = tp if isinstance(tp[0][0], (list, tuple)) else [tp]
        bx = box_of([p for poly in polys for p in poly])
        bw, bh = bx.w, bx.h
        sR, sG, sB = bx.take(R), bx.take(G), bx.take(B)
        sL = [lab(r_, g_, b_, a.space) for r_, g_, b_ in zip(sR, sG, sB)]
        pbin = polygon_mask(polys, a.ox + bx.x0, a.oy + bx.y0, bw, bh, excl)
        inside = [i for i in range(bw * bh) if pbin[i] > 0.5]
        Lin = [sL[i][0] for i in inside]
        T = max(25.0, 0.42 * percentile(Lin, 90))  # gaps and the mouth's interior are darker than this
        top = percentile(Lin, 60)
        at = percentile([sL[i][1] for i in inside if sL[i][0] >= top], 50)  # the lit teeth's a*; gums are pinker
        # gums, lips and tongue are pinker than lit teeth (a*). Teeth deep in warm shadow can be as red as gums and fall
        # out too; that's usually right, they read as shadow (hue doesn't separate them: lip skin and gums overlap)
        gate = [smooth(T - 6, T + 6, sL[i][0]) * (1 - smooth(at + 6, at + 12, sL[i][1])) for i in range(bw * bh)]
        soft = gauss(pbin, bw, bh, 1.0)
        sub = [g_ * s for g_, s in zip(gate, soft)]
        comps = components([v > 0.5 for v in sub], bw, bh)  # a gum or lip highlight is a small island: drop it
        big = max((len(c_) for c_ in comps), default=0)
        for c_ in comps:
            if len(c_) < max(20, 0.01 * big):
                for i in c_:
                    sub[i] = 0.0
        sub = gauss(sub, bw, bh, 0.6)
        bx.put(m_teeth, sub)
        t_stats = {"gapL": round(T, 1), "gumA": round(at + 6, 1)}

    def q8(m, k=1.0):  # masks are 8-bit
        return [round(clamp(v * k) * 255) / 255 if v else 0.0 for v in m]
    m_teeth = q8(m_teeth); m_sclera = q8(m_sclera); m_veins = q8(m_veins, a.veins); m_sharp = q8(m_sharp)

    def region_lab(mask, img=None, thr=0.5):
        rr, gg, bb = img or (R, G, B)
        idx = [i for i in range(N) if mask[i] > thr]
        px = [(rr[i], gg[i], bb[i]) for i in idx]
        if not px:
            return None, px, idx
        ls = [lab(*p, a.space) for p in px]
        return {k: [round(percentile([l[j] for l in ls], p), 1) for j in range(3)] for k, p in (("median", 50), ("p75", 75))} | \
               {"p75L": round(percentile([l[0] for l in ls], 75), 1), "p90L": round(percentile([l[0] for l in ls], 90), 1)}, px, idx

    # the eye whites first: the teeth are capped against their corrected brightness
    layers = []
    sc_before, sc_px, sc_idx = region_lab(m_sclera)
    sc_curves = sc_luts = None
    if sc_px:
        def sclera_target(L, A, Bb):  # colour only; the lift is its own layer
            return (L, max(min(A, 0.5), A * (1 - a.sclera_red)), max(min(Bb, 1.5), Bb * (1 - a.sclera_yellow)))
        sc_curves, sc_luts = solve_curves(sc_px, sclera_target, a.space)
    # the whites' lift: one strength for the mask, so the whites beside the iris move by --sclera-lift L*
    m_wlift = [0.0] * N
    if sc_px and a.sclera_lift > 0:
        near = [i for i in range(N) if m_sclera[i] > 0.5 and w_wlift[i] > 0.85 * m_sclera[i]]
        if near:
            rep_ = [percentile([lut_f(sc_luts[c], ch[i]) for i in near], 50) for c, ch in enumerate((R, G, B))]
            y0 = lum(*rep_)
            got = lum(*(lut_f(lut_d, v) for v in rep_)) - y0
            want = gray_for_l(gray_l(y0) + a.sclera_lift) - y0
            k = clamp(want / got) if got > 0.5 and want > 0 else 0.0
            m_wlift = q8(w_wlift, k)

    def whites_after(p, i):  # an eye-white pixel through the colour and lift layers (for the teeth's limits)
        r_, g_, b_ = (lut_f(sc_luts[c], p[c]) for c in range(3))
        m = m_wlift[i]
        if m:
            tr, tg, tb = set_lum(r_, g_, b_, lum(lut_f(lut_d, r_), lut_f(lut_d, g_), lut_f(lut_d, b_)))
            r_, g_, b_ = r_ + m * (tr - r_), g_ + m * (tg - g_), b_ + m * (tb - b_)
        return lab(r_, g_, b_, a.space)
    te_before, te_px, _ = region_lab(m_teeth)
    te_curves = te_luts = None
    teeth_lift, b_floor, rel = a.teeth_lift, a.teeth_b_min, None
    if te_px:
        if sc_px:  # never whiter than the eye whites: lift only up to them, and stay a little warmer than them
            wh = [whites_after(p, i) for p, i in zip(sc_px, sc_idx)]  # the whites as corrected
            teeth_lift = clamp(percentile([v[0] for v in wh], 75) - a.margin - te_before["p75L"], 0.0, a.teeth_lift)
            wb_after = percentile([v[2] for v in wh], 50)
            b_floor = max(a.teeth_b_min, wb_after + 1.0)
            # the eye whites carry the same light as the teeth: whiten only the teeth's yellow above theirs, so a
            # warm light stays warm (golden hour) instead of being white-balanced out of the teeth
            rel = (wb_after, sc_before["median"][2])

        # teeth that are already white need no brightening either: the lift fades in with the yellow to take out
        teeth_lift *= clamp((te_before["median"][2] - b_floor) / 4)

        def teeth_target(L, A, Bb):
            want = Bb * (1 - a.whiten) if rel is None else rel[0] + max(0.0, Bb - rel[1]) * (1 - a.whiten)
            return (L + teeth_lift, A, max(min(Bb, b_floor), want))
        te_curves, te_luts = solve_curves(te_px, teeth_target, a.space)

    m_iris = q8(w_iris); m_limbal = q8(w_limbal)

    # ------------------------------------------------------------ preview, stacked like the document
    out = [list(R), list(G), list(B)]

    def apply_curves(mask, luts):
        for i in range(N):
            m = mask[i]
            if m:
                for c in range(3):
                    v = out[c][i]; out[c][i] = v + m * (lut_f(luts[c], v) - v)

    def apply_lum(mask, lut):
        for i in range(N):
            m = mask[i]
            if m:
                r_, g_, b_ = out[0][i], out[1][i], out[2][i]
                tr, tg, tb = set_lum(r_, g_, b_, lum(lut_f(lut, r_), lut_f(lut, g_), lut_f(lut, b_)))
                out[0][i], out[1][i], out[2][i] = r_ + m * (tr - r_), g_ + m * (tg - g_), b_ + m * (tb - b_)

    ref_img = [list(R), list(G), list(B)]
    if any(m_veins):
        for i in range(N):
            if clean[i] is not None:
                for c in range(3):
                    ref_img[c][i] = max(0, min(255, int(clean[i][c] + 0.5)))
        for i in range(N):
            m = m_veins[i]
            if m:
                for c in range(3):
                    out[c][i] += m * (ref_img[c][i] - out[c][i])
        save_rgb(os.path.join(a.outdir, "veins_ref.png"), w, h, *ref_img)
        save_gray(os.path.join(a.outdir, "veins.png"), w, h, m_veins)
        layers.append({"name": "Eye whites (veins)", "image": "veins_ref.png", "mask": "veins.png", "blend": "Normal"})
    out_v = [ch[:] for ch in out]
    if te_curves:
        apply_curves(m_teeth, te_luts)
        save_gray(os.path.join(a.outdir, "teeth.png"), w, h, m_teeth)
        layers.append({"name": "Teeth", "adjustment": "curves", "params": te_curves, "mask": "teeth.png"})
    if sc_curves:
        apply_curves(m_sclera, sc_luts)
        save_gray(os.path.join(a.outdir, "sclera.png"), w, h, m_sclera)
        layers.append({"name": "Eye whites (colour)", "adjustment": "curves", "params": sc_curves, "mask": "sclera.png"})
    if any(m_wlift):
        apply_lum(m_wlift, lut_d)
        save_gray(os.path.join(a.outdir, "whites_lift.png"), w, h, m_wlift)
        layers.append({"name": "Eye whites (lift)", "adjustment": "curves", "params": {"points": DODGE}, "mask": "whites_lift.png",
                       "blend": "Luminosity"})
    if any(m_limbal):
        apply_lum(m_limbal, lut_b)
        save_gray(os.path.join(a.outdir, "limbal.png"), w, h, m_limbal)
        layers.append({"name": "Limbal ring", "adjustment": "curves", "params": {"points": BURN}, "mask": "limbal.png", "blend": "Luminosity"})
    if any(m_iris):
        apply_lum(m_iris, lut_d)
        save_gray(os.path.join(a.outdir, "iris.png"), w, h, m_iris)
        layers.append({"name": "Iris", "adjustment": "curves", "params": {"points": DODGE}, "mask": "iris.png", "blend": "Luminosity"})
    sharp_note = None
    if not a.no_sharpen and any(m_sharp) and info["eyes"]:
        cli = pc.find_cli()
        if not cli:
            sharp_note = "skipped: needs photocraft-cli to render the sharpening for the preview"
        else:
            ir_mean = sum(e["iris"][2] for e in info["eyes"]) / len(info["eyes"])
            usm = {"amount": a.sharpen_amount, "radius": round(a.sharpen_radius or clamp(ir_mean / 30, 0.5, 1.5), 2), "threshold": 2}
            pre, sharp = os.path.join(a.outdir, "_pre.png"), os.path.join(a.outdir, "_sharp.png")
            save_rgb(pre, w, h, *out)
            subprocess.run([str(cli), "run", pre, "--cmd", "filter.sharpen.unsharpMask", "--params", json.dumps(usm), "--out", sharp],
                           check=True, capture_output=True)
            _, _, S = pngio.read(sharp)
            rounded = [[max(0, min(255, int(v + 0.5))) for v in ch] for ch in out]  # the stamp holds 8-bit pixels
            for i in range(N):
                m = m_sharp[i]
                y_, x_ = divmod(i, w)
                for c in range(3):
                    out[c][i] = rounded[c][i] + m * (S[y_][x_][c] - rounded[c][i]) if m else rounded[c][i]
            os.remove(pre); os.remove(sharp)
            save_gray(os.path.join(a.outdir, "sharpen.png"), w, h, m_sharp)
            layers.append({"name": "Sharpen eyes", "stamp": [["filter.sharpen.unsharpMask", usm]], "mask": "sharpen.png"})
            sharp_note = usm
    save_rgb(os.path.join(a.outdir, "preview.png"), w, h, *out)

    # ------------------------------------------------------------ checks, viz, regions
    rnd = [[max(0, min(255, int(v + 0.5))) for v in ch] for ch in out]
    sc_after = region_lab(m_sclera, rnd)[0] if sc_px else None
    te_after = region_lab(m_teeth, rnd)[0] if te_px else None
    if any(m_wlift):  # beside the iris, where the lift is meant to land
        top_w = max(m_wlift)
        near = [i for i in range(N) if m_wlift[i] >= 0.85 * top_w]
        whites_near_lift = round(percentile([lab(*(rnd[c][i] for c in range(3)), a.space)[0] - lab(R[i], G[i], B[i], a.space)[0]
                                             for i in near], 50), 1)
    vein_red = None
    if any(m_veins):  # how much redder (R-G) than the clean white around them the veins are
        idx = [i for i in range(N) if m_veins[i] > 0.3]
        base = [ref_img[0][i] - ref_img[1][i] for i in idx]
        vein_red = {"before": round(sum(R[i] - G[i] - b_ for i, b_ in zip(idx, base)) / len(idx), 1),
                    "afterVeinLayer": round(sum(out_v[0][i] - out_v[1][i] - b_ for i, b_ in zip(idx, base)) / len(idx), 1)}

    def hard_edge(m):
        st = 0.0
        for i in (i for i in range(N - w) if m[i] or m[i + 1] or m[i + w]):
            st = max(st, abs(m[i + w] - m[i]), abs(m[i + 1] - m[i]) if (i + 1) % w else 0.0)
        return round(st, 2)
    checks = {}
    if te_before and te_after:
        checks["teethYellowTakenOut"] = round(1 - te_after["median"][2] / te_before["median"][2], 2) if te_before["median"][2] > 0 else None
        if sc_after and sc_before:  # lit teeth minus lit whites (L*), and teeth b* minus whites b*, before -> after
            checks["teethMinusWhitesL"] = [round(te_before["p75L"] - sc_before["p75L"], 1), round(te_after["p75L"] - sc_after["p75L"], 1)]
            checks["teethWarmerThanWhites"] = te_after["median"][2] >= sc_after["median"][2]
    if sc_before and sc_after:
        checks["whitesLift"] = round(sc_after["median"][0] - sc_before["median"][0], 1)
        if any(m_wlift):
            checks["whitesLiftBesideIris"] = whites_near_lift
        checks["whitesNotBlue"] = sc_after["median"][2] >= 0.5
    if any(m_iris):  # the lift actually reached where the iris mask is strongest
        top_m = max(m_iris)
        dl = [lab(*(rnd[c][i] for c in range(3)), a.space)[0] - lab(R[i], G[i], B[i], a.space)[0]
              for i in range(N) if m_iris[i] >= 0.6 * top_m]
        checks["irisLiftL"] = round(percentile(dl, 50), 1)
    checks["maxMaskStep"] = {k: hard_edge(m) for k, m in (("teeth", m_teeth), ("sclera", m_sclera), ("iris", m_iris)) if any(m)}
    vz = [list(R), list(G), list(B)]
    for i in (i for i in range(N) if m_teeth[i] or m_sclera[i] or m_iris[i] or m_limbal[i] or m_veins[i] or m_sharp[i]):
        v = [R[i], G[i], B[i]]
        for m, col, k in ((m_sharp[i], (60, 120, 255), 0.5), (m_teeth[i], (0, 230, 255), 0.8), (m_sclera[i], (255, 230, 0), 0.6),
                          (m_iris[i], (40, 255, 40), 1.0), (m_limbal[i], (255, 40, 255), 1.0), (m_veins[i], (255, 0, 0), 1.0)):
            t = min(1.0, k * m)
            if t:
                v = [v[c] * (1 - t) + col[c] * t for c in range(3)]
        for c in range(3):
            vz[c][i] = v[c]
    save_rgb(os.path.join(a.outdir, "viz.png"), w, h, *vz)

    # regions as drawn (green openings, yellow teeth), irises as fitted (cyan), pupils (blue): one 3x panel per region
    shapes = []  # (kind, data, colour) in full-image coords
    for eye, e in zip(cfg.get("eyes", []), info["eyes"]):
        shapes.append([("poly", eye["opening"], (0, 255, 0)), ("circle", e["iris"], (0, 230, 255))] +
                      ([("circle", [e["iris"][0], e["iris"][1], e["pupilRadius"]], (60, 60, 255))] if e["pupilRadius"] else []))
    if tp:
        shapes.append([("poly", p_, (255, 230, 0)) for p_ in (tp if isinstance(tp[0][0], (list, tuple)) else [tp])])
    panels = []
    for group in shapes:
        pts = []
        for kind, d_, _ in group:
            pts += d_ if kind == "poly" else [[d_[0] - d_[2], d_[1] - d_[2]], [d_[0] + d_[2], d_[1] + d_[2]]]
        rb = box_of(pts, margin=8)
        S_ = 3
        img = [[(int(R[(rb.y0 + y // S_) * w + rb.x0 + x // S_]), int(G[(rb.y0 + y // S_) * w + rb.x0 + x // S_]),
                 int(B[(rb.y0 + y // S_) * w + rb.x0 + x // S_])) for x in range(rb.w * S_)] for y in range(rb.h * S_)]

        def put(x, y, c):
            x, y = int((x - a.ox - rb.x0) * S_), int((y - a.oy - rb.y0) * S_)
            if 0 <= x < rb.w * S_ and 0 <= y < rb.h * S_:
                img[y][x] = c
        for kind, d_, col in group:
            if kind == "poly":
                for k in range(len(d_)):
                    (x0, y0), (x1, y1) = d_[k], d_[(k + 1) % len(d_)]
                    n = int(max(abs(x1 - x0), abs(y1 - y0)) * S_) + 1
                    for j in range(n + 1):
                        put(x0 + (x1 - x0) * j / n, y0 + (y1 - y0) * j / n, col)
            else:
                for k in range(0, 360, 2):
                    put(d_[0] + d_[2] * math.cos(math.radians(k)), d_[1] + d_[2] * math.sin(math.radians(k)), col)
        panels.append(img)
    if panels:
        PW = max(len(p_[0]) for p_ in panels)
        rows = []
        for p_ in panels:
            rows += [row + [(255, 255, 255)] * (PW - len(row)) for row in p_] + [[(255, 255, 255)] * PW] * 6
        pngio.write(os.path.join(a.outdir, "regions.png"), PW, len(rows), rows)

    spec = {"center": [a.ox + w / 2, a.oy + h / 2], "crop": [a.ox, a.oy, w, h], "preview": "preview.png",
            "group": "Eyes & teeth", "layers": layers}
    json.dump(spec, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    hints = []
    if sc_before and not warm and (sc_before["median"][2] > 12 or sc_before["median"][1] > 8):
        hints.append("the eye whites measure warm (a*, b* %s): if that's the light (golden hour, tungsten), rerun with "
                     "--light warm so the eyes and teeth keep it" % sc_before["median"][1:])
    if not sc_before and te_before and te_before["median"][2] > 18:
        hints.append("very yellow teeth and no eye whites to compare: if the light is warm, lower --whiten (0.2-0.25)")
    stats = {"crop": [a.ox, a.oy, w, h], "light": a.light, "hints": hints, "eyes": info["eyes"], "teeth": t_stats, "teethLift": round(teeth_lift, 2),
             "teethBFloor": round(b_floor, 1),
             "teethLab": {"before": te_before, "after": te_after}, "whitesLab": {"before": sc_before, "after": sc_after},
             "veinRedness": vein_red, "sharpen": sharp_note, "checks": checks, "layers": [l["name"] for l in layers]}
    json.dump(stats, open(os.path.join(a.outdir, "eyes_teeth.json"), "w"), indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
