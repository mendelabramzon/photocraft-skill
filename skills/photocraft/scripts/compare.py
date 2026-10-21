#!/usr/bin/env python3
"""Side-by-side before/after of the same region, enlarged, for judging a retouch, with the check views retouchers
toggle on and off while they work.

usage: compare.py before.png after.png out.png [--rect x y w h] [--scale 3] [--check [VIEWS]] [--gain 5]
                  [--origin cropX cropY --marks X,Y[,R] X,Y[,R] …]

Both images must have the same size (e.g. two crops with the same offset). --rect is in those images' pixels
(default: everything); --scale enlarges it (3) or shrinks it (0.5, block means) for the sheet. --check adds one
labelled row of before | after per view, a comma list (bare --check is `local`, as it always was, wherever it stands):
  local     luminance minus its local mean (box 15) x --gain, around mid grey: blotches and uneven tone that colour
            hides. How dodge & burn gets judged.
  solar     KelbyOne's solar curve (a zigzag through four points at quarter intervals) on PhotoCraft's luminance,
            grey: every small tonal step becomes a band, so uneven D&B transitions, dust, creases and healing seams
            jump out. It is exactly what "Check: solar" over "Check: luminance" shows in the live document
            (check_layers.json).
  lum       luminance alone, what a 50 % grey layer in Color mode shows ("Check: luminance"). Chris Knight's point:
            a Black & White adjustment reweights the colours, so it changes the very tones you are judging.
  negative  the colour negative ("Check: negative", an Invert layer): specks and dust on light skies, backdrops
            and skin read as dark dots on dark, and vice versa.
  sat       chroma doubled around luminance, luminance kept ("Check: saturation", a Channel Mixer): colour
            blotches, redness, and colour fringes at mask edges.
  all       all five.
--marks prints, for each mark (full-image coords; --origin = where the crops sit; R its radius, 4 by default), how
much darker (dY, levels), redder ((R-G)/Y) and yellower the mark is than the skin 3.5R-5.5R around it, before and
after, each side as its median colour (a heal brings the source's pores into the disc; the median isn't swung by
them). noise is the spread of the same measure at eight places on that ring: a difference smaller than about twice it
is the skin's texture, not the mark. A good fix keeps the signs and shrinks the numbers; darker-but-not-redder after
reads as a bruise.
"""
import argparse
import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import imgops
import pngio

VIEWS = ("local", "solar", "lum", "negative", "sat")
# KelbyOne's four-point zigzag, one point every quarter; PhotoCraft's Curves spline (imgops.spline_lut) overshoots
# between them and clips, so the peaks are flat. The same points as "Check: solar" in check_layers.json.
SOLAR = [[0, 0], [64, 255], [128, 0], [192, 255], [255, 0]]
SOLAR_LUT = imgops.spline_lut(SOLAR)
SAT_GAIN = 2.0  # "Check: saturation": a Channel Mixer can't go past 200 %, which caps the blue row at x2.12

# 3x5 capitals for the view labels (imgops.FONT has the digits)
LETTERS = {
    "A": "010101111101101", "B": "110101110101110", "C": "011100100100011", "D": "110101101101110",
    "E": "111100110100111", "F": "111100110100100", "G": "011100101101011", "H": "101101111101101",
    "I": "111010010010111", "J": "001001001101010", "K": "101101110101101", "L": "100100100100111",
    "M": "101111111101101", "N": "110101101101101", "O": "010101101101010", "P": "110101110100100",
    "Q": "010101101111011", "R": "110101110101101", "S": "011100010001110", "T": "111010010010010",
    "U": "101101101101111", "V": "101101101101010", "W": "101101111111101", "X": "101101010101101",
    "Y": "101101010010010", "Z": "111001010100111", " ": "000000000000000", ".": "000000000000010",
    "-": "000000111000000", ":": "000010000010000", "%": "101001010100101", "/": "001001010100100",
    "+": "000010111010000", "=": "000111000111000", "|": "010010010010010",
}
GLYPHS = {**imgops.FONT, **LETTERS}


def text(img, x, y, s, colour, k=2):
    """Draw s (capitals, digits) into rows-of-tuples img at (x, y), k px per font pixel."""
    for n, ch in enumerate(s.upper()):
        bits = GLYPHS.get(ch, GLYPHS[" "])
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    for dy in range(k):
                        for dx in range(k):
                            yy, xx = y + r * k + dy, x + (n * 4 + c) * k + dx
                            if 0 <= yy < len(img) and 0 <= xx < len(img[0]):
                                img[yy][xx] = colour


