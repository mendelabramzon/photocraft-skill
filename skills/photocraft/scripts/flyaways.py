#!/usr/bin/env python3
"""Plan a flyaway-hair cleanup on a plain backdrop: stray strands painted over with the backdrop, the hair's edge kept.

Strands that stick out of the hair's silhouette are covered with the clean backdrop on one masked layer, and the
strands close to the hair stay.

How retouchers do it (Unmesh Dinda's method for many flyaways): paint the backdrop over the strands on a separate
layer, then mask it so the hair's own silhouette comes back. Strands are thinner than a median filter's window, the
silhouette and the backdrop's own edges (a paper seam, a vignette) aren't, so:

  hair mass    the median-filtered crop where it stands off the local backdrop by more than 5 x the backdrop's own
               spread there (per 64 px tile, at least 8): everything but the thin strands, the same on a tight crop
               and a whole head
  strands      thin things in the zone, off the mass, in the hair's polarity: darker (for dark hair) than both the
               crop's median and the backdrop, so the light halo JPEG leaves beside a dark strand doesn't count.
               Thin means mostly gone after a 3x3 erosion, however tangled; compact shapes (dust, a clump) are
               left, and the big ones are listed (orange boxes in viz.png), never dropped silently
  kept         strand pixels within --keep px of the mass, fading out over --fade px beyond it: the hair's natural
               edge stays fuzzy (helmet hair, every strand gone, looks fake), and a strand that is removed tapers
               off like a real hair tip instead of ending in a cut
  fill         the photo itself averaged over nearby backdrop that is neither strand nor hair (a gradient, a mottled
               studio backdrop stay as they are), plus grain matched to the backdrop's, baked in (exact preview)

The zone (area.json, full-image coordinates) is the band around the hair to clean: "skin" = a polygon around the head
whose edge lies on clean backdrop, "exclude" = a polygon a few px inside the hair's edge (and anything else that must
stay: an earring, glasses, a collar). Only a strand's backdrop part is painted: where it continues over skin, an
ear or clothes, heal or clone that part first (plan_heals.py --add along it, paint.cloneStamp across an edge), or
keep the whole strand with an exclude polygon over its backdrop part.

usage: flyaways.py crop.png X Y area.json OUTDIR [--keep 12] [--fade 10] [--median 4] [--threshold 0]
crop.png   the photo cropped round the head at full resolution (image.crop), even width and height
Writes OUTDIR/layers.json ("Flyaways": fill.png masked by mask.png) for import_layers.py, preview.png (exact),
viz.png (red = strands removed, cyan = strands kept near the hair, yellow = the hair mass's edge, magenta = zone,
orange = big shapes left), flyaways.json. Prints the stats and warnings as one JSON line.
"""
import argparse
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pc


def chamfer(mask, w, h, cap):
    """Distance in px (3-4 chamfer, within 8 %) from every pixel to the nearest truthy one, capped at cap."""
    big = int(3 * cap + 3)
    d = [0 if m else big for m in mask]
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if d[i]:
                v = d[i]
                if x:
                    v = min(v, d[i - 1] + 3)
                if y:
                    v = min(v, d[i - w] + 3)
                    if x:
                        v = min(v, d[i - w - 1] + 4)
                    if x < w - 1:
                        v = min(v, d[i - w + 1] + 4)
                d[i] = v
    for y in range(h - 1, -1, -1):
        for x in range(w - 1, -1, -1):
            i = y * w + x
            if d[i]:
                v = d[i]
                if x < w - 1:
                    v = min(v, d[i + 1] + 3)
                if y < h - 1:
                    v = min(v, d[i + w] + 3)
                    if x < w - 1:
                        v = min(v, d[i + w + 1] + 4)
                    if x:
                        v = min(v, d[i + w - 1] + 4)
                d[i] = v
    return [min(cap, v / 3) for v in d]


