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
  color_check.py compare BEFORE AFTER [--neutral X,Y[,R] ...] [--skin AREA]

IMAGE: anything photocraft-cli reads: a `pc.py export` of the document as it is now, the original JPEG, a PSD.
Big images are measured on a copy the CLI scales to --max-side (1200 px); every coordinate is in the full image's
pixels, and neutral patches (radius R, default 8 px) are sampled from the full image. AREA: an area.json
({"skin": polygon(s), "exclude": [...]}, full-image coordinates) or a rectangle x0,y0,x1,y1.
correct and match write OUTDIR/layers.json for import_layers.py, with a full-resolution crop's predicted result
(preview.png) so the import verifies itself, and before_after.png / match.png to look at.
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


def sample(img, p):
    """Mean colour of a disk at full resolution, ignoring specks > 3 MADs off its median luminance.
    Returns (rgb, fraction of clipped pixels, pixels used)."""
    x, y, r = p
    x0, y0 = max(0, int(x - r)), max(0, int(y - r))
    x1, y1 = min(img.W, int(x + r) + 1), min(img.H, int(y + r) + 1)
    if x1 <= x0 or y1 <= y0:
        sys.exit(f"error: point {x:g},{y:g} is outside the image ({img.W}x{img.H})")
    w, h, R, G, B = img.crop(x0, y0, x1 - x0, y1 - y0)
    pix = [(R[i], G[i], B[i]) for i in range(w * h) if (x0 + i % w - x) ** 2 + (y0 + i // w - y) ** 2 <= r * r]
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


def skin_stats(R, G, B, mask, space):
    """Median skin colour inside the mask: vectorscope angle (vs the skin-tone line), saturation, Lab."""
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
    return {"pixels": len(idx), "rgb": med, "angle": round(ang, 1), "offLine": round(off, 1),
            "angleIQR": [round(angs[len(angs) // 4], 1), round(angs[3 * len(angs) // 4], 1)] if angs else None,
            "saturation": round(sat, 1), "lab": [round(L, 1), round(a, 1), round(b, 1)],
            "hueAngleLab": round(math.degrees(math.atan2(b, a)), 1), "verdict": verdict}


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
    """Sort, merge inputs closer than `gap` levels (the ends at 0 and 255 win), and drop points until the spline is
    monotone (an overshooting curve solarises). Returns (points, dropped)."""
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
    dropped = 0
    while len(out) > 2 and not monotone(out):
        inner = range(1, len(out) - 1)
        k = min(inner, key=lambda i: min(out[i][0] - out[i - 1][0], out[i + 1][0] - out[i][0]))
        del out[k]
        dropped += 1
    return [[round(x, 2), round(min(255.0, max(0.0, y)), 2)] for x, y in out], dropped


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


def wb_curve(pairs):
    """One channel's white-balance curve through the (x -> t) pairs, ends at 0 and 255. Between the pairs it is
    piecewise power (straight lines in log-log): one pair gives a pure gamma curve, several never overshoot between
    them, where a natural spline through the same few points swings 30 levels past them (measured on a colour
    chart). A linear toe below a quarter of the darkest pair keeps the slope at black finite. Returned as enough
    points that PhotoCraft's spline follows it; the prediction uses those points, so it stays exact.
    Returns (points, pairs dropped because they contradict the others)."""
    pts, dropped = [], 0
    for x, t in sorted(p for p in pairs if 4 <= p[0] <= 251):
        if pts and (t <= pts[-1][1] or x - pts[-1][0] < 3):
            dropped += 1  # a brighter input can't map darker: these references disagree
            continue
        pts.append((x, min(max(t, 1.0), 254.0)))
    if not pts:
        return [[0, 0], [255, 255]], dropped
    U = [math.log(x / 255) for x, _ in pts]
    V = [math.log(t / 255) for _, t in pts]

    def F(x):
        u = math.log(x / 255)
        if u >= U[-1]:
            return 255 * math.exp(V[-1] / U[-1] * u)
        for i in range(len(U) - 1, 0, -1):
            if u >= U[i - 1]:
                return 255 * math.exp(V[i - 1] + (V[i] - V[i - 1]) / (U[i] - U[i - 1]) * (u - U[i - 1]))
        g = (V[1] - V[0]) / (U[1] - U[0]) if len(U) > 1 else V[0] / U[0]
        return 255 * math.exp(V[0] + g * (u - U[0]))

    toe = pts[0][0] / 4
    xs = [x for x in GRID if all(abs(x - p[0]) >= 8 for p in pts)] + [p[0] for p in pts]
    out = sorted([x, 0.0 if x == 0 else 255.0 if x == 255 else F(x) if x >= toe else F(toe) * x / toe] for x in xs)
    pts2, d = clean_points(out, gap=1)
    return pts2, dropped + d


def solve_wb(refs, amount):
    """Per-channel curves taking each reference to grey at its own luminance (or its given level), by `amount`."""
    curves, dropped = {}, 0
    for ci, name in enumerate(("red", "green", "blue")):
        pairs = []
        for rgb, level in refs:
            t = lum(*rgb) if level is None else level
            pairs.append((rgb[ci], rgb[ci] + amount * (t - rgb[ci])))
        curves[name], d = wb_curve(pairs)
        dropped += d
    return curves, dropped


def tone_curve(R, G, B, clip, black, white):
    """A straight composite curve taking the darkest/lightest clip% of every channel to `black`/`white` (an end
    already past its target stays put): Levels' black and white point, measured per channel so that no channel
    clips more than clip% (luminance alone lets the red of warm highlights clip), speculars still free to reach 255."""
    srt = [sorted(ch) for ch in (R, G, B)]
    n = len(R) - 1
    lo, hi = min(s[int(clip / 100 * n)] for s in srt), max(s[int((1 - clip / 100) * n)] for s in srt)
    b_pt = (lo, black) if lo > black + 1 else (0.0, 0.0)
    w_pt = (hi, white) if hi < white - 1 else (255.0, 255.0)
    if b_pt == (0.0, 0.0) and w_pt == (255.0, 255.0):
        return None, lo, hi
    m = (w_pt[1] - b_pt[1]) / (w_pt[0] - b_pt[0])
    x0 = b_pt[0] - b_pt[1] / m if b_pt[0] else 0.0
    x1 = w_pt[0] + (255 - w_pt[1]) / m if w_pt[0] != 255 else 255.0
    return [[round(x0, 2), 0], [round(min(255.0, x1), 2), 255]], lo, hi


def cmd_correct(a):
    img = Image(a.image, a.max_side)
    os.makedirs(a.outdir, exist_ok=True)
    refs, report = [], []
    for kind, spec, level in ([("neutral", p, None) for p in a.neutral] + ([("white", a.white, a.white_level)] if a.white else [])
                              + ([("black", a.black, a.black_level)] if a.black else [])):
        p = point(spec)
        rgb, clipped, n = sample(img, p)
        if clipped > 0.02:
            print(f"warning: {kind} {spec}: {100 * clipped:.0f}% clipped, left out", file=sys.stderr)
            continue
        refs.append((rgb, level))
        report.append({"kind": kind, "at": list(p), "before": describe(rgb, a.space)})
    if not refs:
        sys.exit("error: no usable reference")
    clash = []
    for i in range(len(report)):
        for j in range(i + 1, len(report)):
            (L1, a1, b1), (L2, a2, b2) = report[i]["before"]["lab"], report[j]["before"]["lab"]
            if abs(L1 - L2) < 10 and math.hypot(a1 - a2, b1 - b2) > 4:
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
    for r, (rgb, level) in zip(report, refs):
        r["after"] = describe(through(rgb, luts), a.space)
    big = max(abs(p[1] - p[0]) for c in curves.values() for p in c)
    out = {"image": img.name, "amount": a.amount, "references": report, "curves": curves}
    if len(refs) == 1:
        clash.append("one reference corrects its own brightness level; casts usually change with brightness (a camera's "
                     "tungsten preset measured b* -18 to -32 across a chart's greys): add a darker and a lighter neutral")
    if any(max(rgb) > 235 for rgb, _ in refs) and not any(30 <= r["before"]["lab"][0] <= 75 for r in report):
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
        tc, lo, hi = tone_curve(R2, G2, B2, a.clip, a.black_target, a.white_target)
        out["tone"] = {"darkest": round(lo, 1), "lightest": round(hi, 1), "curve": tc}
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
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-side", type=int, default=1200, help="analysis copy size in px (big images are scaled by the CLI)")
    ap.add_argument("--space", choices=("srgb", "p3"), default="srgb", help="the document's RGB space, for Lab numbers")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("measure", help="tone, clipping, cast (neutral samples or estimate), skin")
    p.add_argument("image")
    p.add_argument("--neutral", action="append", default=[], metavar="X,Y[,R]", help="a surface that is neutral in life")
    p.add_argument("--skin", metavar="AREA")
    p.add_argument("--viz", help="PNG: clipping red/blue, neutral samples green, candidates cyan, skin area yellow")
    p.add_argument("--scope", help="PNG: vectorscope with the skin-tone line")
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("correct", help="white balance (and black/white point) as Curves layers")
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
    p.add_argument("--black-target", type=float, default=4)
    p.add_argument("--white-target", type=float, default=251)
    p.add_argument("--skin", metavar="AREA", help="report the skin angle before and after")
    p.add_argument("--area", metavar="AREA", help="mixed light: apply this white balance only here (masked layer)")
    p.add_argument("--feather", type=float, default=40, help="px the --area mask fades over")
    p.add_argument("--name", default="White balance", help="layer name")
    p.add_argument("--group", default="Colour correction")
    p.set_defaults(fn=cmd_correct)

    p = sub.add_parser("match", help="match a reference shot's colour and tone with per-channel curves")
    p.add_argument("image"); p.add_argument("reference"); p.add_argument("outdir")
    p.add_argument("--amount", type=float, default=1.0)
    p.add_argument("--points", type=int, default=5, help="quantiles fitted per channel (5 = 2/25/50/75/98 %%)")
    p.add_argument("--area", metavar="AREA", help="only this part of IMAGE counts (same content in both shots)")
    p.add_argument("--ref-area", metavar="AREA", help="only this part of REFERENCE counts")
    p.add_argument("--skin", metavar="AREA"); p.add_argument("--ref-skin", metavar="AREA")
    p.add_argument("--anchor-skin", action="store_true", help="also map the median skin colour exactly onto the reference's")
    p.add_argument("--group", default="Colour match")
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("compare", help="before/after numbers")
    p.add_argument("before"); p.add_argument("after")
    p.add_argument("--neutral", action="append", default=[], metavar="X,Y[,R]")
    p.add_argument("--skin", metavar="AREA")
    p.set_defaults(fn=cmd_compare)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
