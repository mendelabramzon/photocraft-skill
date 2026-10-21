#!/usr/bin/env python3
"""Look at LightCraft renders by the numbers. Python 3 standard library only.

  look.py measure IMG [--point X,Y[,NAME] ...] [--radius 4]
      Clipping, tone (L* percentiles) and a colour-cast estimate of a rendered PNG, and the colour at points:
      sRGB, Lab (D50, as photo editors show it), chroma, and the vectorscope angle that skin is judged by
      (skin of every complexion sits near 123 degrees; 110-130 is the usual range).
  look.py grid IMG OUT [--step 0.1]
      A labelled 0..1 grid over a render, to read the normalized coordinates LightCraft's commands take
      (develop.wbPick, mask centres and gradients, spot.add, redeye.add, crop rects). Commands measure in the
      whole upright photo, before any crop: draw the grid on a render without one.
  look.py diff A B OUT [--threshold 6]
      Where two renders of one photo differ: a red heat map over a grey copy of A, the share of the frame that
      changed and its bounding box. Render with a mask's adjustments exaggerated and without, to see what it covers.
  look.py sheet IMG ... --out OUT [--cols 4] [--cell 360] [--labels A,B,C] [--mark 3,5]
      A contact sheet: each image scaled into a cell and labelled, for culling and comparing. Files named by
      photo id (12.png) are labelled with it and put in numeric order; others with their file name. --labels
      replaces the labels, in the cells' order; --mark frames the cells whose label or file name is listed
      (the picks).

Renders to look at come from `lc.py cli render photo -o look.png --size 1200` (headless) or `lc.py render
look.png --size 1200` (live); about 1200 px is plenty, since images are read in pure Python. Anything that
isn't a PNG (an exported JPEG or TIFF, a raw) is first rendered to one by lightcraft-cli, without edits,
into the system temp folder, and removed afterwards.
Points and the grid use the same frame: 0,0 is the top left of the image given, 1,1 the bottom right.
"""

import argparse
import atexit
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # no __pycache__ in the skill's folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngio

_TMP = []

SKIN_LINE = 123.0  # degrees on the vectorscope: the YIQ I axis, 33 degrees past R-Y
FONT = {  # 3x5 glyphs for labels, rows top to bottom; letters are drawn upper case
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111", ".": "000000000000010", "-": "000000111000000",
    "_": "000000000000111", "*": "000101010101000", "+": "000010111010000", " ": "000000000000000",
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
    "Q": "010101101110011", "R": "110101110101101", "S": "011100010001110", "T": "111010010010010",
    "U": "101101101101111", "V": "101101101101010", "W": "101101111111101", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111",
}


# ---------------------------------------------------------------- colour

