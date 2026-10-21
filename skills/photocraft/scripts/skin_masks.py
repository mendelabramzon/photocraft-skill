#!/usr/bin/env python3
"""Micro dodge & burn + skin-colour evening masks: the "clean but natural" half of a skin retouch.

Run it on a crop of the photo AFTER the blemishes are healed. For every skin pixel it measures how far the
local tone AND colour stray from the clean skin around it, at blotch scale (a few px up to ~2.5 x --sigma),
and takes one fraction of that away, the same fraction for tone and for colour:

  dodge.png, burn.png   masks for two Curves adjustment layers in Luminosity mode (the classic D&B pair)
  color.png             mask for the "Skin colour" layer; color_ref.png is that layer's pixels (each pixel recoloured
                        to the clean skin's hue/saturation at its own luminance; Normal mode)
  preview.png           the predicted result, viz.png where the masks act (green dodge, magenta burn, yellow colour)
  masks.json            offsets, curve points and stats for import_masks.py

Why one fraction: a post-acne mark is darker AND redder (or purplish). Taking its red away but only part of its
darkness leaves a dark, neutral patch, and on warm skin that reads as a grey-blue bruise. Moving tone and colour
toward the surrounding skin together just makes the mark fainter. It's the frequency-separation "fix the low
frequency" idea, split into editable D&B and colour layers.

Texture can't be harmed: every decision is made on a copy smoothed by --pre, so pores, stubble and grain (finer
than that) pass through all layers unchanged. Shape can't be harmed either: the reference is a robust local
plane fit at --sigma, so light fall-off, cheekbones and the jaw shadow count as "normal" and are left alone.
And nothing is lifted past the clean skin around it (--margin), so a healed spot inside a dark halo doesn't
turn into a light dot.

usage: skin_masks.py crop.png cropX cropY area.json outdir [--sigma 12] [--strength 0.8]
area.json: {"skin": [[x, y], ...] or [poly, ...], "exclude": [[x0, y0, x1, y1] or [[x, y], ...], ...]}
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pngio
from imgops import gauss, lum, lut_f, raster, save_gray, set_lum, spline_lut

DODGE = [[0, 0], [128, 160], [255, 255]]
BURN = [[0, 0], [128, 96], [255, 255]]


def local_plane(fs, wt, w, h, sigma, ridge=0.05):
    """Weighted local linear fit (order-1 normalized convolution) of each image in fs: at each pixel, the value of
    the plane that best fits it around there, with weights wt * Gaussian(sigma). Unlike a weighted average it
    follows a slope right up to the edge of the skin area, so the shadow beside the hair or under the jaw isn't
    read as a dark blotch."""
    X = [float(i % w) for i in range(w * h)]
    Yc = [float(i // w) for i in range(w * h)]
    g = lambda v: gauss(v, w, h, sigma)
    m0 = g(wt)
    wx = [k * x for k, x in zip(wt, X)]; wy = [k * y for k, y in zip(wt, Yc)]
    mx, my = g(wx), g(wy)
    mxx = g([k * x for k, x in zip(wx, X)]); mxy = g([k * y for k, y in zip(wx, Yc)]); myy = g([k * y for k, y in zip(wy, Yc)])
    reg = ridge * sigma * sigma
    outs = []
    for f in fs:
        wf = [k * v for k, v in zip(wt, f)]
        n0 = g(wf); nx = g([k * x for k, x in zip(wf, X)]); ny = g([k * y for k, y in zip(wf, Yc)])
        out = [0.0] * (w * h)
        for i in range(w * h):
            s0 = m0[i]
            if s0 < 1e-4:
                out[i] = f[i]
                continue
            x0, y0 = X[i], Yc[i]
            sx = mx[i] - x0 * s0; sy = my[i] - y0 * s0
            sxx = mxx[i] - 2 * x0 * mx[i] + x0 * x0 * s0 + reg * s0
            syy = myy[i] - 2 * y0 * my[i] + y0 * y0 * s0 + reg * s0
            sxy = mxy[i] - x0 * my[i] - y0 * mx[i] + x0 * y0 * s0
            fx = nx[i] - x0 * n0[i]; fy = ny[i] - y0 * n0[i]
            # solve [[s0,sx,sy],[sx,sxx,sxy],[sy,sxy,syy]] [a,b,c] = [n0,fx,fy] for a (Cramer)
            det = s0 * (sxx * syy - sxy * sxy) - sx * (sx * syy - sxy * sy) + sy * (sx * sxy - sxx * sy)
            if abs(det) < 1e-9:
                out[i] = n0[i] / s0
                continue
            out[i] = (n0[i] * (sxx * syy - sxy * sxy) - sx * (fx * syy - sxy * fy) + sy * (fx * sxy - sxx * fy)) / det
        outs.append(out)
    return outs


def robust_scale(vals, mask):
    a = sorted(abs(v) for v, k in zip(vals, mask) if k > 0.5)
    return 1.4826 * a[len(a) // 2] if a else 1.0


def gradient_att(img, w, h, edge):
    """1 where img is flat, falling to 1/2 where its gradient is `edge` levels/px."""
    att = [1.0] * (w * h)
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            gx = (img[i + 1] - img[i - 1]) / 2; gy = (img[i + w] - img[i - w]) / 2
            att[i] = 1 / (1 + (gx * gx + gy * gy) / (edge * edge))
    return att


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("crop"); ap.add_argument("ox", type=int); ap.add_argument("oy", type=int)
    ap.add_argument("area"); ap.add_argument("outdir")
    ap.add_argument("--sigma", type=float, default=12, help="reference scale in px (~2-3%% of face width); blotches up to ~2.5x this get evened")
    ap.add_argument("--pre", type=float, default=2.0, help="detail below this scale (pores, grain) is never touched")
    ap.add_argument("--strength", type=float, default=0.8, help="fraction of a dark or discoloured blotch taken away, tone and colour together")
    ap.add_argument("--bright-strength", type=float, default=0.4, help="fraction of a light blotch taken away")
    ap.add_argument("--threshold", type=float, default=1.0, help="dead zone in levels: smaller variations stay")
    ap.add_argument("--color-scale", type=float, default=1.0,
                    help="colour correction relative to tone. Keep <= 1: more colour than tone fix = grey-blue 'bruises'")
    ap.add_argument("--margin", type=float, default=1.0,
                    help="levels: never lift or darken a pixel past the clean-skin level by more than this, so a healed "
                         "centre inside a dark halo doesn't become a light dot")
    ap.add_argument("--max-dev", type=float, default=16,
                    help="levels: a deviation this big is light or shadow (rim light, the shadow under an earlobe, a "
                         "hair), not a mark; the effect fades out from 0.6x this to 0")
    ap.add_argument("--robust", type=float, default=2.0,
                    help="x noise: how hard blotches are ignored when estimating the clean skin (lower = ignores more)")
    ap.add_argument("--iterations", type=int, default=4)
    ap.add_argument("--feather", type=float, default=6, help="px over which the effect fades in from the skin edge")
    ap.add_argument("--edge", type=float, default=3.0, help="gradient (levels/px) of the clean-skin tone at which the effect halves: protects the edges of light and shadow")
    ap.add_argument("--dodge", default=json.dumps(DODGE)); ap.add_argument("--burn", default=json.dumps(BURN))
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    cfg = json.load(open(a.area))

    w, h, P = pngio.read(a.crop)
    N = w * h
    R = [float(p[0]) for row in P for p in row]
    G = [float(p[1]) for row in P for p in row]
    B = [float(p[2]) for row in P for p in row]
    Y = [lum(r, g, b) for r, g, b in zip(R, G, B)]

    skin = raster(cfg, a.ox, a.oy, w, h)
    soft = gauss(skin, w, h, max(a.feather / 2, 0.5))
    weight = [min(1.0, max(0.0, (v - 0.5) / 0.45)) * s for v, s in zip(soft, skin)]

    Rp, Gp, Bp = (gauss(c, w, h, a.pre) for c in (R, G, B))
    Yp = [lum(r, g, b) for r, g, b in zip(Rp, Gp, Bp)]
    base_w = [s if y > 40 else 0.0 for s, y in zip(skin, Yp)]

    # the clean skin around each pixel: robust local plane fit of R, G and B, with blotches down-weighted so
    # they don't pull it. dY = how much darker/lighter, dC = how far off in colour (both in levels).
    wt = base_w[:]
    for _ in range(a.iterations):
        ref = local_plane([Rp, Gp, Bp], wt, w, h, a.sigma)
        dR = [v - r for v, r in zip(Rp, ref[0])]; dG = [v - r for v, r in zip(Gp, ref[1])]; dB = [v - r for v, r in zip(Bp, ref[2])]
        dY = [lum(r, g, b) for r, g, b in zip(dR, dG, dB)]
        dC = [math.sqrt((r - y) ** 2 + (g - y) ** 2 + (b - y) ** 2) for r, g, b, y in zip(dR, dG, dB, dY)]
        e = [math.hypot(y, c) for y, c in zip(dY, dC)]
        c = a.robust * max(robust_scale(e, base_w), 0.5)
        wt = [k / (1 + (d / c) ** 2) for k, d in zip(base_w, e)]
    S = [lum(r, g, b) for r, g, b in zip(*ref)]
    noise = robust_scale(e, base_w)

    # back off at edges of light and shadow: where the clean-skin tone changes fast (broad light fall-off), and
    # where the image itself does at a scale above pores (the flanks of a rim-lit band, hair strands, lashes).
    # A mark's own edge is gentler (~1-1.5 levels/px) and keeps ~90 % of the effect.
    att_s = gradient_att(S, w, h, a.edge)
    att_y = gradient_att(gauss(Y, w, h, 2.0), w, h, 1.25 * a.edge)

    # one fraction per pixel, for tone and colour alike
    f = [0.0] * N
    for i in range(N):
        y, ee = dY[i], e[i]
        if ee <= a.threshold or ee >= a.max_dev:
            continue
        s = a.strength if y <= 0 else a.bright_strength
        fade = min(1.0, (a.max_dev - ee) / (0.4 * a.max_dev))
        f[i] = s * (ee - a.threshold) / ee * fade * weight[i] * att_s[i] * att_y[i]
    f = gauss(f, w, h, 0.7)

    # tone -> Dodge / Burn masks, never past the clean-skin level (+/- margin) at fine scale
    Y1 = gauss(Y, w, h, 1.2)
    lut_d, lut_b = spline_lut(json.loads(a.dodge)), spline_lut(json.loads(a.burn))
    md = [0.0] * N; mb = [0.0] * N; shift = [0.0] * N
    for i in range(N):
        cv = -f[i] * dY[i]
        if cv > 0:
            cv = min(cv, max(0.0, S[i] + a.margin - Y1[i]))
            lift = lum(lut_f(lut_d, Rp[i]), lut_f(lut_d, Gp[i]), lut_f(lut_d, Bp[i])) - Yp[i]
            md[i] = min(1.0, cv / lift) if lift > 0.5 else 0.0
        elif cv < 0:
            cv = max(cv, min(0.0, S[i] - a.margin - Y1[i]))
            drop = Yp[i] - lum(lut_f(lut_b, Rp[i]), lut_f(lut_b, Gp[i]), lut_f(lut_b, Bp[i]))
            mb[i] = min(1.0, -cv / drop) if drop > 0.5 else 0.0
        shift[i] = cv
    # colour -> the Skin colour layer (Color mode) takes the clean skin's hue/saturation, by the same fraction
    mc = [min(1.0, a.color_scale * v) for v in f]

    q = lambda v: round(min(1.0, max(0.0, v)) * 255) / 255  # masks are 8-bit
    md = [q(v) for v in md]; mb = [q(v) for v in mb]; mc = [q(v) for v in mc]
    save_gray(os.path.join(a.outdir, "dodge.png"), w, h, md)
    save_gray(os.path.join(a.outdir, "burn.png"), w, h, mb)
    save_gray(os.path.join(a.outdir, "color.png"), w, h, mc)
    # The Skin colour layer holds the finished recolour (clean skin's hue/saturation at each pixel's own luminance),
    # used in Normal mode, so the document reproduces preview.png exactly. Its colours only survive the trip into
    # the photo if the PNG gets the photo's profile first (import_masks.py assigns it): an untagged PNG copied
    # into a Display P3 photo is converted, and skin comes out ~3 levels less red and ~2 bluer: bruise-coloured.
    recol = [set_lum(ref[0][i], ref[1][i], ref[2][i], lum(R[i], G[i], B[i])) for i in range(N)]
    pngio.write(os.path.join(a.outdir, "color_ref.png"), w, h,
                [[tuple(max(0, min(255, int(v + 0.5))) for v in recol[y * w + x]) for x in range(w)] for y in range(h)])

    # predicted result, stacked like the document: healed -> Skin colour (Normal) -> Dodge -> Burn (Luminosity)
    prev, viz = [], []
    for i in range(N):
        r, g, b = R[i], G[i], B[i]
        if mc[i]:
            cr, cg, cb = (max(0, min(255, int(v + 0.5))) for v in recol[i])
            r, g, b = r + mc[i] * (cr - r), g + mc[i] * (cg - g), b + mc[i] * (cb - b)
        for m, lut in ((md[i], lut_d), (mb[i], lut_b)):
            if m:
                tr, tg, tb = set_lum(r, g, b, lum(lut_f(lut, r), lut_f(lut, g), lut_f(lut, b)))
                r, g, b = r + m * (tr - r), g + m * (tg - g), b + m * (tb - b)
        prev.append(tuple(max(0, min(255, int(v + 0.5))) for v in (r, g, b)))
        k = min(1.0, 4 * md[i]); j = min(1.0, 4 * mb[i]); c = min(1.0, 2 * mc[i])
        v = (R[i], G[i], B[i])
        v = (v[0] * (1 - c) + 255 * c, v[1] * (1 - c) + 230 * c, v[2] * (1 - c) + 0 * c)
        v = (v[0] * (1 - k) + 40 * k, v[1] * (1 - k) + 255 * k, v[2] * (1 - k) + 40 * k)
        v = (v[0] * (1 - j) + 255 * j, v[1] * (1 - j) + 40 * j, v[2] * (1 - j) + 255 * j)
        viz.append(tuple(int(x) for x in v))
    pngio.write(os.path.join(a.outdir, "preview.png"), w, h, [prev[y * w:(y + 1) * w] for y in range(h)])
    pngio.write(os.path.join(a.outdir, "viz.png"), w, h, [viz[y * w:(y + 1) * w] for y in range(h)])

    on = lambda m: sum(1 for v in m if v >= 2 / 255)
    stats = {
        "crop": [a.ox, a.oy, w, h], "center": [a.ox + w / 2, a.oy + h / 2],
        "dodgeCurve": json.loads(a.dodge), "burnCurve": json.loads(a.burn),
        "noise": round(noise, 2),
        "pixels": {"skin": int(sum(skin)), "dodge": on(md), "burn": on(mb), "colour": on(mc)},
        "max": {"dodge": round(max(md), 3), "burn": round(max(mb), 3), "colour": round(max(mc), 3)},
        "meanShift": round(sum(abs(v) for v in shift) / max(1, sum(skin)), 3),
        "params": {k: getattr(a, k) for k in ("sigma", "pre", "strength", "bright_strength", "threshold", "color_scale",
                                              "margin", "max_dev", "robust", "iterations", "feather", "edge")},
    }
    json.dump(stats, open(os.path.join(a.outdir, "masks.json"), "w"), indent=1)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
