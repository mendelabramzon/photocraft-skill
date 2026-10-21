#!/usr/bin/env python3
"""Colour correction by the numbers: measure a photo's cast, clipping and skin; solve white balance and black/white
points as editable Curves layers; match another shot's colour; compare before and after.

Why numbers: eyes and screens adapt to a cast within seconds, so a photo that looks right after a minute of looking
can still be 8 levels blue. Surfaces that are neutral in life (a grey card, a white shirt in light, concrete, a
road, shaded cloud) should read R = G = B, Lab a* = b* = 0. Skin of every complexion lies near the skin-tone line of
a vectorscope. Highlights and shadows shouldn't clip unless that is the intent.

The corrections are Curves layers whose result is predicted exactly: PhotoCraft's Curves is a natural cubic spline per
channel (imgops.spline_lut) and an 8-bit document rounds between layers, so "White balance" (red/green/blue curves) and
"Black & white point" (composite curve) are separate layers and preview.png is what the document will show. The white
balance takes each neutral to grey at its own luminance and is piecewise power between them (a natural spline
through the same few points overshoots between them by up to 30 levels), written out as enough points to follow.

  color_check.py measure IMAGE [--neutral X,Y[,R] ...] [--skin AREA] [--viz viz.png] [--scope scope.png]
  color_check.py correct IMAGE OUTDIR --neutral X,Y[,R] ... [--black X,Y[,R]] [--amount 1] [--tone] [--area AREA]
  color_check.py match   IMAGE REFERENCE OUTDIR [--amount 1] [--area AREA --ref-area AREA] [--skin S --ref-skin S --anchor-skin]
  color_check.py clarity IMAGE OUTDIR [--skin AREA] [--method highpass|usm] [--radius PX] [--opacity 0.5]
  color_check.py chart   IMAGE OUTDIR --corners X,Y X,Y X,Y X,Y [--skin AREA] [--area AREA] [--fit lab|hue|none]
  color_check.py compare BEFORE AFTER [--neutral X,Y[,R] ...] [--skin AREA]

IMAGE: anything photocraft-cli reads: a `pc.py export` of the document as it is now, the original JPEG, a PSD.
Big images are measured on a copy the CLI scales to --max-side (1200 px); every coordinate is in the full image's
pixels, and neutral patches (radius R, default 8 px) are sampled from the full image. AREA: an area.json
({"skin": polygon(s), "exclude": [...]}, full-image coordinates) or a rectangle x0,y0,x1,y1.
correct, match, clarity and chart write OUTDIR/layers.json for import_layers.py, with a full-resolution crop's
predicted result (preview.png) so the import verifies itself, and before_after.png / match.png / chart.png to look at.
Curve points are whole levels and mixer weights whole percents: what a PSD keeps, so a saved file renders as predicted.
chart measures an X-Rite ColorChecker Classic (corner patch centres given) against X-Rite's values by CIEDE2000 and
fits a Channel Mixer for the colour a camera's rendering turned (curves can't move that), optionally masked to skin.
correct --tone takes its end points from --for screen (4/251) or print (8/244). A --white or --black reference with
one clipped channel is kept: that channel's curve end takes it to grey, as the Curves eyedroppers do.
measure, correct, match and compare report skin by vectorscope angle and by Lab on its lit midtone (Margulis's rules).
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
from imgops import FONT, lab, lum, vectorscope

SKIN_LINE = 123.0  # degrees on the vectorscope: the YIQ I axis, 33 degrees past R-Y
TMP = tempfile.mkdtemp(prefix="color_check-")
atexit.register(shutil.rmtree, TMP, True)


# ---------------------------------------------------------------- images, through photocraft-cli

def cli():
    p = pc.find_cli()
    if not p:
        sys.exit("error: photocraft-cli not found; `pc.py cli-info` names the one to install")
    return str(p)


def cli_run(src, cmds, out):
    args = [cli(), "run", src]
    for c, p in cmds:
        args += ["--cmd", c, "--params", json.dumps(p)]
    r = subprocess.run(args + ["--out", out], capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        sys.exit(f"error: photocraft-cli run {src}: {(r.stderr or r.stdout).strip()[:300]}")


def full_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
    r = subprocess.run([cli(), "info", path, "--compact"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"error: cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    return d["width"], d["height"]


def tmp(name):
    return os.path.join(TMP, f"{len(os.listdir(TMP))}{name}")


class Image:
    """A photo to measure: flat channels of the analysis copy; s = full-image pixels per analysis pixel."""

    def __init__(self, path, max_side):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.name = os.path.basename(self.path)
        self.W, self.H = full_size(self.path)
        k = min(1.0, max_side / max(self.W, self.H))
        src = self.path
        if k < 1 or not self.path.lower().endswith(".png"):
            src = tmp("a.png")
            cli_run(self.path, [("image.imageSize", {"width": max(1, round(self.W * k))})] if k < 1 else [], src)
        self.w, self.h, self.R, self.G, self.B = imgops.load(src)
        self.s = self.W / self.w

    def small(self, side=600):
        """Box-downscaled copy of about `side` px: (w, h, R, G, B, full-image pixels per pixel)."""
        k = max(1, round(max(self.w, self.h) / side))
        R, w, h = imgops.downscale(self.R, self.w, self.h, k)
        return (w, h, R, imgops.downscale(self.G, self.w, self.h, k)[0], imgops.downscale(self.B, self.w, self.h, k)[0],
                self.s * k)

    def crop(self, x, y, w, h):
        """Full-resolution pixels of a rectangle: (w, h, R, G, B)."""
        out = tmp("c.png")
        cli_run(self.path, [("image.crop", {"x": x, "y": y, "width": w, "height": h})], out)
        return imgops.load(out)


def point(s):
    v = [float(t) for t in s.split(",")]
    return v[0], v[1], (v[2] if len(v) > 2 else 8.0)


def patch(img, p):
    """The full-resolution pixels of the disk p = (x, y, radius), as (r, g, b) tuples."""
    x, y, r = p
    x0, y0 = max(0, int(x - r)), max(0, int(y - r))
    x1, y1 = min(img.W, int(x + r) + 1), min(img.H, int(y + r) + 1)
    if x1 <= x0 or y1 <= y0:
        sys.exit(f"error: point {x:g},{y:g} is outside the image ({img.W}x{img.H})")
    w, h, R, G, B = img.crop(x0, y0, x1 - x0, y1 - y0)
    return [(R[i], G[i], B[i]) for i in range(w * h) if (x0 + i % w - x) ** 2 + (y0 + i // w - y) ** 2 <= r * r]


def clipped_by_channel(pix):
    """Per channel, the share of the patch at 254 or more and at 1 or less: (high, low)."""
    n = len(pix)
    return ([sum(1 for q in pix if q[c] >= 254) / n for c in range(3)],
            [sum(1 for q in pix if q[c] <= 1) / n for c in range(3)])


def sample(img, p, pix=None):
    """Mean colour of a disk at full resolution, ignoring specks > 3 MADs off its median luminance.
    Returns (rgb, fraction of clipped pixels, pixels used). pix: the disk's pixels if already read (patch())."""
    pix = pix or patch(img, p)
    Y = sorted(lum(*q) for q in pix)
    med = Y[len(Y) // 2]
    mad = max(0.5, sorted(abs(v - med) for v in Y)[len(Y) // 2])
    keep = [q for q in pix if abs(lum(*q) - med) <= 3 * 1.4826 * mad]
    rgb = tuple(sum(q[k] for q in keep) / len(keep) for k in range(3))
    return rgb, sum(1 for q in pix if max(q) >= 254 or min(q) <= 1) / len(pix), len(keep)


def hint(a, b):
    if math.hypot(a, b) < 1.5:
        return "neutral"
    parts = ["yellow/warm" if b > 0 else "blue/cool"] if abs(b) >= 1 else []
    parts += ["magenta" if a > 0 else "green"] if abs(a) >= 1 else []
    return " + ".join(parts)


def describe(rgb, space):
    L, a, b = lab(*rgb, space)
    return {"rgb": [round(v, 1) for v in rgb], "lab": [round(L, 1), round(a, 2), round(b, 2)],
            "R-G": round(rgb[0] - rgb[1], 1), "B-G": round(rgb[2] - rgb[1], 1), "cast": hint(a, b)}


# ---------------------------------------------------------------- measurements

def tone_stats(R, G, B):
    n = len(R)
    Y = sorted(lum(r, g, b) for r, g, b in zip(R, G, B))
    return {"luminance%": {str(p): round(Y[min(n - 1, int(p / 100 * n))], 1) for p in (0.1, 1, 50, 99, 99.9)},
            "clippedHigh%": {c: round(100 * sum(1 for v in ch if v >= 254) / n, 3) for c, ch in zip("RGB", (R, G, B))},
            "clippedLow%": {c: round(100 * sum(1 for v in ch if v <= 1) / n, 3) for c, ch in zip("RGB", (R, G, B))}}


def chroma_stats(R, G, B, space):
    C = sorted(math.hypot(*lab(r, g, b, space)[1:]) for r, g, b in zip(R, G, B))
    return {"meanChroma": round(sum(C) / len(C), 1), "p95Chroma": round(C[int(0.95 * (len(C) - 1))], 1)}


def wmedian(vals, wts):
    pairs = sorted(zip(vals, wts))
    half, acc = sum(wts) / 2, 0.0
    for v, k in pairs:
        acc += k
        if acc >= half:
            return v
    return pairs[-1][0]


def inner_point(comp, w):
    """The pixel of a component farthest from its edge (chamfer distance): (x, y, radius in px)."""
    xs = [i % w for i in comp]; ys = [i // w for i in comp]
    x0, y0 = min(xs), min(ys)
    bw, bh = max(xs) - x0 + 3, max(ys) - y0 + 3
    d = [0] * (bw * bh)
    for i in comp:
        d[(i // w - y0 + 1) * bw + i % w - x0 + 1] = 1 << 30
    for y in range(1, bh - 1):
        for x in range(1, bw - 1):
            j = y * bw + x
            if d[j]:
                d[j] = min(d[j], d[j - 1] + 3, d[j - bw] + 3, d[j - bw - 1] + 4, d[j - bw + 1] + 4)
    for y in range(bh - 2, 0, -1):
        for x in range(bw - 2, 0, -1):
            j = y * bw + x
            if d[j]:
                d[j] = min(d[j], d[j + 1] + 3, d[j + bw] + 3, d[j + bw + 1] + 4, d[j + bw - 1] + 4)
    j = max(range(bw * bh), key=d.__getitem__)
    return x0 - 1 + j % bw, y0 - 1 + j // bw, d[j] / 3


def neutral_candidates(w, h, R, G, B, s, space, top=8):
    """Smooth surfaces whose colour is the photo's dominant low-chroma colour: what a neutral looks like under this
    light, if the photo has neutrals. Painted walls, wood, sand and skin can win too; look before using one.
    Returns ((a*, b*) estimate, candidates, share of the image that agrees)."""
    n = w * h
    Lab = [lab(r, g, b, space) for r, g, b in zip(R, G, B)]
    L = [v[0] for v in Lab]; A = [v[1] for v in Lab]; Bb = [v[2] for v in Lab]

    def local_sd(v):
        m, m2 = imgops.box(v, w, h, 2), imgops.box([x * x for x in v], w, h, 2)
        return [math.sqrt(max(0.0, q - p * p)) for p, q in zip(m, m2)]

    sl, sa, sb = local_sd(L), local_sd(A), local_sd(Bb)
    ok = [sl[i] < 2.5 and sa[i] < 1.5 and sb[i] < 1.5 and 20 <= L[i] <= 97 and max(R[i], G[i], B[i]) < 250
          for i in range(n)]
    ca = cb = 0.0
    for rad in (40, 15, 10, 7):
        idx = [i for i in range(n) if ok[i] and math.hypot(A[i] - ca, Bb[i] - cb) < rad]
        if len(idx) < 20:
            break
        ca, cb = wmedian([A[i] for i in idx], [L[i] for i in idx]), wmedian([Bb[i] for i in idx], [L[i] for i in idx])
    cand = [ok[i] and math.hypot(A[i] - ca, Bb[i] - cb) < 6 for i in range(n)]
    out = []
    for comp in imgops.components(cand, w, h):
        if len(comp) < max(12, n // 2000):
            continue
        x, y, r = inner_point(comp, w)
        mL = sum(L[i] for i in comp) / len(comp)
        out.append({"at": [round((x + 0.5) * s), round((y + 0.5) * s), max(3, min(40, round((r - 0.5) * s)))],
                    "area%": round(100 * len(comp) / n, 2), "lab": [round(mL, 1), round(sum(A[i] for i in comp) / len(comp), 2),
                                                               round(sum(Bb[i] for i in comp) / len(comp), 2)]})
    out.sort(key=lambda d: -d["area%"] * d["lab"][0])
    return (ca, cb), out[:top], sum(cand) / n


def edge_estimate(w, h, R, G, B, space):
    """Grey-edge illuminant estimate (van de Weijer et al. 2007): the Minkowski (p = 6) mean of each linear channel's
    gradient, away from clipped and black pixels. Edges average to grey far more reliably than whole surfaces do,
    so a big coloured wall or a golden dog sways it less. Returns the cast a mid grey would show, as (a*, b*)."""
    sm = [imgops.gauss([imgops.to_linear(v) for v in ch], w, h, 1.0) for ch in (R, G, B)]
    acc = [0.0, 0.0, 0.0]
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            if max(R[i], G[i], B[i]) >= 250 or min(R[i], G[i], B[i]) <= 3:
                continue
            for c in range(3):
                gx, gy = sm[c][i + 1] - sm[c][i - 1], sm[c][i + w] - sm[c][i - w]
                acc[c] += (gx * gx + gy * gy) ** 3
    e = [v ** (1 / 6) for v in acc]
    if not all(e):
        return None
    k = 0.18 / (0.2126 * e[0] + 0.7152 * e[1] + 0.0722 * e[2])
    enc = [imgops.from_linear(k * v) for v in e]
    return lab(*enc, space)[1:]


def area_cfg(spec):
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        return {"skin": cfg.get("skin") or cfg["area"], "exclude": cfg.get("exclude", [])}
    x0, y0, x1, y1 = (float(v) for v in spec.split(","))
    return {"skin": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "exclude": []}


def area_mask(spec, w, h, s):
    """Rasterise an AREA (full-image coordinates) on a copy s times smaller than the full image."""
    cfg = area_cfg(spec)
    polys = cfg["skin"] if isinstance(cfg["skin"][0][0], (list, tuple)) else [cfg["skin"]]
    ex = [[[x / s, y / s] for x, y in e] if isinstance(e[0], (list, tuple)) else [round(v / s) for v in e]
          for e in cfg["exclude"]]
    return imgops.raster({"skin": [[[x / s, y / s] for x, y in p] for p in polys], "exclude": ex}, 0, 0, w, h)


def skin_lab_notes(a, b):
    """Margulis's Lab rules for skin (Dehancer's "Lifelike", ch. 16): a face is positive in both a* and b*, typically
    15-20 each in a midtone; under ~10 reads pale or grey, over 30 oversaturated; b* a little above a* reads healthy,
    a* above b* red or "burned" (normal for babies, the elderly, redheads). Starting points, not targets: on eight
    well-balanced portraits the lit midtone read a* 6-28, b* 7-38, b*/a* 0.62-1.37, and each outlier had its reason in
    the light or the complexion (high-key studio light, low sun, a ruddy face). Returns the notes that apply."""
    if a <= 2 or b <= 2:
        return ["a* or b* near zero or negative: skin isn't red-yellow here, so a cast (green, blue or magenta) or a "
                "coloured light; correct from neutrals first"]
    notes = []
    if max(a, b) < 10:
        notes.append("pale: a* and b* under 10 (fair skin in soft, bright light measures this way: a high-key studio "
                     "portrait balanced on a chart read a* 6, b* 7; a cool or grey cast does too, so check a neutral)")
    if max(a, b) > 30:
        notes.append("oversaturated: a* or b* over 30 (low warm sun raises it: golden-hour skin read b* 28-38; otherwise "
                     "Vibrance down or a Hue/Saturation on reds and yellows)")
    if b < 0.8 * a:
        notes.append("b* well below a*: reads red or pink ('burned'), usual for babies, the elderly, redheads and "
                     "flushed or ruddy skin; otherwise a magenta cast or a red-heavy grade")
    elif b > 1.5 * a:
        notes.append("b* well above a*: reads yellow or sallow (a yellow or green cast, or a warm grade on top)")
    return notes


def skin_stats(R, G, B, mask, space):
    """Median skin colour inside the mask: vectorscope angle (vs the skin-tone line), saturation, Lab. Plus the same on
    the lit midtone only (litMidtone: the 50th-90th percentile of the area's luminance, so the shadow side, hair and
    brows below it and the speculars above it don't count): a skin average mixes in all of those, and a rough face
    area read b*/a* 1.41 where its lit cheeks read 1.09; the lit midtone of that face read 1.22."""
    idx = [i for i in range(len(R)) if mask[i] and 25 < lum(R[i], G[i], B[i]) < 245 and max(R[i], G[i], B[i]) < 254]
    if len(idx) < 20:
        return {"error": "fewer than 20 usable skin pixels in the area"}
    med = [sorted(ch[i] for i in idx)[len(idx) // 2] for ch in (R, G, B)]
    ang, sat = vectorscope(*med)
    angs = sorted(a for a, s in (vectorscope(R[i], G[i], B[i]) for i in idx) if s > 8)
    L, a, b = lab(*med, space)
    off = (ang - SKIN_LINE + 180) % 360 - 180
    # measured: studio skin under a neutral chart 116, golden-hour skin 115, its skylit shadow side 110
    verdict = ("in the usual skin range (110-130)" if 110 <= ang <= 130 else "pinker/redder than usual skin" if 90 <= ang < 110
               else "yellower/greener than usual skin" if 130 < ang <= 150 else "far from any skin hue: a strong cast")
    Ys = sorted(lum(R[i], G[i], B[i]) for i in idx)
    lo, hi = Ys[len(Ys) // 2], Ys[int(0.9 * (len(Ys) - 1))]
    lit = [i for i in idx if lo <= lum(R[i], G[i], B[i]) <= hi]
    mt = [sorted(ch[i] for i in lit)[len(lit) // 2] for ch in (R, G, B)]
    Lm, am, bm = lab(*mt, space)
    notes = skin_lab_notes(am, bm)
    return {"pixels": len(idx), "rgb": med, "angle": round(ang, 1), "offLine": round(off, 1),
            "angleIQR": [round(angs[len(angs) // 4], 1), round(angs[3 * len(angs) // 4], 1)] if angs else None,
            "saturation": round(sat, 1), "lab": [round(L, 1), round(a, 1), round(b, 1)],
            "hueAngleLab": round(math.degrees(math.atan2(b, a)), 1), "verdict": verdict,
            "litMidtone": {"pixels": len(lit), "luminance": [round(lo, 1), round(hi, 1)], "rgb": mt,
                           "lab": [round(Lm, 1), round(am, 1), round(bm, 1)], "chroma": round(math.hypot(am, bm), 1),
                           "bOverA": round(bm / am, 2) if am > 2 and bm > 2 else None,
                           "angle": round(vectorscope(*mt)[0], 1),
                           "labVerdict": "; ".join(notes) if notes else "typical (a*, b* positive, about 10-30, b* near or "
                                                                          "a little above a*)"}}


# ---------------------------------------------------------------- pictures: viz and vectorscope

class Canvas:
    def __init__(self, w, h, px):
        self.w, self.h, self.px = w, h, px  # px: flat list of [r, g, b]

    def put(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y * self.w + x] = c

    def line(self, x0, y0, x1, y1, c):
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n + 1):
            t = i / n
            self.put(int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t)), c)

    def circle(self, x, y, r, c):
        for t in range(0, 360, 3):
            self.put(int(round(x + r * math.cos(math.radians(t)))), int(round(y + r * math.sin(math.radians(t)))), c)

    def rect(self, x0, y0, x1, y1, c):
        for x0_, y0_, x1_, y1_ in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
            self.line(x0_, y0_, x1_, y1_, c)

    def text(self, x, y, s, c, k=2):
        for i, ch in enumerate(s):
            for r in range(5):
                for col in range(3):
                    if FONT.get(ch, "0" * 15)[r * 3 + col] == "1":
                        for dy in range(k):
                            for dx in range(k):
                                self.put(x + (i * 4 + col) * k + dx, y + r * k + dy, c)

    def save(self, path):
        pngio.write(path, self.w, self.h, [[tuple(int(v) for v in p) for p in self.px[y * self.w:(y + 1) * self.w]]
                                           for y in range(self.h)])


def write_viz(path, img, neutrals, cands, skin_spec):
    """The photo with clipped highlights red, clipped shadows blue, neutral samples green, candidates cyan, skin yellow."""
    cv = Canvas(img.w, img.h, [[r, g, b] for r, g, b in zip(img.R, img.G, img.B)])
    for i, (r, g, b) in enumerate(zip(img.R, img.G, img.B)):
        if max(r, g, b) >= 254:
            cv.px[i] = [255, 0, 0]
        elif min(r, g, b) <= 1:
            cv.px[i] = [0, 60, 255]
    s = img.s
    for k, c in enumerate(cands):
        x, y, r = (v / s for v in c["at"])
        cv.rect(int(x - r), int(y - r), int(x + r), int(y + r), [0, 255, 255])
        cv.text(int(x - r), int(y - r) - 12, str(k + 1), [0, 255, 255])
    for k, (x, y, r) in enumerate(neutrals):
        cv.circle(x / s, y / s, max(2, r / s), [0, 255, 0])
        cv.text(int(x / s + r / s + 3), int(y / s - 5), str(k + 1), [0, 255, 0])
    if skin_spec:
        cfg = area_cfg(skin_spec)
        for poly in (cfg["skin"] if isinstance(cfg["skin"][0][0], (list, tuple)) else [cfg["skin"]]):
            for i in range(len(poly)):
                (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
                cv.line(x0 / s, y0 / s, x1 / s, y1 / s, [255, 230, 0])
    cv.save(path)


def write_scope(path, R, G, B, skin=None, marks=()):
    """A vectorscope: U = 0.492 (B - Y) right, V = 0.877 (R - Y) up. Grey ring = saturation 50, the line is the
    skin-tone line, small squares are 75 % red/yellow/green/cyan/blue/magenta. Skin pixels show orange, a neutral
    sample or the cast estimate as a white cross: anything that should be neutral belongs at the centre."""
    S, c, k = 321, 160, 150 / 120  # px per unit of saturation; the edge is saturation 120
    acc, sk = [0] * (S * S), [0] * (S * S)

    def at(u, v):
        x, y = int(round(c + u * k)), int(round(c - v * k))
        return y * S + x if 0 <= x < S and 0 <= y < S else None

    for i, (r, g, b) in enumerate(zip(R, G, B)):
        y = 0.299 * r + 0.587 * g + 0.114 * b
        j = at(0.492 * (b - y), 0.877 * (r - y))
        if j is not None:
            acc[j] += 1
            if skin and skin[i]:
                sk[j] += 1
    top = math.log1p(max(acc) or 1)
    px = [[24, 24, 24] for _ in range(S * S)]
    cv = Canvas(S, S, px)
    cv.circle(c, c, 50 * k, [70, 70, 70]); cv.circle(c, c, 100 * k, [55, 55, 55])
    cv.line(c - 150, c, c + 150, c, [45, 45, 45]); cv.line(c, c - 150, c, c + 150, [45, 45, 45])
    a = math.radians(SKIN_LINE)
    cv.line(c, c, c + 150 * math.cos(a), c - 150 * math.sin(a), [150, 100, 60])
    for col in ((191, 0, 0), (191, 191, 0), (0, 191, 0), (0, 191, 191), (0, 0, 191), (191, 0, 191)):
        y = 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2]
        j = at(0.492 * (col[2] - y), 0.877 * (col[0] - y))
        if j is not None:
            cv.rect(j % S - 4, j // S - 4, j % S + 4, j // S + 4, list(col))
    for j in range(S * S):
        if acc[j]:
            v = 60 + 195 * math.log1p(acc[j]) / top
            px[j] = [v, v * 0.62, v * 0.25] if sk[j] * 2 >= acc[j] else [v, v, v]
    for r, g, b in marks:
        y = 0.299 * r + 0.587 * g + 0.114 * b
        j = at(0.492 * (b - y), 0.877 * (r - y))
        if j is not None:
            x0, y0 = j % S, j // S
            cv.line(x0 - 6, y0, x0 + 6, y0, [255, 255, 255]); cv.line(x0, y0 - 6, x0, y0 + 6, [255, 255, 255])
    cv.save(path)


# ---------------------------------------------------------------- curves

def monotone(pts):
    lut = imgops.spline_lut(pts)
    return all(lut[i + 1] >= lut[i] for i in range(255))


def clean_points(pts, gap=6):
    """Sort, merge inputs closer than `gap` levels (the ends at 0 and 255 win), round to whole levels, and drop points
    until the spline is monotone (an overshooting curve solarises). Whole levels because a PSD stores Curves points that
    way (fractional ones reopened up to 1 level off), so the prediction is what every saved file keeps. Returns
    (points, dropped)."""
    pts = sorted(pts)
    out = []
    for x, y in pts:
        if out and x - out[-1][0] < gap:
            if out[-1][0] in (0, 255):
                continue
            if x in (0, 255):
                out[-1] = [x, y]
                continue
            out[-1] = [(out[-1][0] + x) / 2, (out[-1][1] + y) / 2]
        else:
            out.append([x, y])
    whole = []
    for x, y in out:
        x, y = round(x), round(min(255.0, max(0.0, y)))
        if whole and x <= whole[-1][0]:  # two inputs on one level once rounded: keep one, the ends win
            if whole[-1][0] not in (0, 255):
                whole[-1] = [x, y] if x in (0, 255) else [x, round((whole[-1][1] + y) / 2)]
            continue
        whole.append([x, y])
    out = whole
    dropped = 0
    while len(out) > 2 and not monotone(out):
        inner = range(1, len(out) - 1)
        k = min(inner, key=lambda i: min(out[i][0] - out[i - 1][0], out[i + 1][0] - out[i][0]))
        del out[k]
        dropped += 1
    return out, dropped


def is_identity(pts):
    return all(abs(x - y) < 0.01 for x, y in pts)


def apply_luts(R, G, B, luts, masks=None):
    """luts: per-layer {"red"/"green"/"blue": lut} and/or {"points": lut}, applied in order with 8-bit rounding
    (within one layer PhotoCraft applies the channel curves, then the composite).
    masks: per layer, None or a 0..1 value per pixel (the layer mask: the result is mixed in by that much)."""
    R, G, B = [int(v) for v in R], [int(v) for v in G], [int(v) for v in B]
    for L, m in zip(luts, masks or [None] * len(luts)):
        R0, G0, B0 = R, G, B
        R = [L["red"][v] for v in R] if "red" in L else R
        G = [L["green"][v] for v in G] if "green" in L else G
        B = [L["blue"][v] for v in B] if "blue" in L else B
        if "points" in L:
            t = L["points"]
            R, G, B = [t[v] for v in R], [t[v] for v in G], [t[v] for v in B]
        if m is not None:
            R, G, B = ([int(o + k * (n - o) + 0.5) for o, n, k in zip(old, new, m)] for old, new in ((R0, R), (G0, G), (B0, B)))
    return R, G, B


def through(rgb, luts):
    """A float colour through the layers (sample means: interpolated, as the pixels around them would go)."""
    r, g, b = rgb
    for L in luts:
        r = imgops.lut_f(L["red"], r) if "red" in L else r
        g = imgops.lut_f(L["green"], g) if "green" in L else g
        b = imgops.lut_f(L["blue"], b) if "blue" in L else b
        if "points" in L:
            r, g, b = (imgops.lut_f(L["points"], v) for v in (r, g, b))
    return r, g, b


def write_mask(img, mask_a, outdir):
    """The analysis-scale mask as a full-resolution PNG of its bounding box (even-sized, so it centres exactly on its
    box when imported); the CLI scales it up. Returns (box [x, y, w, h], full-resolution values for crop(x, y, w, h))."""
    on = [i for i, v in enumerate(mask_a) if v > 0.5 / 255]
    if not on:
        sys.exit("error: the area is empty")
    ax0, ay0 = min(i % img.w for i in on), min(i // img.w for i in on)
    ax1, ay1 = max(i % img.w for i in on) + 1, max(i // img.w for i in on) + 1
    x0, y0 = int(ax0 * img.s), int(ay0 * img.s)
    w = (min(img.W, math.ceil(ax1 * img.s)) - x0) // 2 * 2
    h = (min(img.H, math.ceil(ay1 * img.s)) - y0) // 2 * 2
    small = tmp("m.png")
    imgops.save_gray(small, ax1 - ax0, ay1 - ay0, [mask_a[y * img.w + x] for y in range(ay0, ay1) for x in range(ax0, ax1)])
    cli_run(small, [("image.imageSize", {"width": w, "height": h})], os.path.join(outdir, "mask.png"))

    def values(cx, cy, cw, ch):
        M = [0.0] * (cw * ch)
        ix0, iy0, ix1, iy1 = max(cx, x0), max(cy, y0), min(cx + cw, x0 + w), min(cy + ch, y0 + h)
        if ix1 > ix0 and iy1 > iy0:
            out = tmp("mc.png")
            cli_run(os.path.join(outdir, "mask.png"), [("image.crop", {"x": ix0 - x0, "y": iy0 - y0, "width": ix1 - ix0,
                                                                      "height": iy1 - iy0})], out)
            mw, mh, Rm, _, _ = imgops.load(out)
            for y in range(mh):
                for x in range(mw):
                    M[(iy0 - cy + y) * cw + ix0 - cx + x] = Rm[y * mw + x] / 255
        return M
    return [x0, y0, w, h], values


def write_outputs(img, outdir, layers, luts, group, verify_at, extra, masks=None, mask=None):
    """layers.json + preview.png (a full-resolution crop through the predicted layers) + before_after.png.
    masks: per layer, None or the analysis-scale mask; mask: write_mask()'s (box, values) for the masked layer."""
    masks = masks or [None] * len(luts)
    cw, ch = min(512, img.W), min(512, img.H)
    x0 = int(min(max(0, verify_at[0] - cw / 2), img.W - cw)); y0 = int(min(max(0, verify_at[1] - ch / 2), img.H - ch))
    w, h, R, G, B = img.crop(x0, y0, cw, ch)
    full = [mask[1](x0, y0, cw, ch) if m is not None else None for m in masks]
    imgops.save_rgb(os.path.join(outdir, "preview.png"), w, h, *apply_luts(R, G, B, luts, full))
    center = [mask[0][0] + mask[0][2] / 2, mask[0][1] + mask[0][3] / 2] if mask else [x0 + cw / 2, y0 + ch / 2]
    json.dump({"center": center, "crop": [x0, y0, cw, ch], "preview": "preview.png",
               "group": group, "layers": layers}, open(os.path.join(outdir, "layers.json"), "w"), indent=1)
    k = max(1, math.ceil(img.w / 700))
    sw, sh = img.w // k, img.h // k
    ch_ = [imgops.downscale(c, img.w, img.h, k)[0] for c in (img.R, img.G, img.B)]
    after = apply_luts(*ch_, luts, [imgops.downscale(m, img.w, img.h, k)[0] if m is not None else None for m in masks])
    gap = 8
    px = [[255, 255, 255] for _ in range((2 * sw + gap) * sh)]
    for y in range(sh):
        for x in range(sw):
            i = y * sw + x
            px[y * (2 * sw + gap) + x] = [ch_[0][i], ch_[1][i], ch_[2][i]]
            px[y * (2 * sw + gap) + sw + gap + x] = [after[0][i], after[1][i], after[2][i]]
    Canvas(2 * sw + gap, sh, px).save(os.path.join(outdir, extra))


# ---------------------------------------------------------------- subcommands

def cmd_measure(a):
    img = Image(a.image, a.max_side)
    w, h, R, G, B, s = img.small()
    out = {"image": img.name, "size": [img.W, img.H], "analysedAt": [img.w, img.h]}
    out.update(tone_stats(img.R, img.G, img.B))
    out.update(chroma_stats(R, G, B, a.space))
    neutrals = [point(p) for p in a.neutral]
    marks = []
    if neutrals:
        out["neutrals"] = []
        for p in neutrals:
            rgb, clipped, n = sample(img, p)
            d = describe(rgb, a.space)
            if clipped > 0.02:
                d["warning"] = f"{100 * clipped:.0f}% of the patch is clipped: not a usable neutral"
            out["neutrals"].append({"at": [p[0], p[1], p[2]], **d})
            marks.append(rgb)
    est, cands, share = neutral_candidates(w, h, R, G, B, s, a.space)
    warn = []
    if share < 0.01:
        warn.append("few smooth near-neutral surfaces: the estimate is weak")
    if len(cands) >= 2:
        spread = max(math.hypot(p["lab"][1] - q["lab"][1], p["lab"][2] - q["lab"][2]) for p in cands[:3] for q in cands[:3])
        if spread > 6:
            warn.append(f"top candidates disagree by {spread:.0f} a*b* units: mixed light, or coloured surfaces")
    # grey-edge usually reads a real cast 2-3x too weak, but points the same way; a different direction, or a surface
    # estimate far stronger than that, means the dominant "neutral" is probably a coloured surface
    edge = edge_estimate(w, h, R, G, B, a.space)
    if edge:
        me, ms = math.hypot(*edge), math.hypot(*est)
        turn = abs((math.degrees(math.atan2(edge[1], edge[0]) - math.atan2(est[1], est[0])) + 180) % 360 - 180)
        if (me > 3 and ms > 3 and turn > 45) or (ms > 6 and ms > 4 * me):
            warn.append(f"the grey-edge estimate ({edge[0]:.1f}, {edge[1]:.1f}) disagrees: the dominant near-neutral surface "
                        "may be coloured (wall, wood, fur, skin), or the light mixed")
    out["castEstimate"] = {"a": round(est[0], 2), "b": round(est[1], 2), "cast": hint(*est), "agreeingShare%": round(100 * share, 1),
                           "greyEdge": [round(edge[0], 2), round(edge[1], 2)] if edge else None,
                           "candidates": cands, "warnings": warn,
                           "note": "the dominant low-chroma colour: a real neutral under this light, or a painted wall, wood, "
                                   "sand or skin. Look at each candidate in viz.png before passing it as --neutral"}
    skin = area_mask(a.skin, w, h, s) if a.skin else None
    if skin:
        out["skin"] = skin_stats(R, G, B, skin, a.space)
    if a.viz:
        write_viz(a.viz, img, neutrals, cands, a.skin)
    if a.scope:
        Lc = imgops.lab_to_rgb(70, est[0], est[1], a.space)
        write_scope(a.scope, R, G, B, skin, marks or [Lc])
    print(json.dumps(out))


GRID = [0, 16, 32, 56, 80, 104, 128, 160, 192, 224, 255]
# --tone end points by output. Screen: rich black and white with texture. Print: inside what paper and press hold, where
# published targets agree only roughly (Kelby CC 2017 7/245, his CS2 book 20/244, Macworld 10/243, Curvemeister users
# 10-15/245): shadows near 7-10, highlights near 243-245.
TARGETS = {"screen": (4.0, 251.0), "print": (8.0, 244.0)}


def wb_curve(pairs, top=255.0, bottom=0.0):
    """One channel's white-balance curve through the (x -> t) pairs, ends at 0 and 255. Between the pairs it is
    piecewise power (straight lines in log-log): one pair gives a pure gamma curve, several never overshoot between
    them, where a natural spline through the same few points swings 30 levels past them (measured on a colour
    chart). A linear toe below a quarter of the darkest pair keeps the slope at black finite. Returned as enough
    points that PhotoCraft's spline follows it; the prediction uses those points, so it stays exact.
    top / bottom: the output at input 255 / 0. A white reference clipped in this channel sets top (it is 255 there,
    so only the end can take it to grey, as the Curves white eyedropper does); a black one clipped at 0 sets bottom.
    Returns (points, pairs dropped because they contradict the others)."""
    pts, dropped = [], 0
    for x, t in sorted(p for p in pairs if 4 <= p[0] <= 251):
        if pts and (t <= pts[-1][1] or x - pts[-1][0] < 3):
            dropped += 1  # a brighter input can't map darker: these references disagree
            continue
        pts.append((x, min(max(t, 1.0), 254.0)))
    if top < 255:  # the end joins the power-law chain as its last point
        while pts and pts[-1][1] >= top:
            pts.pop()
            dropped += 1
        pts.append((255.0, top))
    if not pts or pts == [(255.0, top)]:
        return [[0, round(bottom)], [255, round(top)]], dropped
    U = [math.log(x / 255) for x, _ in pts]
    V = [math.log(t / 255) for _, t in pts]

    def F(x):
        u = math.log(x / 255)
        if u >= U[-1]:
            return 255 * math.exp(V[-1] / U[-1] * u) if U[-1] < 0 else 255 * math.exp(V[-1])
        for i in range(len(U) - 1, 0, -1):
            if u >= U[i - 1]:
                return 255 * math.exp(V[i - 1] + (V[i] - V[i - 1]) / (U[i] - U[i - 1]) * (u - U[i - 1]))
        g = (V[1] - V[0]) / (U[1] - U[0]) if len(U) > 1 else V[0] / U[0]
        return 255 * math.exp(V[0] + g * (u - U[0]))

    toe = pts[0][0] / 4
    inner = [p[0] for p in pts if p[0] < 255]
    xs = [0, 255] + [x for x in GRID if 0 < x < 255 and all(abs(x - p) >= 8 for p in inner)] + inner
    out = sorted([x, bottom if x == 0 else top if x == 255 else F(x) if x >= toe else bottom + (F(toe) - bottom) * x / toe]
                 for x in xs)
    pts2, d = clean_points(out, gap=1)
    return pts2, dropped + d


def solve_wb(refs, amount):
    """Per-channel curves taking each reference to grey at its own luminance (or its given level), by `amount`.
    refs: (rgb, level) or (rgb, level, ends), ends = {channel index: "top" | "bottom"} for a channel the reference
    has clipped: that channel's curve end is placed so the reference still lands on its target, extrapolated from the
    next reference's slope (a fully clipped patch puts the end on the target itself, like the Curves eyedroppers; a
    partly clipped one, still mostly measured, keeps its own value: a patch 10 % clipped in blue ended b* +2.6 with the
    end on the target and within 1 b* this way)."""
    curves, dropped = {}, 0
    for ci, name in enumerate(("red", "green", "blue")):
        pairs, clipped, top, bottom = [], [], 255.0, 0.0
        for ref in refs:
            rgb, level, ends = ref[0], ref[1], (ref[2] if len(ref) > 2 else {})
            t = lum(*rgb) if level is None else level
            pr = (rgb[ci], rgb[ci] + amount * (t - rgb[ci]))
            (clipped.append((ends[ci], pr)) if ends.get(ci) else pairs.append(pr))
        srt = sorted(pairs)
        for side, (x, y) in clipped:
            if side == "top":
                lower = [p for p in srt if p[0] < x - 3]
                s = (y - lower[-1][1]) / (x - lower[-1][0]) if lower else y / max(x, 1.0)
                top = min(255.0, max(y, y + s * (255 - x)))
            else:
                upper = [p for p in srt if p[0] > x + 3]
                s = (upper[0][1] - y) / (upper[0][0] - x) if upper else (255 - y) / max(255 - x, 1.0)
                bottom = max(0.0, min(y, y - s * x))
        curves[name], d = wb_curve(pairs, top, bottom)
        dropped += d
    return curves, dropped


def tone_curve(R, G, B, clip, black, white, both=False):
    """A straight composite curve taking the darkest/lightest clip% of every channel to `black`/`white`: Levels'
    black and white point, measured per channel so that no channel clips more than clip% (luminance alone lets the
    red of warm highlights clip), speculars still free to reach 255. An end already past its target stays put (for a
    screen: only ever stretch), unless both: then it is pulled in too (for print: the whole range inside the paper's)."""
    srt = [sorted(ch) for ch in (R, G, B)]
    n = len(R) - 1
    lo, hi = min(s[int(clip / 100 * n)] for s in srt), max(s[int((1 - clip / 100) * n)] for s in srt)
    b_pt = (lo, black) if lo > black + 1 or (both and lo < black - 1) else (0.0, 0.0)
    w_pt = (hi, white) if hi < white - 1 or (both and hi > white + 1) else (255.0, 255.0)
    if b_pt == (0.0, 0.0) and w_pt == (255.0, 255.0):
        return None, lo, hi
    m = (w_pt[1] - b_pt[1]) / (w_pt[0] - b_pt[0])
    y0, y1 = b_pt[1] - m * b_pt[0], w_pt[1] + m * (255 - w_pt[0])  # the line's output at inputs 0 and 255
    start = [0.0, y0] if y0 >= 0 else [-y0 / m, 0.0]
    end = [255.0, y1] if y1 <= 255 else [w_pt[0] + (255 - w_pt[1]) / m, 255.0]
    return [[round(start[0]), round(start[1])], [round(end[0]), round(end[1])]], lo, hi  # whole levels, as a PSD keeps


def cmd_correct(a):
    img = Image(a.image, a.max_side)
    os.makedirs(a.outdir, exist_ok=True)
    refs, report, clash = [], [], []
    names = ("red", "green", "blue")
    for kind, spec, level in ([("neutral", p, None) for p in a.neutral] + ([("white", a.white, a.white_level)] if a.white else [])
                              + ([("black", a.black, a.black_level)] if a.black else [])):
        p = point(spec)
        pix = patch(img, p)
        rgb, clipped, n = sample(img, p, pix)
        ends = {}
        if clipped > 0.02:
            # A strong cast clips one channel of the whites (or the blacks) first. That channel is 255 (0) however bright
            # (dark) the patch really is, so a point through it can't move it to grey; the end of its curve can, as the
            # Curves white (black) eyedropper does. Only for --white / --black, and only when one channel is clipped.
            hi, lo = clipped_by_channel(pix)
            bad = [c for c in range(3) if hi[c] > 0.02 or lo[c] > 0.02]
            side = "top" if kind == "white" else "bottom" if kind == "black" else None
            if not (side and len(bad) == 1 and (hi if side == "top" else lo)[bad[0]] > 0.02
                    and (lo if side == "top" else hi)[bad[0]] <= 0.02):
                where = (f"clipped in {', '.join(names[c] for c in bad)}" if bad else
                         "of its pixels have a clipped channel, spread over several channels (specks or a texture)")
                print(f"warning: {kind} {spec}: {100 * clipped:.0f}% {where}, left out" + (
                      " (a near-white or near-black neutral with one clipped channel still works as --white / --black)"
                      if kind == "neutral" and len(bad) == 1 else "; sample a smoother patch nearby" if not bad else ""),
                      file=sys.stderr)
                continue
            c = bad[0]
            ends = {c: side}
            t = lum(*rgb) if level is None else level
            clash.append(f"{kind} {spec}: its {names[c]} channel is clipped in {100 * (hi if side == 'top' else lo)[c]:.0f}% of the "
                         f"patch, so the {side} end of the {names[c]} curve takes it to its target ({t:.0f}), as the Curves {kind} "
                         f"eyedropper would; {names[c]} detail {'brighter' if side == 'top' else 'darker'} than the patch can't come back")
        refs.append((rgb, level, ends))
        report.append({"kind": kind, "at": list(p), "before": describe(rgb, a.space)} |
                      ({"clippedChannel": names[next(iter(ends))]} if ends else {}))
    if not refs:
        sys.exit("error: no usable reference")
    for i in range(len(report)):
        for j in range(i + 1, len(report)):
            (L1, a1, b1), (L2, a2, b2) = report[i]["before"]["lab"], report[j]["before"]["lab"]
            # within 20 L* of white or black a cast changes fast with brightness (a tungsten preset read b* -18 at a
            # chart's N8, L* 85, and -9 at its white, L* 93): there "the same level" is 5 L*, in the midtones 10
            same = 10 if all(20 <= L <= 80 for L in (L1, L2)) else 5
            if abs(L1 - L2) < same and math.hypot(a1 - a2, b1 - b2) > 4:
                clash.append(f"references {i + 1} and {j + 1} are at about the same level but {math.hypot(a1 - a2, b1 - b2):.0f} "
                             "a*b* apart: one isn't neutral, or the light differs between them (--area for a second light)")
    curves, dropped = solve_wb(refs, a.amount)
    wb = {c: imgops.spline_lut(p) for c, p in curves.items() if not is_identity(p)}
    luts, layers = [wb], [{"name": a.name, "adjustment": "curves", "params": {c: curves[c] for c in wb}}]
    masks, mask = [None], None
    if a.area:  # a second light: this white balance only where it falls, feathered
        m = area_mask(a.area, img.w, img.h, img.s)
        masks = [imgops.gauss(m, img.w, img.h, a.feather / img.s / 2) if a.feather > 0 else m]
        mask = write_mask(img, masks[0], a.outdir)
        layers[0]["mask"] = "mask.png"
    for r, ref in zip(report, refs):
        r["after"] = describe(through(ref[0], luts), a.space)
    big = max(abs(p[1] - p[0]) for c in curves.values() for p in c)
    out = {"image": img.name, "amount": a.amount, "references": report, "curves": curves}
    if len(refs) == 1:
        clash.append("one reference corrects its own brightness level; casts usually change with brightness (a camera's "
                     "tungsten preset measured b* -18 to -32 across a chart's greys): add a darker and a lighter neutral")
    if any(max(ref[0]) > 235 for ref in refs) and not any(30 <= r["before"]["lab"][0] <= 75 for r in report):
        clash.append("a reference has a channel above 235: near-white references bend the top of the curve hard and "
                     "leave other levels off; prefer neutrals in the midtones (L* 30-75)")
    if clash:
        out["warningReferences"] = clash
    if dropped:
        out["warning"] = f"{dropped} point(s) dropped to keep the curves monotone: references too close or contradictory"
    if big > 40:
        out["warningStrong"] = (f"a channel moves {big:.0f} levels: fix it in 16-bit (image.mode.bits16 first) or it may band; "
                                "check the result in smooth gradients")
    if a.tone:
        R2, G2, B2 = apply_luts(img.R, img.G, img.B, luts)
        bt, wt = (TARGETS[a.output][0] if a.black_target is None else a.black_target,
                  TARGETS[a.output][1] if a.white_target is None else a.white_target)
        tc, lo, hi = tone_curve(R2, G2, B2, a.clip, bt, wt, both=a.output == "print")
        out["tone"] = {"for": a.output, "targets": [bt, wt], "darkest": round(lo, 1), "lightest": round(hi, 1), "curve": tc}
        if tc:
            luts.append({"points": imgops.spline_lut(tc)})
            masks.append(None)
            layers.append({"name": "Black & white point", "adjustment": "curves", "params": {"points": tc}})
    R2, G2, B2 = apply_luts(img.R, img.G, img.B, luts, masks)
    out["before"], out["after"] = tone_stats(img.R, img.G, img.B), tone_stats(R2, G2, B2)
    if a.skin:
        w, h, R, G, B, s = img.small()
        k = round(s / img.s)
        m = area_mask(a.skin, w, h, s)
        out["skinBefore"] = skin_stats(R, G, B, m, a.space)
        out["skinAfter"] = skin_stats(*apply_luts(R, G, B, luts, [imgops.downscale(q, img.w, img.h, k)[0] if q is not None
                                                                  else None for q in masks]), m, a.space)
    write_outputs(img, a.outdir, layers, luts, a.group, point(a.neutral[0] if a.neutral else (a.white or a.black)),
                  "before_after.png", masks, mask)
    json.dump(out, open(os.path.join(a.outdir, "correct.json"), "w"), indent=1)
    print(json.dumps({k: out[k] for k in out if k not in ("before", "after")} | {
        "clippedHighAfter%": out["after"]["clippedHigh%"], "clippedLowAfter%": out["after"]["clippedLow%"]}))


def qv(s, q):
    k = (len(s) - 1) * q / 100
    i = int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


def match_points(ts, rs, qs, amount, anchor=None):
    """Quantile mapping of one channel at the target's quantiles qs, ends extrapolated from the outer slopes.
    anchor (x, y): a colour that must map exactly (the median skin), replacing quantile points within 12 levels."""
    pts = []
    for q in qs:
        x, y = qv(ts, q), qv(rs, q)
        if anchor and abs(x - anchor[0]) < 12:
            continue
        if not pts or x - pts[-1][0] >= 10:
            pts.append([x, y])
    if anchor:
        pts = sorted(pts + [list(anchor)])
    if len(pts) == 1:
        pts.append([min(255.0, pts[0][0] + 10), min(255.0, pts[0][1] + 10)])
    (x1, y1), (x2, y2) = pts[0], pts[1]
    y0 = min(max(0.0, y1 - (y2 - y1) / max(1e-6, x2 - x1) * x1), y1)
    (xa, ya), (xb, yb) = pts[-2], pts[-1]
    yt = max(min(255.0, yb + (yb - ya) / max(1e-6, xb - xa) * (255 - xb)), yb)
    pts = [p for p in pts if 6 <= p[0] <= 249]
    pts = [[0.0, y0]] + pts + [[255.0, yt]]
    for i in range(1, len(pts)):  # at least a gentle rise between points
        pts[i][1] = max(pts[i][1], pts[i - 1][1] + 0.15 * (pts[i][0] - pts[i - 1][0]))
    return clean_points([[x, x + amount * (y - x)] for x, y in pts])[0]


def cmd_match(a):
    tgt, ref = Image(a.image, a.max_side), Image(a.reference, a.max_side)
    os.makedirs(a.outdir, exist_ok=True)
    tm = area_mask(a.area, tgt.w, tgt.h, tgt.s) if a.area else None
    rm = area_mask(a.ref_area, ref.w, ref.h, ref.s) if a.ref_area else None
    qs = [2, 25, 50, 75, 98] if a.points <= 5 else [1 + 98 * i / (a.points - 1) for i in range(a.points)]
    anchors = [None] * 3
    if a.anchor_skin:
        if not (a.skin and a.ref_skin):
            sys.exit("error: --anchor-skin needs --skin and --ref-skin")
        sk = []
        for img, spec in ((tgt, a.skin), (ref, a.ref_skin)):
            w, h, R, G, B, s = img.small()
            sk.append(skin_stats(R, G, B, area_mask(spec, w, h, s), a.space))
            if "rgb" not in sk[-1]:
                sys.exit(f"error: {img.name}: {sk[-1]['error']}")
        anchors = list(zip(sk[0]["rgb"], sk[1]["rgb"]))
    curves, luts = {}, {}
    for k, (name, T, Rf) in enumerate((("red", tgt.R, ref.R), ("green", tgt.G, ref.G), ("blue", tgt.B, ref.B))):
        ts = sorted(v for i, v in enumerate(T) if tm is None or tm[i])
        rs = sorted(v for i, v in enumerate(Rf) if rm is None or rm[i])
        curves[name] = match_points(ts, rs, qs, a.amount, anchors[k])
        luts[name] = imgops.spline_lut(curves[name])
    layer = {"name": f"Match {ref.name}", "adjustment": "curves", "params": curves}
    R2, G2, B2 = apply_luts(tgt.R, tgt.G, tgt.B, [luts])

    def summary(R, G, B, m):
        idx = [i for i in range(len(R)) if m is None or m[i]]
        mean = [sum(ch[i] for i in idx) / len(idx) for ch in (R, G, B)]
        srt = [sorted(ch[i] for i in idx) for ch in (R, G, B)]
        return {"meanRGB": [round(v, 1) for v in mean], "meanLab": [round(v, 1) for v in lab(*mean, a.space)],
                "p5/50/95": {c: [round(qv(sc, q)) for q in (5, 50, 95)] for c, sc in zip("RGB", srt)}}

    out = {"image": tgt.name, "reference": ref.name, "amount": a.amount, "curves": curves,
           "before": summary(tgt.R, tgt.G, tgt.B, tm), "after": summary(R2, G2, B2, tm), "ref": summary(ref.R, ref.G, ref.B, rm)}
    if a.skin and a.ref_skin:
        w, h, R, G, B, s = tgt.small()
        m = area_mask(a.skin, w, h, s)
        out["skinBefore"] = skin_stats(R, G, B, m, a.space)
        out["skinAfter"] = skin_stats(*apply_luts(R, G, B, [luts]), m, a.space)
        w, h, R, G, B, s = ref.small()
        out["skinRef"] = skin_stats(R, G, B, area_mask(a.ref_skin, w, h, s), a.space)
    write_outputs(tgt, a.outdir, [layer], [luts], a.group, (tgt.W / 2, tgt.H / 2), "match.png")
    # the reference beside the before/after pair, at the same height
    k = max(1, math.ceil(ref.h / (tgt.h // max(1, math.ceil(tgt.w / 700)))))
    rr = [imgops.downscale(c, ref.w, ref.h, k)[0] for c in (ref.R, ref.G, ref.B)]
    rw, rh = ref.w // k, ref.h // k
    w0, h0, P = pngio.read(os.path.join(a.outdir, "match.png"))
    H = max(h0, rh)
    rows = [[(255, 255, 255)] * (w0 + 8 + rw) for _ in range(H)]
    for y in range(h0):
        rows[y][:w0] = P[y]
    for y in range(rh):
        for x in range(rw):
            i = y * rw + x
            rows[y][w0 + 8 + x] = tuple(max(0, min(255, int(c[i] + 0.5))) for c in rr)
    pngio.write(os.path.join(a.outdir, "match.png"), w0 + 8 + rw, H, rows)
    json.dump(out, open(os.path.join(a.outdir, "match.json"), "w"), indent=1)
    print(json.dumps(out))


def local_contrast(R, G, B, w, h, sigma, mask=None):
    """Mean |luminance - its Gaussian blur at sigma px| (where mask > 0.5): what clarity raises."""
    L = [lum(r, g, b) for r, g, b in zip(R, G, B)]
    m = imgops.gauss(L, w, h, sigma)
    d = [abs(p - q) for i, (p, q) in enumerate(zip(L, m)) if mask is None or mask[i] > 0.5]
    return sum(d) / max(1, len(d))


def verify_window(img, change, off=None, at=None, size=512):
    """Top-left (full-image pixels) of the verify crop for a planner's preview: where the layer changes most (change:
    per analysis pixel), and with a mask across its edge, so the import check sees the mask too: at least a tenth of the
    window where the mask turns the layer off (off: 1 there), or half the most any window holds for small areas, and at
    most nine tenths. A window where the mask turns the layer off would match the preview whatever the import did.
    at: X,Y to centre it there instead."""
    cw, ch = min(size, img.W), min(size, img.H)
    if at:
        x, y = point(at)[:2]
        return int(min(max(0, x - cw / 2), img.W - cw)), int(min(max(0, y - ch / 2), img.H - ch))
    ww, wh = max(1, min(img.w, round(cw / img.s))), max(1, min(img.h, round(ch / img.s)))
    change_in = window_sums(change, img.w, img.h)
    off_in = window_sums(off, img.w, img.h) if off else None
    cands = []
    for by in sorted(set(list(range(0, img.h - wh + 1, max(1, wh // 4))) + [img.h - wh])):
        for bx in sorted(set(list(range(0, img.w - ww + 1, max(1, ww // 4))) + [img.w - ww])):
            share = off_in(bx, by, bx + ww, by + wh) / (ww * wh) if off_in else 0.0
            cands.append((change_in(bx, by, bx + ww, by + wh), share, bx, by))
    least = min(0.1, 0.5 * max(c[1] for c in cands))
    best = max((c for c in cands if least <= c[1] <= 0.9), default=None) if least > 0 else None
    best = best or max(cands)
    return int(min(best[2] * img.s, img.W - cw)), int(min(best[3] * img.s, img.H - ch))


CLARITY_BLENDS = {"highpass": ("Overlay", "Soft Light", "Hard Light", "Linear Light"), "usm": ("Normal", "Luminosity")}


def window_sums(vals, w, h):
    """A summed-area table (a zero row and column first) and the sum over x0 <= x < x1, y0 <= y < y1 from it."""
    W = w + 1
    S = [0.0] * (W * (h + 1))
    for y in range(h):
        acc = 0.0
        for x in range(w):
            acc += vals[y * w + x]
            S[(y + 1) * W + x + 1] = S[y * W + x + 1] + acc
    return lambda x0, y0, x1, y1: S[y1 * W + x1] - S[y0 * W + x1] - S[y1 * W + x0] + S[y0 * W + x0]


def cmd_clarity(a):
    """Local contrast ("clarity") on a Stamp Visible layer, masked off skin, with an exact preview."""
    hp = a.method == "highpass"
    blend = a.blend or ("Overlay" if hp else "Normal")
    if blend not in CLARITY_BLENDS[a.method]:
        sys.exit(f"error: --blend {blend} with --method {a.method}: " + (
            "a High Pass layer is mid grey plus the detail, so it needs a contrast blend: " if hp else
            "an Unsharp Mask stamp is the photo itself, sharpened: ") + " or ".join(CLARITY_BLENDS[a.method]) +
            (" (Luminosity keeps the colours as they were)" if not hp else ""))
    img = Image(a.image, a.max_side)
    os.makedirs(a.outdir, exist_ok=True)
    long_ = max(img.W, img.H)
    radius = a.radius or round((0.03 if hp else 0.015) * long_, 1)
    if hp:  # KelbyOne: High Pass at about 180 px on a 6000 px photo, Overlay or Soft Light on a copy
        cmds = [["filter.other.highPass", {"radius": radius}]] + ([] if a.colour else [["image.adjustments.desaturate", {}]])
        opacity = 0.5 if a.opacity is None else a.opacity
    else:  # KelbyOne: Unsharp Mask amount 5-30 %, radius 30-100 px, threshold 0
        cmds = [["filter.sharpen.unsharpMask", {"amount": a.amount, "radius": radius, "threshold": 0}]]
        opacity = 1.0 if a.opacity is None else a.opacity
    layer = {"name": a.name, "stamp": cmds}
    if blend != "Normal":
        layer["blend"] = blend
    if opacity < 1:
        layer["opacity"] = opacity
    warnings = []
    notskin, mask = None, None
    if a.skin:  # clarity amplifies pores, blemishes and the shadows of wrinkles: keep it off skin
        sk = area_mask(a.skin, img.w, img.h, img.s)
        if a.feather > 0:
            sk = imgops.gauss(sk, img.w, img.h, a.feather / img.s / 2)
        notskin = [1.0 - v for v in sk]
        if max(notskin) <= 0.5 / 255:
            sys.exit("error: the --skin area covers the whole photo, so nothing would get local contrast; draw it round "
                     "the visible skin only (face, neck, hands)")
        mask = write_mask(img, notskin, a.outdir)
        layer["mask"] = "mask.png"
    else:
        warnings.append("no --skin: faces get the local contrast too, which deepens pores, blemishes and wrinkles; for "
                        "portraits pass the skin area")

    def filtered(src, x, y, w, h, r):
        """The filter's output for the window (x, y, w, h) of src, run on the window plus 3 radii (exact inside)."""
        W, H = full_size(src)
        m = int(3 * r) + 8
        cx0, cy0 = max(0, x - m), max(0, y - m)
        cx1, cy1 = min(W, x + w + m), min(H, y + h + m)
        steps = [("image.crop", {"x": cx0, "y": cy0, "width": cx1 - cx0, "height": cy1 - cy0})]
        for c, p in cmds:
            steps.append((c, dict(p, radius=r) if "radius" in p else p))
        steps.append(("image.crop", {"x": x - cx0, "y": y - cy0, "width": w, "height": h}))
        out = tmp("f.png")
        cli_run(src, steps, out)
        return imgops.load(out)[2:]

    key = imgops.blend_key(blend)
    f = imgops.SEPARABLE.get(key)  # Normal and the contrast blends work channel by channel; Luminosity doesn't

    def compose(R, G, B, F, M):
        if f is None:
            out = [[], [], []]
            for i in range(len(R)):
                k = opacity * (M[i] if M is not None else 1.0)
                v = imgops.blend(blend, (R[i], G[i], B[i]), (F[0][i], F[1][i], F[2][i]), k) if k > 0 else (R[i], G[i], B[i])
                for c in range(3):
                    out[c].append(v[c])
            return out
        out = []
        for ch, fc in zip((R, G, B), F):
            o = []
            for i, (b, s) in enumerate(zip(ch, fc)):
                k = opacity * (M[i] if M is not None else 1.0)
                o.append(b + k * (255 * min(1.0, max(0.0, f(b / 255, s / 255))) - b) if k > 0 else b)
            out.append(o)
        return out

    # the whole photo on the analysis copy (radius scaled): local contrast, clipping, where the layer changes most
    small = tmp("s.png")
    imgops.save_rgb(small, img.w, img.h, img.R, img.G, img.B)
    Fs = filtered(small, 0, 0, img.w, img.h, round(radius / img.s, 2))
    R2, G2, B2 = compose(img.R, img.G, img.B, Fs, notskin)

    cw, ch = min(512, img.W), min(512, img.H)
    change = [abs(R2[i] - img.R[i]) + abs(G2[i] - img.G[i]) + abs(B2[i] - img.B[i]) for i in range(len(R2))]
    x0, y0 = verify_window(img, change, [1.0 if v < 0.5 else 0.0 for v in notskin] if notskin else None, a.at)
    # exact preview: a full-resolution window, filtered by the CLI with enough margin, blended as PhotoCraft does
    w, h, R, G, B = img.crop(x0, y0, cw, ch)
    Mw = mask[1](x0, y0, cw, ch) if mask else None
    P = compose(R, G, B, filtered(img.path, x0, y0, cw, ch, radius), Mw)
    imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w, h, *P)
    changed = sum(abs(P[c][i] - v) for c, chan in enumerate((R, G, B)) for i, v in enumerate(chan)) / (3 * w * h)
    skin_share = sum(1 for v in Mw if v < 0.5) / (w * h) if Mw else 0.0
    if changed < 0.5:
        warnings.append(f"the verify window changes only {changed:.2f} levels on average: the import check proves little; "
                        "pick a window with --at X,Y where the layer acts")
    center = [mask[0][0] + mask[0][2] / 2, mask[0][1] + mask[0][3] / 2] if mask else [img.W / 2, img.H / 2]
    json.dump({"center": center, "crop": [x0, y0, cw, ch], "preview": "preview.png", "group": a.group, "layers": [layer]},
              open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)

    sig = 0.01 * max(img.w, img.h)
    lc0, lc1 = (local_contrast(*c, img.w, img.h, sig, notskin) for c in ((img.R, img.G, img.B), (R2, G2, B2)))
    out = {"image": img.name, "method": a.method, "radius": radius, "blend": blend, "opacity": opacity,
           "commands": cmds, "localContrast": {"before": round(lc0, 2), "after": round(lc1, 2),
                                               "change%": round(100 * (lc1 / max(1e-6, lc0) - 1), 1)},
           "verifyWindow": {"crop": [x0, y0, cw, ch], "meanChange": round(changed, 2), "skinShare": round(skin_share, 3)},
           "before": tone_stats(img.R, img.G, img.B), "after": tone_stats(R2, G2, B2)}
    if notskin:
        sk_m = [1 - v for v in notskin]
        out["skinLocalContrast"] = {"before": round(local_contrast(img.R, img.G, img.B, img.w, img.h, sig, sk_m), 2),
                                    "after": round(local_contrast(R2, G2, B2, img.w, img.h, sig, sk_m), 2)}
    for c in "RGB":
        if out["after"]["clippedHigh%"][c] > out["before"]["clippedHigh%"][c] + 0.3 or \
                out["after"]["clippedLow%"][c] > out["before"]["clippedLow%"][c] + 0.3:
            warnings.append(f"{c} clips more than 0.3 % more of the photo: lower the opacity (or the amount)")
            break
    out["warnings"] = warnings
    k = max(1, math.ceil(img.w / 700))
    sw, sh = img.w // k, img.h // k
    halves = [[imgops.downscale(c, img.w, img.h, k)[0] for c in chans] for chans in ((img.R, img.G, img.B), (R2, G2, B2))]
    px = [[255, 255, 255] for _ in range((2 * sw + 8) * sh)]
    for y in range(sh):
        for x in range(sw):
            i = y * sw + x
            px[y * (2 * sw + 8) + x] = [c[i] for c in halves[0]]
            px[y * (2 * sw + 8) + sw + 8 + x] = [c[i] for c in halves[1]]
    Canvas(2 * sw + 8, sh, px).save(os.path.join(a.outdir, "before_after.png"))
    json.dump(out, open(os.path.join(a.outdir, "clarity.json"), "w"), indent=1)
    print(json.dumps({k_: v for k_, v in out.items() if k_ not in ("before", "after")} | {
        "clippedHigh%": [out["before"]["clippedHigh%"], out["after"]["clippedHigh%"]],
        "clippedLow%": [out["before"]["clippedLow%"], out["after"]["clippedLow%"]]}))


# X-Rite ColorChecker Classic (the formulation made since November 2014), D50 L*a*b* as X-Rite publishes them: four
# rows of six, dark skin first, the neutral row last.
CHECKER = [("dark skin", 37.54, 14.37, 14.92), ("light skin", 64.66, 19.27, 17.50), ("blue sky", 49.32, -3.82, -22.54),
           ("foliage", 43.46, -12.74, 22.72), ("blue flower", 54.94, 9.61, -24.79), ("bluish green", 70.48, -32.26, -0.37),
           ("orange", 62.73, 35.83, 56.50), ("purplish blue", 39.43, 10.75, -45.17), ("moderate red", 50.57, 48.64, 16.67),
           ("purple", 30.10, 22.54, -20.87), ("yellow green", 71.77, -24.13, 58.19), ("orange yellow", 71.51, 18.24, 67.37),
           ("blue", 28.37, 15.42, -49.80), ("green", 54.38, -39.72, 32.27), ("red", 42.43, 51.05, 28.62),
           ("yellow", 81.80, 2.67, 80.41), ("magenta", 50.63, 51.28, -14.12), ("cyan", 49.57, -29.71, -28.32),
           ("white", 95.19, -1.03, 2.93), ("neutral 8", 81.29, -0.57, 0.44), ("neutral 6.5", 66.89, -0.75, -0.06),
           ("neutral 5", 50.76, -0.13, 0.14), ("neutral 3.5", 35.63, -0.46, -0.48), ("black", 20.64, 0.07, -0.46)]


def de2000(lab1, lab2):
    """CIEDE2000 colour difference (Sharma, Wu and Dalal's formulation): about 1 is just noticeable side by side."""
    (L1, a1, b1), (L2, a2, b2) = lab1, lab2
    Cm = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    G = 0.5 * (1 - math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1, a2 = (1 + G) * a1, (1 + G) * a2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    h1 = math.degrees(math.atan2(b1, a1)) % 360 if C1 else 0.0
    h2 = math.degrees(math.atan2(b2, a2)) % 360 if C2 else 0.0
    dh = 0.0 if C1 * C2 == 0 else (h2 - h1 + 180) % 360 - 180
    dH = 2 * math.sqrt(C1 * C2) * math.sin(math.radians(dh / 2))
    Lm, Cpm = (L1 + L2) / 2, (C1 + C2) / 2
    hm = h1 + h2 if C1 * C2 == 0 else (h1 + h2) / 2 if abs(h1 - h2) <= 180 else (h1 + h2 + 360) / 2 if h1 + h2 < 360 \
        else (h1 + h2 - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hm - 30)) + 0.24 * math.cos(math.radians(2 * hm))
         + 0.32 * math.cos(math.radians(3 * hm + 6)) - 0.20 * math.cos(math.radians(4 * hm - 63)))
    Rt = -2 * math.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7)) * math.sin(math.radians(60 * math.exp(-((hm - 275) / 25) ** 2)))
    SL = 1 + 0.015 * (Lm - 50) ** 2 / math.sqrt(20 + (Lm - 50) ** 2)
    SC, SH = 1 + 0.045 * Cpm, 1 + 0.015 * Cpm * T
    return math.sqrt(((L2 - L1) / SL) ** 2 + ((C2 - C1) / SC) ** 2 + (dH / SH) ** 2 + Rt * (C2 - C1) / SC * dH / SH)


def chart_centres(corners):
    """The 24 patch centres from the centres of the four corner patches: dark skin, bluish green, black, white (the
    chart's corners clockwise from dark skin, whichever way up it is), bilinear between them."""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = corners
    out = []
    for r in range(4):
        for c in range(6):
            u, v = c / 5, r / 3
            out.append(((1 - u) * (1 - v) * x1 + u * (1 - v) * x2 + u * v * x3 + (1 - u) * v * x4,
                        (1 - u) * (1 - v) * y1 + u * (1 - v) * y2 + u * v * y3 + (1 - u) * v * y4))
    return out


def mix(M, rgb):
    """A Channel Mixer (rows as fractions) on one colour, unrounded."""
    return [min(255.0, max(0.0, M[i][0] * rgb[0] + M[i][1] * rgb[1] + M[i][2] * rgb[2])) for i in range(3)]


def whole_percent(row):
    """A mixer row as whole percents adding up to exactly 100: a PSD stores the mixer in whole percents (33.33 x 3
    reopens as 99 %, a photo 1.3 levels darker), so the plan uses exactly what any file will keep."""
    p = [100 * v for v in row]
    r = [round(v) for v in p]
    d = 100 - sum(r)
    for i in sorted(range(3), key=lambda i: (p[i] - r[i]) * (1 if d > 0 else -1), reverse=True)[:abs(d)]:
        r[i] += 1 if d > 0 else -1
    return r


def nelder_mead(f, x0, step=0.05, iters=4000):
    n = len(x0)
    pts = [list(x0)] + [[x0[j] + (step if j == i else 0.0) for j in range(n)] for i in range(n)]
    vals = [f(q) for q in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=vals.__getitem__)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        if vals[-1] - vals[0] < 1e-10:
            break
        c = [sum(q[j] for q in pts[:-1]) / n for j in range(n)]
        r = [2 * c[j] - pts[-1][j] for j in range(n)]
        fr = f(r)
        if fr < vals[0]:
            e = [3 * c[j] - 2 * pts[-1][j] for j in range(n)]
            fe = f(e)
            pts[-1], vals[-1] = (e, fe) if fe < fr else (r, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = r, fr
        else:
            k = [(c[j] + pts[-1][j]) / 2 for j in range(n)]
            fk = f(k)
            if fk < vals[-1]:
                pts[-1], vals[-1] = k, fk
            else:
                pts = [pts[0]] + [[(pts[0][j] + q[j]) / 2 for j in range(n)] for q in pts[1:]]
                vals = [vals[0]] + [f(q) for q in pts[1:]]
    return pts[0]


def cmd_chart(a):
    """Measure an X-Rite ColorChecker Classic in the photo against X-Rite's values; fit a Channel Mixer for the colour
    the camera's rendering got wrong (curves can't: they only move each channel by its own value)."""
    img = Image(a.image, a.max_side)
    os.makedirs(a.outdir, exist_ok=True)
    corners = [point(c)[:2] for c in a.corners]
    if len(corners) != 4:
        sys.exit("error: --corners takes the centres of four patches: dark skin, bluish green, black, white")
    centres = chart_centres(corners)
    pitch = min(math.dist(corners[0], corners[1]) / 5, math.dist(corners[0], corners[3]) / 3)
    rad = max(3.0, a.radius_frac * pitch)
    meas, clipped = [], []
    for k, (x, y) in enumerate(centres):
        pix = patch(img, (x, y, rad))
        rgb, clip, _ = sample(img, (x, y, rad), pix)
        meas.append(rgb)
        if clip > 0.02:
            clipped.append(CHECKER[k][0])
    labs = [lab(*m, a.space) for m in meas]
    warnings = []
    neutral_L = [labs[k][0] for k in range(18, 24)]
    if any(neutral_L[i] <= neutral_L[i + 1] for i in range(5)) or \
            max(math.hypot(*labs[k][1:]) for k in range(18, 24)) > max(10.0, 0.5 * max(math.hypot(*labs[k][1:]) for k in range(18))):
        sys.exit("error: the bottom row doesn't run white to black in grey steps: give the corner patch centres as dark "
                 "skin, bluish green, black, white (clockwise from dark skin), and white-balance the photo first "
                 "(color_check.py correct on the chart's greys)")
    if clipped:
        warnings.append(f"clipped patches ({', '.join(clipped)}): their colour is not measurable; the fit leaves them out")
    greys = [labs[k] for k in range(19, 23)]
    if max(max(abs(g[1]), abs(g[2])) for g in greys) > 2:
        warnings.append("the chart's greys are more than 2 a*b* from neutral: run `correct` on them first, the mixer only "
                        "fixes colour that a white balance can't")

    def hue(L):
        return math.degrees(math.atan2(L[2], L[1])) % 360

    def report(cur):
        rows = []
        for k, (name, Lr, ar, br) in enumerate(CHECKER):
            L = cur[k]
            ref = (Lr, ar, br)
            row = {"patch": name, "lab": [round(v, 1) for v in L], "ref": list(ref), "dE00": round(de2000(L, ref), 1),
                   # at the measured lightness: exposure and the camera's tone curve aside, how far the colour is
                   "dE00colour": round(de2000(L, (L[0], ar, br)), 1)}
            if k < 18:
                row["hueError"] = round((hue(L) - hue(ref) + 180) % 360 - 180, 1)
                row["chroma"] = [round(math.hypot(*L[1:]), 1), round(math.hypot(ar, br), 1)]
            rows.append(row)
        colour = rows[:18]
        return rows, {"meanDE00": round(sum(r["dE00"] for r in rows) / 24, 2),
                      "meanDE00colour": round(sum(r["dE00colour"] for r in colour) / 18, 2),
                      "maxDE00colour": max(r["dE00colour"] for r in colour),
                      "meanAbsHueError": round(sum(abs(r["hueError"]) for r in colour) / 18, 1),
                      "skinPatches": {r["patch"]: {"hueError": r["hueError"], "dE00colour": r["dE00colour"]} for r in colour[:2]}}

    before_rows, before = report(labs)
    out = {"image": img.name, "patchRadius": round(rad, 1), "before": before, "warnings": warnings}
    M, layers = None, []
    if a.fit != "none":
        use = [k for k in range(18) if CHECKER[k][0] not in clipped]
        targets = {}
        for k in use:
            L, (Lr, ar, br) = labs[k], CHECKER[k][1:]
            if a.fit == "hue":  # the published hue at the camera's own lightness and chroma: fix the rotation only
                C, h = math.hypot(*L[1:]), math.atan2(br, ar)
                targets[k] = (L[0], C * math.cos(h), C * math.sin(h))
            else:  # the published colour at the camera's lightness
                targets[k] = (L[0], ar, br)
        # the skin patch nearer the subject's measured skin (lit midtone) carries the weight; without --skin both do
        skin_k = (0, 1)
        if a.skin:
            w0, h0, R0, G0, B0, s0 = img.small()
            st = skin_stats(R0, G0, B0, area_mask(a.skin, w0, h0, s0), a.space)
            if "litMidtone" in st:
                L_skin = st["litMidtone"]["lab"]
                skin_k = (min((0, 1), key=lambda k: de2000(labs[k], L_skin)),)
                out["skinPatch"] = CHECKER[skin_k[0]][0]
        wts = {k: (a.skin_weight if k in skin_k else 1.0) for k in use}

        def mat(v):
            return [[1 - v[0] - v[1], v[0], v[1]], [v[2], 1 - v[2] - v[3], v[3]], [v[4], v[5], 1 - v[4] - v[5]]]

        def cost(v):
            M_ = mat(v)
            e = 0.0
            for k in use:
                L = lab(*mix(M_, meas[k]), a.space)
                t = targets[k]
                e += wts[k] * (0.5 * (L[0] - t[0]) ** 2 + (L[1] - t[1]) ** 2 + (L[2] - t[2]) ** 2)
            return e / sum(wts.values()) + a.ridge * sum(x * x for x in v)

        Mf = mat(nelder_mead(cost, [0.0] * 6))
        pct = [whole_percent(row) for row in Mf]
        M = [[v / 100 for v in row] for row in pct]
        after_labs = [lab(*mix(M, m), a.space) for m in meas]
        after_rows, after = report(after_labs)
        out["mixer%"] = {"red": pct[0], "green": pct[1], "blue": pct[2]}
        out["after"] = after
        for k in skin_k:  # the subject's skin patch (both without --skin) pushed past its reference toward red
            if before_rows[k]["hueError"] > after_rows[k]["hueError"] and after_rows[k]["hueError"] < -3:
                warnings.append(f"{CHECKER[k][0]} ends {-after_rows[k]['hueError']:.0f}° redder than the chart: lower "
                                "--skin-weight" + ("" if a.area else ", or mask the mixer to the skin with --area"))
        # browns elsewhere in the photo (hair, wood, leather): the mixer acts on them too
        w, h, R, G, B, s = img.small()
        xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
        cx0, cx1 = (min(xs) - pitch) / s, (max(xs) + pitch) / s
        cy0, cy1 = (min(ys) - pitch) / s, (max(ys) + pitch) / s
        sk = area_mask(a.skin, w, h, s) if a.skin else None
        hb, ha = [], []
        for i in range(0, w * h, 2):
            x, y = i % w, i // w
            if (cx0 <= x <= cx1 and cy0 <= y <= cy1) or (sk and sk[i] > 0):
                continue
            L = lab(R[i], G[i], B[i], a.space)
            C = math.hypot(L[1], L[2])
            if 10 <= L[0] <= 65 and 6 <= C <= 40 and 30 <= hue(L) <= 75:
                hb.append(hue(L))
                ha.append(hue(lab(*mix(M, (R[i], G[i], B[i])), a.space)))
        if len(hb) > 200:
            mb, ma = sorted(hb)[len(hb) // 2], sorted(ha)[len(ha) // 2]
            out["browns"] = {"pixels": len(hb), "medianHue": [round(mb, 1), round(ma, 1)]}
            if ma < mb - 3 and not a.area:
                warnings.append(f"browns elsewhere (hair, wood, leather; {len(hb)} sampled pixels) turn redder: median hue "
                                f"{mb:.0f}° -> {ma:.0f}°; mask the mixer to the skin with --area skin.json")
        layer = {"name": a.name, "adjustment": "channelMixer",
                 "params": {"red": pct[0] + [0], "green": pct[1] + [0], "blue": pct[2] + [0]}}
        mask_a, mask = None, None
        if a.area:
            mask_a = area_mask(a.area, img.w, img.h, img.s)
            if a.feather > 0:
                mask_a = imgops.gauss(mask_a, img.w, img.h, a.feather / img.s / 2)
            mask = write_mask(img, mask_a, a.outdir)
            layer["mask"] = "mask.png"
        if a.skin:
            out["skinBefore"] = skin_stats(R, G, B, sk, a.space)

            def mixed_small():
                k = round(s / img.s)
                mk = imgops.downscale(mask_a, img.w, img.h, k)[0] if mask_a else None
                o = [[], [], []]
                for i in range(w * h):
                    q = [round(v) for v in mix(M, (R[i], G[i], B[i]))]
                    m = mk[i] if mk else 1.0
                    for c, v in enumerate((R[i], G[i], B[i])):
                        o[c].append(v + m * (q[c] - v))
                return o
            out["skinAfter"] = skin_stats(*mixed_small(), sk, a.space)
        # exact preview where the mixer changes most (across the mask's edge when masked)
        R2, G2, B2 = ([], [], [])
        for i in range(len(img.R)):
            q = [round(v) for v in mix(M, (img.R[i], img.G[i], img.B[i]))]
            m = mask_a[i] if mask_a else 1.0
            R2.append(img.R[i] + m * (q[0] - img.R[i])); G2.append(img.G[i] + m * (q[1] - img.G[i]))
            B2.append(img.B[i] + m * (q[2] - img.B[i]))
        change = [abs(R2[i] - img.R[i]) + abs(G2[i] - img.G[i]) + abs(B2[i] - img.B[i]) for i in range(len(R2))]
        x0, y0 = verify_window(img, change, [1.0 if v < 0.5 else 0.0 for v in mask_a] if mask_a else None, a.at)
        cw, ch = min(512, img.W), min(512, img.H)
        w_, h_, Rw, Gw, Bw = img.crop(x0, y0, cw, ch)
        Mw = mask[1](x0, y0, cw, ch) if mask else None
        P = [[], [], []]
        for i in range(w_ * h_):
            q = [min(255, max(0, round((pct[c][0] * Rw[i] + pct[c][1] * Gw[i] + pct[c][2] * Bw[i]) / 100))) for c in range(3)]
            m = Mw[i] if Mw else 1.0
            for c, v in enumerate((Rw[i], Gw[i], Bw[i])):
                P[c].append(v + m * (q[c] - v))
        imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w_, h_, *P)
        center = [mask[0][0] + mask[0][2] / 2, mask[0][1] + mask[0][3] / 2] if mask else [img.W / 2, img.H / 2]
        json.dump({"center": center, "crop": [x0, y0, cw, ch], "preview": "preview.png", "group": a.group,
                   "layers": [layer]}, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
        layers = [after_rows]
    # chart.png: per patch three stripes, as measured | after the mixer | X-Rite's value
    cell, gap = 66, 6
    W, H = 6 * (cell + gap) + gap, 4 * (cell + gap) + gap
    cv = Canvas(W, H, [[40, 40, 40] for _ in range(W * H)])
    for k in range(24):
        r, c = divmod(k, 6)
        ref_rgb = [max(0.0, min(255.0, v)) for v in imgops.lab_to_rgb(*CHECKER[k][1:], a.space)]
        cols = [meas[k], [round(v) for v in mix(M, meas[k])] if M else meas[k], ref_rgb]
        for j, col in enumerate(cols):
            for y in range(cell):
                for x in range(cell // 3):
                    cv.put(gap + c * (cell + gap) + j * (cell // 3) + x, gap + r * (cell + gap) + y, list(col))
    cv.save(os.path.join(a.outdir, "chart.png"))
    out["patches"] = [dict(b, after=(layers[0][k] if layers else None)) for k, b in enumerate(before_rows)]
    json.dump(out, open(os.path.join(a.outdir, "chart.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "patches"}))


def cmd_compare(a):
    imgs = [Image(p, a.max_side) for p in (a.before, a.after)]
    out = {}
    for tag, img in zip(("before", "after"), imgs):
        d = tone_stats(img.R, img.G, img.B)
        w, h, R, G, B, s = img.small()
        d.update(chroma_stats(R, G, B, a.space))
        if a.neutral:
            d["neutrals"] = [describe(sample(img, point(p))[0], a.space) for p in a.neutral]
        if a.skin:
            d["skin"] = skin_stats(R, G, B, area_mask(a.skin, w, h, s), a.space)
        out[tag] = d
    print(json.dumps(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-side", type=int, default=1200, help="analysis copy size in px (big images are scaled by the CLI)")
    ap.add_argument("--space", choices=("srgb", "p3"), default="srgb", help="the document's RGB space, for Lab numbers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)  # also accepted after the subcommand (it wins there)
    common.add_argument("--max-side", type=int, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--space", choices=("srgb", "p3"), default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = sub.add_parser("measure", parents=[common], help="tone, clipping, cast (neutral samples or estimate), skin")
    p.add_argument("image")
    p.add_argument("--neutral", action="append", default=[], metavar="X,Y[,R]", help="a surface that is neutral in life")
    p.add_argument("--skin", metavar="AREA")
    p.add_argument("--viz", help="PNG: clipping red/blue, neutral samples green, candidates cyan, skin area yellow")
    p.add_argument("--scope", help="PNG: vectorscope with the skin-tone line")
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("correct", parents=[common], help="white balance (and black/white point) as Curves layers")
    p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--neutral", action="append", default=[], metavar="X,Y[,R]",
                   help="neutral surface; repeat for several at different levels (shadow, mid, highlight)")
    p.add_argument("--white", metavar="X,Y[,R]", help="the brightest neutral with detail (a white shirt, paper, a white card)")
    p.add_argument("--white-level", type=float, help="also move the --white patch to this level (e.g. 245); default: neutralise only")
    p.add_argument("--black", metavar="X,Y[,R]", help="the darkest neutral with detail")
    p.add_argument("--black-level", type=float, help="also move the --black patch to this level (e.g. 12)")
    p.add_argument("--amount", type=float, default=1.0, help="fraction of the cast removed: 0.6-0.8 keeps intended warmth")
    p.add_argument("--tone", action="store_true", help="add a 'Black & white point' curve")
    p.add_argument("--clip", type=float, default=0.05, help="%% of pixels allowed past each end with --tone")
    p.add_argument("--for", dest="output", choices=sorted(TARGETS), default="screen",
                   help="--tone end points by output: screen 4/251, print 8/244 (detail the press or paper can hold)")
    p.add_argument("--black-target", type=float, help="--tone: the darkest level (overrides --for)")
    p.add_argument("--white-target", type=float, help="--tone: the lightest level (overrides --for)")
    p.add_argument("--skin", metavar="AREA", help="report the skin angle before and after")
    p.add_argument("--area", metavar="AREA", help="mixed light: apply this white balance only here (masked layer)")
    p.add_argument("--feather", type=float, default=40, help="px the --area mask fades over")
    p.add_argument("--name", default="White balance", help="layer name")
    p.add_argument("--group", default="Colour correction")
    p.set_defaults(fn=cmd_correct)

    p = sub.add_parser("match", parents=[common], help="match a reference shot's colour and tone with per-channel curves")
    p.add_argument("image"); p.add_argument("reference"); p.add_argument("outdir")
    p.add_argument("--amount", type=float, default=1.0)
    p.add_argument("--points", type=int, default=5, help="quantiles fitted per channel (5 = 2/25/50/75/98 %%)")
    p.add_argument("--area", metavar="AREA", help="only this part of IMAGE counts (same content in both shots)")
    p.add_argument("--ref-area", metavar="AREA", help="only this part of REFERENCE counts")
    p.add_argument("--skin", metavar="AREA"); p.add_argument("--ref-skin", metavar="AREA")
    p.add_argument("--anchor-skin", action="store_true", help="also map the median skin colour exactly onto the reference's")
    p.add_argument("--group", default="Colour match")
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("clarity", parents=[common], help="local contrast (High Pass or Unsharp Mask) on a stamp, masked off skin")
    p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--skin", metavar="AREA", help="skin to keep out (feathered): clarity deepens pores and blemishes")
    p.add_argument("--method", choices=("highpass", "usm"), default="highpass")
    p.add_argument("--radius", type=float, help="px; default 3 %% of the long side (highpass), 1.5 %% (usm)")
    p.add_argument("--blend", choices=sorted({b for v in CLARITY_BLENDS.values() for b in v}),
                   help="highpass: Overlay (default), Soft Light, Hard Light, Linear Light; usm: Normal (default), Luminosity")
    p.add_argument("--opacity", type=float, help="default 0.5 (highpass in Overlay), 1 (usm)")
    p.add_argument("--amount", type=float, default=20, help="usm amount, %% (KelbyOne: 5-30)")
    p.add_argument("--colour", action="store_true", help="highpass: keep its colour (adds colour contrast as well)")
    p.add_argument("--feather", type=float, default=40, help="px the skin protection fades over")
    p.add_argument("--at", metavar="X,Y", help="centre of the verify window (default: where the layer changes most, "
                                                 "across the skin mask's edge)")
    p.add_argument("--name", default="Local contrast")
    p.add_argument("--group", default=None, help="group name (default: none)")
    p.set_defaults(fn=cmd_clarity)

    p = sub.add_parser("chart", parents=[common], help="measure a ColorChecker against X-Rite's values; fit a Channel Mixer")
    p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--corners", nargs=4, required=True, metavar="X,Y",
                   help="centres of the dark skin, bluish green, black and white patches (clockwise from dark skin)")
    p.add_argument("--fit", choices=("lab", "hue", "none"), default="lab",
                   help="lab: X-Rite's colours at the camera's lightness (default); hue: only their hues; none: measure")
    p.add_argument("--skin-weight", type=float, default=3.0, help="weight of the two skin patches in the fit")
    p.add_argument("--ridge", type=float, default=20.0, help="pull toward no change (larger = gentler mixer)")
    p.add_argument("--skin", metavar="AREA", help="report this skin before and after (and leave it out of the brown check)")
    p.add_argument("--area", metavar="AREA", help="mask the mixer to this area (the skin, usually), feathered")
    p.add_argument("--feather", type=float, default=30, help="px the --area mask fades over")
    p.add_argument("--radius-frac", type=float, default=0.22, help="sampled disk radius, x the patch pitch")
    p.add_argument("--at", metavar="X,Y", help="centre of the verify window (default: where the mixer changes most)")
    p.add_argument("--name", default="Camera colour (chart)")
    p.add_argument("--group", default=None)
    p.set_defaults(fn=cmd_chart)

    p = sub.add_parser("compare", parents=[common], help="before/after numbers")
    p.add_argument("before"); p.add_argument("after")
    p.add_argument("--neutral", action="append", default=[], metavar="X,Y[,R]")
    p.add_argument("--skin", metavar="AREA")
    p.set_defaults(fn=cmd_compare)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