def parse_views(spec):
    """'solar,lum' -> ['solar', 'lum']; 'all' -> every view."""
    out = []
    for v in (spec or "").split(","):
        v = v.strip().lower()
        if v == "all":
            out += [x for x in VIEWS if x not in out]
        elif v:
            if v not in VIEWS:
                sys.exit(f"error: unknown check view {v!r} (have {', '.join(VIEWS)}, all)")
            if v not in out:
                out.append(v)
    return out


def view(P, name, gain=5.0):
    """One check view of a rows-of-(r, g, b) image, the same size."""
    h, w = len(P), len(P[0])
    if name == "local":  # luminance minus its local mean (box 15), x gain, around mid grey
        L = [[imgops.lum(*p) for p in row] for row in P]
        r = 7
        out = []
        for y in range(h):
            ys = range(max(0, y - r), min(h, y + r + 1))
            row = []
            for x in range(w):
                xs = range(max(0, x - r), min(w, x + r + 1))
                m = sum(L[yy][xx] for yy in ys for xx in xs) / (len(ys) * len(xs))
                v = int(max(0, min(255, 128 + gain * (L[y][x] - m))))
                row.append((v, v, v))
            out.append(row)
        return out
    if name in ("lum", "solar"):
        # the grey Color-mode layer leaves the luminance in every channel, unrounded: the solar curve above it
        # interpolates its table at that value (rounding first is off by up to 4 levels on the steep zigzag)
        out = []
        for row in P:
            o = []
            for p in row:
                L = imgops.lum(*p)
                v = imgops.lut_f(SOLAR_LUT, L) if name == "solar" else L
                v = max(0, min(255, int(v + 0.5)))
                o.append((v, v, v))
            out.append(o)
        return out
    if name == "negative":
        return [[(255 - p[0], 255 - p[1], 255 - p[2]) for p in row] for row in P]
    if name == "sat":
        out = []
        for row in P:
            o = []
            for p in row:
                L = imgops.lum(*p)
                o.append(tuple(max(0, min(255, int(L + SAT_GAIN * (c - L) + 0.5))) for c in p))
            out.append(o)
        return out
    raise ValueError(name)


