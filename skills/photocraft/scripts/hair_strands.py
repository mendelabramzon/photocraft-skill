#!/usr/bin/env python3
"""Rebuild a hair or fur edge after the cut: contract the mask, then strands along the hair's growth direction.

A refined mask (select.refineEdge, Select and Mask) gives hair a soft, fuzzy outline with no strands in it, or
cuts the strands off: on a new background it reads as a blurred helmet. Adobe's two hair tutorials finish it by hand:
  contract    Filter > Other > Minimum on the mask (about 6 px on a high-res bear) pulls the fuzzy rim of old
              backdrop in under the hair (pro-masking: "Use AI to mask faster, then refine like a pro")
  reveal      then paint white on the mask with a strand-shaped brush, Shape Dynamics' angle set to Direction,
              short strokes along the coat's growth direction: the photo's own fur comes back in strand shapes
  paint       for gaps nothing can reveal, paint new strands on a layer below the subject with a hair brush,
              colour sampled from the hair (several colours: one reads as fake), then Gaussian Blur 1 px to match
              the photo's depth of field (select-mask-hair: "Paint digital hair")
This does both by measurement:
  edge        the cut's 0.5 contour inside the zone, contracted by --contract px (the same square Minimum as
              PhotoCraft's, only inside the zone, faded by a 2 px Gaussian at its border); the soft rim's width and how far
              the photo's own faint strands reach past the cut set the defaults
  direction   the hair's own direction: the structure tensor of unit luminance gradients (each pixel votes once),
              from inside the hair (opaque, 2 px or more from the edge, off the excludes) and, weighted up, from the
              photo's own faint strands past the cut, so the silhouette itself (whose gradient runs across the tips)
              never sets it and strands sticking out of combed hair do. Coherence under 0.2 (blown or blurred hair, a
              smooth helmet) means no direction: counted and warned about, no strand painted there, revealed ones
              follow the outline's normal
  strands     roots 1-4 px inside the contracted edge, traced outward along the field with an outward bias
              (--follow) and a little wander, tapered like a real tip, stopped at the crop, the zone's border and
              the excludes (face, skin, ears, an earring). Along an edge where the hair runs parallel to it,
              neighbours share a sign, so the flow is consistent, not a comb
  reveal      new mask = the contracted mask plus 4 px strokes, each weighted by how hair-like the photo is under
              it: the matting estimate (I - B) . (F - B) / |F - B|^2 against the clean backdrop B and the hair colour
              F, carried into the band by normalised convolution, and only on thin pixels (a strand stands off its
              surroundings) or at the hair's own edge: the strands inside a stroke come back at their real coverage,
              the backdrop between them and a smooth shadow on it stay out (the fur-brush stroke)
  paint       new strands on their own layer: strong along most of their length, thinning to a tip, coloured from
              the hair at the root mixed with a nearby tone from a palette of --colors hair tones, blurred like the
              photo's own isolated strands (the blur whose edge statistic matches theirs on test strands), at most
              Adobe's 1 px

usage: hair_strands.py orig.png cut.png X Y area.json OUTDIR [--mode both|reveal|paint] [--contract auto|PX]
                       [--length auto|PX] [--density auto|N] [--width 1.2] [--reveal-width 4] [--colors 4]
                       [--blur auto|PX] [--follow 0.5] [--background #hex] [--seed 1]
       hair_strands.py apply OUTDIR LAYER [--file in.psd --save out.psd]

orig.png   the photo cropped round the hair at full resolution (backdrop visible), even width and height
cut.png    the same crop of the cut layer alone (Background hidden), RGBA: its alpha is the current mask, before
           any Minimum (the planner contracts it)
X Y        the crop's place in the photo
area.json  "hair" (or "area"/"skin") = polygon(s) round the hair's outline where strands may grow, reaching well
           out over the backdrop and ending inside the crop; "exclude" = polygons or boxes strands must not enter
           (the face below the hairline, ears, shoulders, an earring, glasses)
OUTDIR     mask.png (the new mask: contracted, plus the revealed strands), which `apply` makes the cut layer's own
           mask inside the crop (its pixels stay the photo's own: no copy, no colour conversion);
           layers.json ("Strands (painted)": strands.png masked by strands_mask.png) for import_layers.py
           --above <Background id>, the Background visible, so the strands sit under the cut; cut.png (the photo with
           the new mask, RGBA, for cutout_check.py --edge-fix: revealed strands still carry the backdrop's colour),
           sheet.png (before | after on black, then on --background: Select and Mask's On Black and On White views),
           viz.png (yellow = the old edge, orange = contracted, green = revealed strands, red = painted strands,
           blue = roots with no direction to follow, magenta = zone), preview.png, strands.json.
           Prints the stats and warnings as one JSON line.
"""
import argparse
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
from channel_mask import smooth_field
from cutout_check import edge_distance


