#!/usr/bin/env python3
"""Plan a product shot on pure white: keep the product's real shadow, then place it on the marketplace canvas.

A product cut out and dropped on white looks pasted on; the shadow is what makes it stand on something. The real
contact shadow is already in the photo, so it is kept rather than painted: the photo divided by the clean backdrop
behind it is 1 on bare backdrop and < 1 in the shadow, so that ratio as a Multiply layer over pure white reproduces
the shadow exactly while every other pixel becomes exactly 255. The backdrop is fitted robustly (shadows are darker
outliers, so they don't pull it), the backdrop's own noise is cut off so bare areas really are 255, and only shadow
connected to the product is kept, so dust, paper edges and vignetting don't come along. Under the product's edge the
shadow is continued from just outside, so edge pixels don't pick up the product's own colour twice (a dark halo).
No usable shadow (a busy background, an already-white photo): --shadow contact paints one along the product's base.

Then the canvas: scale so the product's longer side fills --fill of the frame (Amazon: 85 %), centred or standing on
a common baseline (--align bottom, for a consistent catalogue), at --size (e.g. 2000 x 2000).

usage: product_shot.py orig.png cut.png outdir [--origin X Y] [--shadow real|contact|none] [--size 2000]
                       [--aspect 1:1] [--fill 0.85] [--align center|bottom]

orig.png  the photo with its backdrop (export with the cut layer hidden, or the original file as PNG)
cut.png   the product as RGBA, same frame: hide everything but the masked product layer and export a PNG
Writes to outdir, in the order they're used: prep.json (grows the canvas when the product needs more room than the
photo has; run it first: a fill layer only covers the canvas it was made on), layers.json (White backdrop + Shadow,
for import_layers.py, ABOVE THE BACKGROUND AND BELOW THE PRODUCT LAYER: --above <Background id>), steps.json (crop
and resample to the canvas, convert to sRGB). Also shadow.png (the Multiply layer), preview.png (the predicted frame,
which the import verifies), final.png (predicted deliverable, small), viz.png (photo | fitted backdrop | shadow).
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pngio
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


def fit_backdrop(R, G, B, sample, w, h, iterations=4):
    """Clean backdrop colour everywhere, from the pixels in `sample`, at coarse scale. Robust: pixels darker than the
    fit (shadows) or much lighter (glare) are down-weighted each round, so the fit runs under the shadow. Returns
    full-size R, G, B fields and the backdrop noise (levels, luminance)."""
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
        for i in range(cw * ch):
            for den, num in fits:
                if den[i] > 0.15 or den is fits[-1][0]:
                    for c in range(3):
                        ref[c][i] = num[c][i] / den[i] if den[i] > 1e-9 else cs[c][i]
                    break
        res = [imgops.lum(cs[0][i], cs[1][i], cs[2][i]) - imgops.lum(ref[0][i], ref[1][i], ref[2][i]) for i in range(cw * ch)]
        a = sorted(abs(res[i]) for i in range(cw * ch) if base[i])
        sigma = max(0.5, 1.4826 * a[len(a) // 2]) if a else 1.0
        wt = [base[i] / (1 + (res[i] / (2.5 * sigma if res[i] < 0 else 6 * sigma)) ** 4) for i in range(cw * ch)]
    full = [upsample(ref[c], cw, ch, w, h) for c in range(3)]
    noise = [imgops.lum(R[i], G[i], B[i]) - imgops.lum(full[0][i], full[1][i], full[2][i]) for i in range(0, w * h, 7) if sample[i]]
    a = sorted(abs(v) for v in noise)
    return full, (1.4826 * a[len(a) // 2] if a else 1.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("orig"); ap.add_argument("cut"); ap.add_argument("outdir")
    ap.add_argument("--origin", type=int, nargs=2, default=[0, 0], help="where the frame sits in the photo")
    ap.add_argument("--doc-size", type=int, nargs=2, help="the document's width and height (default: the frame reaches its right and bottom edges)")
    ap.add_argument("--shadow", choices=["real", "contact", "none"], default="real")
    ap.add_argument("--opacity", type=float, default=1.0, help="Shadow layer opacity (1 = as photographed)")
    ap.add_argument("--color-shadow", action="store_true", help="keep the shadow's colour cast (default: neutral grey)")
    ap.add_argument("--reach", type=float, default=0.35, help="shadow kept within this share of the product's size")
    ap.add_argument("--contact-strength", type=float, default=0.55, help="--shadow contact: darkness of the contact line")
    ap.add_argument("--size", type=int, default=2000, help="canvas long side in px")
    ap.add_argument("--aspect", default="1:1", help="canvas width:height")
    ap.add_argument("--fill", type=float, default=0.85, help="product's longer side as a share of the frame")
    ap.add_argument("--align", choices=["center", "bottom"], default="center")
    ap.add_argument("--bottom", type=float, default=0.06, help="--align bottom: gap under the product, share of height")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

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
    warnings = []

    # ---- backdrop and shadow, inside the product's box grown by --reach
    m = int(a.reach * size) + 8
    rx0, ry0, rx1, ry1 = max(0, pb[0] - m), max(0, pb[1] - m), min(w - 1, pb[2] + m), min(h - 1, pb[3] + m)
    dist = edge_distance(inside, w, h, cap=8)
    sample = [1 if A[i] <= 0.02 and (inside[i] == 0 and dist[i] >= 4) else 0 for i in range(N)]
    (BR, BG, BB), noise = fit_backdrop(R, G, B, sample, w, h)
    back_l = [imgops.lum(BR[i], BG[i], BB[i]) for i in range(N)]
    stats = {"backdrop": {"mean": [round(sum(c[i] for i in range(N) if sample[i]) / max(1, sum(sample))) for c in (BR, BG, BB)],
                          "range": [round(min(back_l[i] for i in range(N) if sample[i]), 1), round(max(back_l[i] for i in range(N) if sample[i]), 1)],
                          "noise": round(noise, 2)}}
    if stats["backdrop"]["mean"] and max(stats["backdrop"]["mean"]) - min(stats["backdrop"]["mean"]) > 12:
        warnings.append("backdrop is not neutral: correct white balance before cutting, or the product's colours are off too")

    rw, rh = rx1 - rx0 + 1, ry1 - ry0 + 1
    ridx = [(ry0 + y) * w + rx0 + x for y in range(rh) for x in range(rw)]
    if a.shadow == "real":
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
        # (fur tips and whiskers just past a soft mask are normal: only detail 8+ px from the mask counts)
        det = [1 if keep[j] and dist[i] >= 8 and lum_d[j] > 0.05 and abs(L[j] - Ls[j]) > lim else 0
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
        shadow_rgb = [[1 - d[j] for j in range(len(ridx))] for d in (res if len(res) == 3 else res * 3)]
        stats["shadow"] = {"pixels": kept, "max": round(max(lum_d[j] for j in range(len(ridx)) if keep[j]) if kept else 0, 3),
                           "cutoff": round(eps, 4)}
        if not kept:
            warnings.append("no shadow found next to the product: try --shadow contact")
    elif a.shadow == "contact":
        # painted the way retouchers do it: a tight dark line hugging the base contour (each column's lowest product
        # pixel), plus a soft, lighter spread below it. Following the contour keeps 3/4 views grounded at every foot.
        core_src, soft_src = [0.0] * len(ridx), [0.0] * len(ridx)
        tc, ts = max(2, int(0.004 * bw)), max(4, int(0.03 * bw))
        bottom = {}
        for x in range(pb[0], pb[2] + 1):
            yb = next((y for y in range(pb[3], pb[1] - 1, -1) if inside[y * w + x]), None)
            if yb is not None:
                bottom[x] = yb
        # the ground: an object resting on a plane touches it at points of the lower convex hull of its silhouette's
        # bottom contour (true for side and 3/4 views alike); steep hull segments are its sides, not ground
        hull = []
        for x in sorted(bottom):
            p = (x, bottom[x])
            while len(hull) >= 2 and ((hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1])
                                      - (hull[-1][1] - hull[-2][1]) * (p[0] - hull[-2][0])) <= 0:
                hull.pop()
            hull.append(p)
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

    SR, SG, SB = ([255.0] * N for _ in range(3))
    for j, i in enumerate(ridx):
        SR[i], SG[i], SB[i] = (255 * shadow_rgb[c][j] for c in range(3))
    q = lambda v: float(max(0, min(255, int(v + 0.5))))  # the PNG is 8-bit; predict with what the app will get
    SR, SG, SB = [q(v) for v in SR], [q(v) for v in SG], [q(v) for v in SB]
    imgops.save_rgb(os.path.join(a.outdir, "shadow.png"), w, h, SR, SG, SB)

    # predicted frame: product (Normal) over Shadow (Multiply, opacity) over White fill
    op = a.opacity
    under = [tuple(255 * (1 - op) + op * s for s in (SR[i], SG[i], SB[i])) for i in range(N)]
    PR = [A[i] * CR[i] + (1 - A[i]) * under[i][0] for i in range(N)]
    PG = [A[i] * CG[i] + (1 - A[i]) * under[i][1] for i in range(N)]
    PB = [A[i] * CB[i] + (1 - A[i]) * under[i][2] for i in range(N)]
    imgops.save_rgb(os.path.join(a.outdir, "preview.png"), w, h, PR, PG, PB)

    k = max(1, math.ceil(max(w, h) / 500))
    vw = w // k
    panels = []
    for c3 in ((R, G, B), (BR, BG, BB), (SR, SG, SB)):
        panels.append([imgops.downscale(c, w, h, k)[0] for c in c3])
    vh = h // k
    gap = 6
    VW = 3 * vw + 2 * gap
    viz = [[(255, 255, 255)] * VW for _ in range(vh)]
    for p, (pr, pg, pbb) in enumerate(panels):
        for y in range(vh):
            for x in range(vw):
                i = y * vw + x
                viz[y][p * (vw + gap) + x] = (int(pr[i]), int(pg[i]), int(pbb[i]))
    pngio.write(os.path.join(a.outdir, "viz.png"), VW, vh, viz)

    # ---- placement on the canvas
    aw, ah = (float(v) for v in a.aspect.split(":"))
    CW, CH = (a.size, round(a.size * ah / aw)) if aw >= ah else (round(a.size * aw / ah), a.size)
    s = a.fill / max(bw / CW, bh / CH)
    cxs = (pb[0] + pb[2] + 1) / 2
    if a.align == "center":
        cys, cyd = (pb[1] + pb[3] + 1) / 2, CH / 2
    else:
        cys, cyd = pb[3] + 1, CH * (1 - a.bottom)
    sx = cxs - (CW / 2) / s
    sy = cys - cyd / s
    sw, sh = CW / s, CH / s
    shadow_box = bbox([1 if SR[i] < 254.5 or SG[i] < 254.5 or SB[i] < 254.5 else 0 for i in range(N)], w, h)
    for name, b in (("product", pb), ("shadow", shadow_box)):
        if b and (b[0] < sx or b[1] < sy or b[2] + 1 > sx + sw or b[3] + 1 > sy + sh):
            warnings.append(f"the {name} doesn't fit the canvas at this fill/alignment; lower --fill or use --align center")
    X, Y = round(sx) + a.origin[0], round(sy) + a.origin[1]
    DW, DH = a.doc_size or (a.origin[0] + w, a.origin[1] + h)
    # The canvas rect may reach past the photo. Grow the canvas BEFORE the layers go in: a fill layer only covers the
    # canvas it was made on, and after a later grow or a crop past the edge the new area stays transparent.
    gl, gt = max(0, -X), max(0, -Y)
    gr, gb = max(0, X + round(sw) - DW), max(0, Y + round(sh) - DH)
    prep = []
    if gl or gt:
        prep.append({"command": "image.canvasSize", "params": {"width": gl, "height": gt, "relative": True, "anchor": "bottomRight", "extensionColor": "white"}})
    if gr or gb:
        prep.append({"command": "image.canvasSize", "params": {"width": gr, "height": gb, "relative": True, "anchor": "topLeft", "extensionColor": "white"}})
    json.dump(prep, open(os.path.join(a.outdir, "prep.json"), "w"), indent=1)
    steps = [{"command": "image.crop", "params": {"x": X + gl, "y": Y + gt, "width": round(sw), "height": round(sh),
                                                  "targetWidth": CW, "targetHeight": CH, "resample": "bicubic"}},
             {"command": "edit.convertToProfile", "params": {"profile": "srgb", "intent": "relative", "bpc": True}}]
    json.dump(steps, open(os.path.join(a.outdir, "steps.json"), "w"), indent=1)

    # predicted deliverable, small
    fk = max(1, math.ceil(max(CW, CH) / 600))
    FW, FH = CW // fk, CH // fk
    fin = []
    for y in range(FH):
        row = []
        for x in range(FW):
            u, v = sx + (x + 0.5) * fk / s, sy + (y + 0.5) * fk / s
            xi, yi = int(u), int(v)
            if 0 <= xi < w and 0 <= yi < h:
                i = yi * w + xi
                row.append((int(PR[i] + .5), int(PG[i] + .5), int(PB[i] + .5)))
            else:
                row.append((255, 255, 255))
        fin.append(row)
    pngio.write(os.path.join(a.outdir, "final.png"), FW, FH, fin)

    layers = [{"name": "White backdrop", "fill": "#ffffff"}]
    if a.shadow != "none":
        layers.append({"name": "Shadow (real)" if a.shadow == "real" else "Shadow (contact)", "image": "shadow.png",
                       "blend": "Multiply", "opacity": op})
    ox, oy = a.origin[0] + gl, a.origin[1] + gt  # where the frame sits once prep.json has grown the canvas
    spec = {"center": [ox + w / 2, oy + h / 2], "crop": [ox, oy, w, h],
            "preview": "preview.png", "group": "Product on white", "layers": layers}
    json.dump(spec, open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)
    stats.update({
        "product": {"bbox": [pb[0] + a.origin[0], pb[1] + a.origin[1], bw, bh]},
        "canvas": [CW, CH], "scale": round(s, 4),
        "productInCanvas": [round((pb[0] - sx) * s), round((pb[1] - sy) * s), round(bw * s), round(bh * s)],
        "fill": round(max(bw * s / CW, bh * s / CH), 3), "warnings": warnings,
        "next": (["pc.py script <outdir>/prep.json   (grow the canvas first)"] if prep else []) +
                ["import_layers.py <outdir>/layers.json --above <Background id>   (below the product layer)",
                 "pc.py script <outdir>/steps.json   (crop + resample to the canvas, sRGB)"],
    })
    if s > 1.05:
        warnings.append(f"the product is enlarged {s:.2f}x to fill the canvas: shoot or export at a higher resolution, or use a smaller --size")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
