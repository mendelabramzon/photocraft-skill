#!/usr/bin/env python3
"""QC measurements for a retouched image: the checks a retoucher otherwise makes by eye at 100 % before delivery.

  qc.py diff    BEFORE AFTER OUTDIR [--area AREA] [--origin X Y] [--threshold 1] [--margin 3] [--space srgb|p3]
  qc.py seams   IMAGE MASK OUTDIR [--origin X Y] [--composite] [--tile 32] [--band 8]
  qc.py repeats IMAGE OUTDIR [--before BEFORE | --area AREA] [--origin X Y] [--min-pairs 3]
  qc.py banding IMAGE OUTDIR [--area AREA] [--origin X Y]

diff     what an edit changed, by how much and where; with --area, every change outside the area it was meant for
         (a heal that strayed onto an eye, a curve that should have been masked, a stamp that moved the photo).
seams    the edge of a composite or patch (a donor layer, a Patch, a fill, a pasted product, a new sky): tile by tile
         along MASK's edge, the grain inside against outside (a fill or blurred patch is smoother than its
         surroundings), the tone step across it once the gradient is removed (a lighter block), and the sharpness of
         edges inside against outside (a soft element in a sharp plate).
repeats  clone-stamp repeats: the same texture twice, a near-exact copy of a spot elsewhere, which the eye catches
         as a pattern. Textured keypoints inside the edit are matched against the whole image; matches sharing one
         offset form a repeat. Periodic textures (brick, weave) also repeat around the edit, and are labelled so.
banding  posterisation in smooth gradients (skies, backdrops, vignettes), typically after strong curves in 8 bits:
         levels missing from the histogram of each smooth area, and stair steps of 2+ levels between flat runs.

Images: anything photocraft-cli reads, PNGs of every kind included (plain 8- and 16-bit PNGs are read directly;
palette, interlaced and 1/2/4-bit ones, JPEG, TIFF and PSD are converted by the CLI first). BEFORE and AFTER, or IMAGE
and MASK, must be the same frame: two exports of the same crop, or the original and a render. --origin is where that
frame sits in the photo; every coordinate in and out (AREA, boxes) is in full-image pixels. AREA: an area.json from
grid.py ("skin", "area" or "sky" polygons, "exclude") or a rectangle x0,y0,x1,y1. MASK: grey, white where the image
was replaced (the donor layer's mask, the patched area, a sky's alpha.png); an RGBA PNG's alpha is used when it has
any transparency (a cut-out). Each writes a PNG to OUTDIR to look at, and prints one JSON line.

Size: pixels are held as bytes and masks as bit rows, and seams and banding work in blocks, so memory stays near
10-20 bytes per pixel of the frame; repeats analyses a copy of at most --max-mp megapixels made by the CLI and
re-scores what it finds at full resolution. Pure Python is the limit on time (see references/qc.md).
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
import zlib
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import compare
import imgops
import pc
import pngio

TMP = tempfile.mkdtemp(prefix="qc-")
atexit.register(shutil.rmtree, TMP, True)
TO01 = bytes.maketrans(b"\x00\x01", b"01")
FROM01 = bytes.maketrans(b"01", b"\x00\x01")


# ---------------------------------------------------------------- loading: bytes, not float lists

def cli_path():
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: this file needs photocraft-cli to read it (pc.py cli-info)")
    return str(cli)


def cli_png(src, cmds=()):
    """src through photocraft-cli (optionally a few commands) into a plain 8-bit PNG; its path."""
    out = os.path.join(TMP, f"{len(os.listdir(TMP))}.png")
    args = [cli_path(), "run", src]
    for c, p in cmds:
        args += ["--cmd", c, "--params", json.dumps(p)]
    r = subprocess.run(args + ["--out", out], capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        sys.exit(f"error: cannot read {src}: {(r.stderr or r.stdout).strip()[:300]}")
    return out


def image_size(path):
    """(w, h) without decoding: a PNG's header, else photocraft-cli info."""
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p):
        sys.exit(f"error: {path}: no such file")
    with open(p, "rb") as f:
        head = f.read(24)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", head[16:24])
    r = subprocess.run([cli_path(), "info", p, "--compact"], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"error: cannot read {path}: {r.stderr.strip()[:300]}")
    d = json.loads(r.stdout)
    return d["width"], d["height"]


def load(path, cmds=()):
    """(w, h, R, G, B, A): one bytes object per channel (A None without alpha). A plain PNG is decoded directly; any
    other file, or a PNG pngio can't read (palette, interlaced, 1/2/4-bit), goes through photocraft-cli first. cmds
    (a crop, a resize) also run in the CLI first, so a big photo is never decoded whole when only part is needed."""
    p = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(p):
        sys.exit(f"error: {path}: no such file")
    dec = None
    if p.lower().endswith(".png") and not cmds:
        try:
            dec = pngio._decode(p)
        except (AssertionError, ValueError, struct.error):
            dec = None
    if dec is None:
        dec = pngio._decode(cli_png(p, cmds))
    w, h, nch, s = dec
    if nch >= 3:
        R, G, B = bytes(s[0::nch]), bytes(s[1::nch]), bytes(s[2::nch])
        A = bytes(s[3::nch]) if nch == 4 else None
    else:
        R = G = B = bytes(s[0::nch])
        A = bytes(s[1::nch]) if nch == 2 else None
    return w, h, R, G, B, A


def lum_rows(R, G, B, w, x0, y0, x1, y1):
    """Luminance (PhotoCraft's 0.3/0.59/0.11) of a rectangle as a flat float list."""
    out = []
    for y in range(y0, y1):
        a, b = y * w + x0, y * w + x1
        out.extend(0.3 * r + 0.59 * g + 0.11 * bb for r, g, bb in zip(R[a:b], G[a:b], B[a:b]))
    return out


def window(ch, w, x0, y0, x1, y1, scale=1.0):
    """A rectangle of one byte channel as a flat float list (x scale)."""
    out = []
    for y in range(y0, y1):
        out.extend(v * scale for v in ch[y * w + x0:y * w + x1])
    return out


# ---------------------------------------------------------------- masks as bit rows (fast dilation and counting)

def to_bits(m, w, h):
    """A 0/1 byte mask as one int per row; x = 0 is the most significant of w bits."""
    return [int(bytes(m[y * w:(y + 1) * w]).translate(TO01), 2) for y in range(h)]


def from_bits(rows, w):
    return bytearray(b"".join(format(v, f"0{w}b").encode() for v in rows).translate(FROM01))


def dilate(rows, w, r):
    """Bit rows grown by r px (chessboard: a square of 2r + 1)."""
    if r <= 0:
        return rows[:]
    full = (1 << w) - 1
    hor = []
    for v in rows:
        u = v
        for s in range(1, r + 1):
            u |= (v << s) | (v >> s)
        hor.append(u & full)
    out, n = [], len(hor)
    for y in range(n):
        u = 0
        for yy in range(max(0, y - r), min(n, y + r + 1)):
            u |= hor[yy]
        out.append(u)
    return out


def seg(v, w, x0, x1):
    """The bits of one row for x0 <= x < x1, as an int whose lowest bit is x1 - 1."""
    return (v >> (w - x1)) & ((1 << (x1 - x0)) - 1)


def raster(spec, ox, oy, w, h):
    """An AREA (area.json or x0,y0,x1,y1, full-image coordinates) as a 0/1 byte mask of the frame at (ox, oy).
    Polygons fill like imgops.raster; exclusion boxes may be floats (rounded)."""
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        polys = (cfg.get("skin") or cfg.get("area") or cfg.get("sky")) if isinstance(cfg, dict) else None
        if not polys:
            sys.exit(f"error: {spec} has no 'skin', 'area' or 'sky' polygon")
        excl = cfg.get("exclude", [])
    else:
        try:
            x0, y0, x1, y1 = (float(v) for v in spec.split(","))
        except ValueError:
            sys.exit(f"error: AREA {spec!r} is neither a file nor x0,y0,x1,y1")
        polys, excl = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], []
    polys = polys if isinstance(polys[0][0], (list, tuple)) else [polys]
    m = bytearray(w * h)

    def fill(pts, val):
        n = len(pts)
        ys = [p[1] for p in pts]
        for y in range(max(0, math.floor(min(ys) - oy)), min(h - 1, math.ceil(max(ys) - oy)) + 1):
            Y = y + oy
            xs = []
            for i in range(n):
                (xa, ya), (xb, yb) = pts[i], pts[(i + 1) % n]
                if (ya > Y) != (yb > Y):
                    xs.append(xa + (Y - ya) * (xb - xa) / (yb - ya))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                a = max(0, math.ceil(xs[k] - ox)); b = min(w - 1, math.floor(xs[k + 1] - ox))
                if b >= a:
                    m[y * w + a:y * w + b + 1] = bytes([val]) * (b - a + 1)
    for pts in polys:
        fill(pts, 1)
    for e in excl:
        if isinstance(e[0], (list, tuple)):
            fill(e, 0)
        else:
            x0, y0, x1, y1 = (int(round(v)) for v in e)
            for y in range(max(0, y0 - oy), min(h, y1 - oy + 1)):
                a, b = max(0, x0 - ox), min(w, x1 - ox + 1)
                if b > a:
                    m[y * w + a:y * w + b] = bytes(b - a)
    return m


def scaled_area(spec, sx, sy):
    """An AREA as an area.json for a copy sx, sy times smaller (polygons and boxes scaled): its path."""
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        polys = cfg.get("skin") or cfg.get("area") or cfg.get("sky")
        excl = cfg.get("exclude", [])
    else:
        x0, y0, x1, y1 = (float(v) for v in spec.split(","))
        polys, excl = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], []
    polys = polys if isinstance(polys[0][0], (list, tuple)) else [polys]
    sc = lambda pts: [[x / sx, y / sy] for x, y in pts]
    out = os.path.join(TMP, f"{len(os.listdir(TMP))}_area.json")
    json.dump({"skin": [sc(q) for q in polys],
               "exclude": [sc(e) if isinstance(e[0], (list, tuple)) else [e[0] / sx, e[1] / sy, e[2] / sx, e[3] / sy]
                           for e in excl]}, open(out, "w"))
    return out


def area_outline(spec):
    """The AREA's polygons (full-image coordinates), for drawing."""
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        polys = cfg.get("skin") or cfg.get("area") or cfg.get("sky")
        return polys if isinstance(polys[0][0], (list, tuple)) else [polys]
    x0, y0, x1, y1 = (float(v) for v in spec.split(","))
    return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]]


def places(rows, w, h, merge, ox, oy, d=None, min_pixels=1, top=None):
    """Where a bit-row mask is set: components on a coarse grid (pixels within `merge` px count as one place), each
    reported with the exact box and count of its own pixels: [x, y, w, h, pixels(, largest d)]."""
    k = max(1, round(math.sqrt(w * h / 250000)))
    gw, gh = (w + k - 1) // k, (h + k - 1) // k
    grid = bytearray(gw * gh)
    for gy in range(gh):
        u = 0
        for y in range(gy * k, min(h, gy * k + k)):
            u |= rows[y]
        if u:
            for gx in range(gw):
                if seg(u, w, gx * k, min(w, gx * k + k)):
                    grid[gy * gw + gx] = 1
    g = max(0, math.ceil(merge / k))
    if g:
        grid = from_bits(dilate(to_bits(grid, gw, gh), gw, g), gw)
    out = []
    for c in imgops.components(grid, gw, gh):
        x_lo = y_lo = 1 << 30
        x_hi = y_hi = -1
        n = dmax = 0
        for j in c:
            gx, gy = j % gw, j // gw
            xa, xb = gx * k, min(w, gx * k + k)
            for y in range(gy * k, min(h, gy * k + k)):
                s = seg(rows[y], w, xa, xb)
                if not s:
                    continue
                n += bin(s).count("1")
                lx, rx = xb - s.bit_length(), xb - (s & -s).bit_length()
                x_lo, x_hi, y_lo, y_hi = min(x_lo, lx), max(x_hi, rx), min(y_lo, y), max(y_hi, y)
                if d is not None:
                    while s:  # the largest change on this mask's own pixels
                        low = s & -s
                        dmax = max(dmax, d[y * w + xb - low.bit_length()])
                        s ^= low
        if n >= min_pixels:
            out.append([x_lo + ox, y_lo + oy, x_hi - x_lo + 1, y_hi - y_lo + 1, n] + ([dmax] if d is not None else []))
    out.sort(key=lambda b: -b[4])
    return out[:top] if top else out


# ---------------------------------------------------------------- distances, statistics

