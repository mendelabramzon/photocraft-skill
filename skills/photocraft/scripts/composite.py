#!/usr/bin/env python3
"""Put a cut-out element into another photo (the plate) so it looks photographed there, as editable layers.

A pasted element gives itself away in a few ways that can be measured, and each gets its own named layer:
  tones     blacks deeper (or whites brighter) than anything in the plate: a plate's darkest tone is rarely pure black
            (flare, haze, processing), so the element's black point goes to the plate's, then its white point, then
            colour, in the order compositors use ("Match plate", Curves clipped to the element); the midtones between
            are --gamma and --ev, by eye: two different things share no midtone to measure
  colour    it was lit by another light: the dominant colour of smooth near-neutral surfaces (a white shirt, a grey
            wall, paper) shows each image's light; the element's is taken to the plate's in linear light, above the
            black and with luminance kept (the same Curves). Picked neutrals (--plate-neutral, --element-neutral) beat
            the estimate
  grain     a clean element in a noisy plate reads as pasted at 100 %: the missing grain goes on a clipped Linear
            Light layer (127.5 + n/2 adds exactly n), both measured as a noise floor (the quietest 8 x 8 blocks)
  sharpness a studio element is usually crisper than a plate at another distance: the blur that makes its edges
            measure like the plate's, found by blurring it and measuring again; --blur bakes it in with an exact
            Gaussian (the cut file stays as it is)
  edge      a hard edge sits on the plate like a sticker: "Light wrap", the plate blurred until no detail is left,
            clipped to the element, in a band just inside its edge, Screen (or Soft Light), stronger where the plate
            behind is bright. A rim of the cut's old backdrop (of its polarity: a white sweep's light rim, not the
            object's own dark underside) is reported and drawn in edge_rim.png: no wrap hides it, decontaminate the cut
  ground    an object resting on a surface needs a contact shadow where it touches: a Multiply layer along the lower
            convex hull of its silhouette (every foot grounded), the ground's own colour at a dark tone, not black;
            in soft light also an occlusion shadow (--occlusion), the soft dark under its overhangs and between its feet
What can't be measured here: light direction and hardness (shadows on the element must fall like the plate's), and
perspective and scale (the element's horizon and size must fit the plate's camera). Check those by eye.

usage: composite.py PLATE CUT OUTDIR (--at X,Y [--anchor bottom|center] [--height H | --width W | --scale S] |
                    --same-frame) [--ref-area AREA] [--tones match|contain|none] [--harmonize 1]
                    [--plate-neutral X,Y[,R]] [--element-neutral X,Y[,R]] [--ev 0] [--gamma 1] [--grain auto|SIGMA]
                    [--blur 0|auto|SIGMA] [--wrap 0.35] [--wrap-width PX] [--wrap-blur PX] [--wrap-blend screen|softlight]
                    [--shadow contact|none] [--shadow-strength 0.6] [--occlusion 0.45] [--old-backdrop auto|light|dark]
                    [--name NAME] [--element-name NAME]

PLATE   the photo the element goes into: the plate document's flat render, or its original file (any format the
        CLI reads). Coordinates (--at, --ref-area) are in its pixels.
CUT     the element as an RGBA PNG at any size: the cutout workflow's masked layer exported alone (cutout.md).
OUTDIR  layers.json for import_layers.py (the group goes on top of the plate document), with element.png, the
        clipped layers' PNGs and preview.png (the frame as PhotoCraft will render it, exactly, so the import verifies
        itself); compare.png (plate | pasted as is | composited), zoom.png (3x edge tiles, pasted | composited),
        edge_rim.png (rim pixels of the old backdrop), element_mask.png (the element's alpha in the frame, for qc.py
        seams) and plan.json (the measurements).
"""
import argparse
import atexit
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pc
import pngio
from color_check import Image, clean_points, point, sample
from cutout_check import bbox, edge_distance, sat, win
from imgops import blend, from_linear, gauss, lum, spline_lut, to_linear
from product_shot import lower_hull

TMP = tempfile.mkdtemp(prefix="composite-")
atexit.register(shutil.rmtree, TMP, True)
FAMILIES = (("ProPhoto", "prophoto-compat"), ("ROMM", "prophoto-compat"), ("Adobe RGB", "adobe-rgb-compat"),
            ("Display P3", "display-p3"))


# ---------------------------------------------------------------- photocraft-cli

def cli():
    p = pc.find_cli()
    if not p:
        sys.exit("error: photocraft-cli not found; `pc.py cli-info` names the one to install")
    return str(p)


def cli_run(src, cmds, out=None):
    """photocraft-cli run: the JSON results, and the output file if one is asked for."""
    args = [cli(), "run", src]
    for c, p in cmds:
        args += ["--cmd", c, "--params", json.dumps(p)]
    r = subprocess.run(args + (["--out", out] if out else []), capture_output=True, text=True)
    if r.returncode or (out and not os.path.exists(out)):
        sys.exit(f"error: photocraft-cli run {os.path.basename(src)}: {(r.stderr or r.stdout).strip()[-300:]}")
    return [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"error: {path}: the cut must be a PNG with transparency")
    return struct.unpack(">II", head[16:24])


def family(desc):
    """A profile description's colour space: 'c2' and the many sRGB descriptions are all sRGB."""
    d = (desc or "").lower()
    return "srgb" if "srgb" in d or d in ("c2", "c2ci", "") else d


def profile(path):
    """(the file's colour profile description, {builtin description: id})."""
    res = cli_run(path, [("edit.profileInfo", {"profile": "document"})])[0]["result"]
    return (res.get("profile") or {}).get("description"), {b["description"]: b["id"] for b in res.get("builtins", [])}


# ---------------------------------------------------------------- measurements

def ends(R, G, B, idx, frac):
    """Mean colour of the darkest and of the lightest `frac` of the pixels idx, by luminance: what a black point and
    a white point are (the colour of the darkest stuff, not three unrelated per-channel percentiles)."""
    order = sorted(idx, key=lambda i: lum(R[i], G[i], B[i]))
    k = max(5, int(frac * len(order)))
    lo, hi = order[:k], order[-k:]
    return ([sum(c[i] for i in lo) / k for c in (R, G, B)], [sum(c[i] for i in hi) / k for c in (R, G, B)])


def neutral_cast(R, G, B, w, h, idx, step=1):
    """What a neutral looks like in this light, as Lab (a*, b*): the dominant colour of smooth, low-chroma surfaces
    (a grey wall, white clothing, paper, concrete), found by narrowing a weighted median, as color_check.py measure
    does. A plate's tungsten room reads warm, a shaded street blue. Returns ((a*, b*), share of the pixels that
    agree), or (None, share) when too few surfaces qualify."""
    keep = set(idx[::step])
    Lab = {}
    for i in keep:
        Lab[i] = imgops.lab(R[i], G[i], B[i])
    def sd(get):
        out = {}
        for i in keep:
            x, y = i % w, i // w
            if 2 <= x < w - 2 and 2 <= y < h - 2:
                vals = [get(j) for j in (i - 2 * w, i - w, i, i + w, i + 2 * w, i - 2, i - 1, i + 1, i + 2)]
                mu = sum(vals) / 9
                out[i] = (sum((v - mu) ** 2 for v in vals) / 9) ** 0.5
        return out
    lum_ = lambda j: lum(R[j], G[j], B[j])
    s_l = sd(lum_)
    cand = [i for i in s_l if s_l[i] < 2.0 and 20 <= Lab[i][0] <= 97 and max(R[i], G[i], B[i]) < 250
            and (Lab[i][1] ** 2 + Lab[i][2] ** 2) < 30 ** 2]
    if len(cand) < 50:
        return None, len(cand) / max(1, len(keep))
    ca = cb = 0.0
    for rad in (30, 15, 10, 7):
        sel = [i for i in cand if math.hypot(Lab[i][1] - ca, Lab[i][2] - cb) < rad]
        if len(sel) < 30:
            break
        wt = sorted((Lab[i][1], Lab[i][0]) for i in sel), sorted((Lab[i][2], Lab[i][0]) for i in sel)
        def wmed(pairs):
            half, acc = sum(k for _, k in pairs) / 2, 0.0
            for v, k in pairs:
                acc += k
                if acc >= half:
                    return v
            return pairs[-1][0]
        ca, cb = wmed(wt[0]), wmed(wt[1])
    agree = sum(1 for i in cand if math.hypot(Lab[i][1] - ca, Lab[i][2] - cb) < 6)
    if agree < 30:
        return None, agree / max(1, len(keep))
    return (ca, cb), agree / max(1, len(keep))


