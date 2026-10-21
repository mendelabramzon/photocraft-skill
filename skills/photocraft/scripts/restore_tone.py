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

Stained black-and-white or toned prints (--channel): restorers keep the colour channel where the stains are
weakest and drop the others. A stain (foxing, water and glue stains, yellowed patches) is a dye in the paper that
absorbs some colours more than others, on a print that should be one tone. In linear light it multiplies each
channel by its own transmission, so the log-ratios between channels carry the stain and none of the picture: they
give each channel's share of the stain's absorbance. On synthetic yellow-brown stains with known absorbance the
estimate came within 0.025 of the truth, and the channel it picks (red for yellow and brown stains) kept 1.3 % of the
tonal range as stain where a plain luminance conversion kept 4.3 %. --channel adds a monochrome Channel Mixer
layer with that channel (or an equal mix of channels that are almost as clean) under the Tone layer, whose curve
is then measured on the mixed image (its end points come from the kept channel). --retone gives the print its own
tone back on top: a Gradient Map in Color blend whose colours are the clean print's colours at each grey level, so
the stains go and the sepia stays; --channel-only leaves out the Tone layer (not Print tone).

usage: restore_tone.py photo outdir [--area area.json] [--white-ref X,Y] [--black-ref X,Y] [--neutral auto|none|X,Y]
                       [--skin-line] [--amount 1] [--keep-tone] [--lift 0] [--clip 0.1] [--black 6] [--white 248]
                       [--channel auto|red|green|blue|R,G,B [--channel-only] [--retone]] [--protect AREA]

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