def inner_distance(region, w, h, cap):
    """For pixels of the region: chessboard distance to the nearest pixel outside it (1 = touching), capped; else 0."""
    d = [0] * (w * h)
    front = []
    for i in range(w * h):
        if region[i]:
            x, y = i % w, i // w
            for yy in (y - 1, y, y + 1):
                if 0 <= yy < h:
                    for xx in (x - 1, x, x + 1):
                        if 0 <= xx < w and not region[yy * w + xx]:
                            break
                    else:
                        continue
                    break
            else:
                continue
            d[i] = 1
            front.append(i)
    k = 1
    while front and k < cap:
        k += 1
        nxt = []
        for i in front:
            x, y = i % w, i // w
            for yy in (y - 1, y, y + 1):
                if 0 <= yy < h:
                    for xx in (x - 1, x, x + 1):
                        j = yy * w + xx
                        if 0 <= xx < w and region[j] and not d[j]:
                            d[j] = k
                            nxt.append(j)
        front = nxt
    return [v if v or not region[i] else cap for i, v in enumerate(d)]


def robust_sigma(vals):
    """1.4826 x the median absolute value: the standard deviation of zero-mean noise, unmoved by a few outliers."""
    if not vals:
        return 0.0
    s = sorted(abs(v) for v in vals)
    return 1.4826 * s[len(s) // 2]


# ---------------------------------------------------------------- pictures

def thumb(R, G, B, w, h, max_side, dim=None):
    """A copy about max_side px across, one sample per block, as rows of (r, g, b): (rows, k). dim fades it to
    grey (0..1) so marks stand out."""
    k = max(1, math.ceil(max(w, h) / max_side))
    rows = []
    for Y in range(h // k):
        row = []
        base = (Y * k + k // 2) * w + k // 2
        for X in range(w // k):
            i = base + X * k
            r, g, b = R[i], G[i], B[i]
            if dim:
                l = 0.3 * r + 0.59 * g + 0.11 * b
                r, g, b = (dim * (0.55 * l + 60) + (1 - dim) * v for v in (r, g, b))
            row.append((int(r + .5), int(g + .5), int(b + .5)))
        rows.append(row)
    return rows or [[(255, 255, 255)]], k


def rect(img, x0, y0, x1, y1, c, t=1):
    h, w = len(img), len(img[0])
    for k in range(t):
        for x in range(max(0, x0 - k), min(w, x1 + k + 1)):
            for y in (y0 - k, y1 + k):
                if 0 <= y < h:
                    img[y][x] = c
        for y in range(max(0, y0 - k), min(h, y1 + k + 1)):
            for x in (x0 - k, x1 + k):
                if 0 <= x < w:
                    img[y][x] = c


def line(img, x0, y0, x1, y1, c):
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    for s in range(n + 1):
        x, y = int(round(x0 + (x1 - x0) * s / n)), int(round(y0 + (y1 - y0) * s / n))
        if 0 <= y < len(img) and 0 <= x < len(img[0]):
            img[y][x] = c


def tile(R, G, B, w, h, cx, cy, size, zoom):
    """A size x size crop around (cx, cy), zoom x, as rows of (r, g, b); outside the frame is white."""
    out = []
    for y in range(size * zoom):
        yy = cy - size // 2 + y // zoom
        row = []
        for x in range(size * zoom):
            xx = cx - size // 2 + x // zoom
            if 0 <= xx < w and 0 <= yy < h:
                i = yy * w + xx
                row.append((R[i], G[i], B[i]))
            else:
                row.append((255, 255, 255))
        out.append(row)
    return out


def paste(img, part, x0, y0):
    for y, row in enumerate(part):
        if 0 <= y0 + y < len(img):
            dst = img[y0 + y]
            for x, p in enumerate(row):
                if 0 <= x0 + x < len(dst):
                    dst[x0 + x] = p


def stack(top, parts, gap=8):
    """`top` (rows of tuples), then the parts (lists of rows) side by side, wrapping at the sheet's width."""
    W = max(len(top[0]), 2 * max((len(p[0]) for p in parts), default=0) + gap)
    rows, cur, cw = [], [], 0
    for p in parts:
        if cur and cw + gap + len(p[0]) > W:
            rows.append(cur)
            cur, cw = [], 0
        cur.append(p)
        cw += (gap if cw else 0) + len(p[0])
    if cur:
        rows.append(cur)
    H = len(top) + sum(gap + max(len(p) for p in r) for r in rows)
    img = [[(255, 255, 255)] * W for _ in range(H)]
    paste(img, top, 0, 0)
    y = len(top)
    for r in rows:
        y += gap
        x = 0
        for p in r:
            paste(img, p, x, y)
            x += len(p[0]) + gap
        y += max(len(p) for p in r)
    return img


def save(path, img):
    pngio.write(path, len(img[0]), len(img), img)


def save_grey(path, w, h, rows_of_bytes):
    """Rows of w grey bytes (a generator is fine) as an 8-bit grey PNG."""
    raw = bytearray()
    for r in rows_of_bytes:
        raw += b"\x00" + bytes(r)
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def erode(rows, w, r):
    full = (1 << w) - 1
    return [full & ~v for v in dilate([full & ~v for v in rows], w, r)]


def save_mask(path, rows, w, h):
    """Bit rows as a full-frame 8-bit grey PNG, 255 where set: a MASK that seams (or any layer mask import) reads."""
    raw = bytearray()
    for v in rows:
        raw += b"\x00" + format(v, f"0{w}b").encode().translate(bytes.maketrans(b"01", b"\x00\xff"))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- diff

def cmd_diff(a):
    w, h, R0, G0, B0, _ = load(a.before)
    w2, h2, R1, G1, B1, _ = load(a.after)
    if (w, h) != (w2, h2):
        sys.exit(f"error: BEFORE is {w}x{h} but AFTER is {w2}x{h2}; compare the same frame")
    os.makedirs(a.outdir, exist_ok=True)
    ox, oy = a.origin
    N = w * h
    # the largest channel difference per pixel, one byte each
    d = bytes(max(abs(r1 - r0), abs(g1 - g0), abs(b1 - b0)) for r0, g0, b0, r1, g1, b1 in zip(R0, G0, B0, R1, G1, B1))
    changed = d.translate(bytes(1 if v > a.threshold else 0 for v in range(256)))
    n_changed = changed.count(1)
    rows = to_bits(changed, w, h)
    out = {"size": [w, h], "threshold": a.threshold, "changedPixels": n_changed, "changed%": round(100 * n_changed / N, 3)}
    outside = None
    if a.area or a.allowed_mask:
        # where changes may happen: the AREA, and/or a grey mask PNG of the same frame (white = allowed: a layer mask
        # exported, skin_masks' area, a selection saved as a PNG), grown by --margin
        allowed = [0] * h
        if a.area:
            allowed = to_bits(raster(a.area, ox, oy, w, h), w, h)
        if a.allowed_mask:
            mw, mh, mr, _, _, ma = load(a.allowed_mask)
            if (mw, mh) != (w, h):
                sys.exit(f"error: --allowed-mask is {mw}x{mh} but the images are {w}x{h}; use the same frame")
            mk = to_bits(mask_channel(mw, mh, mr, ma).translate(bytes(1 if v >= 128 else 0 for v in range(256))), w, h)
            allowed = [u | v for u, v in zip(allowed, mk)]
        allowed = dilate(allowed, w, a.margin)
        full = (1 << w) - 1
        outside = [c & ~al & full for c, al in zip(rows, allowed)]
    if n_changed:
        ys = [y for y in range(h) if rows[y]]
        u = 0
        for y in ys:
            u |= rows[y]
        x_lo, x_hi = w - u.bit_length(), w - (u & -u).bit_length()
        out["bbox"] = [x_lo + ox, ys[0] + oy, x_hi - x_lo + 1, ys[-1] - ys[0] + 1]
        hist = [d.count(v) if v > a.threshold else 0 for v in range(256)]
        acc, q50, q95 = 0, None, None
        for v in range(256):
            acc += hist[v]
            if q50 is None and acc >= n_changed / 2:
                q50 = v
            if q95 is None and acc >= 0.95 * n_changed:
                q95 = v
        vmax = max(v for v in range(256) if hist[v])
        out["change"] = {"median": q50, "p95": q95, "max": vmax}
        i = d.find(bytes([vmax]))
        out["largestAt"] = [i % w + ox, i // w + oy]
        # colour of the change: signed mean dL*, da*, db* (after - before) over up to ~150k changed pixels
        step = max(1, math.ceil(math.sqrt(n_changed / 150000)))
        dl, n = [0.0, 0.0, 0.0], 0
        for y in ys[::step]:
            v = rows[y]
            while v:
                low = v & -v
                x = w - low.bit_length()
                v ^= low
                if x % step:
                    continue
                j = y * w + x
                l0, l1 = imgops.lab(R0[j], G0[j], B0[j], a.space), imgops.lab(R1[j], G1[j], B1[j], a.space)
                for c in range(3):
                    dl[c] += l1[c] - l0[c]
                n += 1
        if n:
            out["meanDeltaLab"] = [round(v / n, 2) for v in dl]
        # where: dabs a few px apart count as one place; each box is its own pixels' extent
        out["places"] = places(rows, w, h, 4, ox, oy, top=8)
    # what was replaced, as a full-frame mask for `qc.py seams AFTER changed.png OUT` after clone, Patch or heal work,
    # which leaves no mask of its own: the changed pixels with gaps of a few px closed, grown --grow px, and graded
    # across the rim the way a soft brush blended it, from 0 at that grown edge to 255 where the change reaches
    # its core level. With a hard edge there instead, seams would compare two halves of the blend and miss a lighter
    # patch whose rim fades (measured: a clone from a lighter row, flagged only with the graded rim)
    foot = dilate(erode(dilate(rows, w, 3), w, 3), w, a.grow)
    fy = [y for y in range(h) if foot[y]]
    grade, rim = None, None
    if fy:
        u = 0
        for y in fy:
            u |= foot[y]
        gx0, gx1 = max(0, w - u.bit_length() - 1), min(w, w - (u & -u).bit_length() + 2)
        gy0, gy1 = max(0, fy[0] - 1), min(h, fy[-1] + 2)
        gw, gh = gx1 - gx0, gy1 - gy0
        fm = bytearray(1 if seg(foot[y], w, x, x + 1) else 0 for y in range(gy0, gy1) for x in range(gx0, gx1)) \
            if gw * gh <= 4e6 else None
        if fm is not None:
            dist = inner_distance(fm, gw, gh, 16)
            prof = {}
            for j, dv in enumerate(dist):
                if dv:
                    prof.setdefault(dv, []).append(d[(gy0 + j // gw) * w + gx0 + j % gw])
            med_at = {k_: sorted(v)[len(v) // 2] for k_, v in prof.items()}
            deep = sorted(v for k_, vs in prof.items() if k_ >= 6 for v in vs)
            core = deep[len(deep) // 2] if deep else max(med_at.values())
            rim = next((k_ for k_ in sorted(med_at) if med_at[k_] >= 0.8 * core), 1)
            rim = max(1, min(12, rim))
            grade = (gx0, gy0, gw, gh, bytes(0 if not dv else min(255, round(255 * dv / rim)) for dv in dist))

    def mask_rows():
        for y in range(h):
            if grade and grade[1] <= y < grade[1] + grade[3]:
                gx0_, gy0_, gw_, _, gb = grade
                row = bytearray(w)
                row[gx0_:gx0_ + gw_] = gb[(y - gy0_) * gw_:(y - gy0_ + 1) * gw_]
                yield row
            else:
                yield format(foot[y], f"0{w}b").encode().translate(bytes.maketrans(b"01", b"\x00\xff"))
    save_grey(os.path.join(a.outdir, "changed.png"), w, h, mask_rows())
    out["changedMask"] = os.path.join(a.outdir, "changed.png")
    if rim:
        out["changedRim"] = rim
    if outside is not None:
        n_out = sum(bin(v).count("1") for v in outside)
        boxes = places(outside, w, h, 4, ox, oy, d=d, min_pixels=a.min_pixels, top=12) if n_out else []
        out["outsideArea"] = {"pixels": n_out, "shareOfChange": round(n_out / max(1, n_changed), 4),
                              "boxes": boxes, "margin": a.margin}
        out["verdict"] = ("nothing changed outside the area" if not boxes else
                          f"{sum(b[4] for b in boxes)} px changed outside the area in {len(boxes)} place(s): look at them")
    # picture: the after image faded to grey; change yellow (small) to red (24+ levels), outside the area magenta
    img, k = thumb(R1, G1, B1, w, h, 1200, dim=0.85)
    th, tw = len(img), len(img[0])
    for Y in range(th):
        u = uo = 0
        for y in range(Y * k, min(h, Y * k + k)):
            u |= rows[y]
            if outside is not None:
                uo |= outside[y]
        if not u:
            continue
        for X in range(tw):
            xa, xb = X * k, min(w, X * k + k)
            if not seg(u, w, xa, xb):
                continue
            if uo and seg(uo, w, xa, xb):
                img[Y][X] = (255, 0, 220)
                continue
            m = max(max(d[y * w + xa:y * w + xb]) for y in range(Y * k, min(h, Y * k + k)))
            t = min(1.0, m / 24)
            img[Y][X] = (255, int(230 * (1 - t)), 0)
    if a.area:
        for poly in area_outline(a.area):
            for j in range(len(poly)):
                (x0, y0), (x1, y1) = poly[j], poly[(j + 1) % len(poly)]
                line(img, (x0 - ox) / k, (y0 - oy) / k, (x1 - ox) / k, (y1 - oy) / k, (0, 220, 255))
    save(os.path.join(a.outdir, "diff.png"), img)
    out["picture"] = os.path.join(a.outdir, "diff.png")
    # diff.png is at most 1200 px across: one picture pixel per k x k block (frame x = picture x * k + origin x)
    out["pictureScale"] = round(1 / k, 4)
    print(json.dumps(out))


# ---------------------------------------------------------------- seams

def mask_channel(w, h, R, A):
    """The mask's values 0..255: an RGBA cut-out's alpha when it has any transparency, else the grey (red) channel."""
    if A is not None and A.count(255) < len(A):
        return A
    return R


def normal_at(M, w, h, x, y):
    """The direction alpha rises fastest at (x, y), from 3 x 3 means two px either side: (nx, ny) or None."""
    def mean3(cx, cy):
        cx, cy = min(w - 1, max(0, cx)), min(h - 1, max(0, cy))
        s = n = 0
        for yy in range(max(0, cy - 1), min(h, cy + 2)):
            row = yy * w
            for xx in range(max(0, cx - 1), min(w, cx + 2)):
                s += M[row + xx]
                n += 1
        return s / n
    gx, gy = mean3(x + 2, y) - mean3(x - 2, y), mean3(x, y + 2) - mean3(x, y - 2)
    n = math.hypot(gx, gy)
    return (gx / n, gy / n) if n > 1e-6 else None


def feather_width(M, w, h, contour, reach=400):
    """Across the mask's edge, the distance from the last fully original pixel (<= 0.02) to the first fully replaced
    one (>= 0.98), at up to 400 points: (median, 90th percentile) in px, or None."""
    at = lambda x, y: M[min(h - 1, max(0, int(y + 0.5))) * w + min(w - 1, max(0, int(x + 0.5)))]
    widths = []
    for i in contour[::max(1, len(contour) // 400)]:
        x, y = i % w, i // w
        nv = normal_at(M, w, h, x, y)
        if nv is None:
            continue
        nx, ny = nv
        t_in = next((t for t in range(1, reach) if at(x + t * nx, y + t * ny) >= 250), None)
        t_out = next((t for t in range(1, reach) if at(x - t * nx, y - t * ny) <= 5), None)
        if t_in is not None and t_out is not None:
            widths.append(t_in + t_out)
    if not widths:
        return None
    widths.sort()
    return widths[len(widths) // 2], widths[int(0.9 * (len(widths) - 1))]


def across(A, Ls, w, h, edge_pts, reach):
    """For each edge point, along the mask's normal: the smoothed luminance just inside minus just outside, from the
    first fully replaced (alpha >= 0.98) and fully original (<= 0.02) pixel 2 px on, and the same span measured
    again entirely on one side (the control: how much the photo itself changes over that distance in that
    direction). A patch too narrow for the inside control uses the outside one alone, and the other way round.
    {point: (seam difference, inside control, outside control)}."""
    As = imgops.gauss(A, w, h, 2.0)
    at = lambda arr, x, y: arr[min(h - 1, max(0, int(y + 0.5))) * w + min(w - 1, max(0, int(x + 0.5)))]
    inside = lambda x, y: 0 <= x < w and 0 <= y < h
    out = {}
    for i in edge_pts:
        x, y = i % w, i // w
        if not (0 < x < w - 1 and 0 < y < h - 1):
            continue
        gx, gy = As[i + 1] - As[i - 1], As[i + w] - As[i - w]
        n = math.hypot(gx, gy)
        if n < 1e-6:
            continue
        nx, ny = gx / n, gy / n  # toward the replaced side
        t_in = next((t for t in range(1, reach) if at(A, x + t * nx, y + t * ny) >= 0.98), None)
        t_out = next((t for t in range(1, reach) if at(A, x - t * nx, y - t * ny) <= 0.02), None)
        if t_in is None or t_out is None:
            continue
        L = lambda t: sum(at(Ls, x + (t + k) * nx, y + (t + k) * ny) for k in (-1, 0, 1)) / 3  # t > 0: inside
        a_in, a_out = t_in + 2, -(t_out + 2)
        if at(A, x + (a_in + 1) * nx, y + (a_in + 1) * ny) < 0.98 or at(A, x + (a_out - 1) * nx, y + (a_out - 1) * ny) > 0.02:
            continue  # the replaced part (or the original one) is thinner than the sample itself here
        span = a_in - a_out
        far_in, far_out = a_in + span + 1, a_out - span - 1
        ci = (L(a_in + span) - L(a_in) if inside(x + far_in * nx, y + far_in * ny)
              and at(A, x + far_in * nx, y + far_in * ny) >= 0.98 else None)
        co = (L(a_out) - L(a_out - span) if inside(x + far_out * nx, y + far_out * ny)
              and at(A, x + far_out * nx, y + far_out * ny) <= 0.02 else None)
        if ci is None and co is None:
            continue
        out[i] = (L(a_in) - L(a_out), co if ci is None else ci, ci if co is None else co)
    return out


def block_grain(R, G, B, w, M, lo, hi, x0, y0, x1, y1, stride=1):
    """imgops.grain_floor's statistic, read from bytes: for every 8 x 8 block on the grid (x0 + 1 + 8i, y0 + 1 + 8j)
    inside (x0, y0, x1, y1) whose pixels all have mask values in lo..hi, 1.4826 x the median |L - 3x3 mean|; blocks
    whose mean is under 10 or over 245 are skipped. stride samples every n-th block each way on big regions."""
    vals = []
    for by in range(y0 + 1, y1 - 9, 8 * stride):
        for bx in range(x0 + 1, x1 - 9, 8 * stride):
            if any(not lo <= v <= hi for yy in range(by, by + 8) for v in M[yy * w + bx:yy * w + bx + 8]):
                continue
            L = lum_rows(R, G, B, w, bx - 1, by - 1, bx + 9, by + 9)  # 10 x 10 with the 1 px ring
            mu = sum(L[(yy + 1) * 10 + xx + 1] for yy in range(8) for xx in range(8)) / 64
            if mu < 10 or mu > 245:
                continue
            dev = sorted(abs(L[j] - sum(L[j + dy * 10 + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9)
                         for j in ((yy + 1) * 10 + xx + 1 for yy in range(8) for xx in range(8)))
            vals.append(1.4826 * dev[32])
    return vals


def solve3(M, v):
    """3 x 3 linear system (Gaussian elimination); None if singular."""
    A = [M[r][:] + [v[r]] for r in range(3)]
    for c in range(3):
        piv = max(range(c, 3), key=lambda r: abs(A[r][c]))
        if abs(A[piv][c]) < 1e-9:
            return None
        A[c], A[piv] = A[piv], A[c]
        for r in range(3):
            if r != c:
                f = A[r][c] / A[c][c]
                for k in range(c, 4):
                    A[r][k] -= f * A[c][k]
    return [A[r][3] / A[r][r] for r in range(3)]


def strand_seams(a, w, h, R, G, B, M, ox, oy):
    """A thin mask (strands 1-3 px wide: a flyaway fill) has no fully replaced band to compare, so each strand is
    judged against the original pixels 3-8 px from it, tile by tile: a plane fitted to those takes out the gradient,
    then the strands' median offset from it is a lighter or darker ghost line where a strand was, and their grain
    against the ring's is a smooth line drawn through grainy backdrop. Returns (summary, tiles, worst)."""
    tab = lambda f: bytes(1 if f(v) else 0 for v in range(256))
    inside = to_bits(M.translate(tab(lambda v: v >= 128)), w, h)
    core = to_bits(M.translate(tab(lambda v: v >= 230)), w, h)
    zero = to_bits(M.translate(tab(lambda v: v <= 5)), w, h)
    full = (1 << w) - 1
    ring = [f & ~n & z & full for f, n, z in zip(dilate(inside, w, 8), dilate(inside, w, 2), zero)]
    ys = [y for y in range(h) if core[y]]
    if not ys:
        sys.exit("error: MASK has no fully replaced pixels (none at 0.9 or more)")
    u = 0
    for y in ys:
        u |= core[y]
    wx0, wx1 = max(0, w - u.bit_length() - 12), min(w, w - (u & -u).bit_length() + 13)
    wy0, wy1 = max(0, ys[0] - 12), min(h, ys[-1] + 13)
    ww, wh = wx1 - wx0, wy1 - wy0
    L = lum_rows(R, G, B, w, wx0, wy0, wx1, wy1)
    hp = [l - m for l, m in zip(L, imgops.box(L, ww, wh, 1))]

    def pix(rows, x0, x1, y0, y1):
        out = []
        for y in range(y0, y1):
            s = seg(rows[y], w, x0, x1)
            while s:
                low = s & -s
                out.append((y - wy0) * ww + x1 - low.bit_length() - wx0)
                s ^= low
        return out
    T = a.tile
    tiles = []
    for ty in range(wy0, wy1, T):
        for tx in range(wx0, wx1, T):
            x1, y1 = min(wx1, tx + T), min(wy1, ty + T)
            pc, pr = pix(core, tx, x1, ty, y1), pix(ring, tx, x1, ty, y1)
            if len(pc) < a.strand_pixels or len(pr) < 40:
                continue
            Mx = [[0.0] * 3 for _ in range(3)]
            vv = [0.0, 0.0, 0.0]
            for i in pr:
                f = (1.0, i % ww - (tx - wx0), i // ww - (ty - wy0))
                for r in range(3):
                    vv[r] += f[r] * L[i]
                    for c in range(3):
                        Mx[r][c] += f[r] * f[c]
            pl = solve3(Mx, vv)
            if pl is None:
                continue
            res = lambda i: L[i] - (pl[0] + pl[1] * (i % ww - (tx - wx0)) + pl[2] * (i // ww - (ty - wy0)))
            rc, rr = sorted(res(i) for i in pc), sorted(res(i) for i in pr)
            mr = rr[len(rr) // 2]
            s = rc[len(rc) // 2] - mr
            spread = robust_sigma([v - mr for v in rr])
            g_in, g_out = robust_sigma([hp[i] for i in pc]), robust_sigma([hp[i] for i in pr])
            gr = g_in / max(g_out, 0.3)
            flags = []
            if abs(s) > a.step and abs(s) > a.consistency * spread:
                flags.append("lighter" if s > 0 else "darker")
            if gr < a.smooth:
                flags.append("smoother")
            elif gr > a.noisy and not flags:  # (a step across a 1-3 px strand fills its 3x3 residual too)
                flags.append("noisier")
            tiles.append({"at": [tx + ox, ty + oy, x1 - tx, y1 - ty], "strandPixels": len(pc),
                          "grainRatio": round(gr, 2), "grain": [round(g_in, 2), round(g_out, 2)],
                          "step": round(s, 2), "stepSpread": round(spread, 2), "flags": flags})
    if not tiles:
        sys.exit(f"error: the mask's strands are too few to judge (under {a.strand_pixels} fully replaced px in every "
                 "tile, or no original pixels beside them); look at them at 3x with compare.py --check local,solar")
    counts = {}
    for t in tiles:
        for f in t["flags"]:
            counts[f] = counts.get(f, 0) + 1
    enough = max(1, math.ceil(0.34 * len(tiles)))
    advice = []
    if counts.get("smoother", 0) >= enough:
        advice.append("the filled strands are smoother than the backdrop beside them: smooth lines show where hairs were "
                      "at 100 %; the fill needs the backdrop's grain")
    if counts.get("noisier", 0) >= enough:
        advice.append("the filled strands are noisier than the backdrop beside them: less grain in the fill")
    if max(counts.get("lighter", 0), counts.get("darker", 0)) >= enough:
        tone = "lighter" if counts.get("lighter", 0) >= counts.get("darker", 0) else "darker"
        advice.append(f"{tone} lines where the strands were: the fill doesn't match the backdrop's tone there (a strand "
                      "left in, or a fill from the wrong level); look at the zooms")
    med = lambda v: sorted(v)[len(v) // 2] if v else None
    worst = sorted([t for t in tiles if t["flags"]], key=lambda t: (-len(t["flags"]), -abs(t["step"])))[:a.spots]
    summary = {"kind": "strands", "tiles": len(tiles), "tile": T, "flagged": sum(1 for t in tiles if t["flags"]),
               "flagged%": round(100 * sum(1 for t in tiles if t["flags"]) / len(tiles), 1),
               "grainRatio": round(med([t["grainRatio"] for t in tiles]), 2),
               "step": round(med([abs(t["step"]) for t in tiles]), 2), "flags": counts, "advice": advice,
               "note": "a thin mask: each strand against the original pixels 3-8 px from it"}
    return summary, tiles, worst


def finish_strands(a, w, h, R, G, B, M, ox, oy, edge_rows, ys, crop):
    summary, tiles, worst = strand_seams(a, w, h, R, G, B, M, ox, oy)
    if crop:
        summary["readAround"] = [crop[0] + a.origin[0], crop[1] + a.origin[1], crop[2], crop[3]]
    img, k = thumb(R, G, B, w, h, 1000, dim=0.4)
    for y in ys[::max(1, k)]:
        v = edge_rows[y]
        while v:
            low = v & -v
            x = w - low.bit_length()
            v ^= low
            if y // k < len(img) and x // k < len(img[0]):
                img[y // k][x // k] = (255, 230, 0)
    for t in tiles:
        x0, y0, tw, th = t["at"]
        col = (0, 200, 80) if not t["flags"] else (255, 140, 0) if len(t["flags"]) == 1 else (230, 0, 0)
        rect(img, (x0 - ox) // k, (y0 - oy) // k, (x0 - ox + tw - 1) // k, (y0 - oy + th - 1) // k, col)
    zooms = []
    for n, t in enumerate(worst):
        cx, cy = t["at"][0] - ox + t["at"][2] // 2, t["at"][1] - oy + t["at"][3] // 2
        z = tile(R, G, B, w, h, cx, cy, 64, 3)
        both = [r1 + [(255, 255, 255)] * 4 + r2 for r1, r2 in zip(z, compare.view(z, "local"))]
        compare.text(both, 4, 4, str(n + 1), (255, 220, 0), 3)
        zooms.append(both)
    save(os.path.join(a.outdir, "seams.png"), stack(img, zooms))
    summary["worst"] = [{"n": n + 1, **t} for n, t in enumerate(worst)]
    summary["picture"] = os.path.join(a.outdir, "seams.png")
    json.dump({"summary": summary, "tiles": tiles}, open(os.path.join(a.outdir, "seams.json"), "w"), indent=1)
    print(json.dumps(summary))


def cmd_seams(a):
    W0, H0 = image_size(a.image)
    if image_size(a.mask) != (W0, H0):
        sys.exit(f"error: IMAGE is {W0}x{H0} but MASK is {image_size(a.mask)}; use the same frame")
    os.makedirs(a.outdir, exist_ok=True)
    ox, oy = a.origin
    crop = None
    if W0 * H0 > a.max_mp * 1e6:
        # a big frame: find the edge on a small copy of the mask, then read both only around it, at full size
        k = math.ceil(math.sqrt(W0 * H0 / 2e6))
        sw, sh, mr, _, _, ma = load(a.mask, [("image.imageSize", {"width": W0 // k, "height": H0 // k})])
        sm = mask_channel(sw, sh, mr, ma)
        part = [i for i in range(sw * sh) if 5 < sm[i] < 250]
        if not part:
            sys.exit("error: MASK has no edge between white and black")
        margin = 256 + 2 * k
        x0 = max(0, min(i % sw for i in part) * W0 // sw - margin); x1 = min(W0, (max(i % sw for i in part) + 1) * W0 // sw + margin)
        y0 = max(0, min(i // sw for i in part) * H0 // sh - margin); y1 = min(H0, (max(i // sw for i in part) + 1) * H0 // sh + margin)
        crop = [x0, y0, x1 - x0, y1 - y0]
        cmd = [("image.crop", {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})]
        w, h, R, G, B, _ = load(a.image, cmd)
        _, _, mr, _, _, ma = load(a.mask, cmd)
        ox, oy = ox + x0, oy + y0
    else:
        w, h, R, G, B, _ = load(a.image)
        _, _, mr, _, _, ma = load(a.mask)
    M = mask_channel(w, h, mr, ma)
    if M.translate(bytes(1 if v >= 250 else 0 for v in range(256))).count(1) == 0 or \
            M.translate(bytes(1 if v <= 5 else 0 for v in range(256))).count(1) == 0:
        sys.exit("error: MASK needs both a white (inserted) and a black (original) part")
    # the edge: partly replaced pixels, or a fully replaced pixel touching a fully original one
    sin_rows = to_bits(M.translate(bytes(1 if v >= 250 else 0 for v in range(256))), w, h)
    sout_rows = to_bits(M.translate(bytes(1 if v <= 5 else 0 for v in range(256))), w, h)
    part_rows = to_bits(M.translate(bytes(1 if 5 < v < 250 else 0 for v in range(256))), w, h)
    edge_rows = [p | (s & o) for p, s, o in zip(part_rows, sin_rows, dilate(sout_rows, w, 1))]
    ys = [y for y in range(h) if edge_rows[y]]
    if not ys:
        sys.exit("error: MASK has no edge between white and black")
    u = 0
    for y in ys:
        u |= edge_rows[y]
    ex0, ex1 = w - u.bit_length(), w - (u & -u).bit_length()
    contour = []  # alpha crosses 0.5
    for y in ys:
        v = edge_rows[y]
        while v:
            low = v & -v
            x = w - low.bit_length()
            v ^= low
            i = y * w + x
            if M[i] >= 128 and any(0 <= j < w * h and M[j] < 128 for j in
                                   ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, i - w, i + w)):
                contour.append(i)
    # a thin mask (strands 1-3 px wide, nothing left of it after a 2 px erosion) has no inside band to compare
    full_w = (1 << w) - 1
    if not any(full_w & ~v for v in dilate([full_w & ~v for v in sin_rows], w, 2)):
        return finish_strands(a, w, h, R, G, B, M, ox, oy, edge_rows, ys, crop)
    # the feather sets how far to look for fully replaced and fully original pixels, and how big a tile must be
    fw = feather_width(M, w, h, contour)
    feather = fw[0] if fw else 2
    reach = max(24, (fw[1] if fw else 2) + 8)
    T = max(a.tile, math.ceil(1.5 * feather) + 2 * a.band + 8)
    # tiles start at the edge (less the bands); a patch small enough for one tile is judged as one
    gx0, gy0 = max(0, ex0 - a.band - 3), max(0, ys[0] - a.band - 3)
    gx1, gy1 = min(w, ex1 + a.band + 4), min(h, ys[-1] + a.band + 4)
    if gx1 - gx0 <= T and gy1 - gy0 <= T:
        T = max(gx1 - gx0, gy1 - gy0)
    m = a.band + T + 2 * reach  # the region round the edge whose noise floors a composite compares
    bx0, bx1 = max(0, ex0 - m), min(w, ex1 + m + 1)
    by0, by1 = max(0, ys[0] - m), min(h, ys[-1] + m + 1)
    W, H = bx1 - bx0, by1 - by0
    pad = 2 * reach + a.band + 16
    BT = max(1, 512 // T)  # tiles per block side: the work is done block by block, so memory stays bounded
    tiles, pooled_in, pooled_out, noise_vals = [], [], [], []
    cset = set(contour)
    for cy0 in range(gy0, gy1, T * BT):
        for cx0 in range(gx0, gx1, T * BT):
            cx1, cy1 = min(gx1, cx0 + T * BT), min(gy1, cy0 + T * BT)  # this block's core, frame coordinates
            if not any(seg(edge_rows[y], w, max(0, cx0 - T), min(w, cx1 + T)) for y in range(max(0, cy0 - T), min(h, cy1 + T))):
                continue
            wx0, wy0 = max(0, cx0 - pad), max(0, cy0 - pad)
            wx1, wy1 = min(w, cx1 + pad), min(h, cy1 + pad)
            ww, wh = wx1 - wx0, wy1 - wy0
            L = lum_rows(R, G, B, w, wx0, wy0, wx1, wy1)
            Aw = window(M, w, wx0, wy0, wx1, wy1, 1 / 255)
            full_in = bytearray(1 if v >= 0.98 else 0 for v in Aw)
            full_out = bytearray(1 if v <= 0.02 else 0 for v in Aw)
            din = inner_distance(full_in, ww, wh, a.band + 2)
            dout = inner_distance(full_out, ww, wh, a.band + 2)
            # bands: the nearest fully replaced and fully original pixels, skipping the one touching the other side
            # (its 3x3 grain window straddles the edge)
            band_in = bytearray(1 if 2 <= v <= a.band + 1 else 0 for v in din)
            band_out = bytearray(1 if 2 <= v <= a.band + 1 else 0 for v in dout)
            hp = [l - mm for l, mm in zip(L, imgops.box(L, ww, wh, 1))]  # grain and the finest texture
            Ls = imgops.gauss(L, ww, wh, 1.5)  # for the tone step: grain averaged out
            pts = [(y - wy0) * ww + (x - wx0) for y in range(cy0, cy1) for x in range(cx0, cx1) if y * w + x in cset]
            diffs = across(Aw, Ls, ww, wh, pts, reach)
            # edge sharpness: at real edges (gradient maxima across a step of 12+ levels), the blur that explains the
            # peak gradient, sigma = step / (peak x sqrt(2 pi)), minus the 0.7 px it is measured at. A plate's
            # in-focus edges read about 1 px; an element blurred 1.5 px reads 1.8.
            Le = imgops.gauss(L, ww, wh, 0.7)
            at = lambda arr, x, y: arr[min(wh - 1, max(0, int(y + 0.5))) * ww + min(ww - 1, max(0, int(x + 0.5)))]

            def mag(x, y):
                j = min(wh - 2, max(1, int(y + .5))) * ww + min(ww - 2, max(1, int(x + .5)))
                return math.hypot(Le[j + 1] - Le[j - 1], Le[j + ww] - Le[j - ww]) / 2
            blur = {}
            for yy in range(cy0 - wy0, cy1 - wy0):
                for xx in range(cx0 - wx0, cx1 - wx0):
                    i = yy * ww + xx
                    if not (band_in[i] or band_out[i]) or not (1 <= xx < ww - 1 and 1 <= yy < wh - 1):
                        continue
                    gx, gy = (Le[i + 1] - Le[i - 1]) / 2, (Le[i + ww] - Le[i - ww]) / 2
                    Mg = math.hypot(gx, gy)
                    if Mg < 3:
                        continue
                    nx, ny = gx / Mg, gy / Mg
                    if mag(xx + nx, yy + ny) > Mg or mag(xx - nx, yy - ny) > Mg:
                        continue
                    same = full_in if band_in[i] else full_out
                    if not (at(same, xx + 4 * nx, yy + 4 * ny) and at(same, xx - 4 * nx, yy - 4 * ny)):
                        continue
                    step = abs(at(Le, xx + 4 * nx, yy + 4 * ny) - at(Le, xx - 4 * nx, yy - 4 * ny))
                    if step >= 12:
                        st = step / (Mg * math.sqrt(2 * math.pi))
                        blur[i] = math.sqrt(max(0.0, st * st - 0.49))
                        (pooled_in if band_in[i] else pooled_out).append(blur[i])
            noise_vals += [hp[i] for i in range(0, ww * wh, 3) if band_out[i]][:5000]
            for ty in range(cy0, cy1, T):
                for tx in range(cx0, cx1, T):
                    ii = [(y - wy0) * ww + (x - wx0) for y in range(ty, min(cy1, ty + T)) for x in range(tx, min(cx1, tx + T))]
                    pin = [i for i in ii if band_in[i]]
                    pout = [i for i in ii if band_out[i]]
                    if len(pin) < a.min_pixels or len(pout) < a.min_pixels:
                        continue
                    g_in, g_out = robust_sigma([hp[i] for i in pin]), robust_sigma([hp[i] for i in pout])
                    gr = g_in / max(g_out, 0.3)
                    here = [diffs[i] for i in diffs if tx <= i % ww + wx0 < tx + T and ty <= i // ww + wy0 < ty + T]
                    s = spread = None
                    if len(here) >= 8:
                        # the seam's difference minus what the photo does over the same span on either side (a
                        # gradient, a sky paling toward the horizon), against how much the controls vary (texture)
                        dd = sorted(sd - (ci + co) / 2 for sd, ci, co in here)
                        s = dd[len(dd) // 2]
                        ctrl = sorted([ci for _, ci, _ in here] + [co for _, _, co in here])
                        cm = ctrl[len(ctrl) // 2]
                        spread = robust_sigma([v - cm for v in ctrl])
                    sharp = bi = bo = None
                    ein = sorted(blur[i] for i in pin if i in blur)
                    eout = sorted(blur[i] for i in pout if i in blur)
                    if len(ein) >= 8 and len(eout) >= 8:
                        bi, bo = ein[len(ein) // 2], eout[len(eout) // 2]
                        sharp = (bo + 0.5) / (bi + 0.5)
                    flags = []
                    if a.composite:
                        pass  # grain is judged on the noise floors below
                    elif gr < a.smooth:
                        flags.append("smoother")
                    elif gr > a.noisy:
                        flags.append("noisier")
                    # a seam's step is the same all along the edge; texture's differences change sign point to point
                    if not a.composite and s is not None and abs(s) > a.step and abs(s) > a.consistency * spread:
                        flags.append("lighter" if s > 0 else "darker")
                    if sharp is not None and sharp < a.softer:
                        flags.append("softer")
                    elif sharp is not None and sharp > a.sharper:
                        flags.append("sharper")
                    tiles.append({"at": [tx + ox, ty + oy, min(T, cx1 - tx), min(T, cy1 - ty)],
                                  "grainRatio": round(gr, 2), "grain": [round(g_in, 2), round(g_out, 2)],
                                  "step": round(s, 2) if s is not None else None,
                                  "stepSpread": round(spread, 2) if spread is not None else None,
                                  "sharpRatio": round(sharp, 2) if sharp is not None else None,
                                  "edgeBlur": [round(bi, 2), round(bo, 2)] if sharp is not None else None, "flags": flags})
    if not tiles:  # too thin or too small for bands: judge it as strands
        return finish_strands(a, w, h, R, G, B, M, ox, oy, edge_rows, ys, crop)
    noise = robust_sigma(noise_vals) or 1.0
    # A placed element is another material: its texture (leather, hair, knit) isn't grain, so a composite is judged by
    # noise floors, the quietest 8 x 8 blocks of each side (imgops.grain_floor's statistic), not tile by tile. Measured
    # on a shoe pasted into a room: the tile ratio read it "noisier" (1.39) while its floor was 0.60 against the
    # plate's 1.46 (0.41; 1.08 once composite.py matched the grain). Regions of one untouched photo differ too
    # (0.27-2.66 over 24 ellipses on 8 photos: a smooth sky against land, bokeh against skin), so only 0.45 / 2.2 are
    # flagged.
    floors = None
    if a.composite:
        stride = max(1, math.ceil(math.sqrt(W * H / 64 / 40000)))  # at most ~40k blocks a side
        fl = []
        for lo, hi in ((250, 255), (0, 5)):
            v = sorted(block_grain(R, G, B, w, M, lo, hi, bx0, by0, bx1, by1, stride))
            fl.append(v[int(0.2 * (len(v) - 1))] if len(v) >= 8 else None)
        floors = tuple(fl)
    med = lambda v: sorted(v)[len(v) // 2] if v else None
    flagged = [t for t in tiles if t["flags"]]
    worst = sorted(flagged, key=lambda t: (-len(t["flags"]), -abs(math.log(max(0.05, t["grainRatio"])))
                                          - abs(t["step"] or 0) / 4))[:a.spots]
    steps = [abs(t["step"]) for t in tiles if t["step"] is not None]
    summary = {"tiles": len(tiles), "tile": T, "feather": feather, "flagged": len(flagged),
               "flagged%": round(100 * len(flagged) / len(tiles), 1),
               "grainRatio": round(med([t["grainRatio"] for t in tiles]), 2),
               "step": round(med(steps), 2) if steps else None,
               "sharpRatio": None, "edgeBlur": None,
               "noiseOutside": round(noise, 2), "kind": "composite" if a.composite else "patch"}
    if crop:
        summary["readAround"] = [crop[0] + a.origin[0], crop[1] + a.origin[1], crop[2], crop[3]]
    if not steps and not a.composite:
        summary["stepNote"] = ("no tone step measured: no edge point had fully replaced and fully original pixels "
                               "on both sides within reach (a patch thinner than a few px, or a frame cropped tight)")
    counts = {}
    for t in flagged:
        for f in t["flags"]:
            counts[f] = counts.get(f, 0) + 1
    summary["flags"] = counts
    # sharpness from every edge point along the whole seam: a single tile rarely has enough edges to judge
    if len(pooled_in) >= 30 and len(pooled_out) >= 30:
        pi, po = sorted(pooled_in)[len(pooled_in) // 2], sorted(pooled_out)[len(pooled_out) // 2]
        summary["edgeBlur"] = [round(pi, 2), round(po, 2)]
        summary["sharpRatio"] = round((po + 0.5) / (pi + 0.5), 2)
    advice = []
    # a fault runs along the edge: a third of the tiles must agree (one or two odd tiles are the photo's own
    # texture); on a small patch with one or two tiles, that one decides
    enough = max(1, math.ceil(0.34 * len(tiles)))
    if counts.get("smoother", 0) >= enough:
        advice.append("the replaced side is smoother than its surroundings: add matched grain (Add Noise, gaussian, "
                      "monochromatic) or heal from a textured source; a fill or blur shows at 100 %")
    if counts.get("noisier", 0) >= enough:
        advice.append("the replaced side is noisier: less added grain, or a cleaner donor")
    if floors:
        f_in, f_out = floors
        summary["noiseFloor"] = [round(f_in, 2) if f_in is not None else None, round(f_out, 2) if f_out is not None else None]
        if f_in is not None and f_out:
            summary["noiseFloorRatio"] = fr = round(f_in / max(f_out, 0.3), 2)
            if fr < a.floor_clean:
                advice.append(f"the element looks cleaner than the plate (noise floor {f_in:.2f} against {f_out:.2f}): "
                              "compare the two at 100 %; if it is, add the plate's grain (composite.py --grain auto adds "
                              "the difference)")
            elif fr > a.floor_noisy:
                advice.append(f"the element looks noisier than the plate (noise floor {f_in:.2f} against {f_out:.2f}): "
                              "compare at 100 % (fine texture everywhere, as on skin, reads as grain too); if it is, "
                              "less added grain, or reduce its noise")
    if max(counts.get("lighter", 0), counts.get("darker", 0)) >= enough:
        advice.append("a tone step along the edge: the donor is in different light; a donor on the same row and "
                      "light, a clipped Curves on the donor, or heal the seam")
    blur_gap = abs(summary["edgeBlur"][0] - summary["edgeBlur"][1]) if summary["edgeBlur"] else 0.0
    if summary["sharpRatio"] is not None and summary["sharpRatio"] < a.soft_seam and blur_gap >= a.blur_diff:
        advice.append("the inserted part is softer than the plate: a sharper source, or blur the plate around it "
                      "to the same focus (Lens Blur), never the other way round on a sharp plate")
    if summary["sharpRatio"] is not None and summary["sharpRatio"] > a.sharp_seam and blur_gap >= a.blur_diff:
        advice.append("the inserted part is sharper than the plate: blur it to the plate's focus at that depth")
    summary["advice"] = advice
    # picture: thumb with the mask edge and tiles; then 3x zooms of the worst tiles, image | local check view
    img, k = thumb(R, G, B, w, h, 1000, dim=0.4)
    for y in ys[::max(1, k)]:
        v = edge_rows[y]
        while v:
            low = v & -v
            x = w - low.bit_length()
            v ^= low
            if y // k < len(img) and x // k < len(img[0]):
                img[y // k][x // k] = (255, 230, 0)
    for t in tiles:
        x0, y0, tw, th = t["at"]
        col = (0, 200, 80) if not t["flags"] else (255, 140, 0) if len(t["flags"]) == 1 else (230, 0, 0)
        rect(img, (x0 - ox) // k, (y0 - oy) // k, (x0 - ox + tw - 1) // k, (y0 - oy + th - 1) // k, col)
    zooms = []
    for n, t in enumerate(worst):
        cx, cy = t["at"][0] - ox + t["at"][2] // 2, t["at"][1] - oy + t["at"][3] // 2
        z = tile(R, G, B, w, h, cx, cy, min(2 * T, 96), 3)
        both = [r1 + [(255, 255, 255)] * 4 + r2 for r1, r2 in zip(z, compare.view(z, "local"))]
        compare.text(both, 4, 4, str(n + 1), (255, 220, 0), 3)
        zooms.append(both)
    save(os.path.join(a.outdir, "seams.png"), stack(img, zooms))
    summary["worst"] = [{"n": n + 1, **t} for n, t in enumerate(worst)]
    summary["picture"] = os.path.join(a.outdir, "seams.png")
    json.dump({"summary": summary, "tiles": tiles}, open(os.path.join(a.outdir, "seams.json"), "w"), indent=1)
    print(json.dumps(summary))


# ---------------------------------------------------------------- repeats

def descriptor(H, w, x, y):
    """The 9 x 9 high-pass patch at (x, y), mean removed, unit length: (vector, std)."""
    v = [H[(y + dy) * w + x + dx] for dy in range(-4, 5) for dx in range(-4, 5)]
    m = sum(v) / 81
    v = [t - m for t in v]
    n = math.sqrt(sum(t * t for t in v))
    return ([t / n for t in v] if n > 1e-9 else v), n / 9


def hash_bits(d):
    """16 signs of 2 x 2 block means over the patch's central 8 x 8, and how sure each sign is."""
    bits, conf = 0, []
    for by in range(4):
        for bx in range(4):
            s = sum(d[(1 + 2 * by + yy) * 9 + 1 + 2 * bx + xx] for yy in (-1, 0) for xx in (-1, 0))
            bits = (bits << 1) | (1 if s > 0 else 0)
            conf.append(abs(s))
    return bits, conf


def probes(bits, conf, n):
    """The key, and the keys with the n least certain bits flipped in every combination."""
    weak = sorted(range(16), key=conf.__getitem__)[:n]
    keys = [bits]
    for b in weak:
        keys += [k ^ (1 << (15 - b)) for k in keys]
    return keys


def footprint(match, x0, y0, x1, y1, exact, seeds, step=4, grow_px=8):
    """Where a repeat really is: on a grid every `step` px over (x0, y0)-(x1, y1), the points whose patch matches its
    counterpart at the repeat's offset exactly (match(x, y) -> correlation or None), kept only where connected to the
    repeat's own matched corners (seeds): the next identical window is periodic evidence, not more of this copy.
    Returns (inside(x, y): within grow_px of the footprint, the footprint's box or None)."""
    gw, gh = (x1 - x0) // step + 1, (y1 - y0) // step + 1
    grid = bytearray(gw * gh)
    for j in range(gw * gh):
        c = match(x0 + j % gw * step, y0 + j // gw * step)
        if c is not None and c >= exact:
            grid[j] = 1
    seed_cells = set()
    for x, y in seeds:
        gx, gy = round((x - x0) / step), round((y - y0) / step)
        seed_cells |= {(gy + ey) * gw + gx + ex for ey in (-1, 0, 1) for ex in (-1, 0, 1)
                       if 0 <= gx + ex < gw and 0 <= gy + ey < gh}
    own = bytearray(gw * gh)
    for c in imgops.components(grid, gw, gh):
        if any(j in seed_cells for j in c):
            for j in c:
                own[j] = 1
    on = [j for j in range(gw * gh) if own[j]]
    box = None
    if on:
        xs, ys = [x0 + j % gw * step for j in on], [y0 + j // gw * step for j in on]
        box = [min(xs) - 4, min(ys) - 4, max(xs) + 4, max(ys) + 4]
    grown = from_bits(dilate(to_bits(own, gw, gh), gw, math.ceil(grow_px / step)), gw)

    def inside(x, y):
        gx, gy = round((x - x0) / step), round((y - y0) / step)
        return 0 <= gx < gw and 0 <= gy < gh and grown[gy * gw + gx]
    return inside, box


def full_crop(path, x, y, cw, ch, W, H):
    """A full-resolution rectangle read through the CLI, clipped to the frame: (x0, y0, w, h, R, G, B, high-pass)
    or None. The high-pass is texture without tone (luminance minus a 3 px blur)."""
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + cw), min(H, y + ch)
    if x1 - x0 < 24 or y1 - y0 < 24:
        return None
    w, h, R, G, B, _ = load(path, [("image.crop", {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0})])
    L = lum_rows(R, G, B, w, 0, 0, w, h)
    return x0, y0, w, h, R, G, B, [l - g for l, g in zip(L, imgops.gauss(L, w, h, 3.0))]


def rescore(path, W, H, pts, off, k, a):
    """A repeat found on the small copy (its target corners in full-size px, its offset), re-measured at full size,
    as a full-size check would have measured it: the offset searched +-(k + 1) px around the small copy's (a copy by
    an offset that isn't a multiple of k sits between its pixels), every pair correlated at the best one, and the
    periodic test on full-size corners in a ring round the repeat. (offset, mean correlation, pairs, ring rate) or
    None."""
    e = 6 * k
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    ix0, iy0, ix1, iy1 = min(xs) - e, min(ys) - e, max(xs) + e, max(ys) + e
    m = a.link + 12
    t = full_crop(path, ix0 - m, iy0 - m, ix1 - ix0 + 2 * m + 1, iy1 - iy0 + 2 * m + 1, W, H)
    s = full_crop(path, ix0 - m + off[0] - k - 1, iy0 - m + off[1] - k - 1, ix1 - ix0 + 2 * m + 2 * k + 3,
                  iy1 - iy0 + 2 * m + 2 * k + 3, W, H)
    if not t or not s:
        return None
    tx0, ty0, tw, th, tR, tG, tB, Ht = t
    sx0, sy0, sw, sh, _, _, _, Hs = s

    def ncc(px, py, dx, dy, d1=None):
        x, y = px - tx0, py - ty0
        u, v = px + dx - sx0, py + dy - sy0
        if not (4 <= x < tw - 4 and 4 <= y < th - 4 and 4 <= u < sw - 4 and 4 <= v < sh - 4):
            return None
        if d1 is None:
            d1, s1 = descriptor(Ht, tw, x, y)
            if s1 <= 0:
                return None
        d2, s2 = descriptor(Hs, sw, u, v)
        return sum(p * q for p, q in zip(d1, d2)) if s2 > 0 else None
    best = []
    for px, py in pts[:24]:
        cand = [(c, (off[0] + ex, off[1] + ey)) for ey in range(-k - 1, k + 2) for ex in range(-k - 1, k + 2)
                if (c := ncc(px, py, off[0] + ex, off[1] + ey)) is not None]
        if cand:
            best.append(max(cand))
    if not best:
        return None
    dxs, dys = sorted(o[0] for _, o in best), sorted(o[1] for _, o in best)
    o = (dxs[len(dxs) // 2], dys[len(dys) // 2])
    vals = [c for p in pts if (c := ncc(p[0], p[1], o[0], o[1])) is not None]
    if not vals:
        return None
    # the ring: full-size corners round the repeat's extent, outside what the edit changed, compared with the source
    # side at the same offset
    edited = None
    if a.before:
        b = full_crop(a.before, tx0, ty0, tw, th, W, H)
        if b and b[2:4] == (tw, th):
            ch = bytes(1 if max(abs(r - r0), abs(g - g0), abs(bb - b0)) > 2 else 0
                       for r, g, bb, r0, g0, b0 in zip(tR, tG, tB, b[4], b[5], b[6]))
            edited = from_bits(dilate(to_bits(ch, tw, th), tw, 3), tw)
    elif a.area:
        edited = raster(a.area, tx0 + a.origin[0], ty0 + a.origin[1], tw, th)
    # (outside the copy's own footprint grown 8 px: corners are sparse in smooth texture, a smooth part of the copy may
    # not have changed enough to count as edited, and a patch straddling its border correlates partly)
    inside, box = footprint(lambda x, y: ncc(x, y, o[0], o[1]), tx0 + 4, ty0 + 4, tx0 + tw - 5, ty0 + th - 5, a.exact, pts)
    ring, _ = features(tR, tG, tB, tw, th, a.max_points, a.texture)
    hits = tested = 0
    for i, (d1, _, _) in list(ring.items())[:400]:
        X, Y = tx0 + i % tw, ty0 + i // tw
        if (ix0 <= X <= ix1 and iy0 <= Y <= iy1) or inside(X, Y) or (edited is not None and edited[i]):
            continue
        c = ncc(X, Y, o[0], o[1], d1)
        if c is not None:
            tested += 1
            hits += c >= a.periodic_ncc
    return o, sum(vals) / len(vals), len(vals), (hits / tested if tested else None), box


def _box1d(v, r):
    """Box mean of a list over 2r + 1, ends clamped: one row of imgops' box passes."""
    if r < 1:
        return v
    inv, n = 1.0 / (2 * r + 1), len(v)
    pad = [v[0]] * r + v + [v[-1]] * (r + 1)
    acc = sum(pad[:2 * r + 1])
    out = [0.0] * n
    for x in range(n):
        out[x] = acc * inv
        acc += pad[x + 2 * r + 1] - pad[x]
    return out


def gauss_f(src, w, h, sigma):
    """imgops.gauss (three box passes each way) on a 4-byte array, row by row and column by column, so a big
    image needs two arrays rather than several lists of Python floats."""
    rs = imgops._box_radii(sigma)
    out = array("f", src)
    for y in range(h):
        row = out[y * w:(y + 1) * w].tolist()
        for r in rs:
            row = _box1d(row, r)
        out[y * w:(y + 1) * w] = array("f", row)
    for x in range(w):
        col = out[x::w].tolist()
        for r in rs:
            col = _box1d(col, r)
        out[x::w] = array("f", col)
    return out


def maxf_f(src, w, h, r):
    """imgops.maxf (the maximum over a 2r + 1 square) on a 4-byte array, row by row and column by column."""
    out = array("f", src)
    for y in range(h):
        row = out[y * w:(y + 1) * w].tolist()
        out[y * w:(y + 1) * w] = array("f", [max(row[max(0, x - r):x + r + 1]) for x in range(w)])
    for x in range(w):
        col = out[x::w].tolist()
        out[x::w] = array("f", [max(col[max(0, y - r):y + r + 1]) for y in range(h)])
    return out


def features(R, G, B, w, h, max_points, texture):
    """Harris corners of an image (bytes) and their texture descriptors: ({index: (descriptor, bits, confidence)},
    the high-pass image). Corners are distinctive in both directions, so a straight edge or a line doesn't match
    itself all along; the descriptor is texture without tone, since a heal blends tone, not texture. The images in
    between are 4-byte arrays, each freed as soon as it's used."""
    N = w * h
    L = array("f", (0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(R, G, B)))
    Ls = gauss_f(L, w, h, 0.8)
    Ix, Iy = array("f", bytes(4 * N)), array("f", bytes(4 * N))
    for y in range(1, h - 1):
        for i in range(y * w + 1, y * w + w - 1):
            Ix[i] = (Ls[i + 1] - Ls[i - 1]) / 2
            Iy[i] = (Ls[i + w] - Ls[i - w]) / 2
    del Ls
    Sxx = gauss_f(array("f", (v * v for v in Ix)), w, h, 1.5)
    Syy = gauss_f(array("f", (v * v for v in Iy)), w, h, 1.5)
    Sxy = gauss_f(array("f", (u * v for u, v in zip(Ix, Iy))), w, h, 1.5)
    del Ix, Iy
    Rh = array("f", (xx * yy - xy * xy - 0.05 * (xx + yy) ** 2 for xx, yy, xy in zip(Sxx, Syy, Sxy)))
    del Sxx, Syy, Sxy
    mx = maxf_f(Rh, w, h, 2)
    # the strongest corners, one per 30 px at most (grain alone can't be told from fine texture on grass or gravel)
    kps = [i for i in range(N) if Rh[i] > 0 and Rh[i] >= mx[i] and 5 <= i % w < w - 5 and 5 <= i // w < h - 5]
    del mx
    cap = min(max_points, N // 30)
    if len(kps) > cap:
        kps = sorted(kps, key=Rh.__getitem__, reverse=True)[:cap]
    del Rh
    Hp = array("f", (l - g for l, g in zip(L, gauss_f(L, w, h, 3.0))))
    del L
    desc = {}
    for i in kps:
        d, sd = descriptor(Hp, w, i % w, i // w)
        if sd >= texture:
            desc[i] = (d,) + hash_bits(d)
    return desc, Hp


def cmd_repeats(a):
    W, H = image_size(a.image)
    os.makedirs(a.outdir, exist_ok=True)
    ox, oy = a.origin
    if a.before and a.area:
        sys.exit("error: give --before or --area, not both")
    if W < 24 or H < 24:
        print(json.dumps({"repeats": [], "verdict": f"too small to check ({W}x{H})"}))
        return
    # The reference is a copy of at most --max-mp megapixels, k times smaller (exactly: the frame is cut to a multiple
    # of k first, so the copy's pixel u covers x = k u .. k u + k - 1). A copy by an offset that isn't a multiple of k
    # falls between its pixels and correlates less (0.84 median against 0.995, measured), so the checked part is read
    # again at every phase: k x k crops 1 px apart, one of which lines up with the source exactly. What's found is
    # re-measured at full size.
    k = max(1, math.ceil(math.sqrt(W * H / (a.max_mp * 1e6))))
    Wc, Hc = W - W % k, H - H % k
    shrink = [] if k == 1 else [("image.crop", {"x": 0, "y": 0, "width": Wc, "height": Hc,
                                                 "targetWidth": Wc // k, "targetHeight": Hc // k})]
    w, h, R, G, B, _ = load(a.image, shrink)
    query, where = None, "the whole image"
    if a.before:
        if image_size(a.before) != (W, H):
            sys.exit(f"error: IMAGE is {W}x{H} but BEFORE is {image_size(a.before)}; use the same frame")
        _, _, R0, G0, B0, _ = load(a.before, shrink)
        changed = bytes(1 if max(abs(r - r0), abs(g - g0), abs(b - b0)) > (2 if k == 1 else 1) else 0
                        for r, g, b, r0, g0, b0 in zip(R, G, B, R0, G0, B0))
        query = from_bits(dilate(to_bits(changed, w, h), w, 3), w)
        where = "what changed since BEFORE"
    elif a.area:
        query = raster(a.area, ox, oy, W, H) if k == 1 else raster(scaled_area(a.area, k, k), ox / k, oy / k, w, h)
        where = "the area"
    if query is not None and not any(query):
        print(json.dumps({"repeats": [], "verdict": f"nothing to check: {where} is empty"}))
        return
    ref, refHp = features(R, G, B, w, h, a.max_points, a.texture)
    table = {}
    for i, (_, bits, _) in ref.items():
        table.setdefault(bits, []).append(i)
    min_d2 = a.min_offset ** 2
    # aligned phases are matched as strictly as at full size; the reference alone (a whole big photo) more loosely,
    # and the full-size score labels what it finds
    thr = a.ncc if (k == 1 or query is not None) else a.ncc_small
    matches = []  # (target x, y, source x, y in full-size px, correlation, phase)
    phases = []  # per phase: its copy's origin in full-size px, w, and (full size only) features and checked pixels

    def match(pn, px0, py0, pw, pf, pq):
        for q, (d, bits, conf) in pf.items():
            if pq is not None and not pq[q]:
                continue
            qx, qy = px0 + q % pw * k, py0 + q // pw * k
            best, bi = thr, None
            for key in probes(bits, conf, 3):
                for c in table.get(key, ()):
                    if (c % w * k - qx) ** 2 + (c // w * k - qy) ** 2 < min_d2:
                        continue
                    s = sum(u * v for u, v in zip(d, ref[c][0]))
                    if s > best:
                        best, bi = s, c
            if bi is not None:
                matches.append((qx, qy, bi % w * k, bi // w * k, best, pn))
    if k == 1 or query is None:
        phases.append((0, 0, w, ref, query))
        match(0, 0, 0, w, ref, query)
    else:
        # every phase of the checked part, one at a time: only its matches are kept
        qi = [i for i in range(w * h) if query[i]]
        pad = math.ceil((a.link + 24) / k)
        bx0, by0 = max(0, min(i % w for i in qi) - pad), max(0, min(i // w for i in qi) - pad)
        bx1, by1 = min(w - 1, max(i % w for i in qi) + pad), min(h - 1, max(i // w for i in qi) + pad)
        for dy in range(k):
            for dx in range(k):
                cw, ch = bx1 - bx0 + 1 - (1 if bx1 == w - 1 and dx else 0), by1 - by0 + 1 - (1 if by1 == h - 1 and dy else 0)
                if cw < 24 or ch < 24:
                    continue
                pw, ph, pr, pg, pb, _ = load(a.image, [("image.crop", {"x": bx0 * k + dx, "y": by0 * k + dy, "width": cw * k,
                                                                        "height": ch * k, "targetWidth": cw, "targetHeight": ch})])
                pq = bytearray(1 if query[(by0 + v) * w + bx0 + u] else 0 for v in range(ph) for u in range(pw))
                pf, _ = features(pr, pg, pb, pw, ph, a.max_points, a.texture)
                match(len(phases), bx0 * k + dx, by0 * k + dy, pw, pf, pq)
                phases.append((bx0 * k + dx, by0 * k + dy, pw, None, None))
                del pf, pq
    # repeats: matches that share one offset and sit near each other (a cloned stroke or patch)
    parent = list(range(len(matches)))

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u
    tol = 2 * k
    link = a.link * k  # corners of a k-times smaller copy are k times sparser
    buckets = {}
    for n, (qx, qy, cx, cy, _, _) in enumerate(matches):
        buckets.setdefault(((cx - qx) // (3 * k), (cy - qy) // (3 * k)), []).append(n)
    for (bx, by), ms in buckets.items():
        near = [m for ex in (-1, 0, 1) for ey in (-1, 0, 1) for m in buckets.get((bx + ex, by + ey), ())]
        for n in ms:
            qx, qy, cx, cy, _, _ = matches[n]
            for m in near:
                if m <= n:
                    continue
                qx2, qy2, cx2, cy2, _, _ = matches[m]
                if (abs((cx - qx) - (cx2 - qx2)) <= tol and abs((cy - qy) - (cy2 - qy2)) <= tol
                        and math.hypot(qx - qx2, qy - qy2) <= link):
                    parent[find(n)] = find(m)
    groups = {}
    for n in range(len(matches)):
        groups.setdefault(find(n), []).append(matches[n])
    reps = []
    for g in groups.values():
        if len(g) < a.min_pairs:
            continue
        ods = sorted(c[2] - c[0] for c in g); odys = sorted(c[3] - c[1] for c in g)
        off = (ods[len(ods) // 2], odys[len(odys) // 2])
        pn = max(set(m[5] for m in g), key=[m[5] for m in g].count)
        px0, py0, pw, pf, pq = phases[pn]
        xs, ys = [m[0] for m in g], [m[1] for m in g]
        # a periodic texture (brick, tiles, weave, a fence) repeats at that offset around the edit as well: corners of
        # the same phase near the repeat, outside the checked part, compared with the reference at the same offset
        # (a ring round the repeat's own extent: inside it, smooth parts of the copy may not have changed enough
        # to count as edited, and would match their source)
        e = 6 * k
        inner = lambda x, y: min(xs) - e <= x <= max(xs) + e and min(ys) - e <= y <= max(ys) + e
        extent = None
        if k == 1:
            def m1(x, y):
                if not (4 <= x < w - 4 and 4 <= y < h - 4 and 4 <= x + off[0] < w - 4 and 4 <= y + off[1] < h - 4):
                    return None
                d1, s1 = descriptor(refHp, w, x, y)
                d2, s2 = descriptor(refHp, w, x + off[0], y + off[1])
                return sum(p_ * q_ for p_, q_ in zip(d1, d2)) if s1 > 0 and s2 > 0 else None
            fin, extent = footprint(m1, max(4, min(xs) - e - a.link), max(4, min(ys) - e - a.link),
                                    min(w - 5, max(xs) + e + a.link), min(h - 5, max(ys) + e + a.link), a.exact,
                                    list(zip(xs, ys)))
            inner = lambda x, y, _i=inner, _f=fin: _i(x, y) or _f(x, y)
        ring = [i for i in pf if (pq is None or not pq[i])
                and min(xs) - e - a.link <= px0 + i % pw * k <= max(xs) + e + a.link
                and min(ys) - e - a.link <= py0 + i // pw * k <= max(ys) + e + a.link
                and not inner(px0 + i % pw * k, py0 + i // pw * k)] if k == 1 else []
        hits = tested = 0
        for i in ring[:200]:
            u, v = (px0 + i % pw * k + off[0]) / k, (py0 + i // pw * k + off[1]) / k
            u, v = int(round(u)), int(round(v))
            if 5 <= u < w - 5 and 5 <= v < h - 5:
                tested += 1
                d2, _ = descriptor(refHp, w, u, v)
                hits += sum(p * q for p, q in zip(pf[i][0], d2)) >= a.periodic_ncc
        rate = hits / tested if tested else None
        r = {"offset": list(off), "pairs": len(g), "ncc": round(sum(m[4] for m in g) / len(g), 3),
             "pts": [(m[0], m[1]) for m in g]}
        if k > 1:  # the small copy only found it: offset, correlation and the ring are all measured at full size
            res = rescore(a.image, W, H, r["pts"], r["offset"], k, a)
            if res:
                r["offset"], r["ncc"], r["pairsFull"], rate, extent = [res[0][0], res[0][1]], round(res[1], 3), res[2], res[3], res[4]
            else:
                r["ncc"], rate = 0.0, None
        r["aroundMatch"] = round(rate, 2) if rate is not None else None
        r["kind"] = ("periodic" if rate is not None and rate >= a.periodic else
                     "copy" if r["ncc"] >= a.exact else "similar")
        pad = 6 * k
        r["target"] = [min(xs) - pad + ox, min(ys) - pad + oy, max(xs) - min(xs) + 2 * pad + 1, max(ys) - min(ys) + 2 * pad + 1]
        if extent and r["kind"] == "copy":  # a copy's own extent, where its patches match exactly
            r["target"] = [extent[0] + ox, extent[1] + oy, extent[2] - extent[0] + 1, extent[3] - extent[1] + 1]
        r["source"] = [r["target"][0] + r["offset"][0], r["target"][1] + r["offset"][1], r["target"][2], r["target"][3]]
        reps.append(r)

    # with source and target both checked, each copy is found twice, once from each side: keep one, and call it
    # periodic if either side's surroundings repeat
    def overlap(b1, b2):
        ix = min(b1[0] + b1[2], b2[0] + b2[2]) - max(b1[0], b2[0])
        iy = min(b1[1] + b1[3], b2[1] + b2[3]) - max(b1[1], b2[1])
        return max(0, ix) * max(0, iy) / max(1, min(b1[2] * b1[3], b2[2] * b2[3]))
    merged = []
    for r in sorted(reps, key=lambda r: -r["pairs"]):
        twin = next((m for m in merged if abs(m["offset"][0] + r["offset"][0]) <= tol + 2
                     and abs(m["offset"][1] + r["offset"][1]) <= tol + 2 and overlap(m["target"], r["source"]) > 0.3), None)
        if twin is None:
            merged.append(r)
        elif r["kind"] == "periodic" or twin["kind"] == "periodic":
            twin["kind"] = "periodic"
    reps = merged
    reps.sort(key=lambda r: ({"copy": 0, "similar": 1, "periodic": 2}[r["kind"]], -r["pairs"]))
    real = [r for r in reps if r["kind"] == "copy"]
    out = {"analysedAt": [w, h], "scale": k, "phases": len(phases), "checked": where, "keypoints": len(ref),
           "matches": len(matches),
           "repeats": [{"n": n + 1, **{x: v for x, v in r.items() if x != "pts"}} for n, r in enumerate(reps[:a.spots * 2])],
           "counts": {kind: sum(1 for r in reps if r["kind"] == kind) for kind in ("copy", "similar", "periodic")},
           "verdict": (f"{len(real)} copied patch(es): the same texture twice, look at each pair" if real else
                       "no copied texture" + (" (only similar or periodic texture)" if reps else ""))}
    if k > 1 and query is None:
        out["note"] = (f"a whole {W}x{H} photo is checked at 1/{k} size: a copy by an offset that isn't a multiple of "
                       f"{k} px can be missed; --before or --area checks the edit at every phase")
    # picture: targets red, sources blue (the rest grey), then target | source at 3x, full resolution
    img, kk = thumb(R, G, B, w, h, 1000, dim=0.5)
    f = 1 / (k * kk)
    for n, r in enumerate(reps[:a.spots * 2]):
        col_t, col_s = ((255, 30, 30), (40, 120, 255)) if r["kind"] == "copy" else ((150, 150, 150), (150, 150, 150))
        for key, col in (("target", col_t), ("source", col_s)):
            x0, y0, bw, bh = r[key]
            rect(img, int((x0 - ox) * f), int((y0 - oy) * f), int((x0 - ox + bw) * f), int((y0 - oy + bh) * f), col, 2)
        compare.text(img, int((r["target"][0] - ox) * f), max(0, int((r["target"][1] - oy) * f) - 12), str(n + 1), col_t)
    pairs = []
    for n, r in enumerate(reps[:a.spots]):
        size = max(32, min(64, max(r["target"][2], r["target"][3]) + 12))
        cx, cy = r["target"][0] - ox + r["target"][2] // 2, r["target"][1] - oy + r["target"][3] // 2
        tiles_ = []
        for dx, dy in ((0, 0), tuple(r["offset"])):
            if k == 1:
                tiles_.append(tile(R, G, B, w, h, cx + dx, cy + dy, size, 3))
                continue
            x0, y0 = max(0, min(W - size, cx + dx - size // 2)), max(0, min(H - size, cy + dy - size // 2))
            tw_, th_, tr, tg, tb, _ = load(a.image, [("image.crop", {"x": x0, "y": y0, "width": min(size, W),
                                                                        "height": min(size, H)})])
            tiles_.append(tile(tr, tg, tb, tw_, th_, cx + dx - x0, cy + dy - y0, size, 3))
        both = [r1 + [(255, 255, 255)] * 4 + r2 for r1, r2 in zip(*tiles_)]
        compare.text(both, 4, 4, str(n + 1), (255, 220, 0), 3)
        pairs.append(both)
    save(os.path.join(a.outdir, "repeats.png"), stack(img, pairs))
    out["picture"] = os.path.join(a.outdir, "repeats.png")
    print(json.dumps(out))


# ---------------------------------------------------------------- banding

def stairs(V, smooth, w, h, run, max_step):
    """Stair steps in one channel: along every row and column of smooth pixels, a jump of 2..max_step levels between
    two flat runs of at least `run` px each. A smooth 8-bit gradient climbs one level at a time, and grain breaks its
    runs up; a stretched one climbs in visible steps between long flat bands. (count, boundaries looked at, marks)."""
    marks = bytearray(w * h)
    count = seen = 0
    for horizontal in (True, False):
        lines = range(h) if horizontal else range(w)
        for ln in lines:
            idx = range(ln * w, ln * w + w) if horizontal else range(ln, w * h, w)
            runs = []  # (first index, length, value) within one smooth stretch
            for i in list(idx) + [None]:
                if i is None or not smooth[i]:
                    for (i0, n0, v0), (i1, n1, v1) in zip(runs, runs[1:]):
                        seen += 1
                        if n0 >= run and n1 >= run and 2 <= abs(v1 - v0) <= max_step:
                            count += 1
                            marks[i1] = 1
                    runs = []
                    continue
                v = V[i]
                if runs and runs[-1][2] == v:
                    runs[-1] = (runs[-1][0], runs[-1][1] + 1, v)
                else:
                    runs.append((i, 1, v))
    return count, seen, marks


def channel_noise(V, w, h, pix):
    """A channel's noise in a region: the robust spread of its values round their 3x3 mean (1.4826 x median, / 0.943
    for white noise), on up to 4000 of the region's pixels. Clean stretched plateaus read 0; grain and JPEG noise
    don't."""
    step = max(1, len(pix) // 4000)
    d = []
    for i in pix[::step]:
        x, y = i % w, i // w
        if 0 < x < w - 1 and 0 < y < h - 1:
            d.append(abs(V[i] - (V[i - w - 1] + V[i - w] + V[i - w + 1] + V[i - 1] + V[i] + V[i + 1] + V[i + w - 1]
                                  + V[i + w] + V[i + w + 1]) / 9))
    d.sort()
    return 1.4826 * d[len(d) // 2] / 0.943 if d else 0.0


def cmd_banding(a):
    w, h, R, G, B, _ = load(a.image)
    os.makedirs(a.outdir, exist_ok=True)
    ox, oy = a.origin
    N = w * h
    inside = raster(a.area, ox, oy, w, h) if a.area else None
    n_smooth, regions = 0, 0
    per = {c: {"stairs": 0, "miss_w": 0.0, "tot_w": 0.0} for c in "RGB"}
    found = []  # every region and channel with levels missing or steps, judged on its own
    img, k = thumb(R, G, B, w, h, 1200, dim=0.5)
    tmarks = bytearray(len(img) * len(img[0]))  # 1 smooth, 2 a step the noise hides, 3 a step in a banded region
    tw = len(img[0])
    P, BS = 14, 768  # blur reach; block side: the work is done block by block, so memory stays bounded
    for y0 in range(0, h, BS):
        for x0 in range(0, w, BS):
            x1, y1 = min(w, x0 + BS), min(h, y0 + BS)
            wx0, wy0, wx1, wy1 = max(0, x0 - P), max(0, y0 - P), min(w, x1 + P), min(h, y1 + P)
            ww, wh = wx1 - wx0, wy1 - wy0
            L = lum_rows(R, G, B, w, wx0, wy0, wx1, wy1)
            # smooth: little texture around a blurred copy (grain and the stair steps themselves stay under --smooth;
            # grass, stone and cloud edges don't) and a gentle slope (a sky, a backdrop, a vignette; no edges)
            Lb = imgops.gauss(L, ww, wh, 3.0)
            tex = imgops.box([(l - b) ** 2 for l, b in zip(L, Lb)], ww, wh, 4)
            cw_, ch_ = x1 - x0, y1 - y0
            smooth = bytearray(cw_ * ch_)
            for yy in range(ch_):
                for xx in range(cw_):
                    j = (yy + y0 - wy0) * ww + xx + x0 - wx0
                    gx, gy = xx + x0, yy + y0
                    if not (0 < gx < w - 1 and 0 < gy < h - 1) or tex[j] >= a.smooth ** 2 or not 4 < Lb[j] < 251:
                        continue
                    if inside is not None and not inside[gy * w + gx]:
                        continue
                    if 0 < j % ww < ww - 1 and ww <= j < ww * (wh - 1) and \
                            abs(Lb[j + 1] - Lb[j - 1]) / 2 + abs(Lb[j + ww] - Lb[j - ww]) / 2 < a.slope:
                        smooth[yy * cw_ + xx] = 1
            del L, Lb, tex
            regs = [c for c in imgops.components(smooth, cw_, ch_) if len(c) >= a.min_area]
            if not regs:
                continue
            keep = bytearray(cw_ * ch_)
            label = {}
            for n, c in enumerate(regs):
                for i in c:
                    keep[i] = 1
                    label[i] = n
            n_smooth += sum(len(c) for c in regs)
            regions += len(regs)
            marks_all = bytearray(cw_ * ch_)
            stats = [{} for _ in regs]  # per region, per channel: (missing, steps per 1000, step, noise, median)
            chmarks = {}
            for name, ch in (("R", R), ("G", G), ("B", B)):
                V = b"".join(ch[y * w + x0:y * w + x1] for y in range(y0, y1))
                cnt, _, marks = stairs(V, keep, cw_, ch_, a.run, a.max_step)
                per[name]["stairs"] += cnt
                chmarks[name] = marks
                steps_in = [0] * len(regs)
                for i in (i for i, mk in enumerate(marks) if mk):
                    steps_in[label[i]] += 1
                    marks_all[i] = 1
                for n, c in enumerate(regs):
                    vals = sorted(V[i] for i in c)
                    lo, hi = vals[int(0.02 * (len(vals) - 1))], vals[int(0.98 * (len(vals) - 1))]
                    med = vals[len(vals) // 2]
                    if hi - lo + 1 < a.min_span:
                        stats[n][name] = (0.0, 0.0, 1.0, 0.0, med, lo, hi)
                        continue
                    present = set(v for v in vals if lo <= v <= hi)
                    miss = 1 - len(present) / (hi - lo + 1)
                    per[name]["miss_w"] += miss * len(c)
                    per[name]["tot_w"] += len(c)
                    dens = 1000 * steps_in[n] / len(c)
                    step = 1 / (1 - miss) if miss < 1 else float(hi - lo)
                    noise = channel_noise(V, cw_, ch_, c) if miss >= a.missing or dens >= a.stairs else 0.0
                    stats[n][name] = (miss, dens, step, noise, med, lo, hi)
            for n, c in enumerate(regs):
                st = stats[n]
                if not any(v[0] >= a.missing or v[1] >= a.stairs for v in st.values()):
                    continue
                # a channel bands where levels are missing, steps between flat runs are frequent, and the step the
                # missing levels leave (1 / share present) stands at least --clear x the region's noise in it: smaller
                # ones are dithered away, as grain or JPEG noise does in an 8-bit stretch
                clear = [nm for nm, v in st.items() if v[0] >= a.missing and v[1] >= a.stairs and v[2] >= a.clear * max(v[3], 0.25)]
                # and the step must be seen: the colour difference of one band, every banding channel stepping at once
                # (a curve posterises them together), at the region's median colour. Two levels of red near black in a
                # saturated blue, or 1.4 levels of blue, are well under a just noticeable difference
                med = [st[nm][4] for nm in "RGB"]
                stepped = [(m + st[nm][2] if m + st[nm][2] <= 255 else m - st[nm][2]) if nm in clear else m
                           for nm, m in zip("RGB", med)]
                L1, a1, b1 = imgops.lab(*med, a.space)
                L2, a2, b2 = imgops.lab(*stepped, a.space)
                de = math.sqrt((L2 - L1) ** 2 + (a2 - a1) ** 2 + (b2 - b1) ** 2)
                banded = bool(clear) and de >= a.delta_e
                xs = [i % cw_ for i in c]; ys = [i // cw_ for i in c]
                found.append({"box": [min(xs) + x0 + ox, min(ys) + y0 + oy, max(xs) - min(xs) + 1, max(ys) - min(ys) + 1],
                              "pixels": len(c), "median": med, "banded": banded, "stepDeltaE": round(de, 2),
                              "channels": {nm: {"levels": [v[5], v[6]], "missing%": round(100 * v[0], 1),
                                                "stairsPer1000": round(v[1], 2), "step": round(v[2], 2), "noise": round(v[3], 2),
                                                "clear": nm in clear} for nm, v in st.items()}})
                if banded:
                    for i in c:
                        if any(chmarks[nm][i] for nm in clear):
                            marks_all[i] = 2
            for i in range(cw_ * ch_):
                if keep[i]:
                    tx, ty = (x0 + i % cw_) // k, (y0 + i // cw_) // k
                    if ty < len(img) and tx < tw:
                        j = ty * tw + tx
                        tmarks[j] = max(tmarks[j], 1 + marks_all[i])
    out = {"size": [w, h], "smooth%": round(100 * n_smooth / N, 1), "regions": regions}
    if not regions:
        out["verdict"] = "no smooth gradient big enough to show banding"
        print(json.dumps(out))
        return
    # image-wide figures are context only: the verdict is each region's own
    out["channels"] = {c: {"stairsPer1000": round(1000 * d["stairs"] / max(1, n_smooth), 2), "stairs": d["stairs"],
                           "missing%": round(100 * d["miss_w"] / d["tot_w"], 1) if d["tot_w"] else None}
                       for c, d in per.items()}
    banded = [r for r in found if r["banded"]]
    comb = lambda r: max(v["missing%"] for v in r["channels"].values())
    hidden = [r for r in found if not r["banded"] and comb(r) >= 100 * a.missing]
    found.sort(key=lambda r: (not r["banded"], -r["stepDeltaE"] * comb(r)))
    out["bandedRegions"] = len(banded)
    out["combNotVisible"] = len(hidden)
    out["worst"] = found[:8]
    chans = sorted(set(nm for r in banded for nm, v in r["channels"].items() if v["clear"]))
    if banded:
        out["verdict"] = (f"banding in {len(banded)} region(s) ({', '.join(chans)}): visible steps between flat bands, "
                          "clear of the noise. A gentler curve there, the stretch from a 16-bit or raw source, or fine "
                          "grain over the gradient (Add Noise 1-2, gaussian, monochromatic, masked to it); converting an "
                          "8-bit file to 16 bits doesn't bring the lost levels back")
    elif hidden:
        out["verdict"] = (f"no visible banding: {len(hidden)} region(s) lost {min(comb(r) for r in hidden):.0f}-"
                          f"{max(comb(r) for r in hidden):.0f} % of their levels, but the steps are dithered by the noise "
                          "or too small to see; keep noise reduction off them, and look at the worst at 100 %")
    else:
        out["verdict"] = "no banding"
    json.dump({"summary": {k_: v for k_, v in out.items() if k_ != "worst"}, "regions": found},
              open(os.path.join(a.outdir, "banding.json"), "w"), indent=1)
    # picture: smooth areas tinted blue, steps the noise hides orange, steps in banded regions red
    for j, mk in enumerate(tmarks):
        if mk:
            Y, X = j // tw, j % tw
            if mk == 3:
                img[Y][X] = (255, 30, 30)
            elif mk == 2:
                img[Y][X] = (255, 170, 0)
            else:
                r_, g_, b_ = img[Y][X]
                img[Y][X] = (int(r_ * 0.6), int(g_ * 0.7), min(255, int(b_ * 0.7 + 90)))
    save(os.path.join(a.outdir, "banding.png"), img)
    out["picture"] = os.path.join(a.outdir, "banding.png")
    print(json.dumps(out))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("diff", help="what changed, how much, where; changes outside an area")
    p.add_argument("before"); p.add_argument("after"); p.add_argument("outdir")
    p.add_argument("--area", metavar="AREA", help="where changes were meant to happen (area.json or x0,y0,x1,y1)")
    p.add_argument("--origin", type=int, nargs=2, default=[0, 0], metavar=("X", "Y"))
    p.add_argument("--threshold", type=float, default=1, help="levels: a pixel counts as changed above this (any channel)")
    p.add_argument("--margin", type=int, default=3, help="px the area may be overstepped (feathered masks, dab rims)")
    p.add_argument("--min-pixels", type=int, default=4, help="ignore changes outside the area smaller than this")
    p.add_argument("--allowed-mask", metavar="PNG", help="where changes were meant to happen, as a grey mask of the same frame (white = allowed)")
    p.add_argument("--grow", type=int, default=2, help="px changed.png grows the changed pixels by (a brush's soft rim)")
    p.add_argument("--space", choices=("srgb", "p3"), default="srgb", help="the document's RGB space, for Lab")
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("seams", help="grain, tone and sharpness across the edge of a composite or patch")
    p.add_argument("image"); p.add_argument("mask"); p.add_argument("outdir")
    p.add_argument("--origin", type=int, nargs=2, default=[0, 0], metavar=("X", "Y"))
    p.add_argument("--composite", action="store_true",
                   help="the inserted part is a different thing (a product on a new background, a sky): no tone step")
    p.add_argument("--tile", type=int, default=32, help="px per tile along the edge (more for a wide feather, by itself)")
    p.add_argument("--band", type=int, default=8, help="px on each side of the edge that are compared")
    p.add_argument("--min-pixels", type=int, default=60, help="pixels per side a tile needs")
    p.add_argument("--smooth", type=float, default=0.5, help="grain ratio below this: smoother inside")
    p.add_argument("--noisy", type=float, default=1.8, help="grain ratio above this: noisier inside")
    p.add_argument("--floor-clean", type=float, default=0.45,
                   help="--composite: element's noise floor below this x the plate's: cleaner (add grain)")
    p.add_argument("--floor-noisy", type=float, default=2.2, help="--composite: above this x the plate's: noisier")
    p.add_argument("--step", type=float, default=3.0, help="levels: tone step across the edge")
    p.add_argument("--consistency", type=float, default=1.5,
                   help="the step must exceed this x how much the photo varies over the same span (texture)")
    p.add_argument("--softer", type=float, default=0.75, help="sharpness ratio below this: softer inside")
    p.add_argument("--sharper", type=float, default=1.35, help="sharpness ratio above this: sharper inside")
    p.add_argument("--soft-seam", type=float, default=0.85, help="whole-seam sharpness ratio below this: softer inside")
    p.add_argument("--sharp-seam", type=float, default=1.25, help="whole-seam sharpness ratio above this: sharper inside")
    p.add_argument("--blur-diff", type=float, default=0.4,
                   help="px of edge blur the two sides must differ by as well (sharp textures read near 0 on both)")
    p.add_argument("--strand-pixels", type=int, default=12, help="thin masks: fully replaced px a tile needs")
    p.add_argument("--max-mp", type=float, default=12, help="bigger frames are read only around the edge, through the CLI")
    p.add_argument("--spots", type=int, default=6, help="worst tiles zoomed in the picture")
    p.set_defaults(fn=cmd_seams)

    p = sub.add_parser("repeats", help="clone-stamp repeats: the same texture twice")
    p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--before", help="the image before the edit: only what changed is checked")
    p.add_argument("--area", metavar="AREA", help="only this area is checked (area.json or x0,y0,x1,y1)")
    p.add_argument("--origin", type=int, nargs=2, default=[0, 0], metavar=("X", "Y"))
    p.add_argument("--ncc", type=float, default=0.9, help="correlation of two texture patches that counts as a copy")
    p.add_argument("--ncc-small", type=float, default=0.75,
                   help="the same on a small copy of a big photo, where a copy can sit half a pixel off its source")
    p.add_argument("--min-pairs", type=int, default=3, help="matched corners sharing an offset that make a repeat")
    p.add_argument("--exact", type=float, default=0.96, help="mean correlation of a copy, at full size (clone, Patch, fill: 0.97-1.0)")
    p.add_argument("--min-offset", type=float, default=16, help="px: closer matches are the same spot or fine texture")
    p.add_argument("--link", type=float, default=40, help="px: matched corners this close belong to one repeat")
    p.add_argument("--texture", type=float, default=2.0, help="levels: flatter patches are skipped (they match anything)")
    p.add_argument("--periodic", type=float, default=0.05, help="share of corners around a repeat that repeat too: periodic texture")
    p.add_argument("--periodic-ncc", type=float, default=0.7, help="correlation that counts as 'repeats too' around a repeat")
    p.add_argument("--max-points", type=int, default=60000, help="strongest corners kept")
    p.add_argument("--max-mp", type=float, default=3.0, help="megapixels of the copy analysed; finds are re-measured at full size")
    p.add_argument("--spots", type=int, default=6)
    p.set_defaults(fn=cmd_repeats)

    p = sub.add_parser("banding", help="posterisation in smooth gradients")
    p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--area", metavar="AREA", help="only this area (area.json or x0,y0,x1,y1)")
    p.add_argument("--origin", type=int, nargs=2, default=[0, 0], metavar=("X", "Y"))
    p.add_argument("--smooth", type=float, default=4.0, help="levels: texture (RMS around a 3 px blur) below this is smooth")
    p.add_argument("--slope", type=float, default=3.0, help="levels per px: steeper is an edge, not a gradient")
    p.add_argument("--min-area", type=int, default=2000, help="px: smaller smooth patches are ignored")
    p.add_argument("--min-span", type=int, default=8, help="levels a region must span to judge its histogram")
    p.add_argument("--run", type=int, default=4, help="px: flat runs on both sides of a step")
    p.add_argument("--max-step", type=int, default=16, help="levels: bigger jumps are edges, not bands")
    p.add_argument("--stairs", type=float, default=1.0, help="steps per 1000 of a region's px that count as banding")
    p.add_argument("--missing", type=float, default=0.3, help="share of a region's levels missing that counts as a comb")
    p.add_argument("--clear", type=float, default=2.0,
                   help="the step the missing levels leave must be this x the region's noise (smaller ones are dithered)")
    p.add_argument("--delta-e", type=float, default=1.2, help="the colour difference (Lab) of one band step that can be seen")
    p.add_argument("--space", choices=("srgb", "p3"), default="srgb", help="the image's RGB space, for that difference")
    p.set_defaults(fn=cmd_banding)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