def cast_gains(plate_ab, elem_ab, amount):
    """Per-channel linear-light gains taking the element's neutral to the plate's, luminance kept, by `amount`."""
    pe = [to_linear(v) for v in imgops.lab_to_rgb(60, *plate_ab)]
    ee = [to_linear(v) for v in imgops.lab_to_rgb(60, *elem_ab)]
    g = [(max(1e-5, p_) / max(1e-5, e)) ** amount for p_, e in zip(pe, ee)]
    yg = 0.2126 * g[0] + 0.7152 * g[1] + 0.0722 * g[2]
    return [v / yg for v in g]


grain_floor = imgops.grain_floor  # the quietest 8 x 8 blocks: grain, not texture (shared with qc.py seams)


def window(vals, w, b, pad, W_, H_):
    """The box b = [x0, y0, x1, y1] grown by pad (clipped) out of a flat image: (values, width, height, x0, y0)."""
    x0, y0, x1, y1 = max(0, b[0] - pad), max(0, b[1] - pad), min(W_ - 1, b[2] + pad), min(H_ - 1, b[3] + pad)
    return [v for y in range(y0, y1 + 1) for v in vals[y * w + x0:y * w + x1 + 1]], x1 - x0 + 1, y1 - y0 + 1, x0, y0


def edge_sigma(L, w, h, mask, min_contrast=30.0, reach=12):
    """How soft the contrasty edges inside mask are, as the sigma of a Gaussian edge: contrast / (sqrt(2 pi) x the
    steepest slope across it), read on a 3x3 median (grain doesn't count) between flat parts 5-12 px either side.
    Blurs add in quadrature, so sqrt(plate^2 - element^2) is the blur that makes the element as soft as the plate.
    Recovered known blurs of 1, 1.5, 2, 3 and 4 px as 1.17, 1.94, 2.48, 3.24 and 3.80 (1.49 for 1.5 under noise of
    sigma 3). Edges under min_contrast levels, or without flat sides (texture, thin lines), are skipped; None when
    fewer than 40 qualify: nothing to compare, judge by eye."""
    b = bbox(mask, w, h)
    if not b:
        return None, 0
    L, cw, chh, x0, y0 = window(L, w, b, reach + 2, w, h)
    m = window(mask, w, b, reach + 2, w, h)[0]
    M = L[:]
    for y in range(1, chh - 1):
        for x in range(1, cw - 1):
            i = y * cw + x
            M[i] = sorted((L[i - cw - 1], L[i - cw], L[i - cw + 1], L[i - 1], L[i], L[i + 1], L[i + cw - 1], L[i + cw],
                           L[i + cw + 1]))[4]

    def at(x, y):
        xi, yi = int(x), int(y)
        tx, ty = x - xi, y - yi
        i = yi * cw + xi
        return (M[i] * (1 - tx) + M[i + 1] * tx) * (1 - ty) + (M[i + cw] * (1 - tx) + M[i + cw + 1] * tx) * ty

    cand = []
    for y in range(reach + 1, chh - reach - 1):
        for x in range(reach + 1, cw - reach - 1):
            i = y * cw + x
            if m[i]:
                gx, gy = (M[i + 1] - M[i - 1]) / 2, (M[i + cw] - M[i - cw]) / 2
                g = math.hypot(gx, gy)
                if g >= min_contrast / 10:
                    cand.append((g, x, y, gx / g, gy / g))
    cand.sort(reverse=True)
    out, used = [], set()
    ts = [k / 2 for k in range(-2 * reach, 2 * reach + 1)]
    q = len(ts) // 5
    for g, x, y, dx, dy in cand:
        if len(out) >= 400:
            break
        if (x // 6, y // 6) in used:  # one edge per 6 px cell: no edge counted many times
            continue
        prof = [at(x + t * dx, y + t * dy) for t in ts]
        lo_s, hi_s = prof[:q], prof[-q:]
        lo, hi = sum(lo_s) / q, sum(hi_s) / q
        c_ = hi - lo
        if c_ < min_contrast or max(lo_s) - min(lo_s) > 0.2 * c_ or max(hi_s) - min(hi_s) > 0.2 * c_:
            continue
        slope = max(prof[k + 1] - prof[k] for k in range(len(prof) - 1)) / 0.5
        if slope > 0:
            out.append(c_ / (math.sqrt(2 * math.pi) * slope))
            used.add((x // 6, y // 6))
    if len(out) < 40:
        return None, len(out)
    out.sort()
    return out[len(out) // 2], len(out)


def gauss_exact(src, w, h, sigma):
    """Gaussian blur with the sampled kernel out to 3 sigma, separable, edges clamped. imgops.gauss approximates it with
    three boxes, which leaves every sigma up to 0.5 untouched and gives one 3 px box for all of 0.6-1.0: matching an
    element's focus to the plate's takes tenths of a pixel."""
    if sigma < 0.6:  # a sampled kernel is too narrow down there; [a, 1 - 2a, a] has variance 2a: exact
        r, k = 1, [sigma * sigma / 2, 1 - sigma * sigma, sigma * sigma / 2]
    else:
        r = max(1, math.ceil(3 * sigma))
        k = [math.exp(-t * t / (2 * sigma * sigma)) for t in range(-r, r + 1)]
        k = [v / sum(k) for v in k]

    def rows(vals, ww, hh):
        out = []
        for y in range(hh):
            row = vals[y * ww:(y + 1) * ww]
            pad = [row[0]] * r + row + [row[-1]] * r
            acc = [0.0] * ww
            for j, kj in enumerate(k):
                acc = [s_ + kj * v for s_, v in zip(acc, pad[j:j + ww])]
            out.extend(acc)
        return out
    t = rows(src, w, h)
    t = rows([v for col in zip(*[t[y * w:(y + 1) * w] for y in range(h)]) for v in col], h, w)
    return [v for row in zip(*[t[x * h:(x + 1) * h] for x in range(w)]) for v in row]


def blur_to_match(L, A, core, w, h, target, measured):
    """The blur that makes the element's edges measure like the plate's (edge_sigma = target), found by blurring the
    element (alpha-weighted, as the layer will be) and measuring the same edges again, so the measure's own
    non-linearity cancels: the quadrature sqrt(plate^2 - element^2) of the two readings ran 15-30 % high on 1-2 px
    blurs. Searched below that quadrature value, to a tenth of a pixel; 0 under 0.3 (invisible)."""
    quad = math.sqrt(max(0.0, target * target - measured * measured))
    if quad < 0.3:
        return 0.0
    b = bbox(core, w, h)
    Lw, cw_, ch_, _, _ = window(L, w, b, 16, w, h)
    Aw = window(A, w, b, 16, w, h)[0]
    mw = window(core, w, b, 16, w, h)[0]
    LA = [l_ * a_ for l_, a_ in zip(Lw, Aw)]
    lo, hi = 0.0, min(8.0, quad + 0.3)
    while hi - lo > 0.06:
        mid = (lo + hi) / 2
        f = gauss_exact if mid < 3 else gauss
        num, den = f(LA, cw_, ch_, mid), f(Aw, cw_, ch_, mid)
        m = edge_sigma([n / d if d > 1e-4 else 0.0 for n, d in zip(num, den)], cw_, ch_, mw)[0]
        if m is None or m < target:
            lo = mid
        else:
            hi = mid
    s_ = round((lo + hi) / 2, 1)
    return s_ if s_ >= 0.3 else 0.0


def blur_rgba(R, G, B, A, w, h, sigma):
    """Gaussian blur of a transparent layer, premultiplied as an editor does it, so edges don't darken; exact up to
    sigma 3 (worked on the element's box only), the three-box approximation beyond (within 6 % there)."""
    b = bbox([1 if v > 0 else 0 for v in A], w, h)
    if not b:
        return R, G, B, A
    pad = math.ceil(3 * sigma) + 2
    x0, y0, x1, y1 = max(0, b[0] - pad), max(0, b[1] - pad), min(w - 1, b[2] + pad), min(h - 1, b[3] + pad)
    cw, ch_ = x1 - x0 + 1, y1 - y0 + 1
    f = gauss_exact if sigma < 3 else gauss
    cut = lambda c: [v for y in range(y0, y1 + 1) for v in c[y * w + x0:y * w + x1 + 1]]
    Ac = cut(A)
    pa = f(Ac, cw, ch_, sigma)
    out = [list(R), list(G), list(B), list(A)]
    for k_, c in enumerate((R, G, B)):
        pc_ = f([v * a for v, a in zip(cut(c), Ac)], cw, ch_, sigma)
        for y in range(ch_):
            for x in range(cw):
                j, i = y * cw + x, (y0 + y) * w + x0 + x
                out[k_][i] = pc_[j] / pa[j] if pa[j] > 1e-4 else 0.0
    for y in range(ch_):
        out[3][(y0 + y) * w + x0:(y0 + y) * w + x1 + 1] = pa[y * cw:(y + 1) * cw]
    return out[0], out[1], out[2], out[3]


# ---------------------------------------------------------------- the curve

def tone_curve(eb, ew, tb, tw, gamma, gain, x):
    """One channel: black point eb -> tb, white point ew -> tw (a Levels stretch), then gamma on what lies between,
    then the light's gain in linear light, on everything (flare is light too, and a camera's white balance scales it
    with the rest: on the white-balance test set this beat keeping the black put, 7.0 against 7.2 mean dE). In that
    order: black, white, gamma, colour."""
    v = tb + (x - eb) * (tw - tb) / max(1e-6, ew - eb)
    v = min(255.0, max(0.0, v))
    if gamma != 1:
        lo, hi = min(tb, tw), max(tb, tw)
        if lo < v < hi:
            v = lo + (hi - lo) * ((v - lo) / (hi - lo)) ** (1 / gamma)
    return min(255.0, max(0.0, from_linear(gain * to_linear(v))))


def curve_points(f):
    """Enough points that PhotoCraft's spline follows f (Curves takes 2..19); the preview uses these points' spline,
    so it stays exact whatever the small difference to f."""
    xs = [0, 6, 14, 24, 36, 52, 72, 96, 124, 152, 180, 206, 228, 244, 255]
    pts, _ = clean_points([[x, f(x)] for x in xs], gap=4)
    return pts


# ---------------------------------------------------------------- contact shadow

def contact_shadow(A, w, h, strength, blur=0.0):
    """A tight dark line along the base where the element touches the ground, plus a soft spread under it: the base
    is the lower convex hull of the silhouette's bottom contour (product_shot.lower_hull: an object on a plane touches
    it at hull points, side and 3/4 views alike; it bridges the gap between a table's legs), steep hull segments are
    its sides, not ground. blur: the element's own, so the shadow is as soft as what casts it. Darkness 0..1 per pixel."""
    inside = [1 if v >= 0.5 else 0 for v in A]
    b = bbox(inside, w, h)
    if not b:
        return [0.0] * (w * h)
    bw, bh = b[2] - b[0] + 1, b[3] - b[1] + 1
    bottom = {}
    for x in range(b[0], b[2] + 1):
        yb = next((y for y in range(b[3], b[1] - 1, -1) if inside[y * w + x]), None)
        if yb is not None:
            bottom[x] = yb
    hull = lower_hull(bottom)
    core_src, soft_src = [0.0] * (w * h), [0.0] * (w * h)
    tc, ts = max(2, int(0.004 * bw)), max(4, int(0.03 * bw))
    seg = 0
    for x in sorted(bottom):
        while seg < len(hull) - 2 and x > hull[seg + 1][0]:
            seg += 1
        (xa, ya), (xb, yb2) = hull[seg], hull[min(seg + 1, len(hull) - 1)]
        slope = abs(yb2 - ya) / max(1, xb - xa)
        yh = ya + (yb2 - ya) * (x - xa) / max(1, xb - xa)
        yb = bottom[x]
        g = (1.0 if slope <= 0.6 else 0.0) * min(1.0, max(0.0, 1 - (yh - yb) / (0.08 * bh)))
        for k in range(-2, ts + 1):
            yy = yb + k
            if g > 0 and 0 <= yy < h:
                j = yy * w + x
                soft_src[j] = max(soft_src[j], g * (1 - max(0, k) / ts))
                if k <= tc:
                    core_src[j] = max(core_src[j], g)
    core = gauss(core_src, w, h, math.hypot(max(1.0, 0.003 * bw), blur))
    soft = gauss(soft_src, w, h, math.hypot(max(3.0, 0.02 * bw), blur))
    mc, ms = max(core) or 1, max(soft) or 1
    return [min(0.9, strength * (core[j] / mc + 0.4 * soft[j] / ms)) for j in range(w * h)]


def occlusion_shadow(A, w, h, blur=0.0, squash=0.25):
    """Soft light darkens the ground under everything near it, also where an object overhangs it (a console's front
    between its feet, a sofa's underside), which a contact line at the feet leaves lit. The silhouette squashed to a
    quarter of its height about the base line (the lower hull, as the contact shadow's), blurred by 1.2 % of the
    width (and by the element's own blur): coverage 0..1 per pixel. A retoucher's hand-built "occlusion shadow"."""
    inside = [1 if v >= 0.5 else 0 for v in A]
    b = bbox(inside, w, h)
    if not b:
        return [0.0] * (w * h)
    bottom = {}
    for x in range(b[0], b[2] + 1):
        yb = next((y for y in range(b[3], b[1] - 1, -1) if inside[y * w + x]), None)
        if yb is not None:
            bottom[x] = yb
    hull = lower_hull(bottom)
    src = [0.0] * (w * h)
    seg = 0
    for x in sorted(bottom):
        while seg < len(hull) - 2 and x > hull[seg + 1][0]:
            seg += 1
        (xa, ya), (xb, yb2) = hull[seg], hull[min(seg + 1, len(hull) - 1)]
        base = ya + (yb2 - ya) * (x - xa) / max(1, xb - xa)
        for y in range(b[1], b[3] + 1):
            al = A[y * w + x]
            if al > 0.02:
                yy = int(round(base - (base - y) * squash))
                if 0 <= yy < h:
                    src[yy * w + x] = max(src[yy * w + x], al)
    s_ = math.hypot(max(1.5, 0.012 * (b[2] - b[0] + 1)), blur)
    return (gauss_exact if s_ < 3 else gauss)(src, w, h, s_)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plate"); ap.add_argument("cut"); ap.add_argument("outdir")
    ap.add_argument("--at", help="X,Y in the plate where the element's anchor goes")
    ap.add_argument("--same-frame", action="store_true", help="the cut is plate-sized and already in place (cut from "
                                                              "another frame of the same tripod shot): keep its position")
    ap.add_argument("--anchor", choices=["bottom", "center"], default="bottom",
                    help="bottom: the bottom centre of the element (where it stands); center: its centre")
    sz = ap.add_mutually_exclusive_group()
    sz.add_argument("--height", type=float, help="element height in plate px (its visible part, alpha bbox)")
    sz.add_argument("--width", type=float, help="element width in plate px")
    sz.add_argument("--scale", type=float, help="scale factor for the cut's pixels")
    ap.add_argument("--ref-area", metavar="AREA", help="measure the plate only here (area.json or x0,y0,x1,y1): leave "
                                                        "out a lamp, a window or a coloured wall that isn't the scene's light")
    ap.add_argument("--tones", choices=["match", "contain", "none"], default="match",
                    help="black/white points: match both ways, contain = only lift blacks deeper than the plate's "
                         "and lower whites brighter than its, none")
    ap.add_argument("--harmonize", type=float, default=1.0, help="share of the colour difference taken over")
    ap.add_argument("--plate-neutral", metavar="X,Y[,R]", help="something neutral in the plate (grey, white): its colour "
                                                              "is the light's")
    ap.add_argument("--element-neutral", metavar="X,Y[,R]", help="something neutral on the element, in the CUT's pixels")
    ap.add_argument("--ev", type=float, default=0.0, help="exposure change of the element in stops (your call)")
    ap.add_argument("--gamma", type=float, default=1.0, help="midtone gamma of the element (>1 lighter; your call)")
    ap.add_argument("--grain", default="auto", help="'auto' (match the plate), or the sigma to add, 0 for none")
    ap.add_argument("--blur", default="0", help="Gaussian sigma baked into the element: 0, 'auto' (the suggestion), or px")
    ap.add_argument("--wrap", type=float, default=0.35, help="light wrap opacity (0 = none)")
    ap.add_argument("--wrap-width", type=float, help="px the wrap reaches into the element (default 1.5 %% of its size)")
    ap.add_argument("--wrap-blur", type=float, help="blur of the plate for the wrap (default 4 %% of the element's size)")
    ap.add_argument("--wrap-blend", choices=["screen", "softlight"], default="screen")
    ap.add_argument("--shadow", choices=["contact", "none"], default="none")
    ap.add_argument("--shadow-strength", type=float, default=0.6)
    ap.add_argument("--occlusion", type=float, default=0.0, help="opacity of a soft occlusion shadow under the element "
                    "(0.4-0.5 in soft light, for overhangs and gaps under it; 0 = none)")
    ap.add_argument("--name", help="what the element is, for the layer names: the group 'Composite: NAME' (default: the "
                                   "cut's file name)")
    ap.add_argument("--element-name", help="the element layer's name (default: NAME, else the cut's file name)")
    ap.add_argument("--old-backdrop", choices=["auto", "light", "dark"], default="auto",
                    help="what the element was cut from, for the edge-rim check (auto: read off its edge, else light)")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    out = lambda n: os.path.join(a.outdir, n)
    warnings = []

    # ---- the plate: an analysis copy for its black and white points and light, full resolution in the frame later
    plate = Image(a.plate, 1200)
    W, H = plate.W, plate.H
    p_prof, builtins = profile(plate.path)

    # ---- the element: trim to its alpha, scale with the CLI (premultiplied resampling: clean edges)
    cut = os.path.abspath(os.path.expanduser(a.cut))
    cw, ch = png_size(cut)
    small = os.path.join(TMP, "small.png")
    k0 = min(1.0, 480 / max(cw, ch))
    cli_run(cut, [("image.imageSize", {"width": max(1, round(cw * k0))})] if k0 < 1 else [], small)
    sw_, sh_, _, _, _, SA = imgops.load_rgba(small)
    sb = bbox([1 if v > 0.02 else 0 for v in SA], sw_, sh_)
    if not sb:
        sys.exit("error: the cut is empty (no pixel with alpha); export only the masked element layer as a PNG")
    if a.same_frame and (cw, ch) != (W, H):
        sys.exit(f"error: --same-frame needs a cut the plate's size ({W}x{H}); this one is {cw}x{ch}")
    if not a.same_frame and not a.at:
        sys.exit("error: --at X,Y says where the element goes (or --same-frame for a cut already in place)")
    pad = math.ceil(2 / k0)
    bx0, by0 = max(0, int(sb[0] / k0) - pad), max(0, int(sb[1] / k0) - pad)
    bx1, by1 = min(cw, math.ceil((sb[2] + 1) / k0) + pad), min(ch, math.ceil((sb[3] + 1) / k0) + pad)
    cut_edges = [side for side, hit in (("left", bx0 == 0), ("top", by0 == 0), ("right", bx1 == cw), ("bottom", by1 == ch))
                 if hit and _alpha_on_border(SA, sw_, sh_, side)]
    bw, bh = bx1 - bx0, by1 - by0
    s5 = bbox([1 if v >= 0.5 else 0 for v in SA], sw_, sh_) or sb  # the visible element, for --height / --width
    s = (1.0 if a.same_frame else a.height * k0 / (s5[3] - s5[1] + 1) if a.height else
         a.width * k0 / (s5[2] - s5[0] + 1) if a.width else a.scale or 1.0)
    tw, th = max(1, round(bw * s)), max(1, round(bh * s))
    steps = [("image.crop", {"x": bx0, "y": by0, "width": bw, "height": bh})]
    c_prof, _ = profile(cut)
    converted = None
    if c_prof and p_prof and family(c_prof) != family(p_prof):
        target = (builtins.get(p_prof) or next((bid for d, bid in builtins.items() if family(d) == family(p_prof)), None)
                  or next((bid for fam, bid in FAMILIES if fam in p_prof and bid in builtins.values()), None))
        if target:
            steps.append(("edit.convertToProfile", {"profile": target}))
            converted = f"{c_prof} -> {target}"
        else:
            warnings.append(f"the cut is in {c_prof!r} and the plate in {p_prof!r}, which has no builtin twin: colours not converted")
    if (tw, th) != (bw, bh):
        steps.append(("image.imageSize", {"width": tw, "height": th, "resample": "bicubic"}))
    scaled = os.path.join(TMP, "scaled.png")
    cli_run(cut, steps, scaled)
    _, _, ER0, EG0, EB0, EA0 = imgops.load_rgba(scaled)
    if s > 1.05:
        warnings.append(f"the element is enlarged {s:.2f}x: it will look softer than the plate; use a bigger cut or place it smaller")

    # ---- placement (the anchor is on the visible element: its alpha >= 0.5) and the working frame, the element
    #      plus a margin of plate around it
    if a.same_frame:
        ex0, ey0 = bx0, by0
    else:
        eb5 = bbox([1 if v >= 0.5 else 0 for v in EA0], tw, th) or [0, 0, tw - 1, th - 1]
        ax, ay = (float(v) for v in a.at.split(","))
        ex0 = round(ax - (eb5[0] + eb5[2] + 1) / 2)
        ey0 = round(ay - (eb5[3] + 1 if a.anchor == "bottom" else (eb5[1] + eb5[3] + 1) / 2))
    m = max(32, round(0.12 * max(tw, th)))
    fx0, fy0 = max(0, ex0 - m), max(0, ey0 - m)
    fx1, fy1 = min(W, ex0 + tw + m), min(H, ey0 + th + m)
    fw, fh = (fx1 - fx0) // 2 * 2, (fy1 - fy0) // 2 * 2
    if fw < 8 or fh < 8:
        sys.exit("error: the element lands outside the plate; check --at")
    fx1, fy1 = fx0 + fw, fy0 + fh
    N = fw * fh
    _, _, PR, PG, PB = plate.crop(fx0, fy0, fw, fh)
    ER, EG, EB, EA = [0.0] * N, [0.0] * N, [0.0] * N, [0.0] * N
    lost = total = 0.0
    for y in range(th):
        Y = ey0 + y - fy0
        for x in range(tw):
            j = y * tw + x
            al = EA0[j]
            total += al
            X = ex0 + x - fx0
            if 0 <= X < fw and 0 <= Y < fh:
                i = Y * fw + X
                ER[i], EG[i], EB[i], EA[i] = ER0[j], EG0[j], EB0[j], al
            else:
                lost += al
    if lost > 0.02 * total:
        warnings.append(f"{100 * lost / total:.0f} % of the element falls outside the plate")
    for side in cut_edges:
        edge = {"bottom": ey0 + th >= H, "top": ey0 <= 0, "left": ex0 <= 0, "right": ex0 + tw >= W}[side]
        if not edge:
            warnings.append(f"the cut is cut off at its {side} but that side lands inside the plate: it will show as a "
                            f"straight edge; place it so that side leaves the frame (or hide it behind something)")

    # ---- what the plate tells: black and white points and light (whole plate, or --ref-area), grain and sharpness
    #      (the plate right round the element, at its distance from the camera)
    # what the element will cover: its alpha, not its box (a table's box hides the plate between its legs), grown by 2
    # cells of the analysis copy
    pw, ph_ = plate.w, plate.h
    foot = [0.0] * (pw * ph_)
    for y in range(th):
        Y = int((ey0 + y) / plate.s)
        if 0 <= Y < ph_:
            row = y * tw
            for x in range(tw):
                if EA0[row + x] > 0.02:
                    X = int((ex0 + x) / plate.s)
                    if 0 <= X < pw:
                        foot[Y * pw + X] = 1.0
    foot = imgops.maxf(foot, pw, ph_, 2)
    if a.ref_area:
        from color_check import area_mask
        ref = area_mask(a.ref_area, pw, ph_, plate.s)
        pidx = [i for i in range(pw * ph_) if ref[i]]
    else:
        pidx = [i for i in range(pw * ph_) if not foot[i]]
    if len(pidx) < 500:
        sys.exit("error: too little plate to measure (the element covers it, or --ref-area is tiny)")
    pblack, pwhite = ends(plate.R, plate.G, plate.B, pidx, 0.005)
    opaque = [i for i in range(N) if EA[i] >= 0.98]
    if len(opaque) < 200:
        strongest = max(EA0) if EA0 else 0.0
        if total <= 0 or lost > 0.5 * total:
            why = (f"{100 * lost / max(total, 1e-9):.0f} % of the element lands outside the plate ({W}x{H}): check --at "
                   "and the size")
        elif strongest < 0.98:
            why = (f"the cut has no fully opaque pixel (its strongest alpha is {strongest:.2f}): export the masked layer "
                   "at full opacity")
        else:
            why = f"only {len(opaque)} fully opaque pixels at this size: the element is almost all edge; place it bigger"
        sys.exit("error: " + why + "".join(f"\n  also: {w_}" for w_ in warnings))
    eblack, ewhite = ends(ER, EG, EB, opaque, 0.005)

    # ---- black point, white point: only where both ends really are a black (or a white); a white product has no
    #      black to match, and a plate without deep shadows has no black level to match it to
    Lb_e, Lb_p, Lw_e, Lw_p = lum(*eblack), lum(*pblack), lum(*ewhite), lum(*pwhite)
    tb, tw_ = list(eblack), list(ewhite)
    tones = {"elementBlack": [round(v, 1) for v in eblack], "plateBlack": [round(v, 1) for v in pblack],
             "elementWhite": [round(v, 1) for v in ewhite], "plateWhite": [round(v, 1) for v in pwhite]}
    if a.tones != "none":
        if Lb_e > 60:
            tones["black"] = "the element has no black (its darkest is light): left"
        elif Lb_p > 45:
            tones["black"] = "the plate has no deep shadows to measure a black level on: left; judge by eye"
            warnings.append(f"the plate's darkest tone is {Lb_p:.0f} (no deep shadows, or haze): blacks not matched; "
                            "judge the element's shadows by eye")
        elif a.tones == "match" or Lb_e < Lb_p:
            # each channel moves by the plate's black (that channel) less the element's black level: a neutral
            # black lands on the plate's black and takes its tint (muddy brown, deep navy), a navy one stays navy
            tb = [max(0.0, e + p_ - Lb_e) for e, p_ in zip(eblack, pblack)]
            tones["black"] = f"moved {Lb_p - Lb_e:+.1f} levels, to the plate's black"
            if Lb_p < 1.5 and Lb_e > 3:
                tones["black"] += " (the plate's blacks are clipped: the element's deepest shadows clip with them)"
            if Lb_p - Lb_e > 25:
                warnings.append(f"the element's blacks lift {Lb_p - Lb_e:.0f} levels to the plate's black point: right "
                                "for a hazy plate, wrong if the plate simply has no dark things; check its shadows")
        else:
            tones["black"] = "left: not deeper than the plate's (--tones contain)"
        if Lw_e < 220:
            tones["white"] = "the element has no white (its brightest is darker): left"
        elif Lw_p < 230:
            tones["white"] = "the plate has no whites to measure a white level on: left"
        elif a.tones == "match" or Lw_e > Lw_p:
            tw_ = [min(255.0, e + Lw_p - Lw_e) for e in ewhite]  # the level only: the light's colour comes next
            tones["white"] = f"moved {Lw_p - Lw_e:+.1f} levels, to the plate's white"
        else:
            tones["white"] = "left: not brighter than the plate's (--tones contain)"

    # ---- colour: the element's neutral to the plate's (linear light, luminance kept), then exposure. A neutral
    #      picked by hand (--plate-neutral, --element-neutral) beats the estimate: grey card, white shirt, concrete
    if a.plate_neutral:
        rgb, clipped, _ = sample(plate, point(a.plate_neutral))
        if clipped > 0.02:
            warnings.append(f"--plate-neutral: {100 * clipped:.0f} % of the patch is clipped")
        pc_ = imgops.lab(*rgb)[1:]
        pshare = 1.0
    else:
        pc_, pshare = neutral_cast(plate.R, plate.G, plate.B, pw, ph_, pidx, step=2)
    if a.element_neutral:
        nx, ny, nr = point(a.element_neutral)  # cut pixels -> frame pixels: trimmed at (bx0, by0), scaled by s
        cx_, cy_, r_ = (nx - bx0) * s + ex0 - fx0, (ny - by0) * s + ey0 - fy0, max(1.5, nr * s)
        pts = [i for i in opaque if (i % fw - cx_) ** 2 + (i // fw - cy_) ** 2 <= r_ * r_]
        if len(pts) < 5:
            sys.exit("error: --element-neutral is not on the opaque element (cut pixels X,Y[,R])")
        ec_ = imgops.lab(*(sum(c[i] for i in pts) / len(pts) for c in (ER, EG, EB)))[1:]
        eshare = 1.0
    else:
        ec_, eshare = neutral_cast(ER, EG, EB, fw, fh, opaque, step=3)
    light = {"plateNeutral": [round(v, 1) for v in pc_] if pc_ else None, "plateShare": round(pshare, 3),
             "elementNeutral": [round(v, 1) for v in ec_] if ec_ else None, "elementShare": round(eshare, 3)}
    gains = [1.0, 1.0, 1.0]
    if not pc_:
        light["note"] = "no smooth near-neutral surfaces in the plate: colour not matched"
        warnings.append("the plate has no smooth near-neutral surfaces to read its light from: colour not matched; "
                        "judge it by eye, or give --plate-neutral and --element-neutral")
    elif not ec_:
        light["note"] = "no smooth near-neutral surfaces on the element: colour not matched"
        warnings.append("the element has no smooth near-neutral surface (white, grey) to read its light from: colour "
                        "not matched; give --element-neutral on something white or grey in the cut, or judge by eye")
    else:
        gains = cast_gains(pc_, ec_, a.harmonize)
        if eshare < 0.02 or pshare < 0.02:
            warnings.append("the neutral estimate rests on few pixels: check that the element's whites and greys sit "
                            "like the plate's, or give --plate-neutral and --element-neutral")
    gains = [v * 2 ** a.ev for v in gains]
    light["gains"] = [round(v, 4) for v in gains]

    # ---- the plate round the element (the frame: within 12 % of its size, about its distance from the camera)
    #      against the element's inside: edge rim, sharpness before any blur
    PL = [lum(r, g_, b) for r, g_, b in zip(PR, PG, PB)]
    near = edge_distance([1 if v >= 0.5 else 0 for v in EA], fw, fh, cap=40)
    ring = [1 if EA[i] < 0.02 and near[i] >= 6 else 0 for i in range(N)]
    # an old backdrop left in the cut's edge pixels pulls them toward its colour: lighter than both the element just
    # inside and the plate just outside on a light sweep, darker on a dark one; on a plate unlike that backdrop it reads
    # as a halo. Only rims of the backdrop's polarity count: a console's shadowed underside or black vents cut from a
    # white sweep are darker than both sides too, and are the object. The polarity is --old-backdrop, or read off the
    # partly transparent edge pixels (C = a F + (1 - a) B with F the element just inside: the median lean of B - F);
    # light when that says nothing (most sweeps are)
    EL0 = [lum(r, g_, b) for r, g_, b in zip(ER, EG, EB)]
    inner = [1.0 if EA[i] >= 0.98 and 4 <= near[i] <= 7 else 0.0 for i in range(N)]
    outer = [1.0 if EA[i] <= 0.02 and 3 <= near[i] <= 6 else 0.0 for i in range(N)]
    Sin, SinL = sat(inner, fw, fh), sat([EL0[i] * inner[i] for i in range(N)], fw, fh)
    Sout, SoutL = sat(outer, fw, fh), sat([PL[i] * outer[i] for i in range(N)], fw, fh)
    leans = []
    for i in range(N):
        al = EA[i]
        if 0.1 < al < 0.9:
            x, y = i % fw, i // fw
            ni = win(Sin, fw, fh, x, y, 6)
            if ni >= 4:
                leans.append((EL0[i] - win(SinL, fw, fh, x, y, 6) / ni) / (1 - al))
    lean = sorted(leans)[len(leans) // 2] if len(leans) >= 50 else None
    if a.old_backdrop != "auto":
        polarity, read = a.old_backdrop, "given"
    elif lean is not None and lean < -15:
        polarity, read = "dark", f"read off the edge (lean {lean:+.0f})"
    else:
        polarity = "light"
        read = f"read off the edge (lean {lean:+.0f})" if lean is not None and lean > 15 else \
               "assumed: the edge says nothing either way (clean, or no partly transparent pixels)"
    light_rim = dark_rim = counted = 0
    flag = {}
    for i in range(N):
        if EA[i] >= 0.15 and (EA[i] < 0.98 or near[i] <= 2):
            x, y = i % fw, i // fw
            ni, no = win(Sin, fw, fh, x, y, 6), win(Sout, fw, fh, x, y, 6)
            if ni >= 4 and no >= 4:
                ri, ro = win(SinL, fw, fh, x, y, 6) / ni, win(SoutL, fw, fh, x, y, 6) / no
                counted += 1
                if polarity == "light" and EL0[i] > max(ri, ro) + 15:
                    light_rim += 1
                    flag[i] = 1
                elif polarity == "dark" and EL0[i] < min(ri, ro) - 15:
                    dark_rim += 1
                    flag[i] = 2
    edge = {"pixels": counted, "lightRim": round(light_rim / max(1, counted), 3),
            "darkRim": round(dark_rim / max(1, counted), 3), "oldBackdrop": polarity, "read": read}
    if edge["lightRim"] > 0.08:
        warnings.append(f"a light rim on {100 * edge['lightRim']:.0f} % of the element's edge pixels: the old backdrop is "
                        "still in them and will show as a halo; decontaminate the cut (cutout.md) before compositing "
                        "(edge_rim.png shows them)")
    if edge["darkRim"] > 0.08:
        warnings.append(f"a dark rim on {100 * edge['darkRim']:.0f} % of the element's edge pixels, from its dark old "
                        "backdrop: decontaminate the cut (cutout.md) before compositing (edge_rim.png shows them)")
    core = [1 if EA[i] >= 0.98 and near[i] >= 4 else 0 for i in range(N)]
    EL = [lum(r, g_, b) for r, g_, b in zip(ER, EG, EB)]
    (wp, np_), (we, ne) = edge_sigma(PL, fw, fh, ring), edge_sigma(EL, fw, fh, core)
    suggest = 0.0
    # only a clear difference: the plate's edges and the element's are different things (a backdrop and a table
    # against eyes and hair in the same frame measured 0.70 and 0.55), so under 1.3x there is nothing to fix
    if wp and we and wp >= 1.3 * we:
        suggest = blur_to_match(EL, EA, core, fw, fh, wp, we)
    sharp = {"plateEdgeSigma": round(wp, 2) if wp else None, "plateEdges": np_,
             "elementEdgeSigma": round(we, 2) if we else None, "elementEdges": ne, "suggestedBlur": suggest}
    if not wp:
        sharp["note"] = "too few contrasty edges in the plate round the element to compare sharpness: judge by eye"
    raw = (ER, EG, EB, EA)  # the element as cut, for the "pasted as is" pictures
    blur = suggest if a.blur == "auto" else float(a.blur)
    changed = 0.0
    if blur > 0:
        ER, EG, EB, EA = blur_rgba(ER, EG, EB, EA, fw, fh, blur)
        idx = [i for i in range(N) if core[i]][::3]
        changed = sum(abs(lum(ER[i], EG[i], EB[i]) - EL[i]) for i in idx) / max(1, len(idx))
        sharp.update({"applied": blur, "meanChange": round(changed, 2)})
    if suggest > 0 and (blur <= 0 or changed < 0.05 or blur < 0.75 * suggest):
        warnings.append(f"the element is crisper than the plate round it: --blur {suggest:g} (or Gaussian Blur radius "
                        f"{suggest:g} on it as a smart filter) unless it is meant to stand in the focal plane")
    EA = [round(v * 255) / 255 for v in EA]  # the PNG holds 8-bit alpha; predict with what the app gets
    ER, EG, EB = ([float(max(0, min(255, int(v + 0.5)))) for v in c] for c in (ER, EG, EB))

    # ---- the Match plate curve, per channel
    luts, curves = {}, {}
    for k, name in enumerate(("red", "green", "blue")):
        f = (lambda x, k=k: tone_curve(eblack[k], ewhite[k], tb[k], tw_[k], a.gamma, gains[k], x))
        pts = curve_points(f)
        curves[name] = pts
        luts[name] = spline_lut(pts)
    identity = all(abs(luts[c][v] - v) <= 1 for c in luts for v in range(256))

    # ---- grain, measured after the curve (its slope scales the element's noise too)
    CR, CG, CB = ([float(luts[c][int(v)]) for v in ch] for c, ch in (("red", ER), ("green", EG), ("blue", EB)))
    CL = [lum(r, g_, b) for r, g_, b in zip(CR, CG, CB)]
    core = [1 if EA[i] >= 0.98 and near[i] >= 4 else 0 for i in range(N)]
    gp, ge = grain_floor(PL, fw, fh, ring), grain_floor(CL, fw, fh, core)
    if a.grain == "auto":
        add = math.sqrt(max(0.0, gp * gp - ge * ge)) / 0.943 if gp is not None and ge is not None else 0.0
        add = add if add >= 0.6 else 0.0
    else:
        add = float(a.grain)
    grain = {"plate": round(gp, 2) if gp is not None else None, "element": round(ge, 2) if ge is not None else None,
             "added": round(add, 2)}
    if gp is None or ge is None:
        grain["note"] = "too few smooth areas to read the grain on: none added; compare at 100 % by eye"
    elif ge > 1.3 * gp and ge > 1.5:
        warnings.append(f"the element measures noisier than the plate ({ge:.1f} against {gp:.1f}): if that is noise and "
                        "not skin or fabric texture (compare at 100 %), reduce it before compositing; grain can be added, "
                        "not taken away")
    GR = None
    if add > 0:
        nz = imgops.noise(N, add, seed=7)
        GR = [float(max(0, min(255, math.floor(128 + v / 2)))) for v in nz]  # floor(127.5 + n/2 + 0.5): mean 0

    # ---- light wrap: the plate blurred until no detail is left, in a band just inside the element's edge,
    #      stronger where the plate behind is bright
    size = max(tw, th)
    ww = a.wrap_width or max(2.0, 0.015 * size)
    wb = a.wrap_blur or max(6.0, 0.04 * size)
    WR = WM = None
    if a.wrap > 0:
        WR = [gauss(c, fw, fh, wb) for c in (PR, PG, PB)]
        WL = [lum(r, g_, b) for r, g_, b in zip(*WR)]
        refl = sorted(WL[i] for i in range(N) if ring[i]) or sorted(WL)
        lo, hi = refl[len(refl) // 4], refl[int(0.95 * (len(refl) - 1))]
        inside_d = edge_distance([1 if v >= 0.5 else 0 for v in EA], fw, fh, cap=int(ww) + 2)
        WM = []
        for i in range(N):
            if EA[i] <= 0:
                WM.append(0.0)
                continue
            d = inside_d[i] if EA[i] >= 0.5 else 0
            band = max(0.0, 1 - d / ww) ** 2 if d <= ww else 0.0
            bright = min(1.0, max(0.15, (WL[i] - lo) / max(8.0, hi - lo)))
            WM.append(round(band * bright * 255) / 255)
        WR = [[float(max(0, min(255, int(v + 0.5)))) for v in c] for c in WR]

    # ---- contact and occlusion shadows, from the element as cut (a 4 px pole blurred by 4 has no pixel at alpha 0.5
    #      left), tinted with the ground right under the base: its median (a dark object nearby doesn't swing it) taken
    #      down to a dark tone; Multiply by it darkens the ground and deepens its own hue, as shadows on a surface do
    SH = OC = None
    shadow = occlusion = None
    if a.shadow == "contact" or a.occlusion > 0:
        eb2 = bbox([1 if v >= 0.5 else 0 for v in raw[3]], fw, fh) or bbox([1 if v > 0.02 else 0 for v in raw[3]], fw, fh)
        gx0, gx1 = eb2[0], eb2[2]
        gy0, gy1 = eb2[3] - int(0.05 * (eb2[3] - eb2[1])), eb2[3] + max(6, int(0.15 * (eb2[3] - eb2[1])))
        ridx = [i for i in range(N) if ring[i] and gx0 <= i % fw <= gx1 and gy0 <= i // fw <= gy1]
        if len(ridx) < 100:
            ridx = [i for i in range(N) if ring[i]]
        med = [sorted(c[i] for i in ridx)[len(ridx) // 2] for c in (PR, PG, PB)]
        k_ = min(1.0, 40.0 / max(1.0, lum(*med)))
        dark = [v * k_ for v in med]
        if "bottom" in cut_edges:
            warnings.append("the cut is cut off at its bottom: it doesn't stand on anything in this frame, no contact or "
                            "occlusion shadow")
        else:
            if a.shadow == "contact":
                d = contact_shadow(raw[3], fw, fh, a.shadow_strength, blur)
                SH = [[float(max(0, min(255, int(255 - v * (255 - t) + 0.5)))) for v in d] for t in dark]
                shadow = {"tint": [round(v) for v in dark], "strength": a.shadow_strength, "max": round(max(d), 3)}
            if a.occlusion > 0:
                d = occlusion_shadow(raw[3], fw, fh, blur)
                OC = [[float(max(0, min(255, int(255 - v * (255 - t) + 0.5)))) for v in d] for t in dark]
                occlusion = {"tint": [round(v) for v in dark], "opacity": a.occlusion}

    # ---- the predicted frame, as PhotoCraft composites it: shadow over the plate; then the clipping group (curve,
    #      grain, wrap act on the element's own colour), over the plate by the element's alpha; 8-bit between layers
    rnd = lambda v: float(max(0, min(255, int(v + 0.5))))
    mode = "screen" if a.wrap_blend == "screen" else "softlight"
    PV = [[0.0] * N for _ in range(3)]
    NV = [[0.0] * N for _ in range(3)]
    for i in range(N):
        p = (PR[i], PG[i], PB[i])
        if OC:
            p = tuple(rnd(v) for v in blend("multiply", p, (OC[0][i], OC[1][i], OC[2][i]), a.occlusion))
        if SH:
            p = tuple(rnd(v) for v in blend("multiply", p, (SH[0][i], SH[1][i], SH[2][i])))
        al, ra = EA[i], raw[3][i]
        q = p
        naive = tuple(rnd(pv + ra * (ev - pv)) for pv, ev in zip(p, (raw[0][i], raw[1][i], raw[2][i]))) if ra > 0 else p
        if al > 0:
            e = (ER[i], EG[i], EB[i])
            e = (luts["red"][int(e[0])], luts["green"][int(e[1])], luts["blue"][int(e[2])]) if not identity else e
            if GR:
                e = tuple(rnd(v) for v in blend("linearlight", e, (GR[i],) * 3))
            if WM and WM[i] > 0:
                e = tuple(rnd(v) for v in blend(mode, e, (WR[0][i], WR[1][i], WR[2][i]), a.wrap * WM[i]))
            q = tuple(rnd(pv + al * (ev - pv)) for pv, ev in zip(p, e))
        for c in range(3):
            PV[c][i], NV[c][i] = q[c], naive[c]
    imgops.save_rgb(out("preview.png"), fw, fh, *PV)

    # ---- the layers. PhotoCraft centres a placed layer on its visible content, not on the PNG's canvas, so two
    #      invisible corner pixels (alpha 1/255, the plate's own colour: nothing changes there) make the element's
    #      bounds the frame's, and it lands where the preview has it
    XR, XG, XB, XA = ER[:], EG[:], EB[:], EA[:]
    for i in (0, N - 1):
        if XA[i] == 0:
            XR[i], XG[i], XB[i], XA[i] = PR[i], PG[i], PB[i], 1 / 255
    imgops.save_rgb(out("element.png"), fw, fh, XR, XG, XB, XA)
    imgops.save_gray(out("element_mask.png"), fw, fh, EA)
    layers = []
    if OC:
        imgops.save_rgb(out("occlusion.png"), fw, fh, *OC)
        layers.append({"name": "Occlusion shadow", "image": "occlusion.png", "blend": "Multiply", "opacity": a.occlusion})
    if SH:
        imgops.save_rgb(out("shadow.png"), fw, fh, *SH)
        layers.append({"name": "Contact shadow", "image": "shadow.png", "blend": "Multiply"})
    name = os.path.splitext(os.path.basename(cut))[0]
    layers.append({"name": a.element_name or a.name or name, "image": "element.png"})
    if not identity:
        layers.append({"name": "Match plate", "adjustment": "curves", "params": curves, "clip": True})
    if GR:
        imgops.save_rgb(out("grain.png"), fw, fh, GR, GR, GR)
        layers.append({"name": "Grain", "image": "grain.png", "blend": "Linear Light", "clip": True})
    if WM:
        imgops.save_rgb(out("wrap.png"), fw, fh, *WR)
        imgops.save_gray(out("wrap_mask.png"), fw, fh, WM)
        layers.append({"name": "Light wrap", "image": "wrap.png", "mask": "wrap_mask.png",
                       "blend": "Screen" if mode == "screen" else "Soft Light", "opacity": a.wrap, "clip": True})
    spec = {"center": [fx0 + fw / 2, fy0 + fh / 2], "crop": [fx0, fy0, fw, fh], "preview": "preview.png",
            "group": f"Composite: {a.name or name}", "layers": layers}
    json.dump(spec, open(out("layers.json"), "w"), indent=1)

    # ---- pictures to judge it by: plate | pasted as is | composited, and 3x tiles along the edge
    k = max(1, math.ceil(3 * fw / 1500))
    vw, vh = fw // k, fh // k
    gap = 8
    panels = [[imgops.downscale(c, fw, fh, k)[0] for c in P] for P in ((PR, PG, PB), NV, PV)]
    rows = [[(255, 255, 255)] * (3 * vw + 2 * gap) for _ in range(vh)]
    for n_, P in enumerate(panels):
        for y in range(vh):
            for x in range(vw):
                j = y * vw + x
                rows[y][n_ * (vw + gap) + x] = tuple(int(P[c][j] + 0.5) for c in range(3))
    pngio.write(out("compare.png"), 3 * vw + 2 * gap, vh, rows)
    rb = bbox([1 if v > 0.02 else 0 for v in raw[3]], fw, fh)
    if rb:  # edge_rim.png: the element pasted as is, dimmed, light-rim pixels red, dark-rim pixels blue
        x0, y0, x1, y1 = max(0, rb[0] - 8), max(0, rb[1] - 8), min(fw - 1, rb[2] + 8), min(fh - 1, rb[3] + 8)
        z = 2 if x1 - x0 < 600 else 1
        rows = []
        for y in range(y0, y1 + 1):
            row = []
            for x in range(x0, x1 + 1):
                i = y * fw + x
                c = (255, 40, 40) if flag.get(i) == 1 else (40, 110, 255) if flag.get(i) == 2 else \
                    tuple(int(0.55 * NV[k][i]) for k in range(3))
                row.extend([c] * z)
            rows.extend([row] * z)
        pngio.write(out("edge_rim.png"), len(rows[0]), len(rows), rows)
    eb_ = bbox([1 if v >= 0.5 else 0 for v in EA], fw, fh)
    if eb_:
        T, z = 40, 3
        cx = (eb_[0] + eb_[2]) // 2
        cy = (eb_[1] + eb_[3]) // 2
        spots = [(cx, eb_[1]), (eb_[0], cy), (eb_[2], cy), (cx, eb_[3])]
        spots = [(next((x for x in range(fw) if EA[sy * fw + x] >= 0.5), sx) if sx == eb_[0] else
                  next((x for x in range(fw - 1, -1, -1) if EA[sy * fw + x] >= 0.5), sx) if sx == eb_[2] else sx,
                  next((y for y in range(fh) if EA[y * fw + sx] >= 0.5), sy) if sy == eb_[1] else
                  next((y for y in range(fh - 1, -1, -1) if EA[y * fw + sx] >= 0.5), sy) if sy == eb_[3] else sy)
                 for sx, sy in spots]
        ZW = 4 * (2 * T * z) + 7 * gap
        zrows = [[(255, 255, 255)] * ZW for _ in range(T * z)]
        for n_, (sx, sy) in enumerate(spots):
            for half, P in enumerate((NV, PV)):
                ox = n_ * (2 * T * z + 2 * gap) + half * (T * z + gap // 2)
                for y in range(T * z):
                    yy = sy - T // 2 + y // z
                    for x in range(T * z):
                        xx = sx - T // 2 + x // z
                        if 0 <= xx < fw and 0 <= yy < fh and ox + x < ZW:
                            j = yy * fw + xx
                            zrows[y][ox + x] = (int(P[0][j]), int(P[1][j]), int(P[2][j]))
        pngio.write(out("zoom.png"), ZW, T * z, zrows)

    stats = {"plate": os.path.basename(plate.path), "cut": os.path.basename(cut),
             "profile": {"plate": p_prof, "cut": c_prof, "converted": converted},
             "element": {"box": [ex0, ey0, tw, th], "scale": round(s, 4), "anchor": a.anchor, "cutOffAt": cut_edges},
             "frame": [fx0, fy0, fw, fh], "edge": edge, "tones": tones, "light": light, "gamma": a.gamma, "ev": a.ev,
             "curve": None if identity else curves, "grain": grain, "sharpness": sharp,
             "wrap": {"amount": a.wrap, "width": round(ww, 1), "blur": round(wb, 1), "blend": a.wrap_blend} if WM else None,
             "shadow": shadow, "occlusion": occlusion, "warnings": warnings,
             "byEye": "light direction and hardness, perspective and scale can't be measured here: shadows on the "
                      "element must fall like the plate's, and its size and horizon must fit the plate's camera",
             "next": ["look at compare.png and zoom.png", "import_layers.py <outdir>/layers.json   (plate document active)",
                      "check: export, crop the frame, qc.py seams frame.png <outdir>/element_mask.png <dir>"]}
    json.dump(stats, open(out("plan.json"), "w"), indent=1)
    print(json.dumps(stats))


def _alpha_on_border(A, w, h, side):
    """True when the element runs into that border of the cut (a half-length portrait cut at the bottom)."""
    if side in ("top", "bottom"):
        y = 0 if side == "top" else h - 1
        row = A[y * w:(y + 1) * w]
    else:
        x = 0 if side == "left" else w - 1
        row = A[x::w]
    return sum(1 for v in row if v >= 0.5) >= max(3, 0.02 * len(row))


if __name__ == "__main__":
    main()
