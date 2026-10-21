#!/usr/bin/env python3
"""Plan a product shot on pure white (or any backdrop colour): keep the product's real shadow, then place it on the
marketplace canvas.

A product cut out and dropped on white looks pasted on; the shadow is what makes it stand on something. The real
contact shadow is already in the photo, so it is kept rather than painted: the photo divided by the clean backdrop
behind it is 1 on bare backdrop and < 1 in the shadow, so that ratio as a Multiply layer over pure white reproduces
the shadow exactly while every other pixel becomes exactly 255. The backdrop is fitted robustly (shadows are darker
outliers, so they don't pull it), the backdrop's own noise is cut off so bare areas really are 255, and only shadow
connected to the product is kept, so dust, paper edges and vignetting don't come along. Under the product's edge the
shadow is continued from just outside, so edge pixels don't pick up the product's own colour twice (a dark halo).
No usable shadow (a busy background, an already-white photo): --shadow contact paints one along the product's base.

--reflection adds the glossy-surface look used for footwear and shiny goods: the product mirrored about the line it
stands on (each column about the ground line under it, so a 3/4 view's faces each mirror about their own bottom
edge), fading out within --reflection-length of the product's height, slightly blurred, on its own layer under the
shadow. --transparent is the glass route: glass shows the backdrop through it, so it is never cut with a binary mask;
the photo divided by the clean backdrop behind it is the glass's transmission, which as a Multiply layer reproduces
it exactly over white and lets any other backdrop colour show through it, and what is brighter than the backdrop
(highlights) goes on a Screen layer. The opaque cut is hidden for it; --opaque AREA keeps labels and caps opaque.

Then the canvas: scale so the product's longer side fills --fill of the frame (Amazon: 85 %), centred, on a common
baseline (--align bottom, for a consistent catalogue) or top, at --size (e.g. 2000 x 2000) or inside --margins.
--preset amazon|google|ebay|shopify|etsy|zalando or --spec spec.json (specs.py) supplies all of these at once;
explicit options override them, and the resolved spec.json is written next to the plan for cutout_check.py
--deliverable --spec to check the finished file against.

usage: product_shot.py orig.png cut.png outdir [--origin X Y] [--preset NAME | --spec FILE] [--shadow real|contact|none]
                       [--size 2000] [--aspect 1:1] [--fill 0.85 | --margins T,R,B,L] [--align center|bottom|top]
                       [--background #ffffff] [--reflection [0.25]] [--transparent [--opaque AREA]]

orig.png  the photo with its backdrop (export with the cut layer hidden, or the original file as PNG)
cut.png   the product as RGBA, same frame: hide everything but the masked product layer and export a PNG
Writes to outdir, in the order they're used: prep.json (grows the canvas when the product needs more room than the
photo has; run it first: a fill layer only covers the canvas it was made on), layers.json (Backdrop, Reflection,
Shadow, Glass layers, for import_layers.py, ABOVE THE BACKGROUND AND BELOW THE PRODUCT LAYER: --above <Background id>),
steps.json (crop and resample to the canvas, convert to sRGB), spec.json (what the deliverable must meet). Also
shadow.png (the Multiply layer), preview.png (the predicted frame, which the import verifies), final.png (predicted
deliverable, small), viz.png (photo | fitted backdrop | shadow, and the glass's transmission with --transparent).
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pngio
import specs
from cutout_check import bbox, edge_distance


def upsample(src, w, h, W, H):
    """Bilinear resize of a smooth coarse field (w x h) to W x H."""
    out = [0.0] * (W * H)
    for Y in range(H):
        fy = min(h - 1.0, max(0.0, (Y + 0.5) * h / H - 0.5))
        y0 = int(fy); y1 = min(h - 1, y0 + 1); ty = fy - y0
        for X in range(W):
            fx = min(w - 1.0, max(0.0, (X + 0.5) * w / W - 0.5))
            x0 = int(fx); x1 = min(w - 1, x0 + 1); tx = fx - x0
            a = src[y0 * w + x0] * (1 - tx) + src[y0 * w + x1] * tx
            b = src[y1 * w + x0] * (1 - tx) + src[y1 * w + x1] * tx
            out[Y * W + X] = a * (1 - ty) + b * ty
    return out


def fit_backdrop(R, G, B, sample, w, h, iterations=8):
    """Clean backdrop colour everywhere, from the pixels in `sample`, at coarse scale. Robust: pixels darker than the
    fit (shadows) or much lighter (glare) are down-weighted each round, so the fit runs under the shadow. A big soft
    shadow pulls the first rounds down, so it takes rounds to let go of it: on a synthetic sweep with a 35 % shadow,
    4 rounds left the fit 15-22 levels low under its faint tail (the tail was lost), 8 rounds 2-7. Deep inside a big
    product, out of reach of any backdrop sample even at the coarsest scale, it takes the backdrop's mean colour
    (it used to be black there, which showed as a black blob in viz.png and lowered the shadow's noise cutoff).
    Returns full-size R, G, B fields and the backdrop noise (levels, luminance)."""
    k = max(1, math.ceil(max(w, h) / 320))
    cw, ch = w // k, h // k
    sm, _, _ = imgops.downscale([float(v) for v in sample], w, h, k)
    cs = [imgops.downscale([c[i] * sample[i] for i in range(w * h)], w, h, k)[0] for c in (R, G, B)]
    cs = [[v / s if s > 1e-6 else 0.0 for v, s in zip(c, sm)] for c in cs]  # mean colour of the backdrop part of each cell
    base = [1.0 if s > 0.5 else 0.0 for s in sm]
    wt = base[:]
    for _ in range(iterations):
        fits = []
        for sig in (2.0, 6.0, 18.0):  # finest scale with enough support wins; coarser ones fill the product's area
            den = imgops.gauss(wt, cw, ch, sig)
            fits.append((den, [imgops.gauss([c[i] * wt[i] for i in range(cw * ch)], cw, ch, sig) for c in cs]))
        ref = [[0.0] * (cw * ch) for _ in range(3)]
        tw = sum(wt) or 1.0
        gm = [sum(cs[c][i] * wt[i] for i in range(cw * ch)) / tw for c in range(3)]  # where nothing is in reach
        for i in range(cw * ch):
            for den, num in fits:
                if den[i] > 0.15 or den is fits[-1][0]:
                    for c in range(3):
                        ref[c][i] = num[c][i] / den[i] if den[i] > 1e-9 else gm[c]
                    break
        res = [imgops.lum(cs[0][i], cs[1][i], cs[2][i]) - imgops.lum(ref[0][i], ref[1][i], ref[2][i]) for i in range(cw * ch)]
        a = sorted(abs(res[i]) for i in range(cw * ch) if base[i])
        sigma = max(0.5, 1.4826 * a[len(a) // 2]) if a else 1.0
        wt = [base[i] / (1 + (res[i] / (2.5 * sigma if res[i] < 0 else 6 * sigma)) ** 4) for i in range(cw * ch)]
    full = [upsample(ref[c], cw, ch, w, h) for c in range(3)]
    noise = [imgops.lum(R[i], G[i], B[i]) - imgops.lum(full[0][i], full[1][i], full[2][i]) for i in range(0, w * h, 7) if sample[i]]
    a = sorted(abs(v) for v in noise)
    return full, (1.4826 * a[len(a) // 2] if a else 1.0)


def lower_hull(bottom):
    """Lower convex hull of each column's lowest product pixel {x: y}: where an object resting on a plane touches it
    (side and 3/4 views alike); steep hull segments are its sides, not ground. Image rows grow downward, so this is the
    chain on the large-y side: it bridges an arch or the gap between legs instead of following it up."""
    hull = []
    for x in sorted(bottom):
        p = (x, bottom[x])
        while len(hull) >= 2 and ((hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1])
                                  - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0])) >= 0:
            hull.pop()
        hull.append(p)
    return hull


def ground_line(bottom, hull, steep=0.6):
    """Per column, the row of the line the product stands on (float): the hull segment under it where that segment is
    ground (slope <= steep); under a steep segment (a round object's side) the nearest ground segment's end height,
    held level. So a box in 3/4 view mirrors each face about its own bottom edge and a ball about its contact."""
    segs = [(hull[i], hull[i + 1]) for i in range(len(hull) - 1)] or [(hull[0], hull[0])]
    flat = [abs(b[1] - a[1]) / max(1, b[0] - a[0]) <= steep for a, b in segs]
    if not any(flat):
        y0 = max(bottom.values())
        return {x: float(y0) for x in bottom}
    out = {}
    for x in bottom:
        k = next((i for i, (a, b) in enumerate(segs) if a[0] <= x <= b[0]), len(segs) - 1)
        if flat[k]:
            (xa, ya), (xb, yb) = segs[k]
            out[x] = ya + (yb - ya) * (x - xa) / max(1, xb - xa)
        else:
            j = min((i for i in range(len(segs)) if flat[i]), key=lambda i: min(abs(x - segs[i][0][0]), abs(x - segs[i][1][0])))
            (xa, ya), (xb, yb) = segs[j]
            out[x] = float(ya if abs(x - xa) < abs(x - xb) else yb)
    return out


def area_in_frame(spec, ox, oy, w, h):
    """An area.json or a rectangle x0,y0,x1,y1 (full-image coordinates) rasterised on the frame."""
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        polys = cfg.get("area") or cfg.get("skin") or cfg.get("opaque")
        return imgops.polygon_mask(polys, ox, oy, w, h, cfg.get("exclude", []))
    x0, y0, x1, y1 = (float(v) for v in spec.split(","))
    return imgops.polygon_mask([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], ox, oy, w, h)


def main():
    ap = argparse.ArgumentParser(description=" ".join(__doc__.split("\n\n")[0].split()))
    ap.add_argument("orig"); ap.add_argument("cut"); ap.add_argument("outdir")
    ap.add_argument("--origin", type=int, nargs=2, default=[0, 0], help="where the frame sits in the photo")
    ap.add_argument("--doc-size", type=int, nargs=2, help="the document's width and height (default: the frame reaches its right and bottom edges)")
    ap.add_argument("--preset", choices=sorted(specs.PRESETS), help="a marketplace's canvas, fill, alignment and backdrop (specs.py)")
    ap.add_argument("--spec", help="a client's spec.json (specs.py documents the keys); options given here override it")
    ap.add_argument("--shadow", choices=["real", "contact", "none"], help="default: the spec's, else real")
    ap.add_argument("--kind", choices=["product", "soft"], default="product",
                    help="hard product, or hair/fur: how far past the mask fine detail may be the subject's own (3 / 8 px)")
    ap.add_argument("--opacity", type=float, default=1.0, help="Shadow layer opacity (1 = as photographed)")
    ap.add_argument("--color-shadow", action="store_true", help="keep the shadow's colour cast (default: neutral grey)")
    ap.add_argument("--reach", type=float, default=0.35, help="shadow kept within this share of the product's size")
    ap.add_argument("--contact-strength", type=float, default=0.55, help="--shadow contact: darkness of the contact line")
    ap.add_argument("--size", type=int, help="canvas long side in px (default: the spec's canvas, else 2000)")
    ap.add_argument("--aspect", help="canvas width:height (default: the spec's canvas, at the spec's aspect if it has one; else 1:1)")
    ap.add_argument("--fill", type=float, help="product's longer side as a share of the frame (default: the spec's, else 0.85; "
                                               "given, it replaces the spec's margins)")
    ap.add_argument("--margins", help="instead of --fill: top,right,bottom,left gaps, shares of the canvas side (or px if > 1)")
    ap.add_argument("--align", choices=["center", "bottom", "top"], help="default: the spec's, else center")
    ap.add_argument("--bottom", type=float, help="--align bottom/top: gap under/over the product, share of height (0.06)")
    ap.add_argument("--background", help="backdrop colour #rrggbb (default: the spec's, else #ffffff)")
    ap.add_argument("--reflection", type=float, nargs="?", const=0.25, help="add a reflection at this opacity (0.15-0.3)")
    ap.add_argument("--reflection-length", type=float, default=0.3, help="reflection fades out within this share of the product's height")
    ap.add_argument("--transparent", action="store_true", help="glass: transmission (Multiply) + highlights (Screen) instead of the opaque cut")
    ap.add_argument("--opaque", metavar="AREA", help="--transparent: labels, caps and other opaque parts (area.json or x0,y0,x1,y1)")
    ap.add_argument("--name", help="the product's name for the suggested deliverable file name (default: orig's file name)")
    a = ap.parse_args()
    if a.preset and a.spec:
        ap.error("--preset or --spec, not both")
    os.makedirs(a.outdir, exist_ok=True)

    spec = specs.resolve(a.spec or a.preset)
    warnings = []
    shadow_kind = a.shadow or spec.get("shadow") or "real"
    CW, CH = specs.canvas_size(spec, a.size, a.aspect)
    if a.size is None and a.aspect is None and [CW, CH] != [int(v) for v in spec["canvas"]]:
        warnings.append(f"the spec's canvas {spec['canvas'][0]}x{spec['canvas'][1]} hasn't its aspect {spec['aspect']}: "
                        f"placed on {CW}x{CH}")
    if a.fill is not None and not 0 < a.fill <= 1:
        ap.error("--fill is a share of the frame, 0 to 1")
    # explicit options win over the spec: --margins, or --fill instead of the spec's margins
    margins = specs.parse_margins(a.margins) if a.margins else None if a.fill is not None else spec.get("margins")
    fill = a.fill if a.fill is not None else (spec.get("fill") or 0.85)
    align = a.align or spec.get("align") or "center"
    gap = a.bottom if a.bottom is not None else spec.get("bottom", 0.06)
    bg = specs.hex_rgb(a.background or spec.get("background") or "#ffffff")
    refl_op = a.reflection if a.reflection is not None else (spec.get("reflection") or 0)

    w, h, R, G, B = imgops.load(a.orig)
    w2, h2, CR, CG, CB, A = imgops.load_rgba(a.cut)
    if (w, h) != (w2, h2):
        sys.exit(f"error: orig is {w}x{h} but cut is {w2}x{h2}; export both from the same frame")
    N = w * h
    inside = [1 if v >= 0.5 else 0 for v in A]
    pb = bbox(inside, w, h)
    if not pb:
        sys.exit("error: the cut is empty")
    bw, bh = pb[2] - pb[0] + 1, pb[3] - pb[1] + 1
    size = max(bw, bh)

    # ---- backdrop and shadow, inside the product's box grown by --reach
    m = int(a.reach * size) + 8
    rx0, ry0, rx1, ry1 = max(0, pb[0] - m), max(0, pb[1] - m), min(w - 1, pb[2] + m), min(h - 1, pb[3] + m)
    dist = edge_distance(inside, w, h, cap=8)
    sample = [1 if A[i] <= 0.02 and (inside[i] == 0 and dist[i] >= 4) else 0 for i in range(N)]
    ns = sum(sample)
    if ns < max(200, 0.002 * N):  # a tight crop: the product fills the frame
        if shadow_kind == "real" or a.transparent:
            sys.exit(f"error: only {ns} px of clear backdrop 4+ px from the cut: the real shadow and the glass route are "
                     "measured against the backdrop. Export a wider frame, or use --shadow contact|none")
        BR = BG = BB = [255.0] * N
        noise = 1.0
        stats = {"backdrop": None}
        warnings.append(f"only {ns} px of clear backdrop around the product: the backdrop was not measured")
    else:
        (BR, BG, BB), noise = fit_backdrop(R, G, B, sample, w, h)
        stats = {"backdrop": {"mean": [round(sum(c[i] for i in range(N) if sample[i]) / ns) for c in (BR, BG, BB)],
                              "range": [round(min(imgops.lum(BR[i], BG[i], BB[i]) for i in range(N) if sample[i]), 1),
                                        round(max(imgops.lum(BR[i], BG[i], BB[i]) for i in range(N) if sample[i]), 1)],
                              "noise": round(noise, 2)}}
        if max(stats["backdrop"]["mean"]) - min(stats["backdrop"]["mean"]) > 12:
            warnings.append("backdrop is not neutral: correct white balance before cutting, or the product's colours are off too")
    back_l = [imgops.lum(BR[i], BG[i], BB[i]) for i in range(N)]

    # the glass's own region (--transparent): the object grown 2 px and feathered, where the transmission layer takes
    # over from the shadow layer (both are photo / backdrop there, so the hand-over is seamless)
    glass_m = None
    if a.transparent:
        g0 = imgops.maxf([1.0 if v > 0.02 else 0.0 for v in A], w, h, 2)
        glass_m = [min(1.0, max(0.0, v)) for v in imgops.gauss(g0, w, h, 1.0)]

    rw, rh = rx1 - rx0 + 1, ry1 - ry0 + 1
    ridx = [(ry0 + y) * w + rx0 + x for y in range(rh) for x in range(rw)]
    bottom = {}
    for x in range(pb[0], pb[2] + 1):
        yb = next((y for y in range(pb[3], pb[1] - 1, -1) if inside[y * w + x]), None)
        if yb is not None:
            bottom[x] = yb
    hull = lower_hull(bottom)
    if shadow_kind == "real":
        # trust the photo only 3 px or more outside the mask: nearer, a slightly tight mask leaves product pixels
        # that would read as shadow (a dark outline); there, and under the product, the shadow is continued
        out_r = [1.0 if A[i] <= 0.02 and dist[i] >= 3 and not inside[i] else 0.0 for i in ridx]
        if a.color_shadow:
            chans = [[max(0.0, 1 - c[i] / max(1.0, bc[i])) for i in ridx] for c, bc in ((R, BR), (G, BG), (B, BB))]
        else:
            chans = [[max(0.0, 1 - imgops.lum(R[i], G[i], B[i]) / max(1.0, back_l[i])) for i in ridx]]
        eps = 2.5 * noise / max(1.0, sum(back_l[i] for i in ridx) / len(ridx)) + 0.004
        res = []
        for d in chans:
            # continue the shadow under the product's edge from just outside (never the product's own colour)
            num = imgops.gauss([d[j] * out_r[j] for j in range(len(ridx))], rw, rh, 2.5)
            den = imgops.gauss(out_r, rw, rh, 2.5)
            d = [d[j] if out_r[j] else (num[j] / den[j] if den[j] > 0.05 else 0.0) for j in range(len(ridx))]
            d = imgops.gauss(d, rw, rh, max(1.0, 0.0015 * size))
            d = [max(0.0, v - eps) / (1 - eps) for v in d]
            if glass_m:  # seen through the glass, the shadow is in the transmission layer already
                d = [v * (1 - glass_m[i]) for v, i in zip(d, ridx)]
            res.append(d)
        lum_d = res[0] if len(res) == 1 else [imgops.lum(res[0][j], res[1][j], res[2][j]) for j in range(len(ridx))]
        # keep only shadow that touches the product (grown a little): no dust, paper edges or vignette
        grow = max(6, int(0.02 * size))
        near = imgops.maxf([float(inside[i]) for i in ridx], rw, rh, grow)
        comps = imgops.components([1 if v > 0.01 else 0 for v in lum_d], rw, rh)
        keep = bytearray(len(ridx))
        for c in comps:
            if any(near[j] for j in c):
                for j in c:
                    keep[j] = 1
        kept = sum(keep)
        res = [[v if keep[j] else 0.0 for j, v in enumerate(d)] for d in res]
        # a shadow is smooth; fine detail inside it is a part of the subject the cut left out (a white paw on white)
        L = [imgops.lum(R[i], G[i], B[i]) for i in ridx]
        Ls = imgops.gauss(L, rw, rh, 1.5)
        lim = max(4.0, 5 * noise)
        # fur tips and whiskers just past a soft mask are normal: there only detail 8+ px from the mask counts; a hard
        # product's edge is crisp, so 3 px (where the photo is trusted again) is enough
        allow = 8 if a.kind == "soft" else 3
        det = [1 if keep[j] and dist[i] >= allow and lum_d[j] > 0.05 and abs(L[j] - Ls[j]) > lim else 0
               for j, i in enumerate(ridx)]
        boxes = []
        for c in imgops.components(imgops.maxf([float(v) for v in det], rw, rh, 3), rw, rh):
            n = sum(det[j] for j in c)
            if n >= max(40, 0.0004 * sum(inside)):
                xs = [rx0 + j % rw for j in c]; ys = [ry0 + j // rw for j in c]
                boxes.append([min(xs) + a.origin[0], min(ys) + a.origin[1], max(xs) - min(xs) + 1, max(ys) - min(ys) + 1])
        if boxes:
            warnings.append(f"the shadow has fine detail in {boxes[:6]}: probably parts of the subject missing from the cut "
                            "(a white paw on white, a strap); add them to the mask and rerun")
        stats["missingParts"] = boxes[:6]
        # Dark parts of the product the cut left out are smooth too (lace tips, a strap, a dark rim), so the detail test
        # misses them; they read as "shadow" well above the line the product stands on, and darker than a shadow on a
        # lit sweep gets. Measured on a shoe: four lace tips 1100 px above the sole at 0.66-0.81, which printed as grey
        # blobs over the laces; a cut that kept them left a shadow of at most 0.52.
        gline = ground_line(bottom, hull)
        lift = 0.03 * bh
        up = [1 if keep[j] and lum_d[j] > 0.5 and (rx0 + j % rw) in gline and ry0 + j // rw < gline[rx0 + j % rw] - lift
              else 0 for j in range(len(ridx))]
        above = []
        for c in imgops.components(up, rw, rh):
            if len(c) >= max(20, 0.00005 * sum(inside)):
                xs = [rx0 + j % rw for j in c]; ys = [ry0 + j // rw for j in c]
                above.append([min(xs) + a.origin[0], min(ys) + a.origin[1], max(xs) - min(xs) + 1, max(ys) - min(ys) + 1,
                              round(max(lum_d[j] for j in c), 2)])
        above.sort(key=lambda b: -b[4])
        stats["shadowAboveGround"] = above[:6]
        if above:
            warnings.append(f"dark \"shadow\" well above the product's ground line in {[b[:4] for b in above[:6]]} (up to "
                            f"{above[0][4]}): almost always dark parts of the product the cut left out (lace tips, a strap, "
                            "an edge); add them to the mask (cutout.md: the backdrop route) and rerun")
        shadow_rgb = [[1 - d[j] for j in range(len(ridx))] for d in (res if len(res) == 3 else res * 3)]
        smax = max(lum_d[j] for j in range(len(ridx)) if keep[j]) if kept else 0
        stats["shadow"] = {"pixels": kept, "max": round(smax, 3), "cutoff": round(eps, 4)}
        if smax > 0.7 and not above:
            warnings.append(f"the shadow's darkest point takes {smax:.2f} of the light: a shadow on a lit sweep rarely gets "
                            "that dark, dark product parts left out of the cut do; look at shadow.png near the product")
        if not kept:
            warnings.append("no shadow found next to the product: try --shadow contact")
    elif shadow_kind == "contact":
        # painted the way retouchers do it: a tight dark line hugging the base contour (each column's lowest product
        # pixel), plus a soft, lighter spread below it. Following the contour keeps 3/4 views grounded at every foot.
        core_src, soft_src = [0.0] * len(ridx), [0.0] * len(ridx)
        tc, ts = max(2, int(0.004 * bw)), max(4, int(0.03 * bw))
        seg = 0
        for x in sorted(bottom):
            while seg < len(hull) - 2 and x > hull[seg + 1][0]:
                seg += 1
            (xa, ya), (xb, yb2) = hull[seg], hull[min(seg + 1, len(hull) - 1)]
            slope = abs(yb2 - ya) / max(1, xb - xa)
            yh = ya + (yb2 - ya) * (x - xa) / max(1, xb - xa)
            yb = bottom[x]
            g = (1.0 if slope <= 0.6 else 0.0) * min(1.0, max(0.0, 1 - (yh - yb) / (0.08 * bh)))
            for k in range(-2, ts + 1):
                yy = yb + k
                if g > 0 and ry0 <= yy <= ry1:
                    j = (yy - ry0) * rw + x - rx0
                    soft_src[j] = max(soft_src[j], g * (1 - max(0, k) / ts))
                    if k <= tc:
                        core_src[j] = max(core_src[j], g)
        core = imgops.gauss(core_src, rw, rh, max(1.0, 0.003 * bw))
        soft = imgops.gauss(soft_src, rw, rh, max(3.0, 0.02 * bw))
        mc, ms = max(core) or 1, max(soft) or 1
        d = [min(0.9, a.contact_strength * (core[j] / mc + 0.4 * soft[j] / ms)) for j in range(len(ridx))]
        shadow_rgb = [[1 - v for v in d]] * 3
        stats["shadow"] = {"pixels": sum(1 for v in d if v > 0.01), "max": round(max(d), 3)}
    else:
        shadow_rgb = [[1.0] * len(ridx)] * 3

    # ---- glass: transmission and highlights, both measured against the clean backdrop behind each pixel
    gl = None
    if a.transparent:
        opq = area_in_frame(a.opaque, a.origin[0], a.origin[1], w, h) if a.opaque else None
        if opq:
            opq = [min(1.0, max(0.0, v)) for v in imgops.gauss(opq, w, h, 1.0)]
        TR, TG, TB = ([255.0] * N for _ in range(3))
        HR, HG, HB = ([0.0] * N for _ in range(3))
        TM = [0.0] * N  # the glass layers' mask: the object grown 2 px, minus its opaque parts
        k_n = 2.5 * noise  # below this a pixel is backdrop noise, not a highlight
        for i in range(N):
            gm = glass_m[i] * (1 - (opq[i] if opq else 0.0))
            if gm <= 0:
                continue
            TM[i] = gm
            for c, (I, Bk, T, Hh) in enumerate(((R, BR, TR, HR), (G, BG, TG, HG), (B, BB, TB, HB))):
                b = max(1.0, Bk[i])
                T[i] = 255 * min(1.0, I[i] / b)
                Hh[i] = 255 * min(1.0, max(0.0, I[i] - b - k_n) / max(1.0, 255 - b - k_n))
        q = lambda v: float(max(0, min(255, int(v + 0.5))))
        gl = {"T": [[q(v) for v in ch] for ch in (TR, TG, TB)], "H": [[q(v) for v in ch] for ch in (HR, HG, HB)],
              "M": [round(min(1.0, max(0.0, v)) * 255) / 255 for v in TM],
              "O": [round(min(1.0, max(0.0, v * A[i])) * 255) / 255 for i, v in enumerate(opq)] if opq else None}
        tl = [imgops.lum(TR[i], TG[i], TB[i]) / 255 for i in range(N) if inside[i] and TM[i] > 0.99]
        hi = sum(1 for i in range(N) if TM[i] > 0 and max(HR[i], HG[i], HB[i]) > 8)
        stats["glass"] = {"transmissionMedian": round(sorted(tl)[len(tl) // 2], 3) if tl else None,
                          "transmissionP5": round(sorted(tl)[len(tl) // 20], 3) if tl else None, "highlightPixels": hi}
        if tl and sorted(tl)[len(tl) // 2] < 0.35:
            warnings.append("most of the object passes under 35 % of the backdrop's light: it reads as opaque, not glass; "
                            "the glass route will tint it with any non-white backdrop (use the normal cut, or --opaque)")

    # ---- the frame the layer PNGs cover: the photo, grown downward when the reflection runs past its bottom
    refl = None
    ext = 0
    if refl_op > 0:
        ground = ground_line(bottom, hull)
        Lf = max(4, int(a.reflection_length * bh))
        ext = max(0, int(max(ground.values()) + 1 + Lf - h + 2))
    FH = h + ext
    FN = w * FH

    def framed(vals, fillv):  # a frame-sized channel padded with ext rows below
        return vals + [fillv] * (w * ext)

    if refl_op > 0:
        # what the reflection shows: the product as it will look (the cut, or the glass over the backdrop)
        if gl:
            look = [[imgops.blend("screen", (bg[c] * gl["T"][c][i] / 255,) * 3, (gl["H"][c][i],) * 3)[0]
                     for i in range(N)] for c in range(3)]
            look = [[look[c][i] if not gl["O"] or gl["O"][i] < 0.5 else (CR, CG, CB)[c][i] for i in range(N)] for c in range(3)]
            look_a = [max(A[i], gl["M"][i]) for i in range(N)]
        else:
            look, look_a = [CR, CG, CB], A
        RA = [0.0] * FN
        RC = [[0.0] * FN for _ in range(3)]
        for x, yh in ground.items():
            base = int(math.floor(yh))  # mirror about the bottom edge of row `base`
            for k in range(Lf):
                ys, yt = base - k, base + 1 + k
                if ys < 0 or yt >= FH:
                    break
                al = look_a[ys * w + x]
                if al <= 0:
                    continue
                f = (1 - k / Lf) ** 2
                j = yt * w + x
                RA[j] = al * f
                for c in range(3):
                    RC[c][j] = look[c][ys * w + x] * al * f
        sig = max(1.0, 0.004 * bh)
        RAb = imgops.gauss(RA, w, FH, sig)
        RCb = [imgops.gauss(ch, w, FH, sig) for ch in RC]
        # nothing of it may show above the line the product stands on (the blur spreads it a few px)
        cols = sorted(ground)
        for x in range(w):
            xn = cols[0] if x < cols[0] else cols[-1] if x > cols[-1] else x if x in ground else min(cols, key=lambda c: abs(c - x))
            for y in range(min(FH, int(math.floor(ground[xn])) + 1)):
                RAb[y * w + x] = 0.0
        rimg = [[(RCb[c][i] / RAb[i]) if RAb[i] > 1e-4 else float(bg[c]) for i in range(FN)] for c in range(3)]
        rimg = [[float(max(0, min(255, int(v + 0.5)))) for v in ch] for ch in rimg]
        rmask = [round(min(1.0, max(0.0, v)) * 255) / 255 for v in RAb]
        refl = {"img": rimg, "mask": rmask}
        imgops.save_rgb(os.path.join(a.outdir, "reflection.png"), w, FH, *rimg)
        imgops.save_gray(os.path.join(a.outdir, "reflection_mask.png"), w, FH, rmask)
        rb = bbox([1 if v > 0.02 else 0 for v in rmask], w, FH)
        stats["reflection"] = {"opacity": refl_op, "length": Lf, "bbox": [rb[0] + a.origin[0], rb[1] + a.origin[1],
                                                                          rb[2] - rb[0] + 1, rb[3] - rb[1] + 1] if rb else None}

    SR, SG, SB = ([255.0] * FN for _ in range(3))
    for j, i in enumerate(ridx):
        SR[i], SG[i], SB[i] = (255 * shadow_rgb[c][j] for c in range(3))
    q = lambda v: float(max(0, min(255, int(v + 0.5))))  # the PNG is 8-bit; predict with what the app will get
    SR, SG, SB = [q(v) for v in SR], [q(v) for v in SG], [q(v) for v in SB]
    imgops.save_rgb(os.path.join(a.outdir, "shadow.png"), w, FH, SR, SG, SB)
    if gl:
        imgops.save_rgb(os.path.join(a.outdir, "glass_transmission.png"), w, FH, *[framed(ch, 255.0) for ch in gl["T"]])
        imgops.save_rgb(os.path.join(a.outdir, "glass_highlights.png"), w, FH, *[framed(ch, 0.0) for ch in gl["H"]])
        imgops.save_gray(os.path.join(a.outdir, "glass_mask.png"), w, FH, framed(gl["M"], 0.0))
        if gl["O"]:
            imgops.save_rgb(os.path.join(a.outdir, "opaque.png"), w, FH, *[framed([float(v) for v in ch], 255.0) for ch in (R, G, B)])
            imgops.save_gray(os.path.join(a.outdir, "opaque_mask.png"), w, FH, framed(gl["O"], 0.0))

    # predicted frame, bottom to top: Backdrop fill, Reflection (Normal, mask x opacity), Shadow (Multiply, opacity),
    # Glass transmission (Multiply) and highlights (Screen) and opaque parts (Normal), masked; the product (Normal, its
    # mask) last, unless it is glass and hidden
    op = a.opacity

    def predict(i):
        p = tuple(float(v) for v in bg)
        if refl and refl["mask"][i]:
            p = imgops.blend("normal", p, (refl["img"][0][i], refl["img"][1][i], refl["img"][2][i]), refl_op * refl["mask"][i])
        if shadow_kind != "none":
            p = imgops.blend("multiply", p, (SR[i], SG[i], SB[i]), op)
        if i < N:
            if gl:
                if gl["M"][i]:
                    p = imgops.blend("multiply", p, (gl["T"][0][i], gl["T"][1][i], gl["T"][2][i]), gl["M"][i])
                    p = imgops.blend("screen", p, (gl["H"][0][i], gl["H"][1][i], gl["H"][2][i]), gl["M"][i])
                if gl["O"] and gl["O"][i]:
                    p = imgops.blend("normal", p, (R[i], G[i], B[i]), gl["O"][i])
            elif A[i]:
                p = imgops.blend("normal", p, (CR[i], CG[i], CB[i]), A[i])
        return p

    pred = [predict(i) for i in range(FN)]
    PR, PG, PB = [v[0] for v in pred], [v[1] for v in pred], [v[2] for v in pred]
    imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w, h, PR[:N], PG[:N], PB[:N])

    k = max(1, math.ceil(max(w, h) / 500))
    vw = w // k
    panels = []
    shown = [(R, G, B), (BR, BG, BB), (SR[:N], SG[:N], SB[:N])] + ([tuple(gl["T"])] if gl else [])
    for c3 in shown:
        panels.append([imgops.downscale(c, w, h, k)[0] for c in c3])
    vh = h // k
    gap_px = 6
    VW = len(panels) * vw + (len(panels) - 1) * gap_px
    viz = [[(255, 255, 255)] * VW for _ in range(vh)]
    for p, (pr, pg, pbb) in enumerate(panels):
        for y in range(vh):
            for x in range(vw):
                i = y * vw + x
                viz[y][p * (vw + gap_px) + x] = (int(pr[i]), int(pg[i]), int(pbb[i]))
    pngio.write(os.path.join(a.outdir, "viz.png"), VW, vh, viz)

    # ---- placement on the canvas, inside the frame box: the canvas, or the centred crop a marketplace's thumbnail
    # shows (safeAspect), intersected with the margins when there are any
    bx0, by0, bx1, by1 = 0.0, 0.0, float(CW), float(CH)
    if spec.get("safeAspect"):
        sw_, sh_ = specs.parse_aspect(spec["safeAspect"])
        fw_, fh_ = min(CW, CH * sw_ / sh_), min(CH, CW * sh_ / sw_)
        bx0, by0, bx1, by1 = (CW - fw_) / 2, (CH - fh_) / 2, (CW + fw_) / 2, (CH + fh_) / 2
    FWb, FHb = bx1 - bx0, by1 - by0  # what fill is a share of
    if margins:
        mt, mr, mb, ml = (v * (CH if k_ in (0, 2) else CW) if v <= 1 else v for k_, v in enumerate(margins))
        bx0, by0, bx1, by1 = max(bx0, ml), max(by0, mt), min(bx1, CW - mr), min(by1, CH - mb)
        if bx1 - bx0 < 1 or by1 - by0 < 1:
            sys.exit(f"error: the margins {margins} leave no room on a {CW}x{CH} canvas")
    rb = bbox([1 if v > 0.02 else 0 for v in refl["mask"]], w, FH) if refl else None
    # centred or top-aligned, a reflection is scaled and placed together with the product: the product alone at the
    # fill would push a tall bottle's reflection (and its neck) off the canvas. Bottom-aligned it needs the gap below.
    tall = (rb[3] + 1 - pb[1]) if rb and align != "bottom" else bh
    if margins:
        s = min((bx1 - bx0) / bw, (by1 - by0) / tall)
    else:
        s = fill / max(bw / FWb, tall / FHb)
    cxd = (bx0 + bx1) / 2
    bgap = gap * (by1 - by0) if not margins else 0.0
    if align == "bottom":
        ref_src, cyd = pb[3] + 1, by1 - bgap
    elif align == "top":
        ref_src, cyd = pb[1], by0 + bgap
    else:
        ref_src, cyd = (pb[1] + pb[1] + tall) / 2, (by0 + by1) / 2
    cxs = (pb[0] + pb[2] + 1) / 2
    sx = cxs - cxd / s
    sy = ref_src - cyd / s
    sw, sh = CW / s, CH / s
    shadow_box = bbox([1 if SR[i] < 254.5 or SG[i] < 254.5 or SB[i] < 254.5 else 0 for i in range(FN)], w, FH)
    for name, b in (("product", pb), ("shadow", shadow_box), ("reflection", rb)):
        if b and (b[0] < sx - 0.5 or b[1] < sy - 0.5 or b[2] + 1 > sx + sw + 0.5 or b[3] + 1 > sy + sh + 0.5):
            how = ("a reflection needs room below: --align center, or a larger --bottom gap"
                   if name == "reflection" and align == "bottom" else
                   "lower --fill" + (" or --reach" if name == "shadow" else "") + ("" if align == "center" else ", or --align center"))
            warnings.append(f"the {name} runs off the canvas at this fill/alignment: {how}")
    X, Y = round(sx) + a.origin[0], round(sy) + a.origin[1]
    DW, DH = a.doc_size or (a.origin[0] + w, a.origin[1] + h)
    # The canvas rect may reach past the photo. Grow the canvas BEFORE the layers go in: a fill layer only covers the
    # canvas it was made on, and after a later grow or a crop past the edge the new area stays transparent.
    gl_, gt = max(0, -X), max(0, -Y)
    gr, gb = max(0, X + round(sw) - DW), max(0, Y + round(sh) - DH)
    prep = []
    if gl_ or gt:
        prep.append({"command": "image.canvasSize", "params": {"width": gl_, "height": gt, "relative": True, "anchor": "bottomRight", "extensionColor": "white"}})
    if gr or gb:
        prep.append({"command": "image.canvasSize", "params": {"width": gr, "height": gb, "relative": True, "anchor": "topLeft", "extensionColor": "white"}})
    json.dump(prep, open(os.path.join(a.outdir, "prep.json"), "w"), indent=1)
    steps = [{"command": "image.crop", "params": {"x": X + gl_, "y": Y + gt, "width": round(sw), "height": round(sh),
                                                  "targetWidth": CW, "targetHeight": CH, "resample": "bicubic"}},
             {"command": "edit.convertToProfile", "params": {"profile": "srgb", "intent": "relative", "bpc": True}}]
    json.dump(steps, open(os.path.join(a.outdir, "steps.json"), "w"), indent=1)

    # predicted deliverable, small
    fk = max(1, math.ceil(max(CW, CH) / 600))
    FW_, FH_ = CW // fk, CH // fk
    fin = []
    for y in range(FH_):
        row = []
        for x in range(FW_):
            u, v = sx + (x + 0.5) * fk / s, sy + (y + 0.5) * fk / s
            xi, yi = int(u), int(v)
            if 0 <= xi < w and 0 <= yi < FH:
                row.append(tuple(int(c + .5) for c in pred[yi * w + xi]))
            else:
                row.append(tuple(bg))
        fin.append(row)
    pngio.write(os.path.join(a.outdir, "final.png"), FW_, FH_, fin)

    white = tuple(bg) == (255, 255, 255)
    layers = [{"name": "White backdrop" if white else "Backdrop", "fill": "#%02x%02x%02x" % bg}]
    if refl:
        layers.append({"name": "Reflection", "image": "reflection.png", "mask": "reflection_mask.png", "opacity": refl_op})
    if shadow_kind != "none":
        layers.append({"name": "Shadow (real)" if shadow_kind == "real" else "Shadow (contact)", "image": "shadow.png",
                       "blend": "Multiply", "opacity": op})
    if gl:
        layers.append({"name": "Glass (transmission)", "image": "glass_transmission.png", "mask": "glass_mask.png", "blend": "Multiply"})
        layers.append({"name": "Glass (highlights)", "image": "glass_highlights.png", "mask": "glass_mask.png", "blend": "Screen"})
        if gl["O"]:
            layers.append({"name": "Opaque parts", "image": "opaque.png", "mask": "opaque_mask.png"})
    ox, oy = a.origin[0] + gl_, a.origin[1] + gt  # where the frame sits once prep.json has grown the canvas
    plan = {"center": [ox + w / 2, oy + FH / 2], "crop": [ox, oy, w, h],
            "preview": "preview.png", "group": "Product on white" if white else "Product on backdrop", "layers": layers}
    json.dump(plan, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)

    # what the deliverable must meet: the spec as it was used here, for cutout_check.py --deliverable --spec
    used = dict(spec)
    used.update({"canvas": [CW, CH], "fill": None if margins else round(fill, 4), "margins": margins, "align": align,
                 "bottom": gap, "background": "#%02x%02x%02x" % bg, "shadow": shadow_kind, "reflection": refl_op,
                 # where this plan put the product: the check measures fill and centring on it (a flat image can't
                 # always tell a soft shadow or a reflection from the product) and confirms the product is there
                 "productInCanvas": [round((pb[0] - sx) * s), round((pb[1] - sy) * s), round(bw * s), round(bh * s)]})
    if rb and align != "bottom" and not margins:  # --fill was the share of product and reflection together
        used["fillWithReflection"] = round(max(bw * s / FWb, tall * s / FHb), 3)
    json.dump(used, open(os.path.join(a.outdir, "spec.json"), "w"), indent=1)

    deliver_as = specs.suggested_name(spec, a.name or os.path.splitext(os.path.basename(a.orig))[0])
    quality = f" --quality {spec.get('quality', 95)}" if deliver_as.rsplit(".", 1)[-1] in ("jpg", "jpeg", "webp") else ""
    stats.update({
        "spec": {"name": spec["name"], "preset": spec.get("preset"), "official": spec.get("official")},
        "product": {"bbox": [pb[0] + a.origin[0], pb[1] + a.origin[1], bw, bh]},
        "canvas": [CW, CH], "scale": round(s, 4),
        "productInCanvas": [round((pb[0] - sx) * s), round((pb[1] - sy) * s), round(bw * s), round(bh * s)],
        # the product's share of the frame box (the safe crop when there is one), as the check measures it
        "fill": round(max(bw * s / FWb, bh * s / FHb), 3), "warnings": warnings,
        "deliverAs": deliver_as,
        "next": (["pc.py script <outdir>/prep.json   (grow the canvas first)"] if prep else []) +
                (["pc.py exec layer.setProps '{\"layer\": <Product id>, \"visible\": false}'   (glass: the layers replace the opaque cut)"]
                 if gl else []) +
                ["import_layers.py <outdir>/layers.json --above <id>   (the top layer under the Product: the Background, "
                 "or a retouch layer above it, which the backdrop would otherwise cover)",
                 "pc.py script <outdir>/steps.json   (crop + resample to the canvas, sRGB)",
                 f"pc.py cli convert <final>.psd {deliver_as}{quality}   (or deliver.py, which also strips camera EXIF and GPS)",
                 f"cutout_check.py --deliverable {deliver_as} <dir> --spec <outdir>/spec.json"],
        # the same in files, with no window; steps.json crops the document to this canvas, so for a second marketplace
        # run its plan from the uncropped PSD (2_layers.psd), not from final.psd
        "nextHeadless": ([f"pc.py script <outdir>/prep.json --open <cut>.psd --save 1_prep.psd"] if prep else []) +
                        ([f"pc.py script hide.json --open {'1_prep' if prep else '<cut>'}.psd --save 1_glass.psd   "
                          "(hide.json: layer.setProps {\"layer\": <Product id>, \"visible\": false})"] if gl else []) +
                        [f"import_layers.py <outdir>/layers.json --file {'1_glass' if gl else '1_prep' if prep else '<cut>'}.psd "
                         "--out 2_layers.psd --above <id>",
                         "pc.py script <outdir>/steps.json --open 2_layers.psd --save final.psd",
                         f"pc.py cli convert final.psd {deliver_as}{quality}",
                         f"cutout_check.py --deliverable {deliver_as} <dir> --spec <outdir>/spec.json"],
    })
    if (FWb, FHb) != (CW, CH):
        stats["fillOfCanvas"] = round(max(bw * s / CW, bh * s / CH), 3)
    if rb and align != "bottom" and not margins:
        stats["fillWithReflection"] = round(max(bw * s / FWb, tall * s / FHb), 3)
    if spec.get("fillRange"):
        lo, hi = spec["fillRange"]
        if not lo - 0.005 <= stats["fill"] <= hi + 0.005:
            warnings.append(f"the product fills {stats['fill']}, outside {spec['name']}'s {lo}-{hi}"
                            + (" (with its reflection it can't fill more: drop --reflection or shorten --reflection-length)"
                               if rb and align != "bottom" and stats["fill"] < lo else ""))
    if s > 1.05:
        warnings.append(f"the product is enlarged {s:.2f}x to fill the canvas: shoot or export at a higher resolution, or use a smaller --size")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
