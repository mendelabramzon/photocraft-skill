#!/usr/bin/env python3
"""Give a faded print its tonal range and colour back: per-channel black and white points plus neutral midtones,
as one Curves adjustment layer whose result is predicted exactly.

Prints fade unevenly. Blacks turn grey-brown, the paper yellows, and in colour prints one dye goes faster than the
others (usually cyan, leaving a red-magenta print). Each channel has lost a different part of its range, so each gets
its own black and white point, set on the picture's real darkest and lightest values (the classic per-channel Levels
fix). A middle point per channel then makes near-neutral midtones neutral, which takes out the cast that remains
between the ends. --keep-tone stretches the three channels together instead: a sepia or warm-toned print keeps its
tone and only gets its range back.

The layer is a Curves layer (red/green/blue curves, or the composite with --keep-tone): PhotoCraft's Curves are a
natural cubic spline that holds its end values beyond the first and last points, which this script reproduces
exactly, so import_layers.py can verify the render. (Levels was not used: its gamma has a toe near black that is
not a plain power curve.)

usage: restore_tone.py photo outdir [--area area.json] [--white-ref X,Y] [--black-ref X,Y] [--neutral auto|none|X,Y]
                       [--skin-line] [--amount 1] [--keep-tone] [--lift 0] [--clip 0.1] [--black 6] [--white 248]

photo      any file the CLI opens (the scan, or a render of the restored state); needs photocraft-cli
area.json  {"area": [[x, y], ...] or [poly, ...], "exclude": [...]} in full-image coordinates: the picture itself,
           without the scan's borders, mount, handwriting or big damage, which would otherwise set the end points.
           Without it, a 3 % margin is left out on every side. Optional "skin": polygons of skin, whose
           vectorscope angle is reported before and after (skin of every complexion sits near 123 degrees);
           --skin-line also brings it back into the normal 115-130 degree band when it lies outside: the most
           reliable colour reference in a family photo with no neutral in it.

The end points assume the picture's lightest and darkest real tones were white and black in every channel. That
holds for most snapshots (a white shirt, a dark suit, deep shadow) and fails on scenes with no neutral at either end
(a yellow scarf as the lightest thing turns white). Then give --white-ref / --black-ref on something that was white
or black, or use --keep-tone, and judge skin by its angle.
Writes outdir/layers.json (the "Tone" layer, with crop + preview so the import verifies itself), preview.png (a
full-resolution window of the result), before_after.png (the whole photo, small) and tone.json.
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

SKIN_BAND = (115.0, 130.0)  # vectorscope angles where skin of every complexion sits, around the 123-degree skin line


def monotone(lut):
    return all(lut[i + 1] >= lut[i] for i in range(255))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("photo"); ap.add_argument("outdir")
    ap.add_argument("--area", help="area.json: the picture without borders, mount, writing, big damage")
    ap.add_argument("--keep-tone", action="store_true", help="stretch all channels together: keep a sepia/warm tone")
    ap.add_argument("--white-ref", help="X,Y of something that was white: its colour sets the white points")
    ap.add_argument("--black-ref", help="X,Y of something that was black: its colour sets the black points")
    ap.add_argument("--neutral", default="auto", help="auto, none, or X,Y of something that should be neutral grey/white")
    ap.add_argument("--skin-line", action="store_true",
                    help="also bring the mean skin (area.json \"skin\") back into the normal 115-130 degree band if it's outside")
    ap.add_argument("--amount", type=float, default=1.0, help="how much of the midtone cast to take out (0..1)")
    ap.add_argument("--lift", type=float, default=0, help="levels to raise the midtones by: a print that is dark, not faded")
    ap.add_argument("--clip", type=float, default=0.1, help="%% of the picture allowed to reach the end points, each end")
    ap.add_argument("--black", type=int, default=6, help="output level of the darkest real tone (rich black, not crushed)")
    ap.add_argument("--white", type=int, default=248, help="output level of the lightest real tone (paper white with texture)")
    ap.add_argument("--stats-size", type=int, default=1000, help="long side of the downscaled copy the statistics use")
    ap.add_argument("--window", type=int, default=640, help="size of the full-resolution preview window")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: needs photocraft-cli (`pc.py cli-info` says which one)")

    def run(*args):
        r = subprocess.run([str(cli)] + [str(x) for x in args], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"error: photocraft-cli {' '.join(map(str, args))[:200]}: {r.stderr.strip()[:300]}")
        return r.stdout

    info = json.loads(run("info", a.photo, "--compact"))
    W, H = info["width"], info["height"]
    # statistics on a small copy, after a light median so dust specks can't set the end points
    k = min(1.0, a.stats_size / max(W, H))
    stats_png = os.path.join(a.outdir, "_stats.png")
    cmds = ["--cmd", "filter.noise.median", "--params", json.dumps({"radius": max(1, round(2 / max(k, 0.25)))})]
    if k < 1:
        cmds += ["--cmd", "image.imageSize", "--params", json.dumps({"width": max(1, round(W * k)), "resample": "bilinear"})]
    run("run", a.photo, *cmds, "--out", stats_png)
    w, h, R, G, B = imgops.load(stats_png)
    sx, sy = w / W, h / H
    cfg = json.load(open(a.area)) if a.area else {}
    scale = lambda p: [[x * sx, y * sy] for x, y in p]
    polys = cfg.get("area") or [[0.03 * W, 0.03 * H], [0.97 * W, 0.03 * H], [0.97 * W, 0.97 * H], [0.03 * W, 0.97 * H]]
    polys = [scale(p) for p in (polys if isinstance(polys[0][0], (list, tuple)) else [polys])]
    excl = [scale(e) if isinstance(e[0], (list, tuple)) else scale([[e[0], e[1]], [e[2], e[1]], [e[2], e[3]], [e[0], e[3]]])
            for e in cfg.get("exclude", [])]
    m = imgops.polygon_mask(polys, 0, 0, w, h, excl)
    idx = [i for i in range(w * h) if m[i] > 0.5]
    if len(idx) < 100:
        sys.exit("error: the area holds almost no pixels")

    Ys = [imgops.lum(R[i], G[i], B[i]) for i in idx]
    lab0 = [imgops.lab(R[i], G[i], B[i]) for i in idx[::max(1, len(idx) // 20000)]]
    chroma = sorted(math.hypot(v[1], v[2]) for v in lab0)
    med_chroma = chroma[len(chroma) // 2]
    hue_x = sum(v[1] for v in lab0) / len(lab0); hue_y = sum(v[2] for v in lab0) / len(lab0)
    # a monochrome print: low chroma, or chroma that all points one way (a tone), not a colour picture
    mean_dir = math.hypot(hue_x, hue_y) / max(1e-6, sum(math.hypot(v[1], v[2]) for v in lab0) / len(lab0))
    kind = "monochrome" if med_chroma < 4 else "toned monochrome" if med_chroma < 14 and mean_dir > 0.9 else "colour"

    def sample(xy, r=2):
        X, Y = (float(v) for v in xy.split(","))
        cx, cy = int(X * sx), int(Y * sy)
        pix = [y * w + x for y in range(max(0, cy - r), min(h, cy + r + 1)) for x in range(max(0, cx - r), min(w, cx + r + 1))]
        return {c: sum(V[i] for i in pix) / len(pix) for c, V in (("r", R), ("g", G), ("b", B))}, pix

    if a.keep_tone:
        lo, hi = imgops.percentile(Ys, a.clip), imgops.percentile(Ys, 100 - a.clip)
        ends = {c: (lo, hi) for c in "rgb"}
    else:
        ends = {c: (imgops.percentile([V[i] for i in idx], a.clip), imgops.percentile([V[i] for i in idx], 100 - a.clip))
                for c, V in (("r", R), ("g", G), ("b", B))}
    wref = sample(a.white_ref)[0] if a.white_ref else None
    bref = sample(a.black_ref)[0] if a.black_ref else None
    if wref or bref:
        ends = {c: ((bref or {}).get(c, ends[c][0]), (wref or {}).get(c, ends[c][1])) for c in "rgb"}
    for c, (lo, hi) in ends.items():
        if hi - lo < 20:
            sys.exit(f"error: channel {c} spans only {hi - lo:.0f} levels in the area; check the area")

    def lin(c, v):
        lo, hi = ends[c]
        return a.black + (v - lo) * (a.white - a.black) / (hi - lo)

    skin_idx = []
    if cfg.get("skin"):
        sp = cfg["skin"]
        sp = [scale(p) for p in (sp if isinstance(sp[0][0], (list, tuple)) else [sp])]
        skin_idx = [i for i, v in enumerate(imgops.polygon_mask(sp, 0, 0, w, h)) if v > 0.5]
    if a.skin_line and not skin_idx:
        sys.exit("error: --skin-line needs \"skin\" polygons in area.json")

    # middle points, each a colour that should come out a known way: a neutral (equal R, G, B at its own
    # luminance), and with --skin-line the mean skin (back inside the skin band, at its own luma and saturation)
    cons, nsamples, spread = [], 0, None
    if not a.keep_tone and a.neutral != "none":
        if a.neutral == "auto":
            cand = []
            for i in idx:
                r, g, b = lin("r", R[i]), lin("g", G[i]), lin("b", B[i])
                y = imgops.lum(r, g, b)
                if 60 < y < 200:
                    cand.append((max(r, g, b) - min(r, g, b), i))
            cand.sort()
            pick = [i for _, i in cand[:max(50, len(cand) // 5)]]
        else:
            pick = sample(a.neutral)[1]
        nsamples = len(pick)
        mu = {c: sum(V[i] for i in pick) / len(pick) for c, V in (("r", R), ("g", G), ("b", B))}
        out = {c: lin(c, mu[c]) for c in "rgb"}
        y = imgops.lum(out["r"], out["g"], out["b"])
        spread = max(out.values()) - min(out.values())
        cons.append(("neutral", mu, {c: y for c in "rgb"}))
    if a.skin_line and not a.keep_tone:
        # only as far as the edge of the normal band: skin varies with complexion and light, so a skin that is
        # already plausible is left alone, and one that is off is brought just back into the band
        mu = {c: sum(V[i] for i in skin_idx) / len(skin_idx) for c, V in (("r", R), ("g", G), ("b", B))}
        r, g, b = (lin(c, mu[c]) for c in "rgb")
        y = 0.299 * r + 0.587 * g + 0.114 * b
        ang, sat = imgops.vectorscope(r, g, b)
        want = min(max(ang, SKIN_BAND[0]), SKIN_BAND[1])
        if want != ang:
            u, v = sat * math.cos(math.radians(want)), sat * math.sin(math.radians(want))
            tr, tb = y + v / 0.877, y + u / 0.492
            cons.append(("skin", mu, {"r": tr, "g": (y - 0.299 * tr - 0.114 * tb) / 0.587, "b": tb}))
    mids = {c: [] for c in "rgb"}
    for _, mu, target in cons:
        for c in "rgb":
            lo, hi = ends[c]
            t = (mu[c] - lo) / (hi - lo)
            # a middle point too close to an end, or to another middle point, bends the spline too hard
            if 0.1 < t < 0.9 and all(abs(mu[c] - m[0]) > 0.08 * (hi - lo) for m in mids[c]):
                o = lin(c, mu[c])
                mids[c].append((mu[c], o + a.amount * (target[c] - o)))
    curves, luts = {}, {}
    for c in "rgb":
        lo, hi = ends[c]
        mid = sorted(mids[c])
        for _ in range(8):  # back the middle points off until the curve rises everywhere
            pts = [[int(round(lo)), a.black]] + [[int(round(x)), int(round(y))] for x, y in mid] + [[int(round(hi)), a.white]]
            lut = imgops.spline_lut(pts)
            if monotone(lut):
                break
            mid = [(x, lin(c, x) + 0.5 * (y - lin(c, x))) for x, y in mid]
        else:
            pts = [[int(round(lo)), a.black], [int(round(hi)), a.white]]
            lut = imgops.spline_lut(pts)
        curves[c], luts[c] = pts, lut
    # --lift: a middle point on the composite curve at the median tone, for a print that is dark rather than faded
    comp = list(range(256))
    if a.lift:
        ys = sorted(imgops.lum(luts["r"][int(R[i])], luts["g"][int(G[i])], luts["b"][int(B[i])]) for i in idx[::7])
        m = int(round(ys[len(ys) // 2]))
        if a.keep_tone:  # one composite curve: the stretch with the lifted middle point on it
            lo, hi = ends["r"]
            x_m = lo + (m - a.black) * (hi - lo) / (a.white - a.black)
            curves["r"] = [curves["r"][0], [int(round(x_m)), int(round(m + a.lift))], curves["r"][-1]]
            luts["r"] = imgops.spline_lut(curves["r"])
        else:
            comp_pts = [[0, 0], [m, int(round(m + a.lift))], [255, 255]]
            comp = imgops.spline_lut(comp_pts)
        if not monotone(luts["r"] if a.keep_tone else comp):
            sys.exit("error: --lift too large for this photo")
    params = {"points": curves["r"]} if a.keep_tone else {"red": curves["r"], "green": curves["g"], "blue": curves["b"]}
    if a.lift and not a.keep_tone:
        params["points"] = comp_pts

    def apply(r, g, b):  # per-channel curves first, then the composite, as PhotoCraft's Curves does
        if a.keep_tone:
            return luts["r"][int(r)], luts["r"][int(g)], luts["r"][int(b)]
        return comp[luts["r"][int(r)]], comp[luts["g"][int(g)]], comp[luts["b"][int(b)]]

    # before/after of the whole photo (small) and numbers
    _, _, P0 = pngio.read(stats_png)
    after = [[apply(*p) for p in row] for row in P0]
    gap = 8
    pngio.write(os.path.join(a.outdir, "before_after.png"), 2 * w + gap, h,
                [P0[y] + [(255, 255, 255)] * gap + after[y] for y in range(h)])

    def skin_angle(f):
        if not skin_idx:
            return None
        px = [f(R[i], G[i], B[i]) for i in skin_idx]
        n = len(px)
        return round(imgops.vectorscope(sum(p[0] for p in px) / n, sum(p[1] for p in px) / n, sum(p[2] for p in px) / n)[0], 1)

    def numbers(px):
        ys = [imgops.lum(*p) for p in px]
        lab = [imgops.lab(*p) for p in px[::max(1, len(px) // 20000)]]
        return {"p1": round(imgops.percentile(ys, 1), 1), "p50": round(imgops.percentile(ys, 50), 1),
                "p99": round(imgops.percentile(ys, 99), 1),
                "clippedPct": round(100 * sum(1 for p in px if max(p) >= 255 or min(p) <= 0) / len(px), 2),
                "meanA": round(sum(v[1] for v in lab) / len(lab), 1), "meanB": round(sum(v[2] for v in lab) / len(lab), 1)}
    before_px = [(R[i], G[i], B[i]) for i in idx]
    after_px = [apply(R[i], G[i], B[i]) for i in idx]
    # the full-resolution window the import is verified on
    ww, wh = min(W, a.window), min(H, a.window)
    wx, wy = (W - ww) // 2, (H - wh) // 2
    win_png = os.path.join(a.outdir, "_window.png")
    run("run", a.photo, "--cmd", "image.crop", "--params", json.dumps({"x": wx, "y": wy, "width": ww, "height": wh}), "--out", win_png)
    _, _, PW = pngio.read(win_png)
    pngio.write(os.path.join(a.outdir, "preview.png"), ww, wh, [[apply(*p) for p in row] for row in PW])
    for p in (stats_png, win_png):
        os.remove(p)

    layers = {"center": [W / 2, H / 2], "crop": [wx, wy, ww, wh], "preview": "preview.png",
              "layers": [{"name": "Tone (keep print tone)" if a.keep_tone else "Tone (faded dyes)",
                          "adjustment": "curves", "params": params}]}
    json.dump(layers, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    stats = {"size": [W, H], "kind": kind, "medianChroma": round(med_chroma, 1),
             "ends": {c: [round(v, 1) for v in e] for c, e in ends.items()},
             "neutral": None if spread is None else {"samples": nsamples, "castLevels": round(spread, 1)},
             "curves": params, "before": numbers(before_px), "after": numbers(after_px),
             "skinAngle": None if not skin_idx else {"before": skin_angle(lambda r, g, b: (r, g, b)), "after": skin_angle(apply)}}
    json.dump(stats, open(os.path.join(a.outdir, "tone.json"), "w"), indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