def mark_stats(P, cx, cy, r=4):
    """A mark at (cx, cy) of radius r against the skin round it: (dY in levels, d redness (R-G)/Y, d yellowness
    ((R+G)/2-B)/Y, noise). Each side is the median colour of its pixels, so the pores or a speck that a heal brought
    into the disc don't swing it: the disc of radius r against the ring 3.5r..5.5r. noise is the spread of the same
    disc measure at eight places on that ring: what this skin's texture alone does to a disc, the size a difference
    must pass before it means anything."""
    h, w = len(P), len(P[0])

    def med_colour(x0, y0, r0, r1):
        px = [P[y][x] for y in range(max(0, int(y0 - r1)), min(h, int(y0 + r1) + 1))
              for x in range(max(0, int(x0 - r1)), min(w, int(x0 + r1) + 1))
              if r0 * r0 <= (x - x0) ** 2 + (y - y0) ** 2 <= r1 * r1]
        if not px:
            return None
        rgb = [sorted(p[k] for p in px)[len(px) // 2] for k in range(3)]
        Y = max(1.0, 0.3 * rgb[0] + 0.59 * rgb[1] + 0.11 * rgb[2])
        return Y, (rgb[0] - rgb[1]) / Y, ((rgb[0] + rgb[1]) / 2 - rgb[2]) / Y
    c, o = med_colour(cx, cy, 0, r), med_colour(cx, cy, 3.5 * r, 5.5 * r)
    if c is None or o is None:
        return None
    around = [med_colour(cx + 4.5 * r * math.cos(t), cy + 4.5 * r * math.sin(t), 0, r)
              for t in (k * math.pi / 4 for k in range(8))]
    ys = sorted(v[0] for v in around if v)
    noise = 1.4826 * sorted(abs(v - ys[len(ys) // 2]) for v in ys)[len(ys) // 2] if ys else 0.0
    return c[0] - o[0], c[1] - o[1], c[2] - o[2], noise


def sheet(A, B, rect, scale, views, gain=5.0, gap=6, label_h=16):
    """Rows of before | after (the region, then one per check view), enlarged `scale` x, as rows of tuples."""
    x0, y0, rw, rh = rect
    crop = lambda P: [row[x0:x0 + rw] for row in P[y0:y0 + rh]]
    rows = [(None, crop(A), crop(B))]
    for v in views:
        rows.append((v, view(rows[0][1], v, gain), view(rows[0][2], v, gain)))
    sw, sh = max(1, round(rw * scale)), max(1, round(rh * scale))
    W = 2 * sw + gap
    H = sum(sh + (label_h if name else 0) for name, _, _ in rows) + gap * (len(rows) - 1)
    img = [[(255, 255, 255)] * W for _ in range(H)]
    oy = 0
    for name, pa, pb in rows:
        if name:
            text(img, 2, oy + 3, name, (40, 40, 40))
            oy += label_h
        for k, P in enumerate((pa, pb)):
            ox = k * (sw + gap)
            for y in range(sh):
                dst = img[oy + y]
                if scale >= 1:  # enlarge: each pixel a block
                    src = P[min(rh - 1, int(y / scale))]
                    for x in range(sw):
                        dst[ox + x] = src[min(rw - 1, int(x / scale))]
                else:  # shrink: the mean of the block each output pixel covers
                    y0, y1 = int(y / scale), max(int(y / scale) + 1, int((y + 1) / scale))
                    for x in range(sw):
                        x0, x1 = int(x / scale), max(int(x / scale) + 1, int((x + 1) / scale))
                        blk = [P[yy][xx] for yy in range(y0, min(rh, y1)) for xx in range(x0, min(rw, x1))]
                        dst[ox + x] = tuple(int(sum(q[c] for q in blk) / len(blk) + 0.5) for c in range(3))
        oy += sh + gap
    return img


def read(path):
    """(w, h, rows of (r, g, b)) of a PNG; a palette, interlaced or 1/2/4-bit PNG, or any other format, goes through
    photocraft-cli convert first."""
    try:
        return pngio.read(path)
    except (AssertionError, ValueError, OSError):
        import os
        import subprocess
        import tempfile
        import pc
        cli = pc.find_cli()
        if not cli or not os.path.exists(path):
            raise
        out = os.path.join(tempfile.mkdtemp(prefix="compare-"), "in.png")
        subprocess.run([str(cli), "convert", path, out], check=True, capture_output=True)
        return pngio.read(out)


def bare_check(argv):
    """`--check` followed by a file name, not a list of views, is the bare flag (as before views existed): put the
    file back among the positionals."""
    out = []
    for i, t in enumerate(argv):
        nxt = argv[i + 1] if i + 1 < len(argv) else ""
        views = nxt and all(v.strip().lower() in VIEWS + ("all",) for v in nxt.split(","))
        out.append("--check=local" if t == "--check" and nxt and not nxt.startswith("-") and not views else t)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("before"); ap.add_argument("after"); ap.add_argument("out")
    ap.add_argument("--rect", type=int, nargs=4)
    ap.add_argument("--scale", type=float, default=3, help="enlargement (3) or reduction (0.5) of the region")
    ap.add_argument("--check", nargs="?", const="local", default=None, metavar="VIEWS",
                    help="check views, a comma list of local, solar, lum, negative, sat, or all (bare: local)")
    ap.add_argument("--gain", type=float, default=5.0, help="contrast of the local check view")
    ap.add_argument("--origin", type=int, nargs=2, default=[0, 0])
    ap.add_argument("--marks", nargs="*", default=[])
    a = ap.parse_args(bare_check(sys.argv[1:]))
    if a.scale <= 0:
        ap.error("--scale must be above 0 (3 enlarges, 0.5 shrinks)")

    w, h, A = read(a.before)
    w2, h2, B = read(a.after)
    assert (w, h) == (w2, h2), "images differ in size"
    for m in a.marks:
        v = [float(t) for t in m.split(",")]
        X, Y, r = int(v[0]), int(v[1]), (v[2] if len(v) > 2 else 4.0)
        cx, cy = X - a.origin[0], Y - a.origin[1]
        parts = []
        for name, P in (("before", A), ("after", B)):
            st = mark_stats(P, cx, cy, r)
            parts.append(f"{name} " + ("outside the crop" if st is None else
                                       "dY %+5.1f (noise %.1f) red %+.3f yellow %+.3f" % (st[0], st[3], st[1], st[2])))
        print(f"mark {X},{Y} r{r:g}: " + "   ".join(parts))
    img = sheet(A, B, a.rect or (0, 0, w, h), a.scale, parse_views(a.check), a.gain)
    pngio.write(a.out, len(img[0]), len(img), img)
    print(f"{a.out}: {len(img[0])}x{len(img)}")


if __name__ == "__main__":
    main()