def _mat(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


# linear sRGB -> XYZ D65, then Bradford to D50: Lab as Lightroom's and Photoshop's readouts give it
_TO_D50 = _mat([[1.0478112, 0.0228866, -0.0501270], [0.0295424, 0.9904844, -0.0170491], [-0.0092345, 0.0150436, 0.7521316]],
               [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
_WHITE = (0.9642, 1.0, 0.8249)


def to_linear(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


LIN = [to_linear(c) for c in range(256)]
# per-channel contributions to Y (D50), so a pixel's luminance is three lookups
_YR, _YG, _YB = ([_TO_D50[1][k] * LIN[c] for c in range(256)] for k in range(3))


def _f(t):
    return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116


def lstar(y):
    return 116 * _f(y) - 16


def lab(r, g, b):
    lr, lg, lb = to_linear(r), to_linear(g), to_linear(b)
    fx, fy, fz = (_f((_TO_D50[i][0] * lr + _TO_D50[i][1] * lg + _TO_D50[i][2] * lb) / _WHITE[i]) for i in range(3))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def vectorscope(r, g, b):
    """(angle in degrees, saturation): U = 0.492 (B - Y) to the right, V = 0.877 (R - Y) up."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u, v = 0.492 * (b - y), 0.877 * (r - y)
    return math.degrees(math.atan2(v, u)) % 360, math.hypot(u, v)


def cast_words(a, b):
    """Which way a colour leans, in words, from its a* and b* (within ±2 counts as neutral)."""
    parts = []
    if abs(b) > 2:
        parts.append("yellow/warm" if b > 0 else "blue/cool")
    if abs(a) > 2:
        parts.append("magenta" if a > 0 else "green")
    return " + ".join(parts) or "neutral"


# ---------------------------------------------------------------- images

def as_png(path):
    """The path itself for a PNG; for anything else (an exported JPEG or TIFF, a raw), a PNG that
    lightcraft-cli renders from it with no edits, which decodes it as LightCraft does."""
    with open(path, "rb") as f:
        if f.read(8) == b"\x89PNG\r\n\x1a\n":
            return path
    import lc
    cli = lc.find_cli()
    if not cli:
        sys.exit(f"error: {path} is not a PNG, and lightcraft-cli isn't installed to convert it; render a PNG first")
    if not _TMP:
        _TMP.append(tempfile.mkdtemp(prefix="look-"))
        atexit.register(shutil.rmtree, _TMP[0], True)
    out = os.path.join(_TMP[0], f"{len(os.listdir(_TMP[0]))}.png")
    r = subprocess.run([str(cli), "render", path, "-o", out], capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        sys.exit(f"error: cannot read {path}: {(r.stderr or r.stdout).strip()[-300:]}")
    return out


def load(path):
    """(w, h, 8-bit RGB samples as a bytearray)."""
    w, h, nch, s = pngio._decode(as_png(path))
    if nch == 3:
        return w, h, s
    rgb = bytearray(w * h * 3)
    if nch == 4:
        rgb[0::3], rgb[1::3], rgb[2::3] = s[0::4], s[1::4], s[2::4]
    elif nch == 2:
        rgb[0::3] = rgb[1::3] = rgb[2::3] = s[0::2]
    else:
        rgb[0::3] = rgb[1::3] = rgb[2::3] = s
    return w, h, rgb


def save(path, w, h, rgb):
    stride = w * 3
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]
    pngio.write_raw(path, w, h, 3, raw)


def text(rgb, w, h, x, y, s, k, color=(255, 230, 0), box=(0, 0, 0)):
    """Draw s (upper-cased) with the 3x5 font scaled by k, on a dark box, with its top left at x, y."""
    s = s.upper()
    tw, th = (4 * len(s) + 1) * k, 7 * k
    for yy in range(max(0, y), min(h, y + th)):
        for xx in range(max(0, x), min(w, x + tw)):
            rgb[(yy * w + xx) * 3:(yy * w + xx) * 3 + 3] = bytes(box)
    for n, ch in enumerate(s):
        glyph = FONT.get(ch)
        if not glyph:
            continue
        for gy in range(5):
            for gx in range(3):
                if glyph[gy * 3 + gx] == "1":
                    for yy in range(y + (gy + 1) * k, y + (gy + 2) * k):
                        for xx in range(x + (n * 4 + gx + 1) * k, x + (n * 4 + gx + 2) * k):
                            if 0 <= xx < w and 0 <= yy < h:
                                rgb[(yy * w + xx) * 3:(yy * w + xx) * 3 + 3] = bytes(color)


# ---------------------------------------------------------------- measure

def measure(a):
    w, h, s = load(a.image)
    n = w * h
    step = max(1, int(math.sqrt(n / 1_500_000)))  # read at most ~1.5 MP
    hist = [0] * 4096
    count = hi_any = hi_all = lo_all = 0
    ch_hi = [0, 0, 0]
    ch_lo = [0, 0, 0]
    sa = sb = neutral = 0.0
    for y in range(0, h, step):
        row = y * w * 3
        for x in range(0, w * 3, 3 * step):
            i = row + x
            r, g, b = s[i], s[i + 1], s[i + 2]
            count += 1
            mx, mn = max(r, g, b), min(r, g, b)
            if mx >= 254:
                hi_any += 1
                if mn >= 254:
                    hi_all += 1
                ch_hi[0] += r >= 254
                ch_hi[1] += g >= 254
                ch_hi[2] += b >= 254
            if mn <= 1:
                ch_lo[0] += r <= 1
                ch_lo[1] += g <= 1
                ch_lo[2] += b <= 1
                if mx <= 1:
                    lo_all += 1
            yv = _YR[r] + _YG[g] + _YB[b]
            hist[min(4095, int(yv * 4095))] += 1
            # near-neutral and well exposed: the pixels a white balance can be judged by
            if mx - mn <= 20 and 30 <= mn and mx <= 245:
                L, aa, bb = lab(r, g, b)
                if math.hypot(aa, bb) < 10:
                    sa += aa
                    sb += bb
                    neutral += 1

    def pct(p):
        target, acc = p / 100 * count, 0
        for k, c in enumerate(hist):
            acc += c
            if acc >= target:
                return round(lstar(k / 4095), 1)
        return 100.0

    mean_y = sum(k * c for k, c in enumerate(hist)) / count / 4095
    share = lambda c: round(100 * c / count, 2)  # noqa: E731
    out = {
        "image": a.image, "size": [w, h],
        "clipping": {
            "highlightsAnyChannelPct": share(hi_any), "highlightsAllChannelsPct": share(hi_all),
            "shadowsAllChannelsPct": share(lo_all),
            "byChannelPct": {c: {"high": share(ch_hi[k]), "low": share(ch_lo[k])} for k, c in enumerate("rgb")},
        },
        "tone": {"L*": {p: pct(float(p)) for p in ("0.5", "5", "50", "95", "99.5")},
                 "meanLuminanceL*": round(lstar(mean_y), 1)},
    }
    if neutral >= 0.005 * count:
        ca, cb = sa / neutral, sb / neutral
        out["cast"] = {"a*": round(ca, 1), "b*": round(cb, 1), "leans": cast_words(ca, cb),
                       "fromPct": share(neutral),
                       "note": "mean of the near-neutral pixels: a hint, since a scene may have no true neutrals"}
    else:
        out["cast"] = {"note": "too few near-neutral pixels to estimate a cast"}

    pts = []
    for spec in a.point or []:
        parts = spec.split(",")
        try:
            px, py = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            sys.exit(f"error: --point wants X,Y[,NAME] with X and Y in 0..1, not {spec!r}")
        name = parts[2] if len(parts) > 2 else None
        cx, cy = min(w - 1, max(0, int(px * w))), min(h - 1, max(0, int(py * h)))
        rad = a.radius
        acc = [0, 0, 0]
        k = bright = dark = 0
        for yy in range(max(0, cy - rad), min(h, cy + rad + 1)):
            for xx in range(max(0, cx - rad), min(w, cx + rad + 1)):
                i = (yy * w + xx) * 3
                acc[0] += s[i]; acc[1] += s[i + 1]; acc[2] += s[i + 2]
                k += 1
                bright += max(s[i], s[i + 1], s[i + 2]) >= 254
                dark += min(s[i], s[i + 1], s[i + 2]) <= 1
        r, g, b = (v / k for v in acc)
        L, aa, bb = lab(r, g, b)
        chroma = math.hypot(aa, bb)
        row = {"at": [px, py], "rgb": [round(r), round(g), round(b)], "lab": [round(L, 1), round(aa, 1), round(bb, 1)],
               "chroma": round(chroma, 1), "leans": cast_words(aa, bb)}
        if chroma >= 4:  # a near-neutral colour has no hue worth reading
            ang, sat = vectorscope(r, g, b)
            row.update(vectorscope=round(ang, 1), offSkinLine=round((ang - SKIN_LINE + 180) % 360 - 180, 1))
        if name:
            row["name"] = name
        if bright or dark:
            row["warning"] = (f"{bright + dark} of {k} pixels clipped ({bright} at 255, {dark} at 0): "
                              "no good as a white-balance reference")
        pts.append(row)
    if pts:
        out["points"] = pts
    print(pretty(out))


def pretty(obj, depth=0):
    """JSON with one key (or list item) per line for the first two levels, compact below them."""
    pad = " " * depth
    if isinstance(obj, dict) and depth < 2:
        return "{\n" + ",\n".join(f"{pad} {json.dumps(k)}: {pretty(v, depth + 1)}" for k, v in obj.items()) + "\n" + pad + "}"
    if isinstance(obj, list) and obj and isinstance(obj[0], dict) and depth < 2:
        return "[\n" + ",\n".join(f"{pad} {json.dumps(v)}" for v in obj) + "\n" + pad + "]"
    return json.dumps(obj)


# ---------------------------------------------------------------- grid

def grid(a):
    w, h, s = load(a.image)
    k = max(2, round(max(w, h) / 450))
    n = int(round(1 / a.step))
    for i in range(1, n):
        t = i / n
        major = abs(t - 0.5) < 1e-9  # the centre lines: solid red, two pixels wide so they survive downscaling
        col = bytes((255, 60, 60) if major else (255, 230, 0))
        for x in range(int(t * w), min(w, int(t * w) + (2 if major else 1))):
            for yy in range(h):
                if major or (yy // 4) % 2 == 0:
                    s[(yy * w + x) * 3:(yy * w + x) * 3 + 3] = col
        for y in range(int(t * h), min(h, int(t * h) + (2 if major else 1))):
            for xx in range(w):
                if major or (xx // 4) % 2 == 0:
                    s[(y * w + xx) * 3:(y * w + xx) * 3 + 3] = col
    labels = {i: f"{i / n:.2f}".rstrip("0") if a.step < 0.1 else f"{i / n:.1f}" for i in range(1, n)}
    widest = (4 * max(len(t) for t in labels.values()) + 1) * k + 4
    every_x = max(1, math.ceil(widest / (w / n)))  # label every line only where the labels fit
    every_y = max(1, math.ceil((7 * k + 4) / (h / n)))
    for i, label in labels.items():
        if i % every_x == 0:
            text(s, w, h, int(i / n * w) + 2, 2, label, k)
        if i % every_y == 0:
            text(s, w, h, 2, int(i / n * h) + 2, label, k)
    save(a.out, w, h, s)
    print(json.dumps({"out": a.out, "size": [w, h], "step": a.step}))


# ---------------------------------------------------------------- diff

def diff(a):
    wa, ha, A = load(a.a)
    wb, hb, B = load(a.b)
    if (wa, ha) != (wb, hb):
        sys.exit(f"error: {a.a} is {wa}x{ha} and {a.b} is {wb}x{hb}; render both at the same --size")
    w, h = wa, ha
    out = bytearray(w * h * 3)
    changed = 0
    total = 0.0
    x0, y0, x1, y1 = w, h, -1, -1
    for p in range(w * h):
        i = p * 3
        d = max(abs(A[i] - B[i]), abs(A[i + 1] - B[i + 1]), abs(A[i + 2] - B[i + 2]))
        g = (0.3 * A[i] + 0.59 * A[i + 1] + 0.11 * A[i + 2]) * 0.45
        t = min(1.0, d / 24)
        out[i] = int(g + (255 - g) * t)
        out[i + 1] = out[i + 2] = int(g * (1 - t) + 40 * t)
        if d > a.threshold:
            changed += 1
            total += d
            y, x = divmod(p, w)
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    save(a.out, w, h, out)
    res = {"out": a.out, "size": [w, h], "changedPct": round(100 * changed / (w * h), 2)}
    if changed:
        res["meanChangeLevels"] = round(total / changed, 1)
        res["bbox"] = [round(x0 / w, 3), round(y0 / h, 3), round((x1 + 1) / w, 3), round((y1 + 1) / h, 3)]
    print(json.dumps(res))


# ---------------------------------------------------------------- sheet

def sheet(a):
    paths = a.images
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    if all(s.isdigit() for s in stems):  # files named by photo id: in numeric order (a glob puts 10 before 2)
        paths, stems = zip(*sorted(zip(paths, stems), key=lambda ps: int(ps[1])))
    labels = a.labels.split(",") if a.labels else list(stems)
    if len(labels) != len(paths):
        sys.exit(f"error: {len(labels)} labels for {len(paths)} images")
    marked = set(a.mark.split(",")) if a.mark else set()
    cell, gap = a.cell, 8
    cols = max(1, min(a.cols, len(paths)))
    rows = (len(paths) + cols - 1) // cols
    W, H = cols * cell + (cols + 1) * gap, rows * cell + (rows + 1) * gap
    canvas = bytearray([28]) * (W * H * 3)
    k = max(2, cell // 100)
    fit = max(1, (cell - 6) // (4 * k))  # characters that fit across a cell
    for idx, path in enumerate(paths):
        w, h, s = load(path)
        sc = min(cell / w, cell / h, 1.0)
        tw, th = max(1, round(w * sc)), max(1, round(h * sc))
        ox = gap + (idx % cols) * (cell + gap) + (cell - tw) // 2
        oy = gap + (idx // cols) * (cell + gap) + (cell - th) // 2
        for ty in range(th):
            sy0, sy1 = int(ty / sc), max(int(ty / sc) + 1, int((ty + 1) / sc))
            ys = range(sy0, min(h, sy1), max(1, (sy1 - sy0) // 3))
            for tx in range(tw):
                sx0, sx1 = int(tx / sc), max(int(tx / sc) + 1, int((tx + 1) / sc))
                xs = range(sx0, min(w, sx1), max(1, (sx1 - sx0) // 3))
                acc = [0, 0, 0]
                m = 0
                for yy in ys:
                    for xx in xs:
                        i = (yy * w + xx) * 3
                        acc[0] += s[i]; acc[1] += s[i + 1]; acc[2] += s[i + 2]
                        m += 1
                j = ((oy + ty) * W + ox + tx) * 3
                canvas[j:j + 3] = bytes(v // m for v in acc)
        stem = os.path.splitext(os.path.basename(path))[0]
        if labels[idx] in marked or stem in marked:  # a frame in the gap around the image, so it hides nothing
            t = gap - 2
            for yy in range(max(0, oy - t), min(H, oy + th + t)):
                for xx in range(max(0, ox - t), min(W, ox + tw + t)):
                    if not (ox <= xx < ox + tw and oy <= yy < oy + th):
                        canvas[(yy * W + xx) * 3:(yy * W + xx) * 3 + 3] = b"\xff\xc8\x00"
        text(canvas, W, H, ox + 2, oy + 2, labels[idx][:fit], k)
    save(a.out, W, H, canvas)
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    print(json.dumps({"out": a.out, "size": [W, H], "cells": [[l, p] for l, p in zip(labels, paths)],
                      "marked": [l for l, st in zip(labels, stems) if l in marked or st in marked]}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="sub", required=True)
    p = sub.add_parser("measure", help="clipping, tone, cast, and the colour at points")
    p.add_argument("image")
    p.add_argument("--point", action="append", help="X,Y[,NAME] in 0..1 of this image (repeatable)")
    p.add_argument("--radius", type=int, default=4, help="average a box this many pixels around each point")
    p.set_defaults(fn=measure)
    p = sub.add_parser("grid", help="labelled 0..1 coordinate grid")
    p.add_argument("image"); p.add_argument("out")
    p.add_argument("--step", type=float, default=0.1)
    p.set_defaults(fn=grid)
    p = sub.add_parser("diff", help="where two renders differ")
    p.add_argument("a"); p.add_argument("b"); p.add_argument("out")
    p.add_argument("--threshold", type=int, default=6, help="levels (0..255) a pixel must change by to count")
    p.set_defaults(fn=diff)
    p = sub.add_parser("sheet", help="numbered contact sheet")
    p.add_argument("images", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--cols", type=int, default=4)
    p.add_argument("--cell", type=int, default=360, help="cell size in pixels")
    p.add_argument("--labels", help="comma-separated labels, one per image (default: the file names)")
    p.add_argument("--mark", help="comma-separated labels of the cells to frame, e.g. the picks' ids")
    p.set_defaults(fn=sheet)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
