#!/usr/bin/env python3
"""Draw a labelled coordinate grid over a crop so you can read full-image coordinates off it
(for area.json polygons, exclusion boxes, healing targets).

usage: grid.py crop.png cropX cropY out.png [--step 50] [--scale 2] [--area area.json]

Lines every --step px in full-image coordinates (every 2nd one brighter), labelled with their
coordinate. --area draws the skin polygon (green) and exclusions (red) from an area.json, so you
can check them before planning.
"""
import argparse
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pngio
from imgops import FONT


ap = argparse.ArgumentParser()
ap.add_argument("crop"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int); ap.add_argument("out")
ap.add_argument("--step", type=int, default=50)
ap.add_argument("--scale", type=int, default=2)
ap.add_argument("--area")
a = ap.parse_args()

w, h, P = pngio.read(a.crop)
S = a.scale
W, H = w * S, h * S
img = [[P[y // S][x // S] for x in range(W)] for y in range(H)]


def put(x, y, c):
    if 0 <= x < W and 0 <= y < H:
        img[y][x] = c


def text(x, y, s, c, k=2):
    for i, ch in enumerate(s):
        bits = FONT[ch]
        for r in range(5):
            for col in range(3):
                if bits[r * 3 + col] == "1":
                    for dy in range(k):
                        for dx in range(k):
                            put(x + (i * 4 + col) * k + dx, y + r * k + dy, c)


def blend(c, d, t=0.55):
    return tuple(int(c[i] * (1 - t) + d[i] * t) for i in range(3))


first_x = (a.ox + a.step - 1) // a.step * a.step
first_y = (a.oy + a.step - 1) // a.step * a.step
for gx in range(first_x, a.ox + w, a.step):
    major = gx % (2 * a.step) == 0
    col = (255, 230, 0) if major else (0, 220, 255)
    X = (gx - a.ox) * S
    for Y in range(H):
        img[Y][X] = blend(img[Y][X], col, 0.8 if major else 0.5)
    for y0 in range(4, H, 300):
        text(X + 3, y0, str(gx), col)
for gy in range(first_y, a.oy + h, a.step):
    major = gy % (2 * a.step) == 0
    col = (255, 230, 0) if major else (0, 220, 255)
    Y = (gy - a.oy) * S
    for X in range(W):
        img[Y][X] = blend(img[Y][X], col, 0.8 if major else 0.5)
    for x0 in range(4, W, 300):
        text(x0, Y + 3, str(gy), col)

if a.area:
    cfg = json.load(open(a.area))

    def line(p, q, c):
        (x0, y0), (x1, y1) = p, q
        n = int(max(abs(x1 - x0), abs(y1 - y0)) * S) + 1
        for i in range(n + 1):
            t = i / n
            put(int(((x0 + (x1 - x0) * t) - a.ox) * S), int(((y0 + (y1 - y0) * t) - a.oy) * S), c)

    def poly(pts, c):
        for i in range(len(pts)):
            line(pts[i], pts[(i + 1) % len(pts)], c)

    skins = cfg["skin"] if isinstance(cfg["skin"][0][0], list) else [cfg["skin"]]
    for pts in skins:
        poly(pts, (0, 255, 0))
    for e in cfg.get("exclude", []):
        if isinstance(e[0], list):
            poly(e, (255, 40, 40))
        else:
            x0, y0, x1, y1 = e
            poly([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], (255, 40, 40))

pngio.write(a.out, W, H, img)
print(f"{a.out}: {W}x{H}")
