#!/usr/bin/env python3
"""Plan, enhance and check a sky replacement, from a sky_mask.py folder (crop.png, alpha.png, edge.png, mask.json).

  sky_check.py plan    maskdir sky.jpg [--sky-x 0.5 --sky-y 1 --zoom 1 --flip] [--harmonize 0.5] [--ev 0] [--haze 0.3]
  sky_check.py plan    maskdir --clear-blue [--haze 0.2]           (real-estate gradient sky, no sky photo)
  sky_check.py enhance maskdir [--contrast 1.35] [--grad 0.5]      (keep the sky, give it depth)
  sky_check.py check   maskdir [--render export.png]               (after the import: halo, grain, horizon)

plan fits the new sky to the crop (the CLI crops and resizes it, converts it to the photo's colour profile, can
mirror it to put its sun on the side the scene is lit from, adds grain if the photo has more), measures the old
and new sky and the land, and writes layers.json for import_layers.py:

  Sky replacement (group)
    Horizon haze             Solid Color = the old sky's horizon colour, mask = a ramp up from the horizon (--haze)
    Sky                      the fitted sky photo, mask = alpha.png
    Foreground harmonise     Curves, red/green/blue: the land takes part of the new light's colour (--harmonize)
                             and an exposure change (--ev), in linear light
    Sky edges                edge.png, mask = edge_mask.png: edge pixels with the old sky taken out
  Background                 untouched

preview.png is the exact predicted result (PhotoCraft's Curves spline and Normal blending, 8-bit masks), so
import_layers.py verifies the build against it; compare.png shows before | after, plan.json the measurements.

Harmonising follows the colour of the light, not of the sky: a scene is lit mostly by the sun, whose colour shows
in the lit clouds (white at noon, golden late in the day), so the reference is the brightest sky pixels that
aren't blue, old and new. Each channel of the land is scaled in linear light by (new light / old light) ^
--harmonize, normalised so luminance stays (Photoshop's Sky Replacement calls this Color Adjustment). A clear blue
sky has no lit clouds and leaves the land's colour alone. Exposure is left to --ev: a sunny sky doesn't make an
overcast foreground sunlit.

check takes the luminance profile across the sky edge in 24 px tiles. A light rim right at the edge, brighter than
both the new sky beside it and the land behind it, is the old sky left in the edge pixels or a mask that stops
short. Thin things (finials, aerials, twigs) have no inside to compare with, and against a darker new sky their
stone or metal rightly looks lighter than the sky, so those tiles are only marked for the eye. It also compares
the new sky's grain with the old one's and reports how the sky's brightness runs toward the horizon.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imgops import box, components, downscale, from_linear, load, lut_f, percentile, save_gray, save_rgb, set_lum, \
    spline_lut, to_linear
from sky_mask import cli_run

NOISE_PER_AMOUNT = 0.64  # Add Noise (gaussian, monochromatic): sigma in levels per unit of amount (PhotoCraft 0.7.0)
CLEAR_BLUE = ("#5d8fd0", "#cfe0ef")  # zenith, horizon: a believable clear sky (sRGB), not the saturated "stock" blue


def load_dir(md):
    meta = json.load(open(os.path.join(md, "mask.json")))
    w, h, R, G, B = load(os.path.join(md, "crop.png"))
    A = [v / 255 for v in load(os.path.join(md, "alpha.png"))[2]]
    return meta, w, h, (R, G, B), A


def skyline(A, w, h):
    """Per column, the lowest row that is sky (alpha > 0.5), smoothed with a running median so chimneys and
    tree gaps don't make spikes; -1 where a column has no sky."""
    ys = [-1] * w
    for i, v in enumerate(A):
        if v > 0.5:
            ys[i % w] = max(ys[i % w], i // w)
    r = max(3, w // 40)
    out = []
    for x in range(w):
        win = sorted(v for v in ys[max(0, x - r):x + r + 1] if v >= 0)
        out.append(win[len(win) // 2] if win else -1)
    return out


def horizon_line(ys, w):
    """A straight horizon for ramps (haze, graduated darkening): a least-squares line through the lowest sky in
    each eighth of the width. Following each column's skyline instead would step at every tree and roof."""
    pts = []
    for k in range(8):
        win = [v for v in ys[k * w // 8:(k + 1) * w // 8] if v >= 0]
        if win:
            pts.append(((k + 0.5) * w / 8, max(win)))
    if not pts:
        return [0.0] * w
    if len(pts) == 1:
        return [pts[0][1]] * w
    mx = sum(p[0] for p in pts) / len(pts); my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx else 0.0
    return [my + b * (x - mx) for x in range(w)]


def near_horizon(A, w, h, ys, frac=0.15):
    """Indices of clean sky (alpha >= 0.99) in a band above the skyline, frac x the crop height tall."""
    hb = max(10, round(frac * h))
    return [i for i, v in enumerate(A) if v >= 0.99 and ys[i % w] >= 0 and ys[i % w] - hb <= i // w <= ys[i % w]]


def mean_rgb(ch, idx):
    n = max(1, len(idx))
    return [sum(c[i] for i in idx) / n for c in ch]


def lin_y(rgb):
    return 0.2126 * to_linear(rgb[0]) + 0.7152 * to_linear(rgb[1]) + 0.0722 * to_linear(rgb[2])


def grain(L, w, h, idx):
    """Robust grain of luminance at pixels idx: 1.4826 x median |L - 3x3 mean| (0.943 x sigma for white noise)."""
    d = []
    for i in idx:
        x, y = i % w, i // w
        if 0 < x < w - 1 and 0 < y < h - 1:
            m = (L[i - w - 1] + L[i - w] + L[i - w + 1] + L[i - 1] + L[i] + L[i + 1] + L[i + w - 1] + L[i + w] + L[i + w + 1]) / 9
            d.append(abs(L[i] - m))
    d.sort()
    return 1.4826 * d[len(d) // 2] if d else 0.0


def gain_curve(g):
    """Curve points that scale a channel by g in linear light, keeping black, and white too when g > 1."""
    pts = []
    for x in (0, 24, 64, 112, 160, 208, 255):
        y = from_linear(to_linear(x) * g)
        if x == 255:
            y = 255 if g >= 1 else y
        pts.append([x, round(min(255.0, max(0.0, y)), 1)])
    for k in range(1, len(pts)):  # keep it rising
        pts[k][1] = max(pts[k][1], pts[k - 1][1] + 0.5)
    pts[-1][1] = min(255, pts[-1][1])
    return pts


def to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


def from_hex(s):
    return [int(s[i:i + 2], 16) for i in (1, 3, 5)]


def cmd_plan(a):
    md = os.path.abspath(os.path.expanduser(a.maskdir))
    meta, w, h, ch, A = load_dir(md)
    R, G, B = ch
    N = w * h
    L = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(R, G, B)]
    ys = skyline(A, w, h)
    hz = near_horizon(A, w, h, ys)
    if len(hz) < 200:
        sys.exit("error: too little clean sky above the skyline to measure; check alpha.png")
    sky_all = [i for i, v in enumerate(A) if v >= 0.99]
    fg = [i for i, v in enumerate(A) if v <= 0.01]
    target = meta["source"].get("profile")
    out_sky = os.path.join(md, "sky_fitted.png")
    warnings = []
    fit = {}

    if a.clear_blue:
        top, bot = from_hex(a.zenith or CLEAR_BLUE[0]), from_hex(a.horizon_color or CLEAR_BLUE[1])
        # vertical gradient from the zenith colour at the top to the horizon colour at the median skyline, in
        # linear light (a gamma-space blend goes muddy in the middle), dithered so 8 bits don't band
        ymed = sorted(v for v in ys if v >= 0)[len([v for v in ys if v >= 0]) // 2]
        rs, gs, bs = [], [], []
        seed = 12345
        for y in range(h):
            t = min(1.0, y / max(1, ymed))
            t = t ** 1.6  # clear skies pale quickly toward the horizon
            col = [from_linear((1 - t) * to_linear(c0) + t * to_linear(c1)) for c0, c1 in zip(top, bot)]
            for x in range(w):
                seed = (seed * 1103515245 + 12345) & 0x7fffffff
                dz = ((seed >> 8) % 1000) / 1000 - 0.5
                rs.append(col[0] + dz); gs.append(col[1] + dz); bs.append(col[2] + dz)
        save_rgb(out_sky, w, h, rs, gs, bs)
        fit = {"kind": "clearBlue", "zenith": to_hex(top), "horizon": to_hex(bot)}
    else:
        info = cli_run([a.sky, "--cmd", "document.inspect", "--cmd", "edit.profileInfo", "--params", '{"profile": "document"}'])
        sw, sh = info[0]["result"]["width"], info[0]["result"]["height"]
        pinfo = info[1]["result"]
        sky_prof = (pinfo.get("profile") or {}).get("description")
        ids = {b["description"]: b["id"] for b in pinfo.get("builtins", [])}
        # an embedded "ProPhoto RGB" or "Adobe RGB (1998)" has a "-compat" builtin with the same primaries
        for fam, bid in (("ProPhoto", "prophoto-compat"), ("Adobe RGB", "adobe-rgb-compat"), ("Display P3", "display-p3")):
            if target and fam in target and target not in ids and bid in ids.values():
                ids[target] = bid
        x0, y0, rw0, rh0 = a.sky_rect or [0, 0, sw, sh]
        aspect = w / h
        if rw0 / rh0 > aspect:
            rh, rw = rh0, rh0 * aspect
        else:
            rw, rh = rw0, rw0 / aspect
        rw, rh = rw / a.zoom, rh / a.zoom
        rx = x0 + (rw0 - rw) * a.sky_x
        ry = y0 + (rh0 - rh) * a.sky_y
        crop = {"x": round(rx), "y": round(ry), "width": round(rw), "height": round(rh), "targetWidth": w, "targetHeight": h}
        steps = [["image.crop", crop]]
        if a.flip:
            steps.append(["image.imageRotation.flipCanvasHorizontal", {}])
        if sky_prof != target:
            if target in ids:
                steps.append(["edit.convertToProfile", {"profile": ids[target]}])
            else:
                warnings.append(f"photo profile {target!r} is not a builtin: sky colours are not converted to it")
        scale = w / rw
        if scale > 1.5:
            warnings.append(f"sky enlarged {scale:.1f}x: softer than the photo; use a larger sky or less --zoom")
        args = [a.sky]
        for c, p in steps:
            args += ["--cmd", c, "--params", json.dumps(p)]
        cli_run(args + ["--out", out_sky])
        fit = {"kind": "photo", "sky": os.path.abspath(a.sky), "rect": [crop["x"], crop["y"], crop["width"], crop["height"]],
               "scale": round(scale, 3), "flip": a.flip, "skyProfile": sky_prof, "converted": sky_prof != target}
        # grain: the old sky shows how much noise this camera put in a sky; a cleaner new sky gets that added
        _, _, NR, NG, NB = load(out_sky)
        NL = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(NR, NG, NB)]
        inner = [i for i in sky_all[::7] if 3 <= i % w < w - 3 and 3 <= i // w < h - 3
                 and all(A[i + dy * w + dx] >= 0.99 for dy in (-3, 0, 3) for dx in (-3, 0, 3))]
        g_old, g_new = grain(L, w, h, inner), grain(NL, w, h, inner)
        fit["grain"] = {"old": round(g_old, 2), "new": round(g_new, 2)}
        add = math.sqrt(max(0.0, g_old ** 2 - g_new ** 2)) / 0.943 if a.grain else 0.0
        if add >= 0.6:
            amount = round(add / NOISE_PER_AMOUNT, 2)
            cli_run(args + ["--cmd", "filter.noise.addNoise", "--params",
                            json.dumps({"amount": amount, "distribution": "gaussian", "monochromatic": True, "seed": 1}),
                            "--out", out_sky])
            fit["grain"]["addNoise"] = amount
    _, _, NR, NG, NB = load(out_sky)

    # non-sky content in the part of the sky photo used (trees, poles, roofs at its edge): dark against the sky
    NLf = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(NR, NG, NB)]
    med = percentile([NLf[i] for i in sky_all[::11]], 50)
    kd = 2  # at half size: it's looking for objects, not pixels
    Ld, dw, dh = downscale(NLf, w, h, kd)
    Ad = downscale(A, w, h, kd)[0]
    Rd, Bd = downscale(NR, w, h, kd)[0], downscale(NB, w, h, kd)[0]
    loc = box(Ld, dw, dh, 8)
    dark = [1 if (Ad[i] > 0.5 and Ld[i] < 0.6 * med and Ld[i] < loc[i] - 25 and Bd[i] < Rd[i] + 20) else 0
            for i in range(dw * dh)]
    blobs = [c_ for c_ in components(dark, dw, dh) if len(c_) > max(15, dw * dh // 20000)]
    if blobs:
        xs = [kd * (i % dw) for c_ in blobs for i in c_]; yy = [kd * (i // dw) for c_ in blobs for i in c_]
        warnings.append(f"the sky photo shows something dark that isn't sky (trees, a pole?) around x {min(xs)}-{max(xs)}, "
                        f"y {min(yy)}-{max(yy)} of the crop: leave it out with --sky-rect or move it with --sky-x/--sky-y")

    # how the new sky meets the land: colour and brightness just above the skyline
    s_old, s_new = mean_rgb(ch, hz), mean_rgb((NR, NG, NB), hz)
    y_fg = sorted(lin_y((R[i], G[i], B[i])) for i in fg[::5])
    y_fg_med = y_fg[len(y_fg) // 2] if y_fg else 0.18
    stops_old = math.log2(max(1e-4, lin_y(s_old)) / max(1e-4, y_fg_med))
    stops_new = math.log2(max(1e-4, lin_y(s_new)) / max(1e-4, y_fg_med))
    # the colour of the light, not of the sky: the land is lit mostly by the sun, whose colour shows in the lit
    # clouds (white at noon, golden or pink late in the day), while blue sky is a small share of the light. So the
    # brightest sky pixels that aren't blue, old and new; a clear blue sky has none and leaves the land as it is.
    def light(chs, idx):
        L_ = sorted(((0.3 * chs[0][i] + 0.59 * chs[1][i] + 0.11 * chs[2][i]), i) for i in idx)
        top = [i for _, i in L_[int(len(L_) * 0.85):]]
        warm = [i for i in top if chs[2][i] <= 1.08 * max(chs[0][i], chs[1][i]) and max(c_[i] for c_ in chs) < 254]
        return mean_rgb(chs, warm) if len(warm) > max(50, len(top) // 10) else None
    l_old, l_new = light(ch, sky_all[::3]), light((NR, NG, NB), sky_all[::3])
    if l_old and l_new and not a.clear_blue:
        ratio = [max(1e-4, to_linear(n)) / max(1e-4, to_linear(o)) for n, o in zip(l_new, l_old)]
    else:
        ratio = [1.0, 1.0, 1.0]
    gains = [r ** a.harmonize for r in ratio]
    yg = 0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2]
    ev = 2 ** a.ev
    gains = [g / yg * ev for g in gains]
    curves = {c: gain_curve(g) for c, g in zip(("red", "green", "blue"), gains)}
    luts = [spline_lut(curves[c]) for c in ("red", "green", "blue")]
    if stops_new < 0.5:
        warnings.append(f"new sky only {stops_new:.1f} stops above the land near the horizon (old: {stops_old:.1f}): "
                        "it will look pasted on; pick a lighter sky, add --haze, or darken the land with --ev")
    elif stops_new > max(4.5, stops_old + 1):
        warnings.append(f"new sky {stops_new:.1f} stops above the land (old: {stops_old:.1f}): the land will look "
                        "underexposed; --ev up a little")
    y_top = max(1, min(v for v in ys if v >= 0)) * 0.4
    top_band = [i for i in sky_all if i // w < y_top]
    if top_band:
        l_top = lin_y(mean_rgb((NR, NG, NB), top_band))
        if lin_y(s_new) < 0.85 * l_top and not a.clear_blue:
            warnings.append("the new sky gets darker toward the horizon (it was shot upward): real skies pale and "
                            "brighten there; use --sky-y to take its lower part, or --haze 0.3")

    # horizon haze: the scene's own horizon colour, rising from the skyline, on the sky only
    haze = None
    hm = [0.0] * N
    if a.haze > 0:
        hz = horizon_line(ys, w)
        hh = max(8.0, a.haze_height * sum(hz) / w)
        for i in range(N):
            if A[i] <= 0:
                continue
            t = 1 - (hz[i % w] - i // w) / hh
            if t > 0:
                hm[i] = a.haze * A[i] * min(1.0, t) ** 2
        haze = [c for c in s_old]
        save_gray(os.path.join(md, "haze.png"), w, h, hm)

    # exact preview, stacked like the document: Background -> Sky edges -> Foreground harmonise -> Sky -> haze
    _, _, ER, EG, EB = load(os.path.join(md, "edge.png"))
    EM = [v / 255 for v in load(os.path.join(md, "edge_mask.png"))[2]]
    q = lambda v: round(min(1.0, max(0.0, v)) * 255) / 255
    hq = [q(v) for v in hm]
    hcol = [round(v) for v in haze] if haze else None
    P = [[], [], []]
    for i in range(N):
        m = EM[i]
        base = [e[i] * m + c_[i] * (1 - m) for e, c_ in ((ER, R), (EG, G), (EB, B))] if m else [R[i], G[i], B[i]]
        base = [float(lut_f(lt, v)) for lt, v in zip(luts, base)]
        al = A[i]
        o = [al * s + (1 - al) * b for s, b in zip((NR[i], NG[i], NB[i]), base)]
        if hcol and hq[i]:
            o = [hq[i] * c + (1 - hq[i]) * v for c, v in zip(hcol, o)]
        for k in range(3):
            P[k].append(o[k])
    save_rgb(os.path.join(md, "preview.png"), w, h, *P)
    # before | after at a viewable size
    k = max(1, math.ceil(w / 900))
    bw, bh = w // k, h // k
    cmp = [[], [], []]
    halves = [[downscale(c, w, h, k)[0] for c in ch], [downscale(c, w, h, k)[0] for c in P]]
    gap = 8
    cw = 2 * bw + gap
    for y in range(bh):
        for x in range(cw):
            if x < bw:
                v = [hc[y * bw + x] for hc in halves[0]]
            elif x < bw + gap:
                v = [255, 255, 255]
            else:
                v = [hc[y * bw + x - bw - gap] for hc in halves[1]]
            for c in range(3):
                cmp[c].append(v[c])
    save_rgb(os.path.join(md, "compare.png"), cw, bh, *cmp)

    layers = [{"name": "Sky edges (decontaminated)", "image": "edge.png", "mask": "edge_mask.png"},
              {"name": "Foreground harmonise", "adjustment": "curves", "params": curves},
              {"name": "Sky", "image": "sky_fitted.png", "mask": "alpha.png"}]
    if haze:
        layers.append({"name": "Horizon haze", "fill": to_hex(haze), "mask": "haze.png"})
    spec = {"center": meta["center"], "crop": meta["crop"], "preview": "preview.png", "group": "Sky replacement",
            "layers": layers}
    json.dump(spec, open(os.path.join(md, "layers.json"), "w"), indent=1)
    stats = {"fit": fit, "skyOld": [round(v, 1) for v in s_old], "skyNew": [round(v, 1) for v in s_new],
             "stopsAboveLand": {"old": round(stops_old, 2), "new": round(stops_new, 2)},
             "lightOld": [round(v, 1) for v in l_old] if l_old else None, "lightNew": [round(v, 1) for v in l_new] if l_new else None,
             "harmonize": a.harmonize, "gains": [round(g, 4) for g in gains], "ev": a.ev,
             "haze": {"amount": a.haze, "color": to_hex(haze)} if haze else None, "warnings": warnings}
    json.dump(stats, open(os.path.join(md, "plan.json"), "w"), indent=1)
    print(json.dumps(stats))


def cmd_enhance(a):
    """Keep the sky; give it back depth: a contrast curve on its own tones and a graduated darkening toward the
    top, both in Luminosity mode and masked to the sky (the advantage over a glass grad filter: nothing that
    sticks up into the sky darkens). Or say it's beyond rescue."""
    md = os.path.abspath(os.path.expanduser(a.maskdir))
    meta, w, h, ch, A = load_dir(md)
    R, G, B = ch
    N = w * h
    L = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(R, G, B)]
    sky = [i for i, v in enumerate(A) if v >= 0.99]
    if len(sky) < 500:
        sys.exit("error: too little sky in alpha.png")
    blown = sum(1 for i in sky if min(R[i], G[i], B[i]) >= 250) / len(sky)
    trend = box(box(L, w, h, 12), w, h, 12)
    detail = 1.4826 * percentile([abs(L[i] - trend[i]) for i in sky[::3]], 50)
    chroma = percentile([max(R[i], G[i], B[i]) - min(R[i], G[i], B[i]) for i in sky[::3]], 50)
    sl = sorted(L[i] for i in sky)
    p2, p50, p98 = (sl[int(len(sl) * f)] for f in (0.02, 0.5, 0.98))
    verdict = "enhance"
    if blown > 0.3:
        verdict = "replace: over 30 % of the sky is blown white, there is nothing to bring back"
    elif detail < 1.0 and chroma < 6:
        verdict = "replace (or a clean gradient for real estate): the sky is flat and colourless"
    c = a.contrast
    lo, hi = max(1.0, p50 - c * (p50 - p2)), min(254.0, p50 + c * (p98 - p50))
    pts = [[0, 0], [round(p2, 1), round(lo, 1)], [round(p50, 1), round(p50, 1)], [round(p98, 1), round(hi, 1)], [255, 255]]
    for k in range(1, len(pts)):
        pts[k][1] = max(pts[k][1], pts[k - 1][1] + 0.5)
    pts[-1][1] = 255
    grad = [[0, 0]] + [[x, round(min(255.0, from_linear(to_linear(x) * 2 ** -a.grad)), 1)] for x in (64, 128, 192)] + [[255, round(from_linear(2 ** -a.grad), 1)]]
    hz = horizon_line(skyline(A, w, h), w)
    m_c = A[:]
    m_g = [0.0] * N
    for i in range(N):
        if A[i] > 0 and hz[i % w] > 0:
            m_g[i] = A[i] * max(0.0, 1 - (i // w) / hz[i % w]) ** 1.2
    save_gray(os.path.join(md, "sky_only.png"), w, h, m_c)
    save_gray(os.path.join(md, "sky_grad.png"), w, h, m_g)
    lc, lg = spline_lut(pts), spline_lut(grad)
    q = lambda v: round(min(1.0, max(0.0, v)) * 255) / 255
    P = [[], [], []]
    for i in range(N):
        r, g, b = R[i], G[i], B[i]
        for lut, m in ((lc, q(m_c[i])), (lg, q(m_g[i]))):
            if m:
                tr, tg, tb = set_lum(r, g, b, 0.3 * lut_f(lut, r) + 0.59 * lut_f(lut, g) + 0.11 * lut_f(lut, b))
                r, g, b = r + m * (tr - r), g + m * (tg - g), b + m * (tb - b)
        P[0].append(r); P[1].append(g); P[2].append(b)
    save_rgb(os.path.join(md, "preview_enhance.png"), w, h, *P)
    spec = {"center": meta["center"], "crop": meta["crop"], "preview": "preview_enhance.png", "group": "Sky enhance",
            "layers": [{"name": "Sky contrast", "adjustment": "curves", "params": {"points": pts}, "mask": "sky_only.png",
                        "blend": "Luminosity"},
                       {"name": "Sky grad", "adjustment": "curves", "params": {"points": grad}, "mask": "sky_grad.png",
                        "blend": "Luminosity"}]}
    json.dump(spec, open(os.path.join(md, "layers_enhance.json"), "w"), indent=1)
    print(json.dumps({"verdict": verdict, "blown": round(blown, 3), "detail": round(detail, 2), "chroma": round(chroma, 1),
                      "skyTones": [round(p2), round(p50), round(p98)], "contrastCurve": pts, "gradCurve": grad}))


def halo_profile(L, A, w, h, R=8, T=24):
    """Per tile along the sky edge: luminance by signed distance from the alpha 0.5 contour (negative = sky side).
    Returns [(tx, ty, rim, dip, n)]: rim = how far the brightest pixels 1-2 px either side of the contour rise
    above both the new sky beside them (3-5 px out) and the land (4-8 px in); dip the same for the darkest."""
    N = w * h
    S = [v > 0.5 for v in A]
    seedx = [-1] * N
    seedy = [0] * N
    dist = [99.0] * N
    front = []
    for i in range(N):
        x, y = i % w, i // w
        s = S[i]
        if (x + 1 < w and S[i + 1] != s) or (x > 0 and S[i - 1] != s) or (y + 1 < h and S[i + w] != s) or (y > 0 and S[i - w] != s):
            seedx[i], seedy[i], dist[i] = x, y, 0.5
            front.append(i)
    while front:
        nxt = []
        for i in front:
            x, y = i % w, i // w
            sx, sy = seedx[i], seedy[i]
            for j, (xx, yy) in ((i - 1, (x - 1, y)), (i + 1, (x + 1, y)), (i - w, (x, y - 1)), (i + w, (x, y + 1))):
                if 0 <= xx < w and 0 <= yy < h:
                    dd = math.hypot(xx - sx, yy - sy) + 0.5
                    if dd < dist[j] and dd <= R + 0.5:
                        dist[j], seedx[j], seedy[j] = dd, sx, sy
                        nxt.append(j)
        front = nxt
    tiles = {}
    for i in range(N):
        d = dist[i]
        if d > R:
            continue
        b = -math.ceil(d) if S[i] else math.ceil(d)  # pixels on either side of the contour: -1 and 1
        key = ((i % w) // T, (i // w) // T)
        t = tiles.get(key)
        if t is None:
            t = tiles[key] = [[0.0, 0] for _ in range(2 * R + 1)]
        t[b + R][0] += L[i]
        t[b + R][1] += 1
    out = []
    for (tx, ty), t in tiles.items():
        prof = {b - R: s_ / n for b, (s_, n) in enumerate(t) if n >= 3}
        if not all(b in prof for b in (-1, 1)):
            continue
        # references right beside the edge, so the clouds' own light and dark don't count: the new sky 3-5 px
        # out, the land 4-8 px in; the rim is the brightest (darkest) of the 2 px either side of the contour
        sky_ref = [prof[b] for b in (-5, -4, -3) if b in prof]
        land_ref = [prof[b] for b in range(4, 9) if b in prof]
        if not sky_ref:
            continue
        near = [prof[b] for b in (-2, -1, 1, 2) if b in prof]
        if not land_ref:
            # a thin thing (finial, aerial, twig) has no inside to compare with: against a darker new sky its own
            # stone or metal can rightly look lighter than the sky, so it's left to the eye (thin tiles)
            out.append((tx, ty, None, None, sum(n for _, n in t)))
            continue
        refs = [sum(sky_ref) / len(sky_ref), sum(land_ref) / len(land_ref)]
        rim = max(near) - max(refs)
        dip = min(refs) - min(near)
        out.append((tx, ty, rim, dip, sum(n for _, n in t)))
    return out


def cmd_check(a):
    md = os.path.abspath(os.path.expanduser(a.maskdir))
    meta, w, h, ch, A = load_dir(md)
    path = a.render
    if path:
        x, y, cw, chh = meta["crop"]
        info = cli_run([path, "--cmd", "document.inspect"])
        if (info[0]["result"]["width"], info[0]["result"]["height"]) != (cw, chh):
            crop_path = os.path.join(md, "render_crop.png")
            cli_run([path, "--cmd", "image.crop", "--params", json.dumps({"x": x, "y": y, "width": cw, "height": chh}),
                     "--out", crop_path])
            path = crop_path
    else:
        path = os.path.join(md, "preview.png")
    _, _, R, G, B = load(path)
    L = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(R, G, B)]
    sky = [i for i, v in enumerate(A) if v >= 0.99]
    g_new = grain(L, w, h, sky[::7])
    OL = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(*ch)]
    g_old = grain(OL, w, h, sky[::7])
    allt = halo_profile(L, A, w, h)
    tiles = [t for t in allt if t[2] is not None]
    thin = [t for t in allt if t[2] is None]
    thr = max(a.threshold, 2.5 * g_new)
    bad = sorted((t for t in tiles if t[2] > thr), key=lambda t: -t[2])
    dark = sorted((t for t in tiles if t[3] > 2 * thr), key=lambda t: -t[3])
    ys = skyline(A, w, h)
    ymed = sorted(v for v in ys if v >= 0)[len([v for v in ys if v >= 0]) // 2]
    bands = {}
    for name, (f0, f1) in {"top": (0.0, 0.3), "middle": (0.3, 0.7), "horizon": (0.85, 1.0)}.items():
        idx = [i for i in sky if f0 * ymed <= i // w < f1 * ymed]
        bands[name] = round(sum(L[i] for i in idx) / len(idx), 1) if idx else None
    # viz: the render with each edge tile outlined green (clean), orange (light rim), red (strong or dark rim),
    # blue (thin structure only: judge by eye)
    T = 24
    VR, VG, VB = list(R), list(G), list(B)
    for tx, ty, rim, dip, n in allt:
        col = (40, 220, 60)
        if rim is None:
            col = (60, 160, 255)
        elif rim > thr or dip > 2 * thr:
            col = (255, 150, 0) if rim < 2 * thr and dip <= 2 * thr else (255, 30, 30)
        for yy in range(ty * T, min(h, ty * T + T)):
            for xx in (tx * T, min(w - 1, tx * T + T - 1)):
                VR[yy * w + xx], VG[yy * w + xx], VB[yy * w + xx] = col
        for xx in range(tx * T, min(w, tx * T + T)):
            for yy in (ty * T, min(h - 1, ty * T + T - 1)):
                VR[yy * w + xx], VG[yy * w + xx], VB[yy * w + xx] = col
    save_rgb(os.path.join(md, "check.png"), w, h, VR, VG, VB)
    print(json.dumps({
        "render": path, "edgeTiles": len(tiles), "thinTiles": len(thin), "threshold": round(thr, 2),
        "medianRim": round(percentile([t[2] for t in tiles], 50), 2) if tiles else None,
        "lightRim": {"tiles": len(bad), "share": round(len(bad) / max(1, len(tiles)), 3),
                     "worst": [[t[0] * T + T // 2, t[1] * T + T // 2, round(t[2], 1)] for t in bad[:6]]},
        "darkRim": {"tiles": len(dark), "worst": [[t[0] * T + T // 2, t[1] * T + T // 2, round(t[3], 1)] for t in dark[:4]]},
        "grain": {"oldSky": round(g_old, 2), "newSky": round(g_new, 2)},
        "skyLuminance": bands}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="fit a new sky, harmonise the land, write layers.json + exact preview")
    p.add_argument("maskdir"); p.add_argument("sky", nargs="?", help="the new sky photo")
    p.add_argument("--clear-blue", action="store_true", help="a clean gradient sky instead of a photo (real estate)")
    p.add_argument("--zenith", help="clear-blue top colour (#rrggbb)"); p.add_argument("--horizon-color", help="clear-blue horizon colour")
    p.add_argument("--sky-rect", type=int, nargs=4, help="usable part of the sky photo (leave out ground, trees)")
    p.add_argument("--sky-x", type=float, default=0.5, help="0 = take the left of the sky photo, 1 = the right")
    p.add_argument("--sky-y", type=float, default=1.0, help="1 = its bottom (the horizon part) at the skyline, 0 = its top")
    p.add_argument("--zoom", type=float, default=1.0, help=">1 takes a smaller part of the sky photo: bigger clouds")
    p.add_argument("--flip", action="store_true", help="mirror the sky, to put its sun on the side the scene is lit from")
    p.add_argument("--harmonize", type=float, default=0.5, help="share of the change in the light's colour (lit clouds, "
                   "old vs new sky) the land takes; 0 = none")
    p.add_argument("--ev", type=float, default=0.0, help="exposure change of the land in stops")
    p.add_argument("--haze", type=float, default=0.0, help="horizon haze opacity at the skyline (0.2-0.4)")
    p.add_argument("--haze-height", type=float, default=0.35, help="haze height, x the sky's height above the skyline")
    p.add_argument("--no-grain", dest="grain", action="store_false", help="don't add grain to a cleaner sky")
    p = sub.add_parser("enhance", help="improve the existing sky in place (or say it needs replacing)")
    p.add_argument("maskdir")
    p.add_argument("--contrast", type=float, default=1.35, help="spread of the sky's own tones around their median")
    p.add_argument("--grad", type=float, default=0.5, help="stops of darkening at the top of the frame, fading to 0 at the skyline")
    p = sub.add_parser("check", help="halo, grain and horizon checks on the imported result")
    p.add_argument("maskdir")
    p.add_argument("--render", help="export of the document (full size or the crop); default preview.png")
    p.add_argument("--threshold", type=float, default=3.0, help="levels a rim must rise above sky and land to count")
    a = ap.parse_args()
    if a.cmd == "plan" and not a.sky and not a.clear_blue:
        sys.exit("error: give a sky photo, or --clear-blue")
    {"plan": cmd_plan, "enhance": cmd_enhance, "check": cmd_check}[a.cmd](a)


if __name__ == "__main__":
    main()
