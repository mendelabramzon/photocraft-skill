#!/usr/bin/env python3
"""Side-by-side before/after of the same region, enlarged, for judging a retouch.

usage: compare.py before.png after.png out.png [--rect x y w h] [--scale 3] [--check]
                  [--origin cropX cropY --marks X,Y X,Y …]

Both images must have the same size (e.g. two crops with the same offset). --rect is in those images'
pixels (default: everything). --check adds the retoucher's "check layer" view under each: luminance with
strong local contrast, which shows blotches and uneven tone that colour hides; it's how D&B gets judged.
--marks prints, for each mark (full-image coords; --origin = where the crops sit), how much darker (dY,
levels), redder ((R-G)/Y) and yellower than the skin 14-22 px around it the mark is, before and after.
A good fix keeps the signs and shrinks the numbers; darker-but-not-redder after reads as a bruise.
"""
import argparse
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pngio

ap = argparse.ArgumentParser()
ap.add_argument("before"); ap.add_argument("after"); ap.add_argument("out")
ap.add_argument("--rect", type=int, nargs=4)
ap.add_argument("--scale", type=int, default=3)
ap.add_argument("--check", action="store_true")
ap.add_argument("--gain", type=float, default=5.0, help="contrast of the check view")
ap.add_argument("--origin", type=int, nargs=2, default=[0, 0])
ap.add_argument("--marks", nargs="*", default=[])
a = ap.parse_args()

w, h, A = pngio.read(a.before)
w2, h2, B = pngio.read(a.after)
assert (w, h) == (w2, h2), "images differ in size"


def mark_stats(P, cx, cy):
    def ring(r0, r1):
        s = [0.0, 0.0, 0.0]; n = 0
        for y in range(max(0, cy - r1), min(h, cy + r1 + 1)):
            for x in range(max(0, cx - r1), min(w, cx + r1 + 1)):
                if r0 * r0 <= (x - cx) ** 2 + (y - cy) ** 2 <= r1 * r1:
                    p = P[y][x]; s = [s[i] + p[i] for i in range(3)]; n += 1
        r, g, b = (v / n for v in s); Y = 0.3 * r + 0.59 * g + 0.11 * b
        return Y, (r - g) / Y, ((r + g) / 2 - b) / Y
    c, o = ring(0, 4), ring(14, 22)
    return c[0] - o[0], c[1] - o[1], c[2] - o[2]


for m in a.marks:
    X, Y = (int(v) for v in m.split(","))
    cx, cy = X - a.origin[0], Y - a.origin[1]
    print(f"mark {X},{Y}: " + "   ".join("%s dY %+5.1f red %+.3f yellow %+.3f" % ((name,) + mark_stats(P, cx, cy))
                                         for name, P in (("before", A), ("after", B))))
x0, y0, rw, rh = a.rect or (0, 0, w, h)
S = a.scale
gap = 6


def crop(P):
    return [row[x0:x0 + rw] for row in P[y0:y0 + rh]]


def check(P):
    """Luminance minus its local mean (box 15), times gain, around mid grey."""
    L = [[0.3 * p[0] + 0.59 * p[1] + 0.11 * p[2] for p in row] for row in P]
    r = 7
    out = []
    for y in range(rh):
        ys = range(max(0, y - r), min(rh, y + r + 1))
        row = []
        for x in range(rw):
            xs = range(max(0, x - r), min(rw, x + r + 1))
            m = sum(L[yy][xx] for yy in ys for xx in xs) / (len(ys) * len(xs))
            v = int(max(0, min(255, 128 + a.gain * (L[y][x] - m))))
            row.append((v, v, v))
        out.append(row)
    return out


panels = [crop(A), crop(B)]
if a.check:
    panels += [check(panels[0]), check(panels[1])]
cols = 2
rows = len(panels) // cols
W = cols * rw * S + (cols - 1) * gap
H = rows * rh * S + (rows - 1) * gap
img = [[(255, 255, 255)] * W for _ in range(H)]
for k, P in enumerate(panels):
    oxp = (k % cols) * (rw * S + gap)
    oyp = (k // cols) * (rh * S + gap)
    for y in range(rh * S):
        src = P[y // S]
        dst = img[oyp + y]
        for x in range(rw * S):
            dst[oxp + x] = src[x // S]
pngio.write(a.out, W, H, img)
print(f"{a.out}: {W}x{H}")