def hexrgb(s):
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return [int(s[i:i + 2], 16) for i in (0, 2, 4)]


def tohex(c):
    return "#" + "".join(f"{max(0, min(255, int(v + 0.5))):02x}" for v in c)


def sharpness(L, w, h, idx, min_range=12.0):
    """Edge statistic: the median of |gradient| / (max - min over 5x5) at the steeper half of pixels idx whose
    local range is at least min_range. About 0.45 on a sharp edge, falling as the edge softens."""
    vals = []
    for i in idx:
        x, y = i % w, i // w
        if not (2 <= x < w - 2 and 2 <= y < h - 2):
            continue
        win = [L[(y + dy) * w + x + dx] for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2)]
        rng = max(win) - min(win)
        if rng < min_range:
            continue
        g = math.hypot((L[i + 1] - L[i - 1]) / 2, (L[i + w] - L[i - w]) / 2)
        vals.append((g, g / rng))
    if len(vals) < 30:
        return None
    vals.sort()
    top = [r for _, r in vals[len(vals) // 2:]]
    top.sort()
    return top[len(top) // 2]


def splat(buf, w, h, x, y, r, v):
    """Max a disc of radius r (anti-aliased, 1 px ramp) with value v into buf (a dict index -> value)."""
    R = int(r + 1.5)
    xi, yi = int(x), int(y)
    for yy in range(max(0, yi - R), min(h, yi + R + 2)):
        for xx in range(max(0, xi - R), min(w, xi + R + 2)):
            d = math.hypot(xx + 0.5 - x, yy + 0.5 - y)
            c = min(1.0, max(0.0, r + 0.5 - d)) * v
            if c > 0:
                i = yy * w + xx
                if c > buf.get(i, 0.0):
                    buf[i] = c


def strand_profile(t, width):
    """A painted strand at t (0 = root, 1 = tip): its radius and opacity. Strong along most of its length and
    thinning to a fine tip, like a hair; a soft, fading stroke read as a smudge in testing."""
    return width / 2 * (1 - 0.7 * t) + 0.15, 1 - t ** 3


def test_strands(w, h, width, length, seed):
    """Coverage of a patch of straight-ish strands like the planner draws, for calibrating the blur."""
    rnd = random.Random(seed)
    cov = [0.0] * (w * h)
    for _ in range(40):
        x, y = rnd.uniform(10, w - 10), rnd.uniform(10, h - 10)
        a = rnd.uniform(0, math.pi)
        buf = {}
        n = int(length / 0.7)
        for k in range(n):
            t = k / max(1, n - 1)
            splat(buf, w, h, x + math.cos(a) * k * 0.7, y + math.sin(a) * k * 0.7, *strand_profile(t, width))
        for i, c in buf.items():
            cov[i] = 1 - (1 - cov[i]) * (1 - c)
    return cov


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("orig"); ap.add_argument("cut"); ap.add_argument("x", type=int); ap.add_argument("y", type=int)
    ap.add_argument("area"); ap.add_argument("outdir")
    ap.add_argument("--mode", choices=("both", "reveal", "paint"), default="both")
    ap.add_argument("--contract", default="auto", help="Minimum radius in px on the mask inside the zone (auto: half the "
                    "soft rim's width, 1-6; 0 = none)")
    ap.add_argument("--length", default="auto", help="px: the longest strand (auto: from the soft rim's width)")
    ap.add_argument("--density", default="auto", help="strands per 100 px of edge (auto: 30 revealed, 8 painted)")
    ap.add_argument("--width", type=float, default=1.2, help="px: a painted strand's width at the root (it tapers to a tip)")
    ap.add_argument("--reveal-width", type=float, default=4.0, help="px: a reveal stroke's width at the root: the photo's own "
                    "strands inside it come back, the backdrop between them stays out (the fur-brush stroke)")
    ap.add_argument("--colors", type=int, default=4, help="hair tones in the painted strands' palette")
    ap.add_argument("--blur", default="auto", help="px (Gaussian) on the painted strands (auto: matched to the photo's own "
                    "strands, at most 1 px)")
    ap.add_argument("--follow", type=float, default=0.5, help="outward bias: 0 = strictly along the hair's direction")
    ap.add_argument("--background", default="#ffffff", help="the second check background in sheet.png (first: black)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    rnd = random.Random(a.seed)

    w, h, R, G, B = imgops.load(a.orig)
    w2, h2, _, _, _, A = imgops.load_rgba(a.cut)
    if (w, h) != (w2, h2):
        sys.exit(f"error: orig is {w}x{h} but cut is {w2}x{h2}; crop both the same")
    if w % 2 or h % 2:
        sys.exit(f"error: the crop is {w}x{h}; crop an even width and height (the layers are centred on the crop)")
    if min(A) >= 0.999:
        sys.exit("error: cut.png has no transparency: export the cut layer alone (Background hidden) as an RGBA PNG")
    N = w * h
    cfg = json.load(open(a.area))
    polys = cfg.get("hair") or cfg.get("area") or cfg.get("skin")
    if not polys:
        sys.exit("error: area.json needs a \"hair\" polygon round the hair's outline")
    zone_all = imgops.polygon_mask(polys, a.x, a.y, w, h)
    zone = imgops.polygon_mask(polys, a.x, a.y, w, h, cfg.get("exclude", []))
    excl = [1 if zone_all[i] and not zone[i] else 0 for i in range(N)]
    excl_g = imgops.maxf([float(v) for v in excl], w, h, 2)  # strands stop 2 px short of an exclude
    L = [imgops.lum(r, g, b) for r, g, b in zip(R, G, B)]

    # the edge and its soft rim
    inside = [1 if v >= 0.5 else 0 for v in A]
    dist = edge_distance(inside, w, h, cap=60)
    soft = [dist[i] for i in range(N) if zone[i] and 0.05 < A[i] < 0.95]
    if len(soft) < 50:
        sys.exit("error: the cut has (almost) no edge inside the zone; check area.json, X Y, and that cut.png is the cut")
    soft.sort()
    fuzz = float(soft[int(0.9 * (len(soft) - 1))])
    contract = max(1, min(6, round(fuzz / 2))) if a.contract == "auto" else max(0, int(round(float(a.contract))))
    zf = imgops.gauss([float(v) for v in zone], w, h, 2.0)
    Ac = imgops.minf(A, w, h, contract) if contract else A[:]
    Ab = [A[i] + zf[i] * (Ac[i] - A[i]) for i in range(N)]

    # clean backdrop and hair colour, carried into the band
    far = [1.0 if A[i] < 0.02 and dist[i] > 2 else 0.0 for i in range(N)]
    core = [1.0 if A[i] > 0.98 and dist[i] > 2 and not excl[i] else 0.0 for i in range(N)]
    if sum(far) < max(500, 0.01 * N):
        sys.exit("error: too little clear backdrop in the crop to measure; crop a wider frame round the hair")
    sig = 2 * fuzz + 8
    Bk = [smooth_field(c, far, w, h, sig)[0] for c in (R, G, B)]
    Fh = [smooth_field(c, core, w, h, sig)[0] for c in (R, G, B)]
    hair_like, contrast = [0.0] * N, []
    for i in range(N):
        d = [Fh[k][i] - Bk[k][i] for k in range(3)]
        dd = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        if zone[i] and 0.02 < A[i] < 0.98:
            contrast.append(math.sqrt(dd / 3))
        if dd < 3 * 15 ** 2:
            continue  # hair and backdrop alike here: nothing tells a strand from the backdrop
        p = ((R[i] - Bk[0][i]) * d[0] + (G[i] - Bk[1][i]) * d[1] + (B[i] - Bk[2][i]) * d[2]) / dd
        hair_like[i] = min(1.0, max(0.0, p))
    contrast.sort()
    cmed = contrast[len(contrast) // 2] if contrast else 0.0
    # thin: a strand stands off its own surroundings (a shadow on the backdrop is hair-like too, but smooth), in the
    # hair's polarity, by more than 3x the backdrop's grain
    grain = imgops.grain(L, w, h, [i for i in range(0, N, 3) if far[i]])
    nf_, nb_ = (max(1, sum(1 for i in range(0, N, 5) if m_[i])) for m_ in (core, far))  # means, not sums: counts differ
    lf = imgops.lum(*(sum(c[i] for i in range(0, N, 5) if core[i]) / nf_ for c in (R, G, B)))
    lb = imgops.lum(*(sum(c[i] for i in range(0, N, 5) if far[i]) / nb_ for c in (R, G, B)))
    pol = 1.0 if lf < lb else -1.0  # dark hair on a light backdrop: strands are darker than around them
    Lg = imgops.gauss(L, w, h, 2.0)
    thin_t = max(3.0, 3 * grain)
    thin = [1 if pol * (Lg[i] - L[i]) > thin_t else 0 for i in range(N)]
    # how far the photo's own strands reach past the cut, however faint
    beyond = sorted(dist[i] for i in range(N) if zone[i] and A[i] < 0.5 and thin[i] and not excl_g[i]
                    and hair_like[i] > max(0.03, thin_t / max(1.0, cmed)))

    # the hair's direction: structure tensor inside the hair, carried outward
    Ls = imgops.gauss(L, w, h, 0.7)
    Ix, Iy = [0.0] * N, [0.0] * N
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            Ix[i] = (Ls[i + 1] - Ls[i - 1]) / 2
            Iy[i] = (Ls[i + w] - Ls[i - w]) / 2
    # inside the hair (opaque, off the silhouette) and, weighted up, the photo's own strands past the cut: where they
    # stick out of combed hair they set the direction there
    tw = [1.0 if A[i] > 0.97 and dist[i] >= 2 and not excl_g[i] and zone_all[i]
          else 4.0 if A[i] < 0.5 and thin[i] and zone[i] and not excl_g[i] else 0.0 for i in range(N)]
    # each pixel votes its orientation once (unit gradients): the faint strands past the cut, 10-20 levels off the
    # backdrop, otherwise drown under the hair's own 100-level texture
    g_t = max(1.0, 2 * grain)
    for i in range(N):
        m = math.hypot(Ix[i], Iy[i])
        if m > g_t:
            Ix[i], Iy[i] = Ix[i] / m, Iy[i] / m
        else:
            Ix[i] = Iy[i] = 0.0
    s_dir = max(4.0, fuzz)
    den = imgops.gauss(tw, w, h, s_dir)
    Jxx = imgops.gauss([t * gx * gx for t, gx in zip(tw, Ix)], w, h, s_dir)
    Jxy = imgops.gauss([t * gx * gy for t, gx, gy in zip(tw, Ix, Iy)], w, h, s_dir)
    Jyy = imgops.gauss([t * gy * gy for t, gy in zip(tw, Iy)], w, h, s_dir)
    # where the local estimate has too little hair under it, a wider one
    s2 = 3 * s_dir
    den2 = imgops.gauss(tw, w, h, s2)
    J2 = [imgops.gauss([t * p * q for t, p, q in zip(tw, P, Q)], w, h, s2) for P, Q in ((Ix, Ix), (Ix, Iy), (Iy, Iy))]

    def field(i):
        if den[i] > 0.05:
            xx, xy, yy, dn = Jxx[i], Jxy[i], Jyy[i], den[i]
        elif den2[i] > 0.01:
            xx, xy, yy, dn = J2[0][i], J2[1][i], J2[2][i], den2[i]
        else:
            return 0.0, 0.0, 0.0
        xx, xy, yy = xx / dn, xy / dn, yy / dn
        tr = xx + yy
        if tr < 1e-6:
            return 0.0, 0.0, 0.0
        coh = math.sqrt((xx - yy) ** 2 + 4 * xy * xy) / tr
        th = 0.5 * math.atan2(2 * xy, xx - yy)  # the gradient's orientation; strands run across it
        return -math.sin(th), math.cos(th), coh

    As = imgops.gauss(A, w, h, 2.0)

    def normal(i):
        x, y = i % w, i // w
        if not (0 < x < w - 1 and 0 < y < h - 1):
            return 0.0, 0.0
        nx, ny = -(As[i + 1] - As[i - 1]), -(As[i + w] - As[i - w])
        m = math.hypot(nx, ny)
        return (nx / m, ny / m) if m > 1e-6 else (0.0, 0.0)

    # roots: the contracted edge inside the zone, in order round the hair's centre
    inb = [1 if v >= 0.5 else 0 for v in Ab]
    edge = [i for i in range(N) if inb[i] and zone[i] and not excl_g[i]
            and any(not inb[j] for j in (i - 1, i + 1, i - w, i + w) if 0 <= j < N)]
    if not edge:
        sys.exit("error: no edge to grow strands from in the zone (it lies off the cut's outline, or all excluded)")
    hx = [i % w for i in range(N) if core[i]] or [w / 2]
    hy = [i // w for i in range(N) if core[i]] or [h / 2]
    cx, cy = sum(hx) / len(hx), sum(hy) / len(hy)
    fz = max(fuzz, 3.0)
    reach = float(beyond[int(0.97 * (len(beyond) - 1))]) if len(beyond) >= 0.02 * len(edge) else None
    length = float(a.length) if a.length != "auto" else None
    dens = None if a.density == "auto" else float(a.density)
    modes = ("reveal", "paint") if a.mode == "both" else (a.mode,)
    plans = {}
    for m in modes:
        base = reach if reach else 2 * fz + 8
        L_m = length or (max(8.0, 1.2 * base) if m == "reveal" else min(60.0, max(14.0, 1.5 * base)))
        d_m = dens if dens is not None else (30.0 if m == "reveal" else 8.0)
        plans[m] = (L_m, d_m)

    def trace(i0, length_px, prev_t):
        """A strand from root pixel i0: points [(x, y)], root coherence, its tangent (for the next root's sign)."""
        nx, ny = normal(i0)
        if nx == 0 and ny == 0:
            return None
        depth = rnd.uniform(1, 4)
        x, y = i0 % w + 0.5 - nx * depth, i0 // w + 0.5 - ny * depth
        j = int(y) * w + int(x)
        if not (0 <= x < w and 0 <= y < h) or A[j] < 0.9 or excl_g[j]:  # off the crop: x wrapped into the next row
            x, y = i0 % w + 0.5, i0 // w + 0.5
        tx, ty, coh0 = field(i0)
        if abs(tx * nx + ty * ny) >= 0.2:
            s = 1 if tx * nx + ty * ny > 0 else -1
        elif prev_t is not None:
            s = 1 if tx * prev_t[0] + ty * prev_t[1] >= 0 else -1
        else:
            s = rnd.choice((1, -1))
        tx, ty = tx * s, ty * s
        wt = min(1.0, coh0 / 0.3)
        dx, dy = wt * tx + a.follow * nx, wt * ty + a.follow * ny
        m = math.hypot(dx, dy) or 1.0
        dx, dy = dx / m, dy / m
        pts = [(x, y)]
        steps = int(length_px * rnd.uniform(0.6, 1.0) / 0.7)
        wander = 0.0
        for _ in range(steps):
            j = int(y) * w + int(x)
            fx, fy, coh = field(j)
            if fx * dx + fy * dy < 0:
                fx, fy = -fx, -fy
            k = min(1.0, coh / 0.3)
            gx, gy = k * fx + a.follow * nx, k * fy + a.follow * ny
            dx, dy = 0.75 * dx + 0.25 * gx, 0.75 * dy + 0.25 * gy
            wander += rnd.gauss(0, 0.012)
            c, sn = math.cos(wander), math.sin(wander)
            dx, dy = dx * c - dy * sn, dx * sn + dy * c
            m = math.hypot(dx, dy) or 1.0
            dx, dy = dx / m, dy / m
            x, y = x + 0.7 * dx, y + 0.7 * dy
            if not (1 <= x < w - 1 and 1 <= y < h - 1):
                break
            j = int(y) * w + int(x)
            if excl_g[j] or not zone_all[j]:
                break
            pts.append((x, y))
        return pts, coh0, (tx, ty)

    edge.sort(key=lambda i: math.atan2(i // w - cy, i % w - cx))
    out = {}
    roots_nodir, cohs, stopped_short, skipped_nodir = [], [], 0, 0
    for m in modes:
        L_m, d_m = plans[m]
        n = max(1, int(round(d_m * len(edge) / 100)))
        picks = sorted(rnd.sample(range(len(edge)), min(n, len(edge))))
        strands, prev = [], None
        for p in picks:
            r = trace(edge[p], L_m, prev)
            if not r:
                continue
            pts, coh0, prev = r
            if len(pts) < 4:
                stopped_short += 1
                continue
            if m == modes[0]:
                cohs.append(coh0)
                if coh0 < 0.2:
                    roots_nodir.append(edge[p])
            if m == "paint" and coh0 < 0.2:
                skipped_nodir += 1  # a painted strand with no direction to follow is a spike: none there
                continue
            strands.append(pts)
        out[m] = strands

    width = a.width
    # reveal: strand strokes on the mask, weighted by how hair-like the photo is under them
    M = Ab[:]
    revealed = 0
    if "reveal" in out:
        S = [0.0] * N
        for pts in out["reveal"]:
            buf = {}
            n = len(pts)
            for k, (x, y) in enumerate(pts):
                t = k / max(1, n - 1)
                splat(buf, w, h, x, y, a.reveal_width / 2 * (1 - t) ** 0.5 + 0.5, (1 - t) ** 0.5)
            for i, c in buf.items():
                S[i] = max(S[i], c)
        for i in range(N):
            if S[i] > 0:
                # the photo's coverage there: a strand, or the hair's own edge (within 2 px of the old cut), never
                # a smooth shadow on the backdrop
                hq = hair_like[i] if (thin[i] or dist[i] <= 2 or A[i] > 0.05) else 0.0
                v = max(M[i], S[i] * hq)
                if v > M[i] + 0.1:
                    revealed += 1
                M[i] = v
    q = lambda v: round(min(1.0, max(0.0, v)) * 255) / 255
    M = [q(v) for v in M]

    # paint: new strands on their own layer, hair-coloured, blurred like the photo
    blur = 0.0
    palette = []
    Sp, CR, CG, CB = [0.0] * N, Fh[0][:], Fh[1][:], Fh[2][:]
    real_sharp = test_sharp = matched = None
    if "paint" in out:
        near = [i for i in range(N) if core[i] and dist[i] <= 10 and zone[i]]
        if len(near) < 50:
            near = [i for i in range(N) if core[i]] or list(range(N))
        near.sort(key=lambda i: L[i])
        K = max(1, a.colors)
        for k in range(K):
            part = near[int(len(near) * (0.1 + 0.8 * k / K)):int(len(near) * (0.1 + 0.8 * (k + 1) / K))] or near
            palette.append([sum(c[i] for i in part) / len(part) for c in (R, G, B)])
        pal_l = [imgops.lum(*c) for c in palette]
        num = [[0.0] * N for _ in range(3)]
        acc = [0.0] * N
        for pts in out["paint"]:
            x0, y0 = pts[0]
            j = int(y0) * w + int(x0)
            # the hair's colour at the root, varied toward a palette tone near it: a tabby's dark stripe colour on its
            # light ear tip read as grey smoke in testing
            root = [Fh[k][j] for k in range(3)]
            lr = imgops.lum(*root)
            near_k = min(range(len(palette)), key=lambda k: abs(pal_l[k] - lr))
            pc_ = palette[min(len(palette) - 1, max(0, near_k + rnd.choice((-1, 0, 0, 1))))]
            col = [0.5 * root[k] + 0.5 * pc_[k] for k in range(3)]
            buf = {}
            n = len(pts)
            for k, (x, y) in enumerate(pts):
                t = k / max(1, n - 1)
                splat(buf, w, h, x, y, *strand_profile(t, width))
            for i, c in buf.items():
                Sp[i] = 1 - (1 - Sp[i]) * (1 - c)
                acc[i] += c
                for k in range(3):
                    num[k][i] += c * col[k]
        for i in range(N):
            if acc[i] > 0:
                CR[i], CG[i], CB[i] = num[0][i] / acc[i], num[1][i] / acc[i], num[2][i] / acc[i]
        # the blur: match the photo's real strands against the backdrop (its soft rim) on test strands
        # the photo's own strands past the cut, isolated against the backdrop; the cut's soft rim (the mask's own
        # transition, the backdrop mixed in) only when there are too few: on a kitten it read 2.5 px, and strands
        # that soft looked like smoke
        mr = max(6.0, 4 * grain)
        strays = [i for i in range(N) if zone[i] and A[i] < 0.5 and thin[i] and not excl_g[i]]
        real_sharp = sharpness(L, w, h, strays, mr)
        if real_sharp is None:
            real_sharp = sharpness(L, w, h, [i for i in range(0, N, 2) if zone[i] and 0.1 < A[i] < 0.9], mr)
        if a.blur != "auto":
            blur = float(a.blur)
        elif real_sharp is not None:
            tw_, th_ = 160, 160
            cov = test_strands(tw_, th_, width, plans["paint"][0], a.seed)
            fl = [imgops.lum(*palette[len(palette) // 2])] * 1
            bl = imgops.lum(*(sum(c[i] for i in range(0, N, 7) if far[i]) / max(1, sum(1 for i in range(0, N, 7) if far[i]))
                              for c in (R, G, B)))
            best = None
            for s in (0.0, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
                cv = imgops.gauss(cov, tw_, th_, s) if s else cov
                Lt = [bl + (fl[0] - bl) * v for v in cv]
                st = sharpness(Lt, tw_, th_, [i for i in range(tw_ * th_) if cv[i] > 0.05], mr)
                if st is None:
                    continue
                if best is None or abs(st - real_sharp) < best[0]:
                    best = (abs(st - real_sharp), s, st)
            if best:
                # the statistic also falls with a strand's width, and the photo's finest strands are thinner than a
                # painted one: matched blurs of 2-2.5 px made a kitten's strands look like smoke. Adobe's 1 px is the
                # ceiling; give --blur for a really soft photo
                matched, test_sharp = best[1], best[2]
                blur = min(1.0, matched)
        if blur > 0:
            Sb = imgops.gauss(Sp, w, h, blur)
            Cb = [imgops.gauss([c[i] * Sp[i] for i in range(N)], w, h, blur) for c in (CR, CG, CB)]
            for i in range(N):
                if Sb[i] > 1e-3:
                    CR[i], CG[i], CB[i] = Cb[0][i] / Sb[i], Cb[1][i] / Sb[i], Cb[2][i] / Sb[i]
            Sp = Sb
        Sp = [q(v) for v in Sp]
        CR, CG, CB = ([float(max(0, min(255, int(v + 0.5)))) for v in c] for c in (CR, CG, CB))

    # files
    if "reveal" not in out:
        revealed = 0  # paint only: the mask is the old one, contracted
    imgops.save_rgb(os.path.join(a.outdir, "orig.png"), w, h, R, G, B)
    imgops.save_gray(os.path.join(a.outdir, "mask.png"), w, h, M)
    imgops.save_rgb(os.path.join(a.outdir, "cut.png"), w, h, R, G, B, M)
    if "paint" in out:
        imgops.save_rgb(os.path.join(a.outdir, "strands.png"), w, h, CR, CG, CB)
        imgops.save_gray(os.path.join(a.outdir, "strands_mask.png"), w, h, Sp)
        # preview: what import_layers renders after `apply`, the Background (the photo) visible under the strands and
        # the cut with its new mask on top: the strands show only where that mask doesn't cover them
        P = [[c[i] + (Cc[i] - c[i]) * Sp[i] * (1 - M[i]) if Sp[i] else c[i] for i in range(N)]
             for c, Cc in ((R, CR), (G, CG), (B, CB))]
        imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w, h, *P)
        json.dump({"center": [a.x + w / 2, a.y + h / 2], "crop": [a.x, a.y, w, h], "preview": "preview.png",
                   "layers": [{"name": "Strands (painted)", "image": "strands.png", "mask": "strands_mask.png"}]},
                  open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    else:
        for f in ("layers.json", "preview.png", "strands.png", "strands_mask.png"):  # a previous run's paint plan
            if os.path.exists(os.path.join(a.outdir, f)):
                os.remove(os.path.join(a.outdir, f))

    # sheet: before | after on black, then on --background; the after with painted strands under the new mask
    k = max(1, math.ceil(2 * w / 1600))
    vw, vh = w // k, h // k
    rows = []
    for bg in ([0, 0, 0], hexrgb(a.background)):
        for y in range(vh):
            row = []
            for after in (False, True):
                for x in range(vw):
                    i = y * k * w + x * k
                    px = []
                    for c, Cc, b in ((R, CR, bg[0]), (G, CG, bg[1]), (B, CB, bg[2])):
                        if after:
                            base = b + (Cc[i] - b) * Sp[i]
                            px.append(base + (c[i] - base) * M[i])
                        else:
                            px.append(b + (c[i] - b) * A[i])
                    row.append(px)
                row.append([128, 128, 128])
            rows.append(row)
    sw = 2 * vw + 2
    imgops.save_rgb(os.path.join(a.outdir, "sheet.png"), sw, 2 * vh,
                    *[[rows[y][x][c] for y in range(2 * vh) for x in range(sw)] for c in range(3)])

    # viz
    def contour(vals):
        return [1 if vals[i] >= 0.5 and any(vals[j] < 0.5 for j in (i - 1, i + 1, i - w, i + w) if 0 <= j < N) else 0
                for i in range(N)]
    VR, VG, VB = ([0.5 * v for v in c] for c in (R, G, B))
    ze = contour(zone_all)
    for i in range(N):
        if ze[i]:
            VR[i], VG[i], VB[i] = 255, 0, 255
    for m_, col in (("reveal", (40, 230, 60)), ("paint", (255, 40, 40))):
        for pts in out.get(m_, []):
            for x, y in pts:
                j = int(y) * w + int(x)
                VR[j], VG[j], VB[j] = col
    for vals, col in ((A, (255, 220, 0)), (Ab, (255, 140, 0))):
        for i, e in enumerate(contour(vals)):
            if e:
                VR[i], VG[i], VB[i] = col
    for i0 in roots_nodir:
        for j in (i0, i0 - 1, i0 + 1, i0 - w, i0 + w):
            if 0 <= j < N:
                VR[j], VG[j], VB[j] = 40, 120, 255
    imgops.save_rgb(os.path.join(a.outdir, "viz.png"), w, h, VR, VG, VB)

    warnings = []
    border = sum(1 for i in range(N) if zone[i] and 0.02 < A[i] < 0.98
                 and (i % w < 4 or i % w >= w - 4 or i // w < 4 or i // w >= h - 4))
    if border and contract:
        warnings.append(f"the hair's edge crosses the crop's border inside the zone ({border} px): the contracted mask "
                        "steps there against the untouched one outside the crop; crop wider, or end the zone 10 px inside")
    cs = sorted(cohs)
    coh_med = cs[len(cs) // 2] if cs else 0.0
    nodir = len(roots_nodir) / max(1, len(cohs))
    if nodir > 0.3:
        warnings.append(f"{100 * nodir:.0f}% of the roots have no hair direction to follow (blown, blurred or very smooth "
                        "hair there): no strands are painted there, and revealed ones follow the outline's normal. Look "
                        "at the blue dots in viz.png")
    if "reveal" in out and cmed < 25:
        warnings.append(f"only {cmed:.0f} levels between the hair and the backdrop at the edge: reveal can't tell strands "
                        "from the backdrop, so it adds little; rely on --mode paint, or the channel route first")
    if stopped_short > 0.3 * max(1, sum(len(v) for v in out.values()) + stopped_short):
        warnings.append(f"{stopped_short} strands stopped within 3 px (the zone's border or an exclude right at the edge): "
                        "draw the zone further out over the backdrop")
    if "paint" in out and real_sharp is None and a.blur == "auto":
        warnings.append("too few real strands against the backdrop to measure the photo's softness: painted strands get "
                        "no blur; give --blur (1 px is Adobe's default for a portrait at normal depth of field)")
    stats = {"crop": [a.x, a.y, w, h], "mode": a.mode, "contract": contract, "softRim": fuzz, "strandReach": reach, "edgeLength": len(edge),
             "strands": {m_: len(v) for m_, v in out.items()}, "stoppedShort": stopped_short,
             "paintSkippedNoDirection": skipped_nodir,
             "length": {m_: round(plans[m_][0], 1) for m_ in plans}, "density": {m_: plans[m_][1] for m_ in plans},
             "direction": {"coherenceMedian": round(coh_med, 2), "noDirectionShare": round(nodir, 2)},
             "hairBackdropContrast": round(cmed, 1), "revealedPx": revealed, "grain": round(grain, 2),
             "paint": {"palette": [tohex(c) for c in palette], "blur": blur, "blurMatched": matched,
                       "sharpness": {"photo": real_sharp and round(real_sharp, 3), "strands": test_sharp and round(test_sharp, 3)}},
             "warnings": warnings,
             "next": ["look at sheet.png and viz.png, then at a 3x crop of the edge",
                      "hair_strands.py apply <outdir> <cut layer id or name>   (the new mask, on the cut layer itself)",
                      ("import_layers.py <outdir>/layers.json --above <Background id>   (Background visible; the painted "
                       "strands go under the cut)") if a.mode != "reveal" else "no layers.json: --mode reveal paints nothing",
                      "cutout_check.py <outdir>/cut.png <outdir>/orig.png <dir> --kind soft --edge-fix, then import "
                      "<dir>/edgefix/layers.json --above <cut layer id>   (revealed strands carry the backdrop's colour)"]}
    json.dump(stats, open(os.path.join(a.outdir, "strands.json"), "w"), indent=1)
    print(json.dumps(stats))


def apply_mask():
    """hair_strands.py apply OUTDIR LAYER [--file in.psd --save out.psd]: make OUTDIR/mask.png the cut layer's mask
    inside the crop it was planned on, keeping the layer's own mask outside it (the PNG is pasted into the mask, as
    Edit > Paste into a mask channel). The layer's pixels stay the photo's own; only its mask changes, as painting
    on the mask would. The live app's clipboard is replaced by the mask."""
    ap = argparse.ArgumentParser(prog="hair_strands.py apply", description=apply_mask.__doc__)
    ap.add_argument("outdir"); ap.add_argument("layer", help="the cut layer: id or name")
    ap.add_argument("--file", help="headless: the document to open (else the live app's active document)")
    ap.add_argument("--save", help="headless: where to save it (.psd keeps layers)")
    ap.add_argument("--port", type=int)
    a = ap.parse_args(sys.argv[2:])
    import pc
    from import_layers import walk
    st = json.load(open(os.path.join(a.outdir, "strands.json")))
    x, y, w, h = st["crop"]
    png = os.path.abspath(os.path.join(a.outdir, "mask.png"))
    if a.file:
        if not a.save:
            sys.exit("error: --file needs --save")
        c = pc.Headless()
        r = c.call("doc.open", {"path": os.path.abspath(os.path.expanduser(a.file))})
        if not r.get("ok"):
            sys.exit(f"error: cannot open {a.file}: {r.get('error')}")
    else:
        c = pc.Control(a.port)

    def call(method, params=None):
        r = c.call(method, params or {})
        if not r.get("ok"):
            sys.exit(f"error: {method} {json.dumps(params)[:200]}: {r.get('error')}")
        return r.get("result")

    def run(command, params=None):
        return call("engine.execute", {"command": command, "params": params or {}})

    main_doc = call("ui.inspect")["session"]["active"]
    doc = run("document.inspect", {"document": main_doc})
    named = [l for _, l in walk(doc["layers"]) if l.get("name") == a.layer or str(l.get("id")) == str(a.layer)]
    if len(named) != 1:
        sys.exit(f"error: {len(named)} layers match {a.layer!r} in {doc['name']}; give its id or a unique name")
    target = named[0]
    if not target.get("hasMask"):
        sys.exit(f"error: layer {target['name']!r} has no mask: give the masked cut layer (refineEdge's newLayerWithMask)")
    call("app.open", {"path": png})
    src = call("ui.inspect")["session"]["active"]
    # copy the grey PNG and paste it into the layer's mask at the crop's place: a mask channel takes the numbers as
    # they are, and the mask outside the crop stays. (Copying it in as a layer and loading that as a selection
    # converted it: an Apple RGB portrait's mid-greys came out up to 19 levels darker.)
    run("select.all")
    run("edit.copy")
    run("file.close", {"document": src})
    run("document.activate", {"document": main_doc})
    run("layer.select", {"layer": target["id"]})
    run("edit.paste", {"target": "mask", "center": [x + w / 2, y + h / 2]})
    c.call("engine.execute", {"command": "select.deselect", "params": {}})
    res = {"appliedTo": target["id"], "name": target["name"], "crop": [x, y, w, h]}
    if a.file:
        out = os.path.abspath(os.path.expanduser(a.save))
        r = c.call("doc.save", {"path": out})
        if not r.get("ok"):
            sys.exit(f"error: cannot save {a.save}: {r.get('error')}")
        res["saved"] = out
    print(json.dumps(res))
    c.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "apply":
        apply_mask()
    else:
        main()
