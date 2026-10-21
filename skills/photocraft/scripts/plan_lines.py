#!/usr/bin/env python3
"""Plan power-line and wire removal: find thin dark (or light) lines across smooth background (sky, a plain wall) and
heal each with Healing Brush strokes along it that copy clean background from beside the wire.

A wire comes out cleanly with healing strokes along it in segments, each copying background from a little to one side,
so the sky's grain and gradient run on through where the wire was. Where the wire crosses structure (a pole, a
branch, a roof edge) healing smears, so the strokes stop there; those spots are listed for the clone stamp.

  - ridge residual: how much darker (--polarity light: lighter) each pixel is than a median of the image at a radius
    of 2-3x the widest wire (crop + filter.noise.median from the CLI), only where the background is smooth
  - line pixels: residual over --threshold x the noise, grown by hysteresis, thinned to a 1 px centreline and traced
    into paths (crossings split them). Only long, smooth, thin paths count as wires: twigs and branches are crooked
  - each path becomes strokes: brush = wire width + margin; one offset per stroke, perpendicular to the wire, to the
    side where the strip it copies is clean (no other wire, smooth, the same tone and grain). A stroke with no clean
    side is split; a piece too short to split falls back to --fallback (a content-aware Remove stroke by default)

usage: plan_lines.py crop.png ref.png cropX cropY [--area area.json] [--polarity dark|light] [--layer ID]
                     [--sample currentAndBelow] [--steps steps.json] [--overlay overlay.png]
crop.png  the region at full resolution (image.crop); ref.png the same + filter.noise.median radius 12 (2-3x the
          widest wire or more; thicker cables need a bigger radius)
area.json optional {"skin": [[x, y], ...] (where to look: the sky), "exclude": [...]}, full-image coords
Writes steps.json for pc.py script and overlay.png: red = stroke, cyan = the strip it copies, yellow = fallback
stroke, orange circle = where a wire meets structure (finish with the clone stamp), magenta = a line it rejected
as too wide or crooked (a branch, an edge; or a wire in a tangle: add a stroke by hand).
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pngio
from plan_spots import draw_circle, draw_line, find_source, gradient, heal_step, load_area, overlay_image, robust_sigma, texture

N8 = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (-1, -1), (1, -1)]  # 4-neighbours first


def thin(mask, w, h):
    """Zhang-Suen thinning to a 1 px skeleton."""
    m = bytearray(mask)
    for x in range(w):
        m[x] = m[(h - 1) * w + x] = 0
    for y in range(h):
        m[y * w] = m[y * w + w - 1] = 0
    pts = [i for i in range(w * h) if m[i]]
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            rm = []
            for i in pts:
                if not m[i]:
                    continue
                p2, p3, p4, p5 = m[i - w], m[i - w + 1], m[i + 1], m[i + w + 1]
                p6, p7, p8, p9 = m[i + w], m[i + w - 1], m[i - 1], m[i - w - 1]
                b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
                if b < 2 or b > 6:
                    continue
                seq = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
                if sum(1 for u, v in zip(seq, seq[1:]) if not u and v) != 1:
                    continue
                if step == 0 and (p2 and p4 and p6 or p4 and p6 and p8):
                    continue
                if step == 1 and (p2 and p4 and p8 or p2 and p6 and p8):
                    continue
                rm.append(i)
            for i in rm:
                m[i] = 0
            changed = changed or bool(rm)
        pts = [i for i in pts if m[i]]
    return m


def trace(sk, w, h):
    """Paths of a skeleton: pixel index lists between endpoints and junctions (crossing number != 2)."""
    def nbrs(i):
        x, y = i % w, i // w
        return [(y + dy) * w + x + dx for dx, dy in N8 if 0 <= x + dx < w and 0 <= y + dy < h and sk[(y + dy) * w + x + dx]]

    def crossings(i):
        x, y = i % w, i // w
        ring = [sk[(y + dy) * w + x + dx] if 0 <= x + dx < w and 0 <= y + dy < h else 0
                for dx, dy in ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))]
        return sum(1 for u, v in zip(ring, ring[1:] + ring[:1]) if not u and v)

    pix = [i for i in range(w * h) if sk[i]]
    node = {i for i in pix if crossings(i) != 2}
    used = set()  # traversed (a, b) steps
    paths = []
    for start in list(node) + pix:
        for nb in nbrs(start):
            if (start, nb) in used:
                continue
            path, prev, cur = [start], start, nb
            used.add((start, nb)); used.add((nb, start))
            while True:
                path.append(cur)
                if cur in node or cur == start:
                    break
                nxt = [n for n in nbrs(cur) if n != prev and (cur, n) not in used and n not in path[-3:]]
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                used.add((prev, cur)); used.add((cur, prev))
            paths.append(path)
        if start not in node and all((start, n) in used for n in nbrs(start)):
            node.add(start)  # so a loop is traced once
    return paths


def distance_to(mask, w, h, cap=80):
    """Approximate distance (px, chamfer 3-4) from every pixel to the nearest truthy pixel of mask, up to cap."""
    big = 3 * cap
    d = [0 if mask[i] else big for i in range(w * h)]
    for y in range(h):
        r = y * w
        for x in range(w):
            i = r + x
            v = d[i]
            if v == 0:
                continue
            if x > 0: v = min(v, d[i - 1] + 3)
            if y > 0:
                v = min(v, d[i - w] + 3)
                if x > 0: v = min(v, d[i - w - 1] + 4)
                if x < w - 1: v = min(v, d[i - w + 1] + 4)
            d[i] = v
    for y in range(h - 1, -1, -1):
        r = y * w
        for x in range(w - 1, -1, -1):
            i = r + x
            v = d[i]
            if v == 0:
                continue
            if x < w - 1: v = min(v, d[i + 1] + 3)
            if y < h - 1:
                v = min(v, d[i + w] + 3)
                if x < w - 1: v = min(v, d[i + w + 1] + 4)
                if x > 0: v = min(v, d[i + w - 1] + 4)
            d[i] = v
    return [v / 3 for v in d]


def link(paths, w, max_gap=4, max_angle=25, min_len=6):
    """Join traced paths that continue each other through a junction (or across a small gap): the skeleton of a
    real wire grows little spurs, and every spur cuts the wire at a junction. Ends must nearly meet and point at
    each other within max_angle degrees; best-aligned pairs join first. Paths are pixel-index lists, shorter ones
    (spurs, specks) are dropped; returns lists of (x, y)."""
    P = [[(i % w, i // w) for i in p] for p in paths if len(p) >= min_len]

    def end_dir(p, at_start, k=10):
        a, b = (p[min(k, len(p) - 1)], p[0]) if at_start else (p[-1 - min(k, len(p) - 1)], p[-1])
        d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)  # pointing out of the path
    ends = [(k, s, (p[0] if s else p[-1]), end_dir(p, s)) for k, p in enumerate(P) for s in (True, False)]
    grid = {}
    for e, (_, _, pt, _) in enumerate(ends):
        grid.setdefault((pt[0] // max_gap, pt[1] // max_gap), []).append(e)
    cos_min = math.cos(math.radians(max_angle))
    pairs = []
    for ea, (ka, sa, pa, da) in enumerate(ends):
        gx, gy = pa[0] // max_gap, pa[1] // max_gap
        for nb in ((gx + i, gy + j) for i in (-1, 0, 1) for j in (-1, 0, 1)):
            for eb in grid.get(nb, ()):
                kb, sb, pb, db = ends[eb]
                if eb <= ea or kb == ka:
                    continue
                gap = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                c = -(da[0] * db[0] + da[1] * db[1])  # 1 = the two ends point straight at each other
                if gap <= max_gap and c >= cos_min:
                    pairs.append((c - 0.02 * gap, ea, eb))
    # greedy, best first; each end joins once, and never into a loop (union-find over paths)
    root = list(range(len(P)))

    def find(k):
        while root[k] != k:
            root[k] = root[root[k]]; k = root[k]
        return k
    nxt = {}  # end index -> the end it is joined to
    for _, ea, eb in sorted(pairs, reverse=True):
        ka, kb = ends[ea][0], ends[eb][0]
        if ea in nxt or eb in nxt or find(ka) == find(kb):
            continue
        nxt[ea], nxt[eb] = eb, ea
        root[find(ka)] = find(kb)
    # walk each chain from a free end
    out, seen = [], set()
    for k in range(len(P)):
        if k in seen:
            continue
        # find a free end of this chain: start at path k, follow joins from its start end
        e = 2 * k
        cur, at_start = k, True
        while (2 * cur + (0 if at_start else 1)) in nxt:
            o = nxt[2 * cur + (0 if at_start else 1)]
            cur, at_start = ends[o][0], not ends[o][1]
            if cur == k:
                break
        chain = []
        while True:
            seen.add(cur)
            p = P[cur] if at_start else P[cur][::-1]
            chain.extend(p if not chain else p[1:])
            tail = 2 * cur + (1 if at_start else 0)
            if tail not in nxt:
                break
            o = nxt[tail]
            cur, at_start = ends[o][0], ends[o][1]
            if cur in seen:
                break
        out.append(chain)
    return out


def smooth_path(pts, k):
    """Moving average of a polyline (window 2k+1, ends kept)."""
    n = len(pts)
    out = []
    for i in range(n):
        a, b = max(0, i - k), min(n, i + k + 1)
        out.append((sum(p[0] for p in pts[a:b]) / (b - a), sum(p[1] for p in pts[a:b]) / (b - a)))
    return out


def split_at_corners(pts, win=8, max_turn=18):
    """Cut a path where it turns sharply: at a shallow crossing the skeleton runs from one wire onto the other."""
    n = len(pts)
    if n < 2 * win + 3:
        return [pts]
    turn = [0.0] * n
    for i in range(win, n - win):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - win], pts[i], pts[i + win]
        a1, a2 = math.atan2(y1 - y0, x1 - x0), math.atan2(y2 - y1, x2 - x1)
        turn[i] = abs((a2 - a1 + math.pi) % (2 * math.pi) - math.pi)
    cuts = [i for i in range(win, n - win) if turn[i] > math.radians(max_turn) and turn[i] == max(turn[max(0, i - win):i + win + 1])]
    out, s0 = [], 0
    for c in cuts:
        out.append(pts[s0:c + 1]); s0 = c
    out.append(pts[s0:])
    return out


def length(pts):
    return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))


def resample(pts, step):
    """Points every `step` px along the polyline, ends included."""
    out, carry = [pts[0]], 0.0
    for p, q in zip(pts, pts[1:]):
        seg = math.hypot(q[0] - p[0], q[1] - p[1])
        t = step - carry
        while t <= seg:
            out.append((p[0] + (q[0] - p[0]) * t / seg, p[1] + (q[1] - p[1]) * t / seg))
            t += step
        carry = seg - (t - step)
    if math.hypot(out[-1][0] - pts[-1][0], out[-1][1] - pts[-1][1]) > 0.5:
        out.append(pts[-1])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crop"); ap.add_argument("ref"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
    ap.add_argument("--area")
    ap.add_argument("--polarity", choices=["dark", "light"], default="dark", help="dark wires on sky, or lit ones on storm cloud")
    ap.add_argument("--threshold", type=float, default=4.0, help="x noise: a line pixel's residual")
    ap.add_argument("--min-contrast", type=float, default=4.0, help="levels: fainter lines are left alone")
    ap.add_argument("--relative-contrast", type=float, default=0.4,
                    help="a line must be at least this fraction as dark as the strong wires (75th percentile); "
                         "dark gaps between cloud wisps are fainter")
    ap.add_argument("--min-length", type=float, default=40, help="px: shorter paths are twigs, specks, texture")
    ap.add_argument("--max-width", type=float, default=9, help="px: wider is a pole, a branch, a cloud edge")
    ap.add_argument("--max-wiggle", type=float, default=0.9,
                    help="px: how far a wire may stray from its own smooth course (branches zigzag)")
    ap.add_argument("--max-gradient", type=float, default=4.0, help="levels/px: background steeper than this is structure")
    ap.add_argument("--structure-gradient", type=float, default=12.0,
                    help="levels/px: a background edge this hard is structure no brush may touch (poles, roofs, branches)")
    ap.add_argument("--median-radius", type=int, default=12, help="the radius ref.png was made with")
    ap.add_argument("--margin", type=float, default=2.5, help="px of background on each side of the wire under the brush")
    ap.add_argument("--segment", type=float, default=160, help="px: longest stroke with one source offset")
    ap.add_argument("--tool", choices=["heal", "remove", "spot"], default="heal",
                    help="heal: Healing Brush with a chosen clean source (default); remove / spot: content-aware strokes")
    ap.add_argument("--fallback", choices=["remove", "spot", "none"], default="remove",
                    help="for a piece with no clean source on either side")
    ap.add_argument("--crossing-tool", choices=["heal", "remove", "spot"], default="heal",
                    help="where wires cross or run together (done last, one brush over all of them)")
    ap.add_argument("--min-free-length", type=float, default=250,
                    help="px: a line shorter than this with hard structure at both ends is hardware (lamp arm, crossarm)")
    ap.add_argument("--max-bundle", type=int, default=80, help="px: widest brush for wires running together")
    ap.add_argument("--hardness", type=int, default=80)
    ap.add_argument("--layer", type=int, help="the retouch layer (an empty layer: --sample currentAndBelow)")
    ap.add_argument("--sample", default="current", choices=["current", "currentAndBelow", "all"])
    ap.add_argument("--steps", default="steps.json")
    ap.add_argument("--overlay")
    ap.add_argument("--debug", action="append", default=[], metavar="X,Y",
                    help="print what happened to any line passing this point (full-image coords). Repeatable")
    a = ap.parse_args()

    w, h, R, G, B = imgops.load(a.crop)
    w2, h2, Rr, Gr, Br = imgops.load(a.ref)
    assert (w, h) == (w2, h2), "crop and ref differ in size"
    N = w * h
    Y = [imgops.lum(*v) for v in zip(R, G, B)]
    Yr = [imgops.lum(*v) for v in zip(Rr, Gr, Br)]
    area = load_area(a.area, a.ox, a.oy, w, h)
    grad = gradient(imgops.gauss(Yr, w, h, 1.5), w, h)  # of the background (the median: wires gone)
    smooth = bytearray(1 if area[i] and grad[i] < a.max_gradient and Yr[i] > 12 else 0 for i in range(N))

    # ridge residual and line pixels (hysteresis: strong seeds grown into weaker neighbours)
    sign = 1 if a.polarity == "dark" else -1
    res = imgops.gauss([sign * (yr - y) for y, yr in zip(Y, Yr)], w, h, 0.6)
    sig = robust_sigma([res[i] for i in range(0, N, 3) if smooth[i]])
    hi = max(a.threshold * sig, a.min_contrast)
    weak = bytearray(1 if smooth[i] and res[i] > 0.5 * hi else 0 for i in range(N))
    line = bytearray(N)
    for pix in imgops.components(weak, w, h):
        if len(pix) < a.min_length / 2 or max(res[i] for i in pix) < hi:
            continue
        for i in pix:
            line[i] = 1

    # centrelines -> paths; keep the long, thin, smooth ones
    paths, dropped, crooked = [], [], []
    rejected = {"short": 0, "wide": 0, "crooked": 0, "faint": 0, "hardware": 0}
    dbg = [(float(v.split(",")[0]) - a.ox, float(v.split(",")[1]) - a.oy) for v in a.debug]

    def say(pts, msg):
        """Debug: report msg for each --debug point this polyline passes within 6 px."""
        for x, y in dbg:
            if any(abs(px - x) < 6 and abs(py - y) < 6 for px, py in pts):
                print(f"debug {x + a.ox:.0f},{y + a.oy:.0f}: {msg}", file=sys.stderr)

    pieces = []
    for p in link(trace(thin(line, w, h), w, h), w):
        sm = smooth_path(p, 3)
        k0 = 0
        for piece in split_at_corners(sm):
            e0, e1 = p[min(k0, len(p) - 1)], p[min(k0 + len(piece) - 1, len(p) - 1)]
            pieces.append((piece, (e0[1] * w + e0[0], e1[1] * w + e1[0])))
            k0 += len(piece) - 1
    for pts, ends in pieces:
        L = length(pts)
        if L < min(12, a.min_length):
            rejected["short"] += 1
            continue
        # wiggle: how far the centreline strays from its own course smoothed over ~40 px (interior points only:
        # at the ends a moving average slides along the line)
        coarse = smooth_path(pts, 20)
        inner = list(zip(pts, coarse))[20:-20] or list(zip(pts, coarse))
        wig = math.sqrt(sum((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for p, q in inner) / len(inner))
        # width: area under the residual across the wire / its peak, sampled along it
        widths, contrast = [], []
        for k in range(2, len(pts) - 2, 6):
            (x0, y0), (x1, y1) = pts[k - 2], pts[k + 2]
            dl = math.hypot(x1 - x0, y1 - y0) or 1.0
            nx, ny = -(y1 - y0) / dl, (x1 - x0) / dl
            prof = []
            for t in range(-int(a.max_width) - 2, int(a.max_width) + 3):
                x, y = int(round(pts[k][0] + nx * t)), int(round(pts[k][1] + ny * t))
                prof.append(res[y * w + x] if 0 <= x < w and 0 <= y < h else 0.0)
            pk = max(prof)
            if pk > 0:
                widths.append(sum(max(v, 0.0) for v in prof) / pk)
                contrast.append(pk)
        if not widths:
            continue
        width = sorted(widths)[len(widths) // 2]
        if width > a.max_width:
            rejected["wide"] += 1
            dropped.append(pts)
            say(pts, f"line {L:.0f} px, {width:.1f} px wide: too wide (--max-width {a.max_width:g})")
            continue
        info = {"pts": pts, "width": width, "contrast": sorted(contrast)[len(contrast) // 2], "len": L, "ends": ends, "wig": wig}
        if L < a.min_length or (wig > a.max_wiggle and L < 6 * a.min_length):
            crooked.append(info)  # too short or crooked to be a wire on its own; may be part of one (a tangle)
            continue
        paths.append(info)

    # contrast: a wire is about as dark as the others, or (a thin, distant one) as crisp: dark for its width. A dark
    # gap between cloud wisps is faint and soft
    strong = sorted(p["contrast"] for p in paths)
    floor_c = max(a.min_contrast, a.relative_contrast * strong[3 * len(strong) // 4]) if strong else a.min_contrast
    crisp = sorted(p["contrast"] / max(p["width"], 1.5) for p in paths if p["contrast"] >= floor_c)
    floor_s = 0.25 * crisp[len(crisp) // 2] if crisp else 0.0

    def wire_like(p):  # dark like the wires, or crisp for its width, or long and dead straight (no cloud is)
        return (p["contrast"] >= floor_c or p["contrast"] / max(p["width"], 1.5) >= floor_s
                or (p["len"] >= 300 and p["wig"] <= 0.5 and p["contrast"] >= 2 * a.min_contrast))
    for p in paths:
        if not wire_like(p):
            rejected["faint"] += 1
            say(p["pts"], f"line {p['len']:.0f} px, contrast {p['contrast']:.0f} (< {floor_c:.0f}), "
                          f"{p['contrast'] / max(p['width'], 1.5):.1f} per px of width (< {floor_s:.1f}): too faint and soft, rejected")
        else:
            say(p["pts"], f"wire {p['len']:.0f} px, {p['width']:.1f} px wide, wiggle {p['wig']:.2f}, contrast {p['contrast']:.0f}: accepted")
    paths = [p for p in paths if wire_like(p)]
    crooked = [c for c in crooked if wire_like(c)]

    # a crooked piece is part of a tangle of wires (where they converge on a pole the skeleton zigzags between
    # them) if it is thin, as dark as the wires, touches one and runs within 20 degrees of it; a branch crossing
    # a wire runs at its own angle and stays rejected
    def direction(pts):
        return math.atan2(pts[-1][1] - pts[0][1], pts[-1][0] - pts[0][0])
    wire_c = sorted(p["contrast"] for p in paths)[len(paths) // 2] if paths else 0

    def joins(c, p):
        reach = 2 * (p["width"] + 2 * a.margin)
        for e in (c["pts"][0], c["pts"][-1]):
            j = min(range(0, len(p["pts"]), 2), key=lambda j: (p["pts"][j][0] - e[0]) ** 2 + (p["pts"][j][1] - e[1]) ** 2)
            if math.hypot(p["pts"][j][0] - e[0], p["pts"][j][1] - e[1]) <= reach:
                lo, hi = max(0, j - 10), min(len(p["pts"]) - 1, j + 10)
                dd = abs((direction(c["pts"]) - direction(p["pts"][lo:hi + 1]) + math.pi / 2) % math.pi - math.pi / 2)
                if dd < math.radians(20):
                    return True
        return False
    tangle, todo = [], [c for c in crooked if c["contrast"] >= 0.5 * wire_c]
    grew = True
    while grew:  # a chain of tangle pieces joins the wires one link at a time
        grew = False
        for c in todo[:]:
            if any(joins(c, p) for p in paths + tangle):
                tangle.append(c); todo.remove(c); grew = True
    for c in crooked:
        if c not in tangle:
            if c["len"] < a.min_length:
                rejected["short"] += 1
            else:
                rejected["crooked"] += 1
                dropped.append(c["pts"])
        say(c["pts"], f"{'short' if c['len'] < a.min_length else 'crooked'} line {c['len']:.0f} px, wiggle {c['wig']:.2f}, "
                      f"contrast {c['contrast']:.0f} (wires {wire_c:.0f}): {'part of a wire or tangle, accepted' if c in tangle else 'rejected'}")
    paths += tangle

    # a short line held by hard structure at both ends is hardware (a crossarm, a lamp arm, a bracket), not a wire
    def at_structure(i):
        x, y = i % w, i // w
        return any(grad[(y + dy) * w + x + dx] > a.structure_gradient for dy in range(-6, 7, 2) for dx in range(-6, 7, 2)
                   if 0 <= x + dx < w and 0 <= y + dy < h)
    kept = []
    for p in paths:
        if p["len"] < a.min_free_length and all(at_structure(i) for i in p["ends"]):
            rejected["hardware"] += 1
            dropped.append(p["pts"])
            say(p["pts"], "short and held by structure at both ends: hardware, rejected")
        else:
            kept.append(p)
    paths = kept

    # where a wire meets structure (non-smooth background, not the crop border): finish there with the clone stamp
    def meets_structure(i):
        x, y = i % w, i // w
        if x < 3 or y < 3 or x > w - 4 or y > h - 4:
            return False
        return any(not smooth[(y + dy) * w + x + dx] and area[(y + dy) * w + x + dx]
                   for dy in range(-4, 5) for dx in range(-4, 5) if 0 <= x + dx < w and 0 <= y + dy < h)
    clone_spots = sorted({(i % w, i // w) for p in paths for i in p["ends"] if meets_structure(i)})

    # sources: smooth, not on (or right beside) any wire
    near = imgops.maxf([float(v) for v in line], w, h, 2)
    ok = bytearray(1 if smooth[i] and near[i] == 0 else 0 for i in range(N))
    tex = texture(Y, Yr, w, h)
    # no brush may touch structure (a pole, a branch, a roof) or leave the area: strokes are cut where they would.
    # Structure is a hard edge in the background (--structure-gradient; soft cloud edges heal fine) away from the
    # wires found: next to a wire the median itself has edges (it can't remove a bundle), so those don't count.
    # Whatever must never be touched (poles, lamps, branches) belongs outside area.json.
    wirezone = bytearray(N)
    for p in paths:
        for x, y in p["pts"]:
            wirezone[int(round(y)) * w + int(round(x))] = 1
    wz = distance_to(wirezone, w, h, cap=a.median_radius + 4)
    dstruct = distance_to(bytearray(1 if not area[i] or (grad[i] > a.structure_gradient and wz[i] > a.median_radius + 2) else 0
                                    for i in range(N)), w, h)
    cuts = []

    def clear_runs(seg, size):
        """Pieces of seg whose brush footprint stays on smooth background; records where it had to stop."""
        r = size / 2 + 1.5
        good = [dstruct[int(round(y)) * w + int(round(x))] > r for x, y in seg]
        runs, cur = [], []
        for p, g in zip(seg, good):
            if g:
                cur.append(p)
            else:
                if cur:
                    runs.append(cur); cuts.append(cur[-1])
                    say([cur[-1]], f"stroke (brush {size}) stops: structure or the area's edge within reach")
                cur = []
        if cur:
            runs.append(cur)
        if len(runs) > 1 or (runs and len(runs[0]) < len(seg)):
            if good and not good[0] and runs:
                cuts.append(runs[0][0])
        return [r_ for r_ in runs if len(r_) >= 2]

    def strip_cost(seg, off, size):
        """Cost of copying from seg shifted by off, or None if any of that strip isn't clean."""
        r = size / 2 + 1
        ring = [(dx, dy) for dx in range(-int(r), int(r) + 1, 2) for dy in range(-int(r), int(r) + 1, 2) if dx * dx + dy * dy <= r * r]
        cost = n = 0
        for x, y in seg[::2]:
            sx, sy = int(round(x + off[0])), int(round(y + off[1]))
            for dx, dy in ring:
                X, Y_ = sx + dx, sy + dy
                if not (0 <= X < w and 0 <= Y_ < h) or not ok[Y_ * w + X]:
                    return None
            xi, yi = int(round(x)), int(round(y))
            cost += abs(Yr[sy * w + sx] - Yr[yi * w + xi]) + 0.5 * abs(tex[sy * w + sx] - tex[yi * w + xi])
            n += 1
        return cost / max(n, 1) + 0.02 * math.hypot(*off)

    def best_offset(seg, size):
        (x0, y0), (x1, y1) = seg[0], seg[-1]
        dl = math.hypot(x1 - x0, y1 - y0) or 1.0
        best = None
        for d in (size + 3, size + 6, size + 10, size + 15, size + 22, size + 30):
            for rot in (0, 25, -25):
                c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
                nx, ny = -(y1 - y0) / dl, (x1 - x0) / dl
                nx, ny = nx * c - ny * s, nx * s + ny * c
                for sgn in (1, -1):
                    off = (round(sgn * nx * d), round(sgn * ny * d))
                    cost = strip_cost(seg, off, size)
                    if cost is not None and (best is None or cost < best[0]):
                        best = (cost, off)
            if best is not None:
                break  # the nearest clean distance wins
        return None if best is None else best[1]

    steps, drawn = [], []

    def plan(seg, size, tool=None, checked=False):
        if not checked:
            for run in clear_runs(seg, size):
                plan(run, size, tool, True)
            return
        if (tool or a.tool) == "heal":
            off = best_offset(seg, size)
            if off is not None:
                steps.append(heal_step(seg, size, a.hardness, off, a.layer, a.sample, a.ox, a.oy))
                drawn.append((seg, size, off, "heal"))
                say(seg, f"healing stroke, brush {size}, offset {off}")
                return
            if length(seg) > 3 * size:  # no clean side for the whole piece: try halves
                mid = len(seg) // 2
                plan(seg[:mid + 1], size, tool, True)
                plan(seg[mid:], size, tool, True)
                return
            tool = a.fallback
        else:
            tool = tool or a.tool
        if tool == "none":
            drawn.append((seg, size, None, "skipped"))
            return
        p = {"points": [[round(x + a.ox, 1), round(y + a.oy, 1)] for x, y in seg], "size": size, "hardness": a.hardness,
             "target": "pixels"}
        if a.layer is not None:
            p["layer"] = a.layer
        if tool == "remove":
            p.update({"closeLoops": False, "sampleAllLayers": a.sample != "current"})
            steps.append({"command": "paint.remove", "params": p})
        else:
            p.update({"type": "contentAware", "sampleAllLayers": a.sample != "current"})
            steps.append({"command": "paint.spotHealing", "params": p})
        drawn.append((seg, size, None, tool))
        say(seg, f"{tool} stroke, brush {size}")

    # free stretches first; where wires come within a brush width of each other (a crossing, a bundle), that part
    # is done last, once the wires around it are gone, with a brush over all of them: a stroke along one wire with
    # its neighbour under the edge of the dab would take the neighbour's tone and leave a smudge
    def extend(p, q, by):
        d = math.hypot(p[0] - q[0], p[1] - q[1]) or 1.0
        return (p[0] + (p[0] - q[0]) / d * by, p[1] + (p[1] - q[1]) / d * by)

    def to_border(p, q):  # how far along q->p until the crop edge
        d = math.hypot(p[0] - q[0], p[1] - q[1]) or 1.0
        ux, uy = (p[0] - q[0]) / d, (p[1] - q[1]) / d
        ts = [t for t in ((-p[0] / ux) if ux < 0 else (w - 1 - p[0]) / ux if ux > 0 else 1e9,
                          (-p[1] / uy) if uy < 0 else (h - 1 - p[1]) / uy if uy > 0 else 1e9) if t >= 0]
        return min(ts) if ts else 1e9

    later = []
    for idx, pth in enumerate(sorted(paths, key=lambda p: -p["len"])):
        size = max(4, int(math.ceil(pth["width"] * 1.25 + 2 * a.margin)))
        pts = pth["pts"]
        k = min(4, len(pts) - 1)
        ends = []
        for p, q in ((pts[0], pts[k]), (pts[-1], pts[-1 - k])):
            tb = to_border(p, q)  # a wire running off the crop: all the way out; else a brush width past the end
            ends.append(extend(p, q, tb + 1 if tb < 40 else size))
        pts = [ends[0]] + pts + [ends[1]]
        pts = [(min(max(x, 0), w - 1), min(max(y, 0), h - 1)) for x, y in pts]
        dense = resample(pts, 3)
        order = sorted(paths, key=lambda p: -p["len"])
        others = [q for j, o in enumerate(order) if j != idx for q in o["pts"][::2]]
        other_paths = [o["pts"][::2] for j, o in enumerate(order) if j != idx]
        crossing = [any(abs(x - qx) < size and abs(y - qy) < size and math.hypot(x - qx, y - qy) < size
                        for qx, qy in others) for x, y in dense]
        runs, s0 = [], 0
        for i in range(1, len(dense) + 1):
            if i == len(dense) or crossing[i] != crossing[s0]:
                runs.append((crossing[s0], dense[max(0, s0 - 1):i + 1]))
                s0 = i
        for is_cross, run in runs:
            if is_cross:
                # the brush covers every wire within reach (a crossing, or a bundle running together), so one
                # stroke clears them all and its edge lies on clean sky
                spread = 0.0  # the farthest neighbouring wire, by its closest approach
                for x, y in run[::3]:
                    for op in other_paths:
                        d = min((math.hypot(x - qx, y - qy) for qx, qy in op if abs(x - qx) < 3 * size and abs(y - qy) < 3 * size),
                                default=None)
                        if d is not None and d < 2.5 * size:
                            spread = max(spread, d)
                bsize = int(math.ceil(2 * spread + size))
                if bsize > a.max_bundle:  # a tangle (on a pole, a junction box): clone stamp work
                    cuts.append(run[len(run) // 2])
                    say(run, f"wires run together: brush {bsize} > --max-bundle {a.max_bundle}, left for the clone stamp")
                    continue
                later.append((run, bsize))
                continue
            nseg = max(1, math.ceil(length(run) / a.segment))
            per = math.ceil(len(run) / nseg)
            for q0 in range(0, len(run) - 1, per):
                plan(run[q0:q0 + per + 1], size)
    for run, size in later:
        if len(run) >= 2:
            plan(run, size, tool=a.crossing_tool)

    # touch-ups: bits of a found wire that no brush covers (between strokes cut short or split) get a dab each.
    # Covered means well inside a brush: on the rim of a dab healing keeps the boundary's tone, so a wire stays
    covered = bytearray(N)
    for seg, size, off, kind in drawn:
        if kind == "skipped":
            continue
        r = max(1.0, size / 2 - 2)
        for x, y in resample(seg, 2) if len(seg) > 1 else seg:
            for dy in range(-int(r), int(r) + 1):
                for dx in range(-int(r), int(r) + 1):
                    X, Yy = int(round(x)) + dx, int(round(y)) + dy
                    if dx * dx + dy * dy <= r * r and 0 <= X < w and 0 <= Yy < h:
                        covered[Yy * w + X] = 1
    left = bytearray(1 if line[i] and not covered[i] and wz[i] <= 8 and dstruct[i] > 6 else 0 for i in range(N))
    touchups = 0
    for pix in imgops.components(left, w, h):
        if len(pix) < 4:
            continue
        # a short stroke along the bit's own axis (a dab if it is round)
        n = len(pix)
        mx = sum(i % w for i in pix) / n; my = sum(i // w for i in pix) / n
        sxx = sum((i % w - mx) ** 2 for i in pix) / n; syy = sum((i // w - my) ** 2 for i in pix) / n
        sxy = sum((i % w - mx) * (i // w - my) for i in pix) / n
        ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
        ux, uy = math.cos(ang), math.sin(ang)
        proj = [(i % w - mx) * ux + (i // w - my) * uy for i in pix]
        t0, t1 = min(proj), max(proj)
        thick = n / max(1.0, t1 - t0 + 1)
        size = int(math.ceil(max(thick, 2.0) * 1.25 + 2 * a.margin + 2))
        if size > 2 * a.max_width + 8:
            continue  # not a wire bit
        seg = resample([(mx + ux * t0, my + uy * t0), (mx + ux * t1, my + uy * t1)], 3) if t1 - t0 > 2 else [(mx, my), (mx + 0.1, my)]
        before = len(steps)
        plan(seg, size)
        touchups += len(steps) > before
    json.dump(steps, open(a.steps, "w"))

    clone_spots = sorted(set(clone_spots) | {(int(x), int(y)) for x, y in cuts})
    if a.overlay:
        img = overlay_image(pngio.read(a.crop)[2], w, h, 1)
        for seg, size, off, kind in drawn:
            col = {"heal": (255, 40, 40), "skipped": (150, 150, 150)}.get(kind, (255, 230, 0))
            for p, q in zip(seg, seg[1:]):
                draw_line(img, p, q, col, 1)
                if off:
                    draw_line(img, (p[0] + off[0], p[1] + off[1]), (q[0] + off[0], q[1] + off[1]), (0, 230, 255), 1, dash=2)
        for pts in dropped:  # wide or crooked: not treated as a wire
            for p, q in zip(pts, pts[1:]):
                draw_line(img, p, q, (220, 0, 220), 1)
        for x, y in clone_spots:
            draw_circle(img, x, y, 7, (255, 140, 0), 1)
        pngio.write(a.overlay, w, h, img)

    kinds = [d[3] for d in drawn]
    print(json.dumps({"wires": len(paths), "tangled": len(tangle), "touchups": touchups, "length": round(sum(p["len"] for p in paths)), "strokes": len(steps),
                      "heal": kinds.count("heal"), "remove": kinds.count("remove"), "spot": kinds.count("spot"),
                      "skipped": kinds.count("skipped"), "widths": sorted(round(p["width"], 1) for p in paths)[:20],
                      "noise": round(sig, 2), "rejected": rejected,
                      "cloneSpots": [[x + a.ox, y + a.oy] for x, y in clone_spots][:30]}))


if __name__ == "__main__":
    main()