def backdrop_surface(chs, zone, w, h, step=None, rounds=8):
    """A quadratic surface per channel through the zone's pixels, robust (Tukey biweight on the colour distance, from
    the zone's median colour): the backdrop with its gradient and vignette, ignoring hair, skin and strands as long as
    most of the zone is backdrop. Returns the fitted channels and the backdrop's spread around them (levels)."""
    step = step or max(3, round(math.sqrt(sum(1 for z in zone if z) / 40000)))  # ~40k samples
    idx = [y * w + x for y in range(0, h, step) for x in range(0, w, step) if zone[y * w + x]]
    X = [(i % w) / w * 2 - 1 for i in idx]
    Y = [(i // w) / h * 2 - 1 for i in idx]
    F = [(1.0, x, y, x * x, x * y, y * y) for x, y in zip(X, Y)]
    vals = [[c[i] for i in idx] for c in chs]
    fit = [[sorted(v)[len(v) // 2]] * len(idx) for v in vals]  # start: the median colour, a constant
    for _ in range(rounds):
        r = [math.sqrt(((vals[0][j] - fit[0][j]) ** 2 + (vals[1][j] - fit[1][j]) ** 2 + (vals[2][j] - fit[2][j]) ** 2) / 3)
             for j in range(len(idx))]
        sig = max(0.5, 1.4826 * sorted(r)[len(r) // 2])
        c = 4.685 * sig
        wt = [(1 - (v / c) ** 2) ** 2 if v < c else 0.0 for v in r]
        A = [[0.0] * 6 for _ in range(6)]
        bs = [[0.0] * 6 for _ in range(3)]
        for j, f in enumerate(F):
            if wt[j]:
                for p in range(6):
                    wf = wt[j] * f[p]
                    for q in range(p, 6):
                        A[p][q] += wf * f[q]
                    for k in range(3):
                        bs[k][p] += wf * vals[k][j]
        for p in range(6):
            for q in range(p):
                A[p][q] = A[q][p]
            A[p][p] += 1e-6
        coef = [solve(A, bs[k]) for k in range(3)]
        fit = [[sum(cf * v for cf, v in zip(coef[k], f)) for f in F] for k in range(3)]
    out = [[0.0] * (w * h) for _ in range(3)]
    for y in range(h):
        yy = y / h * 2 - 1
        for k in range(3):
            c0, c1, c2, c3, c4, c5 = coef[k]
            a0, a1, a2 = c0 + c2 * yy + c5 * yy * yy, c1 + c4 * yy, c3  # in x: a0 + a1 x + a2 x^2
            row = out[k]
            for x in range(w):
                xx = x / w * 2 - 1
                row[y * w + x] = a0 + (a1 + a2 * xx) * xx
    good = sorted(v for v, k in zip(r, wt) if k > 0)
    return out, (1.4826 * good[len(good) // 2] if good else sig)


def solve(A, b):
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(b)
    M = [row[:] + [v] for row, v in zip(A, b)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crop"); ap.add_argument("x", type=int); ap.add_argument("y", type=int)
    ap.add_argument("area"); ap.add_argument("outdir")
    ap.add_argument("--keep", type=float, default=12, help="px: strands this close to the hair mass stay (its fuzzy edge)")
    ap.add_argument("--fade", type=float, default=10, help="px beyond --keep over which a removed strand fades out")
    ap.add_argument("--median", type=int, default=4, help="median radius: strands thinner than about this are found")
    ap.add_argument("--threshold", type=float, default=0, help="levels a strand differs from the backdrop (0 = 4 x "
                    "the noise beside the hair or the backdrop's grain, at least 4); fainter strands are left")
    ap.add_argument("--min-length", type=int, default=8, help="px: shorter thin bits are grain or dust, not hair")
    ap.add_argument("--polarity", choices=["auto", "dark", "light"], default="auto",
                    help="strands darker than the backdrop (dark hair on light) or lighter (auto: from the hair mass)")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    w, h, R, G, B = imgops.load(a.crop)
    if w % 2 or h % 2:
        sys.exit(f"error: the crop is {w}x{h}; crop an even width and height (the layer is centred on the crop)")
    N = w * h
    zone = imgops.raster(json.load(open(a.area)), a.x, a.y, w, h)
    if sum(zone) < 1000:
        sys.exit("error: the zone is (almost) empty in this crop; check area.json and X Y")

    # median: strands gone, the silhouette and backdrop edges kept
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: photocraft-cli not found; `pc.py cli-info` names the one to install")
    med = os.path.join(a.outdir, "_median.png")
    subprocess.run([str(cli), "run", a.crop, "--cmd", "filter.noise.median", "--params", json.dumps({"radius": a.median}),
                    "--out", med], check=True, capture_output=True)
    _, _, MR, MG, MB = imgops.load(med)
    os.remove(med)

    # The backdrop as a smooth surface: a robust quadratic through the zone. It can't bend into a band of hair the zone
    # reaches into; a local fit did, in testing, and found "strands" inside 40-60 px of dark hair.
    dist3 = lambda r1, g1, b1, r2, g2, b2: math.sqrt(((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2) / 3)
    (QR, QG, QB), qspread = backdrop_surface((MR, MG, MB), zone, w, h)
    Dm = [dist3(MR[i], MG[i], MB[i], QR[i], QG[i], QB[i]) for i in range(N)]
    min_mass = max(50, (5 * a.median) ** 2)  # px, fixed: a share of the crop grew with it (3920 px on a whole head)

    def big(mask):
        out = bytearray(N)
        for c in imgops.components(mask, w, h):
            if len(c) >= min_mass:
                for i in c:
                    out[i] = 1
        return out

    def local_backdrop(hair):
        """The median averaged over backdrop only (it follows a vignette or a mottled studio backdrop, and never the
        hair), at the finest scale with enough backdrop around; inside the hair (where nothing is cleaned) and in the
        few px beside it that have little backdrop around (within --keep, so kept) the smooth surface."""
        off = imgops.maxf([float(v) for v in hair], w, h, 3)
        wb = [1.0 - v for v in off]
        out = [list(q) for q in (QR, QG, QB)]
        todo = [i for i in range(N) if not off[i]]
        for s in (3.0, 6.0):
            if not todo:
                break
            den = imgops.gauss(wb, w, h, s)
            nums = [imgops.gauss([c[i] * wb[i] for i in range(N)], w, h, s) for c in (MR, MG, MB)]
            rest = []
            for i in todo:
                if den[i] > 0.3:
                    for o, num in zip(out, nums):
                        o[i] = num[i] / den[i]
                else:
                    rest.append(i)
            todo = rest
        return off, out

    # the hair, first against the smooth surface (sure hair only), then against the local backdrop with a local
    # threshold: 5 x the backdrop's own spread there, per 64 px tile. One threshold from the surface fit grew with the
    # crop (12.3 on a tight crop, 28.9 on the whole head, whose backdrop varies more across the frame), so faint nape
    # wisps stopped counting as hair, joined a stray strand into one shape, and the strand was dropped.
    mass = big([1 if v > max(8.0, 5 * qspread) else 0 for v in Dm])
    if not any(mass):
        sys.exit("error: no hair found: nothing in the crop stands out from the backdrop; is the zone over the head?")
    off, (BR, BG, BB) = local_backdrop(mass)
    Dl = [dist3(MR[i], MG[i], MB[i], BR[i], BG[i], BB[i]) for i in range(N)]
    T_ = 64
    nx, ny = (w + T_ - 1) // T_, (h + T_ - 1) // T_
    grid = [[None] * nx for _ in range(ny)]
    for ty in range(ny):
        for tx in range(nx):
            v = sorted(Dl[y * w + x] for y in range(ty * T_, min(h, ty * T_ + T_)) for x in range(tx * T_, min(w, tx * T_ + T_))
                       if zone[y * w + x] and not off[y * w + x])
            if len(v) >= 0.25 * T_ * T_:
                grid[ty][tx] = 1.4826 * v[len(v) // 2]  # residuals are distances: their median scales to a spread
    known = sorted(g for row in grid for g in row if g is not None) or [qspread]
    grid = [[known[len(known) // 2] if g is None else g for g in row] for row in grid]

    def t_at(x, y):
        fx = min(max((x + 0.5) / T_ - 0.5, 0.0), nx - 1.0)
        fy = min(max((y + 0.5) / T_ - 0.5, 0.0), ny - 1.0)
        x0, y0 = int(fx), int(fy)
        x1, y1 = min(nx - 1, x0 + 1), min(ny - 1, y0 + 1)
        u, v = fx - x0, fy - y0
        s = (grid[y0][x0] * (1 - u) + grid[y0][x1] * u) * (1 - v) + (grid[y1][x0] * (1 - u) + grid[y1][x1] * u) * v
        return max(8.0, 5 * s)
    tm = [t_at(i % w, i // w) if Dl[i] > 8.0 else 8.0 for i in range(N)]
    mass = big([1 if mass[i] or Dl[i] > tm[i] else 0 for i in range(N)])
    # holes in the mass (highlights in the hair, a loop of hair with backdrop inside) count as hair: never cleaned
    for c in imgops.components([1 - v for v in mass], w, h):
        if not any(i % w in (0, w - 1) or i // w in (0, h - 1) for i in c):
            for i in c:
                mass[i] = 1
    _, (BR, BG, BB) = local_backdrop(mass)
    tms = sorted(t_at(i % w, i // w) for i in range(0, N, 97) if zone[i]) or [8.0]

    # the backdrop's grain, measured on the photo where it is clearly backdrop
    Lp = [imgops.lum(r, g, b) for r, g, b in zip(R, G, B)]
    Lm = [imgops.lum(r, g, b) for r, g, b in zip(MR, MG, MB)]
    Lb = [imgops.lum(r, g, b) for r, g, b in zip(BR, BG, BB)]
    near_mass = imgops.maxf([float(v) for v in mass], w, h, 6)
    clean = [i for i in range(0, N, 3) if zone[i] and not near_mass[i] and Dl[i] < 0.5 * tm[i]]
    if len(clean) < 500:
        sys.exit("error: too little clean backdrop in the zone to measure; draw the zone further out from the hair")
    grain = imgops.grain(Lp, w, h, clean)

    # polarity: strands are the hair's colour, so dark hair on a light backdrop only counts what is darker than both
    # the median and the backdrop. JPEG and sharpening leave light halos beside dark strands (and dark beside light
    # ones); counting those joined every strand to its halo into a blob in testing.
    hair = [i for i in range(0, N, 2) if mass[i] and zone[i]] or [i for i in range(0, N, 2) if mass[i]]
    darker = sum(Lb[i] - Lm[i] for i in hair) / len(hair)
    sign = 1.0 if (a.polarity == "dark" or (a.polarity == "auto" and darker > 0)) else -1.0
    S = [min(Lm[i], Lb[i]) - Lp[i] if sign > 0 else Lp[i] - max(Lm[i], Lb[i]) for i in range(N)]
    # the noise floor beside the hair (ringing, grain), not on the far, often flat or clipped backdrop
    dmass = chamfer(mass, w, h, max(40.0, a.keep + a.fade + 4))
    band = sorted(abs(S[i]) for i in range(0, N, 2) if zone[i] and not mass[i] and 8 <= dmass[i] <= 40)
    floor = 1.4826 * band[len(band) // 2] if band else grain
    t_hi = a.threshold or max(4.0, 4 * floor, 4 * grain)
    t_lo = 0.5 * t_hi

    # strands: thinner than the median's window and off the backdrop, in the hair's polarity, outside the mass
    cand = [1 if zone[i] and not mass[i] and S[i] > t_lo else 0 for i in range(N)]
    strand = bytearray(N)
    blobs = []
    found = kept_only = removed = specks = 0
    for c in imgops.components(cand, w, h):
        if max(S[i] for i in c) <= t_hi:
            continue
        xs = [i % w for i in c]; ys = [i // w for i in c]
        extent = math.hypot(max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
        # thin = mostly gone after a 3x3 erosion (hair is 1-3 px wide, however tangled); a compact blob keeps its core.
        # Area over extent (the earlier test) called a tangle of strands a blob, and it was dropped.
        cs = set(c)
        core = sum(1 for i in c if all((i + d) in cs for d in (-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1)))
        if extent < a.min_length or core > 0.4 * len(c):
            specks += 1  # dust, a speck of grain, a stray blob; not hair (object-removal's job)
            if len(c) >= 150:  # never drop a big one silently
                blobs.append([min(xs) + a.x, min(ys) + a.y, max(xs) + a.x, max(ys) + a.y, len(c)])
            continue
        found += 1
        far = sum(1 for i in c if dmass[i] > a.keep)
        if far:
            removed += 1
        else:
            kept_only += 1
        for i in c:
            strand[i] = 1

    # the mask: strands grown 1 px (their anti-aliased edge), off beyond keep + fade, faded in between, feathered
    grown = imgops.maxf([float(v) for v in strand], w, h, 1)
    ramp = [min(1.0, max(0.0, (dmass[i] - a.keep) / max(1e-6, a.fade))) for i in range(N)]
    m = [grown[i] * ramp[i] * zone[i] if not mass[i] else 0.0 for i in range(N)]
    m = [v * zone[i] * (1 - mass[i]) for i, v in enumerate(imgops.gauss(m, w, h, 0.7))]  # the hair and the outside stay exact
    q = lambda v: round(min(1.0, max(0.0, v)) * 255) / 255
    mq = [q(v) for v in m]

    # the fill: nearby backdrop that is neither strand nor hair, at the finest scale that has enough of it
    # only backdrop goes into the fill: not the strands or the hair, and no pixel off the local backdrop either way
    # (light hairs beside dark ones left a pale smudge where a strand met the hair, in testing)
    excl = imgops.maxf([float(strand[i] or mass[i] or abs(Lp[i] - Lb[i]) > t_hi) for i in range(N)], w, h, 2)
    wt = [0.0 if v else 1.0 for v in excl]
    fill = [list(c) for c in (R, G, B)]  # under the mask only the strands' pixels show
    todo = [i for i in range(N) if m[i] > 0]
    for s in (2.0, 4.0, 8.0):
        if not todo:
            break
        den = imgops.gauss(wt, w, h, s)
        nums = [imgops.gauss([c[i] * wt[i] for i in range(N)], w, h, s) for c in (R, G, B)]
        rest = []
        for i in todo:
            if den[i] > 0.3:
                for k in range(3):
                    fill[k][i] = nums[k][i] / den[i]
            else:
                rest.append(i)
        todo = rest
    for i in todo:  # deep in a tangle: the local backdrop
        fill[0][i], fill[1][i], fill[2][i] = BR[i], BG[i], BB[i]
    n = imgops.noise(N, grain / 0.943, seed=7)  # monochromatic, like the backdrop's own grain
    FR, FG, FB = ([float(max(0, min(255, int(c[i] + n[i] + 0.5)))) for i in range(N)] for c in fill)
    imgops.save_rgb(os.path.join(a.outdir, "fill.png"), w, h, FR, FG, FB)
    imgops.save_gray(os.path.join(a.outdir, "mask.png"), w, h, mq)
    P = [[c[i] + mq[i] * (f[i] - c[i]) for i in range(N)] for c, f in ((R, FR), (G, FG), (B, FB))]
    imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w, h, *P)

    # viz: removed strands red, kept strand pixels cyan, mass edge yellow, zone edge magenta
    edge = lambda mk: [1 if mk[i] and any(not mk[j] for j in (i - 1, i + 1, i - w, i + w) if 0 <= j < N) else 0 for i in range(N)]
    me, ze = edge(mass), edge([1 if z else 0 for z in zone])
    VR, VG, VB = [list(c) for c in (R, G, B)]
    for x0, y0, x1, y1, _ in blobs:  # big non-strand shapes left in the zone: orange boxes
        for x in range(x0 - a.x, x1 - a.x + 1):
            for y in (y0 - a.y, y1 - a.y):
                VR[y * w + x], VG[y * w + x], VB[y * w + x] = 255, 140, 0
        for y in range(y0 - a.y, y1 - a.y + 1):
            for x in (x0 - a.x, x1 - a.x):
                VR[y * w + x], VG[y * w + x], VB[y * w + x] = 255, 140, 0
    for i in range(N):
        col = None
        if strand[i]:
            col = (255, 30, 30) if m[i] > 0.5 else (0, 220, 255)
        elif me[i]:
            col = (255, 220, 0)
        elif ze[i]:
            col = (255, 0, 255)
        if col:
            VR[i], VG[i], VB[i] = col
    imgops.save_rgb(os.path.join(a.outdir, "viz.png"), w, h, VR, VG, VB)

    # left after the layer: the same detector on the preview, beyond keep + fade
    PL = [imgops.lum(P[0][i], P[1][i], P[2][i]) for i in range(N)]
    left = sum(1 for i in range(N) if zone[i] and not mass[i] and dmass[i] > a.keep + a.fade
               and (min(Lm[i], Lb[i]) - PL[i] if sign > 0 else PL[i] - max(Lm[i], Lb[i])) > t_hi)
    warnings = []
    resid = sorted(Dl[i] for i in clean)
    spread = resid[int(0.9 * (len(resid) - 1))]
    if spread > max(6.0, 3 * grain):
        warnings.append(f"the backdrop varies {spread:.0f} levels around its local level (a mottled or painted backdrop, "
                        "a seam, a busy background): look at viz.png and the result at 2x")
    if blobs:
        warnings.append(f"{len(blobs)} large shapes in the zone are not thin enough for hair and are left (orange boxes in "
                        f"viz.png, x0, y0, x1, y1, px): {blobs[:12]}. Look at each: a clump of strands is better healed "
                        "or cloned by hand, a speck of dust with the dust tools")
    zone_n = sum(1 for z in zone if z)
    if sum(strand) > 0.08 * zone_n:
        warnings.append("strands cover over 8 % of the zone: that may be the hair's natural fuzzy edge, or the zone reaches "
                        "into the hair; raise --keep or pull the zone's inner edge outward")
    if sum(1 for i in range(N) if zone[i] and mass[i]) > 0.5 * zone_n:
        warnings.append("most of the zone is hair or skin: draw it over the backdrop around the head, its inner edge just "
                        "inside the hair")
    stats = {"polarity": "dark" if sign > 0 else "light",
             "strands": {"found": found, "removed": removed, "keptNearHair": kept_only, "specksIgnored": specks},
             "maskedPixels": sum(1 for v in mq if v > 0.5), "leftBeyondKeep": left,
             "grain": round(grain, 2), "noiseBesideHair": round(floor, 2), "threshold": round(t_hi, 1),
             "massThreshold": [round(tms[0], 1), round(tms[len(tms) // 2], 1), round(tms[-1], 1)],
             "bigShapesLeft": blobs, "backdropSpreadP90": round(spread, 1), "keep": a.keep, "fade": a.fade,
             "warnings": warnings}
    layers = {"center": [a.x + w / 2, a.y + h / 2], "crop": [a.x, a.y, w, h], "preview": "preview.png",
              "layers": [{"name": f"Flyaways (keep {a.keep:g} px)", "image": "fill.png", "mask": "mask.png"}]}
    json.dump(layers, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    json.dump(stats, open(os.path.join(a.outdir, "flyaways.json"), "w"), indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