--protect AREA keeps the layers off part of the photo, an area.json (its "area" or "skin" polygons minus its
"exclude") or x0,y0,x1,y1: a pasted-in colour print, hand colouring or a coloured mount that the channel step would
turn grey. The area is left out of the measurements and protect.png (black there, edges feathered 4 px) becomes the
mask of every layer written.
Writes outdir/layers.json (the "Tone" layer, with crop + preview so the import verifies itself), preview.png (a
full-resolution window of the result), before_after.png (the whole photo, small) and tone.json (before and after:
percentiles, clippedPct, and "clipped": each channel's % of the area at 0 and at 255); with --channel also
channels.png (the photo, its red, green and blue channels, the chosen mix, and the stains found in magenta).
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
CHANNELS = ("red", "green", "blue")


def monotone(lut):
    return all(lut[i + 1] >= lut[i] for i in range(255))


def stain_absorbance(R, G, B, w, h, idx):
    """How strongly stains show in each channel, from a print that should be one tone. A stain multiplies each
    channel's light by its own transmission, so in linear light ln(R/G) and ln(B/G) move by the stain alone, the
    same at every brightness, while the picture (the same in every channel) cancels out of them. Their clean value
    at each brightness is the densest cluster (the print's own tone, sepia or neutral); pixels well off it are
    stained, and the direction they move in gives the absorbance per channel up to a common part. That part is
    taken as zero in the cleanest channel (yellow and brown stains barely absorb red), which doesn't change which
    channel is cleanest. Returns (share of the area stained, absorbance per channel 0..1 with the strongest 1,
    stain mask) or (share, None, mask) when there are too few stained pixels to tell."""
    N = w * h
    inside = bytearray(N)
    for i in idx:
        inside[i] = 1
    lin = [[imgops.to_linear(v) for v in ch] for ch in (R, G, B)]
    # dark pixels make noisy ratios (and stains hardly show there); clipped ones have lost a channel
    ok = [inside[i] and min(R[i], G[i], B[i]) > 30 and max(R[i], G[i], B[i]) < 253 for i in range(N)]
    qr = [math.log(max(1e-5, lin[0][i]) / max(1e-5, lin[1][i])) for i in range(N)]
    qb = [math.log(max(1e-5, lin[2][i]) / max(1e-5, lin[1][i])) for i in range(N)]
    Y = [imgops.lum(R[i], G[i], B[i]) for i in range(N)]
    nb = 16
    bins = [[] for _ in range(nb)]
    for i in range(0, N, 2):
        if ok[i]:
            bins[min(nb - 1, int(Y[i] / 256 * nb))].append(i)
    centre = [None] * nb
    for k, ids in enumerate(bins):
        if len(ids) < 40:
            continue
        cr = sorted(qr[i] for i in ids)[len(ids) // 2]
        cb = sorted(qb[i] for i in ids)[len(ids) // 2]
        for rad in (0.3, 0.12, 0.06, 0.04):  # mean shift from the median to the densest cluster: stains are a minority
            near = [i for i in ids if math.hypot(qr[i] - cr, qb[i] - cb) < rad]
            if len(near) < 20:
                break
            cr = sorted(qr[i] for i in near)[len(near) // 2]
            cb = sorted(qb[i] for i in near)[len(near) // 2]
        centre[k] = (cr, cb)
    have = [k for k in range(nb) if centre[k]]
    if not have:
        return 0.0, None, [0] * N
    for k in range(nb):
        if centre[k] is None:
            centre[k] = centre[min(have, key=lambda j: abs(j - k))]

    def tone(y):
        x = min(nb - 1.0, max(0.0, y / 256 * nb - 0.5))
        i = int(x); t = x - i; j = min(nb - 1, i + 1)
        return centre[i][0] * (1 - t) + centre[j][0] * t, centre[i][1] * (1 - t) + centre[j][1] * t

    dr, db = [0.0] * N, [0.0] * N
    for i in range(N):
        if ok[i]:
            tr, tb = tone(Y[i])
            dr[i], db[i] = qr[i] - tr, qb[i] - tb
    mag = imgops.gauss([math.hypot(dr[i], db[i]) if ok[i] else 0.0 for i in range(N)], w, h, 1.0)
    vals = sorted(mag[i] for i in range(0, N, 5) if ok[i])
    med = vals[len(vals) // 2]
    mad = sorted(abs(v - med) for v in vals)[len(vals) // 2]
    thr = max(0.03, med + 5 * 1.4826 * mad)  # 0.03: a 3 % transmission difference between channels
    mask = [1 if ok[i] and mag[i] > thr else 0 for i in range(N)]
    keep = [0] * N
    for comp in imgops.components(mask, w, h):  # specks are dust, not stains
        if len(comp) >= max(20, N // 20000):
            for i in comp:
                keep[i] = 1
    st = [i for i in range(N) if keep[i]]
    share = len(st) / max(1, len(idx))
    if share < 0.003:
        return share, None, keep
    # the principal direction of (dr, db) through the origin over the stained pixels, pointing the way they moved
    sxx = sum(dr[i] * dr[i] for i in st); syy = sum(db[i] * db[i] for i in st); sxy = sum(dr[i] * db[i] for i in st)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(ang), math.sin(ang)
    if sum(dr[i] * ux + db[i] * uy for i in st) < 0:
        ux, uy = -ux, -uy
    d = [-ux, 0.0, -uy]  # moved by -(a_r - a_g) t and -(a_b - a_g) t: absorbance relative to green
    lo = min(d)
    top = max(v - lo for v in d) or 1.0
    return share, [round((v - lo) / top, 3) for v in d], keep


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    ap.add_argument("--channel", help="stained black & white or toned print: auto (the channel the stains show least "
                                      "in), red, green, blue, or R,G,B percentages: a monochrome Channel Mixer layer under the tone")
    ap.add_argument("--channel-only", action="store_true",
                    help="with --channel: only the Channel Mixer layer, and Print tone with --retone (import it early and "
                         "judge the repairs through it)")
    ap.add_argument("--retone", action="store_true",
                    help="with --channel: put the print's own tone back on top (Gradient Map from its clean colours, Color blend)")
    ap.add_argument("--protect", metavar="AREA",
                    help="area.json or x0,y0,x1,y1 the layers leave alone (an inset colour print, hand colouring): left out "
                         "of the measurements, masked off every layer (protect.png)")
    a = ap.parse_args()
    if (a.channel_only or a.retone) and not a.channel:
        ap.error("--channel-only and --retone need --channel")
    if a.channel:
        a.channel = a.channel.strip().lower()
        if a.channel not in ("auto",) + CHANNELS:
            try:
                weights = [float(v) for v in a.channel.split(",")]
            except ValueError:
                weights = []
            if len(weights) != 3 or abs(sum(weights) - 100) > 1:
                ap.error("--channel takes auto, red, green, blue, or three percentages that add up to 100 (R,G,B)")
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
    keep = [1.0] * (w * h)  # 0 where --protect keeps the layers off
    if a.protect:
        import mask as maskmod
        pcfg = maskmod.area_cfg(a.protect)
        pp = pcfg["skin"] if isinstance(pcfg["skin"][0][0], (list, tuple)) else [pcfg["skin"]]
        pex = [scale(e) if isinstance(e[0], (list, tuple)) else [round(e[0] * sx), round(e[1] * sy), round(e[2] * sx),
                                                                 round(e[3] * sy)] for e in pcfg["exclude"]]
        keep = [1.0 - v for v in imgops.raster({"skin": [scale(p) for p in pp], "exclude": pex}, 0, 0, w, h)]
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "mask.py"), a.protect,
                            os.path.join(a.outdir, "protect.png"), "--size", str(W), str(H), "--feather", "4",
                            "--inside", "0", "--outside", "1"], capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"error: --protect: {(r.stderr or r.stdout).strip()[:300]}")
        m = [v * k_ for v, k_ in zip(m, keep)]
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

    # --channel: the picture becomes one channel (or a mix) before anything else is measured, as a Channel Mixer layer
    R0, G0, B0 = R, G, B
    mix, stains, smask, warnings = None, None, None, []
    if a.channel:
        share, absorb, smask = stain_absorbance(R, G, B, w, h, idx)
        stains = {"share%": round(100 * share, 1),
                  "absorbance": None if absorb is None else dict(zip(CHANNELS, absorb))}
        if a.channel == "auto":
            if absorb is None:
                mix = [33, 34, 33]  # nothing to avoid: an even mix has the least grain
                warnings.append("no stains found (under 0.3 % of the area): an even mix of the channels")
            else:
                # channels nearly as clean as the cleanest are mixed in equally: less grain, hardly more stain
                best = [c for c in range(3) if absorb[c] <= min(absorb) + 0.1]
                mix = [0, 0, 0]
                for n, c in enumerate(best):
                    mix[c] = 100 // len(best) + (1 if n < 100 % len(best) else 0)
        elif a.channel in CHANNELS:
            mix = [100 if c == a.channel else 0 for c in CHANNELS]
        else:  # whole percentages that add up to 100: a PSD stores the mixer in whole percent (33.3 x 3 would reopen as 99)
            mix = [round(float(v)) for v in a.channel.split(",")]
            mix[mix.index(max(mix))] += 100 - sum(mix)
        if kind == "colour" and med_chroma >= 10:  # (a print with brown shadows and greyer lights reads "colour" too)
            warnings.append("this looks like a colour print: the channel step makes it black and white")
        # PhotoCraft's monochrome Channel Mixer: (r R + g G + b B) / 100, rounded half up (checked on random colours)
        mixf = lambda r, g, b: max(0, min(255, int((mix[0] * r + mix[1] * g + mix[2] * b) / 100 + 0.5)))
        M = [float(mixf(r, g, b)) for r, g, b in zip(R, G, B)]
        R, G, B = M, M, M
        Ys = [M[i] for i in idx]  # the end points come from the mixed channel, not the colour picture's luminance
        a.keep_tone = True  # one grey image now: one composite curve
        if a.retone and not a.channel_only:
            # the paper of a toned print is cream, not white: re-toned at a neutral white level its brightest channel
            # clips (red at 255 over a tenth of a sepia test print). So its white level is lowered just enough that the
            # paper's own colour fits.
            top = imgops.percentile([M[i] for i in idx], 99.5)
            paper = [i for i in idx if M[i] >= top and not smask[i]]
            if len(paper) >= 12:
                c = [sorted(V[i] for i in paper)[len(paper) // 2] for V in (R0, G0, B0)]
                lift = max(c) - imgops.lum(*c)
                if a.white + lift > 254:
                    warnings.append(f"white point lowered from {a.white} to {int(254 - lift)} so the paper's tone doesn't clip")
                    a.white = int(254 - lift)
    else:
        mixf = None

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
    if a.channel_only:
        luts["r"] = list(range(256))

    # --retone: the clean print's own colour at each grey level the Tone layer puts out, as Gradient Map stops in Color
    # blend (it keeps each pixel's luminosity and takes the tone's hue and saturation). PhotoCraft's Gradient Map
    # reads Rec. 601 luma and interpolates its stops linearly in 8-bit RGB (both checked); on a grey image the luma
    # is the grey level itself, so the prediction below is exact.
    stops, gm = None, None
    if a.retone:
        clean = [i for i in idx if not smask[i] and 3 < max(R0[i], G0[i], B0[i]) < 253]
        bins = {}
        for i in clean:
            bins.setdefault(luts["r"][int(R[i])] // 8, []).append(i)
        stops = []
        for k_ in sorted(bins):
            ids = bins[k_]
            if len(ids) >= 12:
                med = [sorted(V[i] for i in ids)[len(ids) // 2] for V in (R0, G0, B0)]
                stops.append([round((8 * k_ + 4) / 255, 4), "#%02x%02x%02x" % tuple(int(v + 0.5) for v in med)])
        if len(stops) < 2:
            warnings.append("too few clean pixels to measure the print's tone: no Print tone layer")
            stops = None
        else:
            cols = [(t, [int(s[1][k:k + 2], 16) for k in (1, 3, 5)]) for t, s in ((s[0], s) for s in stops)]

            def grad(v):
                x = v / 255
                if x <= cols[0][0]:
                    return cols[0][1]
                for (x0, c0), (x1, c1) in zip(cols, cols[1:]):
                    if x <= x1:
                        t = (x - x0) / (x1 - x0)
                        return [int(p + (q - p) * t + 0.5) for p, q in zip(c0, c1)]
                return cols[-1][1]
            gm = [tuple(max(0, min(255, int(c + 0.5))) for c in imgops.set_lum(*grad(v), float(v))) for v in range(256)]

    def apply(r, g, b):  # per-channel curves first, then the composite, as PhotoCraft's Curves does
        if mixf:
            t = luts["r"][mixf(r, g, b)]
            return gm[t] if gm else (t, t, t)
        if a.keep_tone:
            return luts["r"][int(r)], luts["r"][int(g)], luts["r"][int(b)]
        return comp[luts["r"][int(r)]], comp[luts["g"][int(g)]], comp[luts["b"][int(b)]]

    # before/after of the whole photo (small) and numbers
    def kept_off(base, changed, k_):  # a layer mask: k_ of the change (protect.png's value), rounded like a blend
        if k_ >= 1:
            return changed
        return tuple(int(u + k_ * (v - u) + 0.5) for u, v in zip(base, changed)) if k_ > 0 else tuple(base)

    _, _, P0 = pngio.read(stats_png)
    after = [[apply(*p) for p in row] for row in P0]
    if a.protect:
        after = [[kept_off(P0[y][x], p, keep[y * w + x]) for x, p in enumerate(row)] for y, row in enumerate(after)]
    gap = 8
    pngio.write(os.path.join(a.outdir, "before_after.png"), 2 * w + gap, h,
                [P0[y] + [(255, 255, 255)] * gap + after[y] for y in range(h)])
    if mixf:  # the photo | red | green | blue | the mix | the stains found (magenta), each about 300 px wide
        kk = max(1, math.ceil(w / 300))
        pw, ph = w // kk, h // kk
        panels = [lambda i: (R0[i], G0[i], B0[i])] + [lambda i, V=V: (V[i],) * 3 for V in (R0, G0, B0, R)]
        panels.append(lambda i: (255, 0, 255) if smask[i] else (R0[i], G0[i], B0[i]))
        sheet = [[(255, 255, 255)] * (len(panels) * (pw + gap) - gap) for _ in range(ph)]
        for n, f in enumerate(panels):
            for y in range(ph):
                for x in range(pw):
                    sheet[y][n * (pw + gap) + x] = tuple(int(v + 0.5) for v in f(y * kk * w + x * kk))
        pngio.write(os.path.join(a.outdir, "channels.png"), len(sheet[0]), ph, sheet)

    def skin_angle(f):
        if not skin_idx:
            return None
        px = [f(R0[i], G0[i], B0[i]) for i in skin_idx]
        n = len(px)
        return round(imgops.vectorscope(sum(p[0] for p in px) / n, sum(p[1] for p in px) / n, sum(p[2] for p in px) / n)[0], 1)

    def numbers(px):
        ys = [imgops.lum(*p) for p in px]
        lab = [imgops.lab(*p) for p in px[::max(1, len(px) // 20000)]]
        return {"p1": round(imgops.percentile(ys, 1), 1), "p50": round(imgops.percentile(ys, 50), 1),
                "p99": round(imgops.percentile(ys, 99), 1),
                "clippedPct": round(100 * sum(1 for p in px if max(p) >= 255 or min(p) <= 0) / len(px), 2),
                "clipped": {c: [round(100 * sum(1 for p in px if p[k_] <= 0) / len(px), 2),
                                round(100 * sum(1 for p in px if p[k_] >= 255) / len(px), 2)] for k_, c in enumerate(CHANNELS)},
                "meanA": round(sum(v[1] for v in lab) / len(lab), 1), "meanB": round(sum(v[2] for v in lab) / len(lab), 1)}
    before_px = [(R0[i], G0[i], B0[i]) for i in idx]
    after_px = [apply(R0[i], G0[i], B0[i]) for i in idx]
    # the full-resolution window the import is verified on
    ww, wh = min(W, a.window), min(H, a.window)
    wx, wy = (W - ww) // 2, (H - wh) // 2
    win_png = os.path.join(a.outdir, "_window.png")
    run("run", a.photo, "--cmd", "image.crop", "--params", json.dumps({"x": wx, "y": wy, "width": ww, "height": wh}), "--out", win_png)
    _, _, PW = pngio.read(win_png)
    PV = [[apply(*p) for p in row] for row in PW]
    if a.protect:  # the mask's own values over the window (exact except along its feathered edge)
        run("run", os.path.join(a.outdir, "protect.png"), "--cmd", "image.crop", "--params",
            json.dumps({"x": wx, "y": wy, "width": ww, "height": wh}), "--out", win_png)
        KW = imgops.load(win_png)[2]
        PV = [[kept_off(PW[y][x], p, KW[y * ww + x] / 255) for x, p in enumerate(row)] for y, row in enumerate(PV)]
    pngio.write(os.path.join(a.outdir, "preview.png"), ww, wh, PV)
    for p in (stats_png, win_png):
        os.remove(p)

    out_layers = []
    if mixf:
        used = [f"{c} {v:g} %" for c, v in zip(CHANNELS, mix) if v]
        out_layers.append({"name": f"Channel ({used[0].split()[0]}: least stained)" if len(used) == 1 and a.channel == "auto"
                           else "Channel (" + ", ".join(used) + ")",
                           "adjustment": "channelMixer", "params": {"monochrome": True, "gray": [mix[0], mix[1], mix[2], 0]}})
    if not a.channel_only:
        out_layers.append({"name": "Tone (keep print tone)" if a.keep_tone else "Tone (faded dyes)",
                           "adjustment": "curves", "params": params})
    if stops:
        out_layers.append({"name": "Print tone", "adjustment": "gradientMap", "params": {"stops": stops}, "blend": "Color"})
    if a.protect:
        for L in out_layers:
            L["mask"] = "protect.png"
    layers = {"center": [W / 2, H / 2], "crop": [wx, wy, ww, wh], "preview": "preview.png", "layers": out_layers}
    json.dump(layers, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    stats = {"size": [W, H], "kind": kind, "medianChroma": round(med_chroma, 1),
             "ends": {c: [round(v, 1) for v in e] for c, e in ends.items()},
             "neutral": None if spread is None else {"samples": nsamples, "castLevels": round(spread, 1)},
             "curves": None if a.channel_only else params, "before": numbers(before_px), "after": numbers(after_px),
             "skinAngle": None if not skin_idx else {"before": skin_angle(lambda r, g, b: (r, g, b)), "after": skin_angle(apply)}}
    if mixf:
        stats["stains"] = stains
        stats["channelMix"] = dict(zip(CHANNELS, mix))
        stats["printTone"] = {"stops": len(stops)} if stops else None
    if a.protect:
        stats["protect"] = {"mask": "protect.png", "areaPct": round(100 * sum(1 for v in keep if v < 0.5) / len(keep), 1)}
    if warnings:
        stats["warnings"] = warnings
    json.dump(stats, open(os.path.join(a.outdir, "tone.json"), "w"), indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
