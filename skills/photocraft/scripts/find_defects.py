#!/usr/bin/env python3
"""Map the dust, specks, hairs, scratches and cracks on a scanned photo and plan their repair: masked median layers
for the small and thin ones, healing for the bigger ones, and nothing else touched.

Restorers never run Dust & Scratches over a whole photo: it melts grain, eyelashes and texture along with the dust.
They run it through a mask that holds only the defects. This script makes that mask. It compares the scan with
median-filtered copies made by the CLI (radius --fine, --coarse, --structure). A defect has to stand out --texture
times more than the texture around it, so skin pores, hair and fabric stay; two matched filters find what is faint in
heavy grain: a 3x3 mean of the residual for specks, and its mean along lines (--line lengths, 12 angles; Motion Blur
computes them) for hairlines and long scratches. Big blobs (flaking emulsion) are found against the structure median.

Each defect then goes where its repair works, measured on its own pixels: to the "fine" median layer if Median
--fine takes it away, to the "coarse" one if Median --coarse does, else to heal.json: the Remove tool (one dab a little
bigger than a compact defect, a closed loop round a big blob, a stroke along an elongated one), or inside faces the
Healing Brush copying the face's own clean skin nearby. Very large ones are listed for hand work. Each median layer gets grain matched to what its median removed where its defects are
(two layers per scale when the grain differs a lot across the photo).

A context gate keeps real detail: a candidate's contrast against the clean ring around it, over the ring's spread,
must reach --context for the coarse layer or healing (half for the fine layer), since dust or a streak on smooth
ground is foreign and a stripe, nostril or mouth line belongs to its surroundings. Real detail that looks like a
defect (catchlights, specular highlights on buttons, white lettering, lace) must still be excluded with area.json;
faces get stricter thresholds. Read overlay.png before importing.

usage: find_defects.py crop.png cropX cropY outdir [--area area.json] [--texture 4] [--line-threshold 5]
                       [--fine 2] [--coarse 5] [--polarity both|light|dark] [--no-grain] [--layer ID] [--add X,Y[,D] ...]

crop.png   the photo or a region of it at full resolution (image.crop); cropX/cropY = where it sits in the photo
area.json  optional, full-image coordinates: {"area": polygon(s) to work in (default: all of the crop),
           "exclude": [[x0, y0, x1, y1] or polygon, ...] (eyes, catchlights, lettering, jewellery: never touched),
           "faces": [polygon, ...] (stricter: only clear specks and scratches)}
Writes to outdir: fine*.png and coarse*.png (the masks), layers.json (the median layers for import_layers.py, with a
verify window and its exact preview.png), heal.json (pc.py script steps for an empty "Heal" layer), overlay.png
(2x: green = fine, yellow = coarse, red rings = heal dabs, magenta boxes = large damage, blue = candidates left
alone as real detail) and defects.json.
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
import pngio

NOISE_PER_AMOUNT = 0.643  # filter.noise.addNoise, gaussian, monochromatic: standard deviation per unit of amount


def line_cap(r):
    """Widest line a median of radius r removes (measured on PhotoCraft 0.7.0)."""
    return int(0.8 * r + 0.4)


def speck_cap(r):
    """Widest speck a median of radius r removes."""
    return int(round(1.4 * r))


def thickness(pix, w):
    """Width of a component in px: twice its largest inscribed distance (chamfer distance on its bounding box)."""
    xs = [i % w for i in pix]; ys = [i // w for i in pix]
    x0, y0 = min(xs) - 1, min(ys) - 1
    bw, bh = max(xs) - x0 + 2, max(ys) - y0 + 2
    big = 10 ** 6
    d = [0] * (bw * bh)
    for i in pix:
        d[(i // w - y0) * bw + (i % w - x0)] = big
    for y in range(1, bh - 1):
        for x in range(1, bw - 1):
            k = y * bw + x
            if d[k]:
                d[k] = min(d[k], d[k - 1] + 3, d[k - bw] + 3, d[k - bw - 1] + 4, d[k - bw + 1] + 4)
    for y in range(bh - 2, 0, -1):
        for x in range(bw - 2, 0, -1):
            k = y * bw + x
            if d[k]:
                d[k] = min(d[k], d[k + 1] + 3, d[k + bw] + 3, d[k + bw + 1] + 4, d[k + bw - 1] + 4)
    return 2 * max(d) / 3 - 1


def shape(pix, w):
    """(length, elongation) from the spread of the component's pixels."""
    n = len(pix)
    xs = [i % w for i in pix]; ys = [i // w for i in pix]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs) / n; syy = sum((y - my) ** 2 for y in ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    l1 = tr / 2 + math.sqrt(max(0.0, tr * tr / 4 - det))
    length = math.sqrt(12 * l1) + 1
    return length, length / max(1.0, n / length)


def fill_holes(pix, w, h):
    """The component with its enclosed holes filled: a blob too wide for a median shows up as a ring of residual."""
    xs = [i % w for i in pix]; ys = [i // w for i in pix]
    x0, y0 = max(0, min(xs) - 1), max(0, min(ys) - 1)
    x1, y1 = min(w - 1, max(xs) + 1), min(h - 1, max(ys) + 1)
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if bw * bh > 250000:
        return pix
    inside = bytearray(bw * bh)
    for i in pix:
        inside[(i // w - y0) * bw + i % w - x0] = 1
    seen = bytearray(bw * bh)
    st = [k for k in range(bw * bh) if (k % bw in (0, bw - 1) or k // bw in (0, bh - 1)) and not inside[k]]
    for k in st:
        seen[k] = 1
    while st:
        k = st.pop()
        x, y = k % bw, k // bw
        for j in ((k - 1) if x > 0 else -1, (k + 1) if x < bw - 1 else -1, (k - bw) if y > 0 else -1, (k + bw) if y < bh - 1 else -1):
            if j >= 0 and not seen[j] and not inside[j]:
                seen[j] = 1; st.append(j)
    return [(y0 + k // bw) * w + x0 + k % bw for k in range(bw * bh) if inside[k] or not seen[k]]


def hull(points):
    """Convex hull, counter-clockwise (monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    cross = lambda o, p, q: (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("crop"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int); ap.add_argument("outdir")
    ap.add_argument("--area", help="area.json: area / exclude / faces polygons, full-image coordinates")
    ap.add_argument("--min-contrast", type=float, default=12, help="levels: never flag less than this")
    ap.add_argument("--texture", type=float, default=5,
                    help="x the local texture: a defect must also stand out this much from the detail around it")
    ap.add_argument("--polarity", default="both", choices=["both", "light", "dark"])
    ap.add_argument("--line", type=int, nargs="+", default=[11, 25], help="px: lengths of the line means that find faint hairlines")
    ap.add_argument("--line-threshold", type=float, default=5, help="x the local spread of the line means")
    ap.add_argument("--fine", type=int, default=2, help="median radius of the fine layer (specks, hairlines)")
    ap.add_argument("--coarse", type=int, default=5, help="median radius of the coarse layer (bigger specks, scratches)")
    ap.add_argument("--structure", type=int, default=12, help="median radius of the structure reference")
    ap.add_argument("--max-gradient", type=float, default=7,
                    help="levels/px of the structure reference above which a compact candidate is read as real detail")
    ap.add_argument("--face-factor", type=float, default=1.6, help="threshold multiplier inside 'faces'")
    ap.add_argument("--context", type=float, default=6,
                    help="contrast against the clean ring around a defect, over the ring's spread, that coarse and "
                         "healing repairs need (fine specks need half): below it a candidate is kept as detail")
    ap.add_argument("--heal-tool", default="remove", choices=["remove", "healing"],
                    help="remove: the Remove tool (content-aware; clean on flat and grainy ground); healing: Healing "
                         "Brush dabs copied from clean texture of the same tone (keeps a texture's own pattern)")
    ap.add_argument("--heal-max", type=int, default=48, help="largest dab, px (bigger blobs get a loop round them)")
    ap.add_argument("--max-defect", type=int, default=3000, help="px: bigger compact defects are listed as large damage")
    ap.add_argument("--no-grain", action="store_true", help="don't add grain matched to the photo's to the median layers")
    ap.add_argument("--layer", type=int, help="layer id for the healing dabs (default: the active layer)")
    ap.add_argument("--add", action="append", default=[], metavar="X,Y[,D]", help="also heal this spot (full-image coords)")
    ap.add_argument("--window", type=int, default=640, help="size of the verify window")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: needs photocraft-cli (`pc.py cli-info` says which one)")

    def run(*args):
        r = subprocess.run([str(cli)] + [str(x) for x in args], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"error: photocraft-cli {' '.join(map(str, args))[:160]}: {r.stderr.strip()[:300]}")

    tmp = lambda n: os.path.join(a.outdir, "_" + n + ".png")
    gray = ["--cmd", "image.mode.grayscale"]
    med = lambda r: ["--cmd", "filter.noise.median", "--params", json.dumps({"radius": r})]
    run("run", a.crop, *gray, "--out", tmp("g"))
    for name, r in (("mf", a.fine), ("mc", a.coarse), ("ms", a.structure), ("ms2", 2 * a.structure)):
        run("run", a.crop, *gray, *med(r), "--out", tmp(name))
    w, h, Gy, _, _ = imgops.load(tmp("g"))
    Mf, Mc, Ms, Ms2 = (imgops.load(tmp(n))[2] for n in ("mf", "mc", "ms", "ms2"))
    N = w * h

    cfg = json.load(open(a.area)) if a.area else {}
    polys = cfg.get("area") or cfg.get("skin")
    area = imgops.polygon_mask(polys, a.ox, a.oy, w, h) if polys else [1.0] * N
    whole = [[a.ox - 1, a.oy - 1], [a.ox + w + 1, a.oy - 1], [a.ox + w + 1, a.oy + h + 1], [a.ox - 1, a.oy + h + 1]]
    excl = [1.0 - v for v in imgops.polygon_mask([whole], a.ox, a.oy, w, h, cfg.get("exclude", []))]
    faces = imgops.polygon_mask(cfg["faces"], a.ox, a.oy, w, h) if cfg.get("faces") else [0.0] * N
    ok = [area[i] > 0.5 and excl[i] < 0.5 for i in range(N)]

    # local spread of a residual (the line means use an RMS, clipped twice so defects raise it little).
    # Grain = the texture of the smoothest tenth of the area.
    def texture(res, r=7):
        t0 = [math.sqrt(max(0.0, v)) for v in imgops.box([min(40.0, abs(v)) ** 2 for v in res], w, h, r)]
        return [math.sqrt(max(0.0, v)) for v in imgops.box([min(3 * t, abs(q)) ** 2 for q, t in zip(res, t0)], w, h, r)]
    def spread(res, r=7):
        """1.48 x the local median of |res|: the texture's spread around each pixel, blind to defects as long as they
        cover less than half the window (an RMS is raised by every defect nearby). The CLI's median does the work."""
        imgops.save_gray(tmp("abs"), w, h, [min(1.0, abs(v) / 255) for v in res])
        run("run", tmp("abs"), *med(r), "--out", tmp("absm"))
        return [1.4826 * v for v in imgops.load(tmp("absm"))[2]]
    resf = [Gy[i] - Mf[i] for i in range(N)]
    resc = [Gy[i] - Mc[i] for i in range(N)]
    texf, texc = spread(resf), spread(resc)
    sigma = max(0.8, imgops.percentile([texf[i] for i in range(0, N, 5) if ok[i]], 10))
    # matched filters find what is faint in heavy grain: 3x3 and 7x7 means of the residuals (a speck or blob survives
    # them, the grain averages out), and the residual's mean along lines (--line px) at 12 angles, the strongest kept
    # (a hairline or scratch adds up along its length, the grain doesn't). Motion Blur is that line mean, so the CLI
    # computes it: 12 blurred copies of the residual, blended Lighten (light lines) or Darken (dark ones).
    spk = imgops.box(resf, w, h, 1)
    texk = spread(spk)
    blb = imgops.box(resc, w, h, 3)  # the same at blob scale: a 7x7 mean of the coarse residual
    texb = spread(blb, 10)
    imgops.save_gray(tmp("res"), w, h, [min(1.0, max(0.0, (128 + v) / 255)) for v in resf])

    def line_mean(blend, length):
        cmds = []
        for k in range(1, 12):
            cmds += ["--cmd", "layer.select", "--params", '{"layer": 2}', "--cmd", "layer.duplicate",
                     "--cmd", "filter.blur.motionBlur", "--params", json.dumps({"angle": 15 * k, "distance": length - 1}),
                     "--cmd", "layer.setProps", "--params", json.dumps({"blend": blend})]
        cmds += ["--cmd", "layer.select", "--params", '{"layer": 2}',
                 "--cmd", "filter.blur.motionBlur", "--params", json.dumps({"angle": 0, "distance": length - 1})]
        run("run", tmp("res"), *cmds, "--out", tmp("line"))
        return [v - 128 for v in imgops.load(tmp("line"))[2]]
    # short means find hairs and fibres, long ones the long faint straight scratches of a film transport
    lines = {1: [line_mean("Lighten", n) for n in a.line], -1: [[-v for v in line_mean("Darken", n)] for n in a.line]}
    # gradient of the structure reference: real edges, which a median lags behind
    grad = [0.0] * N
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            grad[i] = math.hypot(Ms[i + 1] - Ms[i - 1], Ms[i + w] - Ms[i - w]) / 2

    classes = {"fine": [], "coarse": [], "heal": [], "large": [], "kept": []}
    comps_out = []
    for sign in ((1, -1) if a.polarity == "both" else (1,) if a.polarity == "light" else (-1,)):
        ff = [a.face_factor if faces[i] > 0.5 else 1.0 for i in range(N)]
        cand = [0] * N
        peakres = [0.0] * N

        def add(score, thr, res, bit):
            """Components of score > thr/2 that reach thr somewhere join the candidates (bit = which detector)."""
            grow = [ok[i] and score[i] > 0.5 * thr[i] for i in range(N)]
            for pix in imgops.components(grow, w, h):
                if any(score[i] >= thr[i] for i in pix):
                    for i in pix:
                        if sign * res[i] > 0:
                            cand[i] |= bit
                            peakres[i] = max(peakres[i], sign * res[i])
        # 1. per-pixel residuals at both medians: clear specks and scratches
        for res, tex in ((resf, texf), (resc, texc)):
            add([sign * v for v in res], [max(a.min_contrast, a.texture * tex[i]) * ff[i] for i in range(N)], res, 1)
        # 2. small specks and blobs in grain
        add([sign * v for v in spk], [max(0.5 * a.min_contrast, a.texture * texk[i]) * ff[i] for i in range(N)], resf, 2)
        add([sign * v for v in blb], [max(0.5 * a.min_contrast, a.texture * texb[i]) * ff[i] for i in range(N)], resc, 2)
        # 3. hairlines and scratches in grain: the line mean against its own local level and spread
        for L in lines[sign]:
            mL = imgops.box(L, w, h, 15)
            dL = [v - m for v, m in zip(L, mL)]
            texl = texture(dL, 15)
            add(dL, [max(0.3 * a.min_contrast, a.line_threshold * texl[i]) for i in range(N)], resf, 4)
        for pix in imgops.components(cand, w, h):
            length, elong = shape(pix, w)
            # seen by the line means alone: grain makes short streaks there, a hair or scratch is long
            if all(cand[i] == 4 for i in pix) and (length < 1.6 * min(a.line) or elong < 5):
                continue
            pix = [i for i in fill_holes(pix, w, h) if ok[i]]
            n = len(pix)
            length, elong = shape(pix, w)
            t = thickness(pix, w) if n > 2 else 1.0
            peak = max(peakres[i] for i in pix)
            g = sum(grad[i] for i in pix) / n
            in_face = sum(faces[i] for i in pix) > n / 2
            is_line = elong >= 4 and length >= 10
            rec = {"sign": sign, "n": n, "len": round(length, 1), "elong": round(elong, 1), "thick": round(t, 1),
                   "peak": round(peak, 1), "grad": round(g, 1), "pix": pix}
            # how much of the defect (measured against the structure reference) each median takes away: the
            # filters themselves decide which layer can repair it, whatever its shape
            dev = sum(sign * (Gy[i] - Ms[i]) for i in pix)
            rem_f = sum(sign * (Gy[i] - Mf[i]) for i in pix) / dev if dev > 0 else 0.0
            rem_c = sum(sign * (Gy[i] - Mc[i]) for i in pix) / dev if dev > 0 else 0.0
            local = max(a.min_contrast, a.texture * max(texf[i] for i in pix))
            rec.update(removed=[round(rem_f, 2), round(rem_c, 2)])
            # real detail: a compact bump on a strong edge (the median lags there), a line along an edge, or in a
            # face a short line (an eyelash, a lip line), which a scratch across the face is not
            if (not is_line and g > a.max_gradient and peak < 3 * local) or (is_line and g > 1.5 * a.max_gradient) \
                    or (in_face and is_line and elong < 6):
                rec["class"] = "kept"
            elif not is_line and n > a.max_defect:
                rec["class"] = "large"
            elif rem_f >= 0.75 or (dev <= 0 and t <= (line_cap(a.fine) if is_line else speck_cap(a.fine))):
                rec["class"] = "fine"
            elif rem_c >= 0.75 or (dev <= 0 and t <= (line_cap(a.coarse) if is_line else speck_cap(a.coarse))):
                rec["class"] = "coarse"
            else:
                rec["class"] = "heal"
            classes[rec["class"]].append(rec)
            comps_out.append(rec)

    # big defects (emulsion flakes, blobs of dirt) are thicker than the coarse median sees: look for them against the
    # structure reference, but only compact, crisp-edged, high-contrast ones; real features of that size (eyes,
    # teeth, buttons) are soft-edged or sit on strong structure
    owner = [-1] * N
    for k, r in enumerate(comps_out):
        for i in r["pix"]:
            owner[i] = k
    dropped = set()
    gy = [0.0] * N
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            gy[i] = math.hypot(Gy[i + 1] - Gy[i - 1], Gy[i + w] - Gy[i - w]) / 2
    # a median only sees a blob up to ~1.4x its radius across: the structure median, then one twice as wide
    big_passes = [(r, M, sign) for r, M in ((a.structure, Ms), (2 * a.structure, Ms2))
                  for sign in ((1, -1) if a.polarity == "both" else (1,) if a.polarity == "light" else (-1,))]
    for radius, Mbig, sign in big_passes:
        ress = [Gy[i] - Mbig[i] for i in range(N)]
        texs = spread(ress, 2 * radius)  # a window much wider than the blob, so the blob can't raise its own bar
        thr = [max(2.5 * a.min_contrast, a.texture * texs[i]) * (a.face_factor if faces[i] > 0.5 else 1.0) for i in range(N)]
        grow = [ok[i] and sign * ress[i] > 0.5 * thr[i] for i in range(N)]
        for pix in imgops.components(grow, w, h):
            if len(pix) < 12 or not any(sign * ress[i] >= thr[i] for i in pix):
                continue
            pix = [i for i in fill_holes(pix, w, h) if ok[i]]
            n = len(pix)
            length, elong = shape(pix, w)
            t = thickness(pix, w)
            if elong >= 8 or t <= speck_cap(a.coarse):
                continue  # thin enough for the coarse median, or a line rather than a blob
            # the smaller passes often catch only a big blob's rim, and a median can't repair the blob anyway: it
            # replaces them, unless they are already planned for healing and hold most of it
            inside = {owner[i] for i in pix if owner[i] >= 0}
            if sum(comps_out[k]["n"] for k in inside if comps_out[k]["class"] in ("heal", "large")) > 0.75 * n:
                continue
            sp = set(pix)
            edge = [i for i in pix if any(j not in sp for j in (i - 1, i + 1, i - w, i + w))]
            peak = max(sign * ress[i] for i in pix)
            sharp = sum(gy[i] for i in edge) / len(edge) / peak
            rec = {"sign": sign, "n": n, "len": round(length, 1), "elong": round(elong, 1), "thick": round(t, 1),
                   "peak": round(peak, 1), "grad": round(sum(grad[i] for i in pix) / n, 1), "sharp": round(sharp, 2), "pix": pix}
            rec["class"] = "kept" if sharp < 0.2 else "large" if n > a.max_defect else "heal"
            if rec["class"] != "kept":
                dropped |= inside
                for i in pix:
                    owner[i] = len(comps_out)
            classes[rec["class"]].append(rec)
            comps_out.append(rec)
    if dropped:
        gone = [comps_out[k] for k in dropped]
        comps_out = [r for r in comps_out if not any(r is g for g in gone)]
        for c in classes:
            classes[c] = [r for r in classes[c] if not any(r is g for g in gone)]

    # context: a defect is foreign to its surroundings, real detail belongs to them. Contrast against the clean ring
    # 2..6 px around it, over that ring's own spread: dust or a streak on smooth ground scores far higher than a stripe
    # on a cap, a nostril or a mouth line among the structure of a face. Repairs that rebuild a whole area (coarse
    # median, healing) need clear foreignness; anything less is kept for review (blue).
    cand_all = bytearray(N)
    for r in comps_out:
        for i in r["pix"]:
            cand_all[i] = 1
    for r in comps_out:
        if r["class"] == "kept":
            continue
        pix = r["pix"]
        xs = [i % w for i in pix]; ys = [i // w for i in pix]
        x0, y0 = max(0, min(xs) - 7), max(0, min(ys) - 7)
        x1, y1 = min(w, max(xs) + 8), min(h, max(ys) + 8)
        bw, bh = x1 - x0, y1 - y0
        sub = [0.0] * (bw * bh)
        for i in pix:
            sub[(i // w - y0) * bw + i % w - x0] = 1.0
        outer, inner = imgops.maxf(sub, bw, bh, 6), imgops.maxf(sub, bw, bh, 2)
        ring = [Gy[(y0 + k // bw) * w + x0 + k % bw] for k in range(bw * bh)
                if outer[k] and not inner[k] and not cand_all[(y0 + k // bw) * w + x0 + k % bw]]
        if len(ring) < 8:
            continue
        m = sum(ring) / len(ring)
        sd = math.sqrt(sum((v - m) ** 2 for v in ring) / len(ring))
        dev = sorted((abs(Gy[i] - m) for i in pix), reverse=True)[:max(1, len(pix) // 4)]  # its core, not its halo
        r["context"] = round(sum(dev) / len(dev) / max(1.0, sd), 1)
        need = a.context if r["class"] in ("coarse", "heal", "large") else a.context / 2
        if r["context"] < need:
            r["class"] = "kept"
    classes = {c: [r for r in comps_out if r["class"] == c] for c in classes}

    def mask_of(recs, grow_r):
        m = [0.0] * N
        for r in recs:
            for i in r["pix"]:
                m[i] = 1.0
        m = imgops.maxf(m, w, h, grow_r)
        return [v if ok[i] else 0.0 for i, v in enumerate(imgops.gauss(m, w, h, 0.5))]

    # one median layer per scale, or two when the grain differs a lot between where the defects are (a negative's
    # highlights carry 2-3x the grain of its shadows): each layer's added noise replaces what its median took away
    # there, which is the local spread of that median's residual
    q = lambda v: round(min(1.0, max(0.0, v)) * 255) / 255

    # the grain around each defect, from the clean pixels only (a defect would raise its own estimate)
    clean = [1.0] * N
    for r in comps_out:
        if r["class"] != "kept":
            for i in r["pix"]:
                clean[i] = 0.0
    clean = imgops.minf(clean, w, h, 1)
    cnt = imgops.box(clean, w, h, 7)

    def grain_map(res):
        num = imgops.box([min(40.0, abs(v)) ** 2 * k for v, k in zip(res, clean)], w, h, 7)
        return [math.sqrt(max(0.0, n) / c) if c > 0.05 else 0.0 for n, c in zip(num, cnt)]

    def groups(recs, res):
        gm = grain_map(res)
        for r in recs:
            r["grain"] = sorted(gm[i] for i in r["pix"])[len(r["pix"]) // 2]
        if not recs:
            return []
        g = sorted(r["grain"] for r in recs)
        lo, hi = g[len(g) // 5], g[4 * len(g) // 5]
        if hi < 1.8 * lo:
            return [recs]
        cut = math.sqrt(lo * hi)
        return [part for part in ([r for r in recs if r["grain"] < cut], [r for r in recs if r["grain"] >= cut]) if part]
    median_layers = []  # (name, radius, mask file, mask, grain)
    for cls, radius, res_ in (("fine", a.fine, resf), ("coarse", a.coarse, resc)):
        parts = groups(classes[cls], res_)
        for k, part in enumerate(parts):
            m = [q(v) for v in mask_of(part, 1)]
            fname = f"{cls}.png" if len(parts) == 1 else f"{cls}{k + 1}.png"
            imgops.save_gray(os.path.join(a.outdir, fname), w, h, m)
            grain = sorted(r["grain"] for r in part)[len(part) // 2]
            median_layers.append((cls, radius, fname, m, grain))
    union = lambda cls: [max([ml[3][i] for ml in median_layers if ml[0] == cls] or [0.0]) for i in range(N)]
    mfine, mcoarse = union("fine"), union("coarse")

    # healing for defects too thick for the medians. A healing brush blends the copied texture into the colours at its
    # edge, so its edge has to lie on clean surroundings: one dab a little bigger than a compact defect, or a stroke
    # along an elongated one, copied from clean texture whose tone matches the ring around the defect.
    bad = [0.0] * N
    for r in comps_out:
        if r["class"] != "kept":
            for i in r["pix"]:
                bad[i] = 1.0
    bad = imgops.maxf(bad, w, h, 2)
    tex = texc

    def disk(cx, cy, rad):
        ri = int(math.ceil(rad))
        for dy in range(-ri, ri + 1):
            for dx in range(-ri, ri + 1):
                if dx * dx + dy * dy <= rad * rad:
                    yield cx + dx, cy + dy

    def ring_tone(pix):
        """Mean of the scan 3..6 px outside the defect, other defects left out."""
        m = [0.0] * N
        for i in pix:
            m[i] = 1.0
        xs = [i % w for i in pix]; ys = [i // w for i in pix]
        x0, x1, y0, y1 = max(0, min(xs) - 7), min(w, max(xs) + 8), max(0, min(ys) - 7), min(h, max(ys) + 8)
        sub = [m[y * w + x] for y in range(y0, y1) for x in range(x0, x1)]
        sw, sh = x1 - x0, y1 - y0
        outer, inner = imgops.maxf(sub, sw, sh, 6), imgops.maxf(sub, sw, sh, 2)
        vals = [Gy[(y0 + k // sw) * w + x0 + k % sw] for k in range(sw * sh)
                if outer[k] and not inner[k] and not bad[(y0 + k // sw) * w + x0 + k % sw]]
        return sum(vals) / len(vals) if vals else None

    def find_offset(path, size, tone, texv):
        """Offset (dx, dy) to copy the whole stroke from: clean, in the area, the tone of the ring, similar texture."""
        rad = size / 2 + 1
        foot = {(px, py) for x, y in path for px, py in disk(x, y, rad)}
        best = None
        for dist in range(size + 2, 3 * size + 16, max(2, size // 4)):
            for k in range(24):
                ang = 2 * math.pi * k / 24
                dx, dy = round(dist * math.cos(ang)), round(dist * math.sin(ang))
                tot, cnt, okk = 0.0, 0, True
                for px, py in foot:
                    qx, qy = px + dx, py + dy
                    if not (0 <= qx < w and 0 <= qy < h):
                        okk = False; break
                    j = qy * w + qx
                    if not ok[j] or bad[j]:
                        okk = False; break
                    tot += Gy[j]; cnt += 1
                if not okk:
                    continue
                j = (path[0][1] + dy) * w + path[0][0] + dx
                cost = abs(tot / cnt - tone) + 2 * abs(tex[j] - texv) + 0.5 * max(0.0, grad[j] - 2) + 0.05 * dist
                if best is None or cost < best[0]:
                    best = (cost, dx, dy)
        return None if best is None else (best[1], best[2])

    heal_recs = classes["heal"] + [r for r in classes["large"] if r["n"] <= 4 * a.max_defect]
    for spec in a.add:
        v = [int(float(s)) for s in spec.split(",")]
        cx, cy, d = v[0] - a.ox, v[1] - a.oy, (v[2] if len(v) > 2 else 8)
        pix = [(cy + dy) * w + cx + dx for dy in range(-(d // 2), d // 2 + 1) for dx in range(-(d // 2), d // 2 + 1)
               if dx * dx + dy * dy <= (d / 2) ** 2 and 0 <= cx + dx < w and 0 <= cy + dy < h]
        heal_recs.append({"pix": pix, "thick": d, "elong": 1.0, "class": "heal"})
    # fragments of one defect (a scratch broken where it crosses a light patch) are planned as one: a dab or stroke
    # whose edge lands on another fragment blends that fragment back in
    hm = [0.0] * N
    thick_at = {}
    for r in heal_recs:
        for i in r["pix"]:
            hm[i] = 1.0
            thick_at[i] = max(thick_at.get(i, 0.0), r.get("thick", 1.0))
    merged = []
    for comp in imgops.components(imgops.maxf(hm, w, h, 3), w, h):
        pix = [i for i in comp if hm[i]]
        if pix:
            merged.append({"pix": pix, "thick": max(thick_at[i] for i in pix)})

    def offset(path, size, pix):
        if tool(pix) != "healing":
            return None
        c = path[len(path) // 2]
        tone = ring_tone(pix)
        return find_offset(path, size, tone if tone is not None else Ms[c[1] * w + c[0]], tex[c[1] * w + c[0]])

    def tool(pix):
        """Inside a face, copy the face's own skin (Healing Brush): content-aware Remove may bring texture from elsewhere."""
        return "healing" if sum(faces[i] for i in pix) > len(pix) / 2 else a.heal_tool

    strokes = []  # (path in crop coords, brush size, healing offset or None, closed loop, tool)
    for r in merged:
        pix = r["pix"]
        xs = [i % w for i in pix]; ys = [i // w for i in pix]
        span = max(max(xs) - min(xs), max(ys) - min(ys)) + 1
        elong = shape(pix, w)[1] if len(pix) > 2 else 1.0
        if elong < 3 or span + 8 <= a.heal_max:
            if span + 8 <= a.heal_max:  # one dab a little bigger than the defect and its halo
                c = ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)
                strokes.append(([c], span + 8, offset([c], span + 8, pix), False, tool(pix)))
            elif tool(pix) == "remove":  # a big blob: a closed loop round it, and Remove fills what it encloses
                x0, y0 = min(xs) - 6, min(ys) - 6
                bw, bh = max(xs) - x0 + 7, max(ys) - y0 + 7
                sub = [0.0] * (bw * bh)
                for i in pix:
                    sub[(i // w - y0) * bw + i % w - x0] = 1.0
                sub = imgops.maxf(sub, bw, bh, 4)
                loop = hull([(k % bw + x0, k // bw + y0) for k in range(bw * bh) if sub[k]])
                strokes.append((loop + loop[:1], 10, None, True, "remove"))
            else:  # healing: a grid of the largest dabs
                d = a.heal_max
                st = max(4, int(d * 0.6))
                for cy in range(min(ys), max(ys) + 1, st):
                    for cx in range(min(xs), max(xs) + 1, st):
                        if any((p % w - cx) ** 2 + (p // w - cy) ** 2 <= (d / 2) ** 2 for p in pix):
                            strokes.append(([(cx, cy)], d, offset([(cx, cy)], d, pix), False, "healing"))
        else:
            # elongated: a stroke along its centre line (local centroids along the main axis), a little wider than it
            n = len(pix)
            mx, my = sum(xs) / n, sum(ys) / n
            sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
            sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
            ux, uy = math.cos(ang), math.sin(ang)
            size = int(max(6, min(a.heal_max, r["thick"] + 8)))
            bins = {}
            for x, y in zip(xs, ys):
                bins.setdefault(int(((x - mx) * ux + (y - my) * uy) // max(2, size // 2)), []).append((x, y))
            path = [(round(sum(p[0] for p in b) / len(b)), round(sum(p[1] for p in b) / len(b))) for _, b in sorted(bins.items())]
            strokes.append((path, size, offset(path, size, pix), False, tool(pix)))
    steps, dabs = [], []
    for path, d, src, closed, how in strokes:
        p = {"points": [[x + a.ox, y + a.oy] for x, y in path], "size": int(d), "hardness": 80, "target": "pixels"}
        if a.layer is not None:
            p["layer"] = a.layer
        if how == "remove":
            p.update({"sampleAllLayers": True, "closeLoops": closed})
            steps.append({"command": "paint.remove", "params": p})
        elif src:
            p.update({"offset": list(src), "aligned": True, "sampleLayer": "currentAndBelow"})
            steps.append({"command": "paint.healingBrush", "params": p})
        else:
            p.update({"type": "contentAware", "sampleAllLayers": True})
            steps.append({"command": "paint.spotHealing", "params": p})
        dabs += [(x, y, d, src) for x, y in path]
    json.dump(steps, open(os.path.join(a.outdir, "heal.json"), "w"))

    # verify window: the 640 px square with the most masked pixels, rendered exactly like the two stamp layers
    ww, wh = min(w, a.window), min(h, a.window)
    B = 16  # masked pixels per 16 px block, then the best window of blocks
    bw_, bh_ = (w + B - 1) // B, (h + B - 1) // B
    blk = [0.0] * (bw_ * bh_)
    for i in range(N):
        if mfine[i] or mcoarse[i]:
            blk[(i // w) // B * bw_ + (i % w) // B] += 1
    best, bx, by = -1, 0, 0
    nx, ny = max(1, ww // B), max(1, wh // B)
    for y0 in range(0, max(1, bh_ - ny + 1)):
        for x0 in range(0, max(1, bw_ - nx + 1)):
            s = sum(blk[y * bw_ + x] for y in range(y0, min(bh_, y0 + ny)) for x in range(x0, min(bw_, x0 + nx)))
            if s > best:
                best, bx, by = s, min(x0 * B, w - ww), min(y0 * B, h - wh)
    m = a.coarse + 2  # margin so the medians at the window's edge see the same pixels as in the whole photo
    ex0, ey0 = max(0, bx - m), max(0, by - m)
    ex1, ey1 = min(w, bx + ww + m), min(h, by + wh + m)
    ew, eh = ex1 - ex0, ey1 - ey0
    run("run", a.crop, "--cmd", "image.crop", "--params", json.dumps({"x": ex0, "y": ey0, "width": ew, "height": eh}), "--out", tmp("w"))
    run("run", tmp("w"), *med(a.fine), "--out", tmp("wf"))
    _, _, P0 = pngio.read(tmp("w")); _, _, PF = pngio.read(tmp("wf"))

    def blend(A, B, mask):
        out = []
        for y in range(eh):
            row = []
            for x in range(ew):
                k = mask[(ey0 + y) * w + ex0 + x]
                pa, pb = A[y][x], B[y][x]
                row.append(tuple(int(pa[c] + k * (pb[c] - pa[c]) + 0.5) for c in range(3)) if k else pa)
            out.append(row)
        return out
    P1 = blend(P0, PF, mfine)
    pngio.write(tmp("w1"), ew, eh, P1)
    run("run", tmp("w1"), *med(a.coarse), "--out", tmp("wc"))
    P2 = blend(P1, pngio.read(tmp("wc"))[2], mcoarse)
    vx, vy = bx - ex0, by - ey0
    pngio.write(os.path.join(a.outdir, "preview.png"), ww, wh, [row[vx:vx + ww] for row in P2[vy:vy + wh]])

    layers = {"center": [a.ox + w / 2, a.oy + h / 2], "crop": [a.ox + bx, a.oy + by, ww, wh], "preview": "preview.png",
              "group": "Dust & scratches", "layers": []}
    noise = 0.0  # the preview has no grain: the render differs by the added noise under the masks, E|N(0, s)| = 0.8 s
    for k, (cls, radius, fname, m, grain) in enumerate(median_layers):
        stamp = [["filter.noise.median", {"radius": radius}]]
        if not a.no_grain:  # matching grain: the median smooths the grain away under the mask
            stamp.append(["filter.noise.addNoise", {"amount": round(grain / NOISE_PER_AMOUNT, 2), "distribution": "gaussian",
                                                    "monochromatic": True, "seed": k + 1}])
            noise += 0.8 * grain * sum(m[(by + y) * w + bx + x] for y in range(wh) for x in range(ww)) / (ww * wh)
        layers["layers"].append({"name": f"{cls.capitalize()} (median {radius}, grain {grain:.1f})", "stamp": stamp, "mask": fname})
    layers["tolerance"] = round(0.5 + 1.25 * noise, 2)
    json.dump(layers, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)

    # overlay at 2x for review
    S = 2
    _, _, PC = pngio.read(tmp("g"))
    img = [[PC[y // S][x // S] for x in range(w * S)] for y in range(h * S)]
    colours = {"fine": (40, 220, 40), "coarse": (255, 220, 0), "kept": (60, 140, 255), "heal": (255, 60, 60), "large": (255, 0, 255)}
    for r in comps_out:
        col = colours[r["class"]]
        sp = set(r["pix"])
        for i in r["pix"]:
            x, y = i % w, i // w
            if any(j not in sp for j in (i - 1, i + 1, i - w, i + w)):
                for dy in range(S):
                    for dx in range(S):
                        img[y * S + dy][x * S + dx] = col
        if r["class"] == "large":
            xs = [i % w for i in r["pix"]]; ys = [i // w for i in r["pix"]]
            for x in range(min(xs) * S, max(xs) * S + S):
                for y in (min(ys) * S, max(ys) * S + S - 1):
                    img[y][x] = col
            for y in range(min(ys) * S, max(ys) * S + S):
                for x in (min(xs) * S, max(xs) * S + S - 1):
                    img[y][x] = col
    for cx, cy, d, src in dabs:
        rad = d / 2 * S
        for t in range(0, 360, 8):
            px, py = int(cx * S + rad * math.cos(math.radians(t))), int(cy * S + rad * math.sin(math.radians(t)))
            if 0 <= px < w * S and 0 <= py < h * S:
                img[py][px] = colours["heal"]
    pngio.write(os.path.join(a.outdir, "overlay.png"), w * S, h * S, img)
    for n in ("g", "mf", "mc", "ms", "ms2", "w", "wf", "w1", "wc", "res", "line", "abs", "absm"):
        os.remove(tmp(n))

    count = lambda c: len(classes[c])
    stats = {"crop": [a.ox, a.oy, w, h], "grain": round(sigma, 2),
             "found": {c: count(c) for c in classes}, "maskedPct": round(100 * sum(1 for v in mfine if v > 0.5) / N, 2),
             "coarsePct": round(100 * sum(1 for v in mcoarse if v > 0.5) / N, 2), "healSteps": len(steps),
             "medianLayers": [l["name"] for l in layers["layers"]],
             "large": [[min(i % w for i in r["pix"]) + a.ox, min(i // w for i in r["pix"]) + a.oy,
                        max(i % w for i in r["pix"]) + a.ox, max(i // w for i in r["pix"]) + a.oy] for r in classes["large"]],
             "verifyWindow": layers["crop"]}
    bbox = lambda p: [min(i % w for i in p) + a.ox, min(i // w for i in p) + a.oy, max(i % w for i in p) + a.ox, max(i // w for i in p) + a.oy]
    json.dump({**stats, "defects": [{**{k: v for k, v in r.items() if k != "pix"}, "bbox": bbox(r["pix"])} for r in comps_out]},
              open(os.path.join(a.outdir, "defects.json"), "w"))
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
