#!/usr/bin/env python3
"""Change one colour: a garment, a product colourway, a wall, a car, with its shading and texture kept.

How it's done in Photoshop (Adobe's "Adjust colors"): pick one of the photo's prominent colours, move its Hue,
Saturation and Lightness on a Hue/Saturation adjustment layer, then narrow that colour's range (drag the far slider in
until the edge of the range sits about 10 degrees past the object's own hues) so skin and neighbouring colours that
share the hue aren't touched, and paint the layer mask black where colour still bleeds (lips, eyes, the hairline).
Professionals add the numbers: the object's median colour lands on the target (a product swatch, a brand colour) within
a CIEDE2000 of about 2, nothing outside the object changes, and the shading and texture stay (the same detail, only the
colour moved). A near-neutral object (a grey jacket, a white wall) has no hue for a range to catch: it gets Colorize,
which sets one hue for everything under the mask, so the mask must be tight.

PhotoCraft's Hue/Saturation, as measured on hue ramps (0.7.0): a range is [a, b, c, d] in HSV hue degrees, full
effect from b to c and fading linearly to nothing at a and d; any of the six named ranges can hold any range (the
defaults are the name's centre +-15 at full effect, +-45 to nothing). A pixel's effect is also scaled by its chroma
(max - min of R, G, B over 64 levels, capped at 1), so greys are never touched and dull, dark pixels only partly: deep
shadows of a dark garment move less than its midtones. Hue rotates the HSV hue, Saturation scales HSL saturation by
(1 + s/100), Lightness then scales toward black (l < 0) or white, each times that weight. Colorize keeps HSL lightness and sets hue and saturation. This script models exactly that
(preview.png, checked by import_layers.py) and solves the numbers on the photo's own pixels.

  recolor.py colors IMAGE OUTDIR [--area AREA] [--n 6]
  recolor.py plan   IMAGE AREA OUTDIR --target #RRGGBB|L,a,b [--point X,Y] [--mask MASK] [--mode auto|range|colorize]
                    [--falloff 10] [--spread 2] [--keep-range] [--similar 12] [--feather 4] [--space srgb|p3]
  recolor.py check  BEFORE AFTER AREA --target #RRGGBB|L,a,b [--space srgb|p3]

colors   the prominent colours, like Adobe's colour circles: hue families with their share of the photo, median
         colour (hex and Lab), hue spread, the Hue/Saturation range they fall in, and a point on each. colors.png
         shows a swatch per family and where it is. --area limits it to an area.
plan     AREA is an area.json ({"skin": polygon(s) round the object, "exclude": [patches, logos, faces, hands]},
         full-image coordinates, read with grid.py) or a rectangle x0,y0,x1,y1. The object is the area's dominant hue
         family (or the one at --point). Range mode (the object has a hue) narrows the range's skin side until skin-like
         pixels stop being caught, Adobe's step (--keep-range skips it); Colorize (a near-neutral object) fades the mask
         over pixels more than --similar a*b* off the object's colour, so hands and coloured patches drop out. Writes OUTDIR/layers.json (one Hue/Saturation layer, masked), mask.png, preview.png (the exact
         result of a full-resolution window, for import_layers.py to verify), before_after.png (the whole area,
         before | after | what the layer touches: grey = full effect, red = skin-like pixels it catches, cyan =
         parts of the object it misses), and plan.json. --mask: a grey PNG the size of the whole photo (an exported
         selection or cut-out mask), used inside the area instead of the polygon's edge.
check    measure a render of the finished document against the original: the object's median vs the target, what
         changed outside the area, detail kept, skin moved.

Prints one JSON line: the params, deltaE00 to the target, the object's coverage, bleed and warnings.
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import color_check as cc
import imgops

NAMES = ("reds", "yellows", "greens", "cyans", "blues", "magentas")  # Hue/Saturation ranges, centres 0, 60, ... 300


# ---------------------------------------------------------------- PhotoCraft's Hue/Saturation, modelled

def weight(rng, h):
    """Effect of a range [a, b, c, d] (HSV hue degrees, wrapping) at hue h: 1 from b to c, linear to 0 at a and d."""
    a, b, c, d = rng
    span_in = (c - b) % 360
    t = (h - b) % 360
    if t <= span_in:
        return 1.0
    up = (b - a) % 360
    before = (b - h) % 360
    if up and before < up:
        return 1 - before / up
    down = (d - c) % 360
    after = (h - c) % 360
    if down and after < down:
        return 1 - after / down
    return 0.0


def effect(r, g, b, q):
    """How much of a range's settings q a pixel gets: the range's weight at its hue times its chroma over 64 levels."""
    c = max(r, g, b) - min(r, g, b)
    return weight(q["range"], _hsl(r, g, b)[0]) * min(1.0, c / 64) if c else 0.0


def _hsl(r, g, b):
    mx, mn = max(r, g, b), min(r, g, b)
    L = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, L
    d = mx - mn
    S = d / (mx + mn) if L <= 127.5 else d / (510 - mx - mn)
    if mx == r:
        H = ((g - b) / d) % 6
    elif mx == g:
        H = (b - r) / d + 2
    else:
        H = (r - g) / d + 4
    return H * 60, S, L


def _from_hsl(H, S, L):
    C = (255 - abs(2 * L - 255)) * S
    X = C * (1 - abs((H / 60) % 2 - 1))
    m = L - C / 2
    k = int(H // 60) % 6
    r, g, b = ((C, X, 0), (X, C, 0), (0, C, X), (0, X, C), (X, 0, C), (C, 0, X))[k]
    return r + m, g + m, b + m


def _light(rgb, l):
    if l < 0:
        return tuple(v * (1 + l) for v in rgb)
    if l > 0:
        return tuple(v + (255 - v) * l for v in rgb)
    return rgb


def huesat(r, g, b, p):
    """One pixel through a Hue/Saturation layer with params p (as layers.json gives them): 0..255 floats."""
    if p.get("colorize"):
        _, _, L = _hsl(r, g, b)
        return _light(_from_hsl(p.get("hue", 0) % 360, min(1.0, p.get("saturation", 25) / 100), L),
                      p.get("lightness", 0) / 100)
    q = p[next(n for n in NAMES if n in p)]
    H, S, L = _hsl(r, g, b)
    w = effect(r, g, b, q)
    if w == 0:
        return r, g, b
    H2 = (H + w * q.get("hue", 0)) % 360
    S2 = min(1.0, S * (1 + w * q.get("saturation", 0) / 100))
    return _light(_from_hsl(H2, S2, L), w * q.get("lightness", 0) / 100)


def apply(R, G, B, M, p):
    """The layer over flat channels with mask M (0..1): new R, G, B, rounded like the 8-bit document."""
    oR, oG, oB = [], [], []
    for r, g, b, m in zip(R, G, B, M):
        if m <= 0:
            oR.append(r); oG.append(g); oB.append(b)
            continue
        nr, ng, nb = huesat(r, g, b, p)
        oR.append(round(min(255, max(0, r + m * (nr - r)))))
        oG.append(round(min(255, max(0, g + m * (ng - g)))))
        oB.append(round(min(255, max(0, b + m * (nb - b)))))
    return oR, oG, oB


# ---------------------------------------------------------------- measures

def median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else 0.0


def med_lab(pix, space):
    labs = [imgops.lab(*q, space=space) for q in pix]
    return tuple(median([x[k] for x in labs]) for k in range(3))


def circ_hist(hues, bins=72):
    n = [0.0] * bins
    for h in hues:
        n[int(h / (360 / bins)) % bins] += 1
    k = [1, 2, 3, 2, 1]
    return [sum(k[j] * n[(i + j - 2) % bins] for j in range(5)) / 9 for i in range(bins)]


def families(hues, bins=72, floor=0.02):
    """Hue families: the circular histogram cut at its valleys; [(peak bin, first bin, last bin, count)]."""
    hist = circ_hist(hues, bins)
    tot = sum(hist) or 1
    peaks = [i for i in range(bins) if hist[i] > 0 and hist[i] >= hist[i - 1] and hist[i] > hist[(i + 1) % bins]
             and hist[i] / tot * bins / 5 >= floor]
    out = []
    for p in peaks:
        lo = p
        while (hist[(lo - 1) % bins] <= hist[lo % bins] and hist[(lo - 1) % bins] > hist[p] * 0.03
               and (p - lo) < bins // 2):
            lo -= 1
        hi = p
        while (hist[(hi + 1) % bins] <= hist[hi % bins] and hist[(hi + 1) % bins] > hist[p] * 0.03
               and (hi - p) < bins // 2):
            hi += 1
        out.append((p % bins, lo % bins, hi % bins, sum(hist[(lo + j) % bins] for j in range((hi - lo) % bins + 1))))
    return sorted(out, key=lambda f: -f[3])


def in_family(h, f, bins=72):
    i = int(h / (360 / bins)) % bins
    return (i - f[1]) % bins <= (f[2] - f[1]) % bins


def circ_pct(hues, centre, ps):
    d = sorted(((h - centre + 180) % 360 - 180) for h in hues)
    return [(centre + d[min(len(d) - 1, int(p / 100 * len(d)))]) % 360 for p in ps]


def range_name(h):
    return NAMES[int(((h + 30) % 360) // 60)]


def skin_like(r, g, b, space):
    """A pixel that could be skin (any complexion), lips or the hairline: Lab hue 28-80 degrees, moderate chroma, near
    the vectorscope's skin line. Saturated reds (a dress, a mural) sit below 28 and don't count."""
    ang = imgops.vectorscope(r, g, b)[0]
    L, a, bb = imgops.lab(r, g, b, space=space)
    C = math.hypot(a, bb)
    return (100 <= ang <= 150 and 20 <= L <= 92 and 6 <= C <= 50 and a > 2
            and 28 <= math.degrees(math.atan2(bb, a)) <= 80)


def detail(L, w, h, M):
    """Luminance detail (L minus a 2 px box blur) where M > 0.5."""
    bl = imgops.box(L, w, h, 2)
    return [L[i] - bl[i] if M[i] > 0.5 else None for i in range(w * h)]


def rel_contrast(cr, Lb, La, M):
    """corr()'s detail ratio relative to the change in mean tone: 1 when the object is darker or lighter the way a
    darker or lighter dye would be (detail scales with it), below 1 when the shading is flattened."""
    idx = [i for i in range(len(M)) if M[i] > 0.5]
    mb = sum(Lb[i] for i in idx) / max(1, len(idx)); ma = sum(La[i] for i in idx) / max(1, len(idx))
    return cr[1] / (ma / mb) if cr and cr[1] is not None and mb and ma else None


def corr(x, y):
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 10:
        return None
    mx = sum(a for a, _ in pairs) / len(pairs); my = sum(b for _, b in pairs) / len(pairs)
    sxy = sum((a - mx) * (b - my) for a, b in pairs)
    sx = math.sqrt(sum((a - mx) ** 2 for a, _ in pairs)); sy = math.sqrt(sum((b - my) ** 2 for _, b in pairs))
    return sxy / (sx * sy) if sx and sy else None, (sy / sx if sx else None)


def parse_target(s, space):
    s = s.strip()
    if s.startswith("#") and len(s) == 7:
        rgb = tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
        return imgops.lab(*rgb, space=space), rgb
    try:
        L, a, b = (float(v) for v in s.split(","))
    except ValueError:
        sys.exit(f"error: --target {s!r}: give #RRGGBB or L,a,b")
    rgb = imgops.lab_to_rgb(L, a, b, space=space)
    return (L, a, b), tuple(max(0, min(255, round(v))) for v in rgb)


def hexof(rgb):
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in rgb)


# ---------------------------------------------------------------- area and mask

def area_of(spec, W, H):
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        polys = cfg.get("skin") or cfg.get("area")
        if not polys:
            sys.exit(f"error: {spec} has no \"skin\" (or \"area\") polygon")
        cfg = {"skin": polys, "exclude": cfg.get("exclude", [])}
    else:
        try:
            x0, y0, x1, y1 = (float(v) for v in spec.split(","))
        except ValueError:
            sys.exit(f"error: {spec} is neither an area.json nor a rectangle x0,y0,x1,y1")
        cfg = {"skin": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "exclude": []}
    polys = cfg["skin"] if isinstance(cfg["skin"][0][0], (list, tuple)) else [cfg["skin"]]
    xs = [p[0] for q in polys for p in q]; ys = [p[1] for q in polys for p in q]
    box = [max(0, int(min(xs))), max(0, int(min(ys))), min(W, int(math.ceil(max(xs))) + 1), min(H, int(math.ceil(max(ys))) + 1)]
    if box[2] <= box[0] or box[3] <= box[1]:
        sys.exit("error: the area lies outside the image")
    return cfg, box


def scaled_cfg(cfg, ox, oy, k):
    sc = lambda pts: [[(x - ox) / k, (y - oy) / k] for x, y in pts]
    polys = cfg["skin"] if isinstance(cfg["skin"][0][0], (list, tuple)) else [cfg["skin"]]
    ex = [sc(e) if isinstance(e[0], (list, tuple)) else sc([[e[0], e[1]], [e[2], e[1]], [e[2], e[3]], [e[0], e[3]]])
          for e in cfg.get("exclude", [])]
    return {"skin": [sc(p) for p in polys], "exclude": ex}


def soft(m, w, h, feather):
    return imgops.gauss(m, w, h, feather / 2) if feather > 0 else m


# ---------------------------------------------------------------- colors

def cmd_colors(a):
    img = cc.Image(a.image, 600)
    w, h, R, G, B, s = img.w, img.h, img.R, img.G, img.B, img.s
    M = [1.0] * (w * h)
    if a.area:
        cfg, _ = area_of(a.area, img.W, img.H)
        M = imgops.raster(scaled_cfg(cfg, 0, 0, s), 0, 0, w, h)
    idx = [i for i in range(w * h) if M[i] > 0.5]
    hs = {}
    for i in idx:
        H, S, L = _hsl(R[i], G[i], B[i])
        if S >= 0.12 and 12 <= L <= 245 and max(R[i], G[i], B[i]) - min(R[i], G[i], B[i]) >= 10:
            hs[i] = H
    fams = families(list(hs.values()))[:a.n]
    out, cols = [], {}
    for k, f in enumerate(fams):
        mem = [i for i, H in hs.items() if in_family(H, f)]
        if not mem:
            continue
        L = med_lab([(R[i], G[i], B[i]) for i in mem], a.space)
        hh = [hs[i] for i in mem]
        p5, p50, p95 = circ_pct(hh, f[0] * 5 + 2.5, (5, 50, 95))
        best = min(mem[::max(1, len(mem) // 3000)], key=lambda i: cc.de2000(imgops.lab(R[i], G[i], B[i], space=a.space), L))
        rgb = imgops.lab_to_rgb(*L, space=a.space)
        out.append({"n": k + 1, "share": round(len(mem) / len(idx), 3), "hex": hexof(rgb), "lab": [round(v, 1) for v in L],
                    "hue": round(p50), "hueSpread": [round(p5), round(p95)], "range": range_name(p50),
                    "point": [round((best % w + 0.5) * s), round((best // w + 0.5) * s)]})
        for i in mem:
            cols[i] = k
    neutral = 1 - len(hs) / max(1, len(idx))
    # colors.png: the photo, families greyed out except in their swatch colour, a strip of swatches on top
    sw = 40
    oR, oG, oB = [], [], []
    for i in range(w * h):
        g = imgops.lum(R[i], G[i], B[i]) * 0.5 + 64
        if i in cols:
            rgb = imgops.lab_to_rgb(*out[cols[i]]["lab"], space=a.space)
            oR.append(rgb[0]); oG.append(rgb[1]); oB.append(rgb[2])
        else:
            oR.append(g); oG.append(g); oB.append(g)
    top = [[255.0] * (w * sw) for _ in range(3)]
    for k, o in enumerate(out):
        rgb = imgops.lab_to_rgb(*o["lab"], space=a.space)
        for y in range(4, sw - 4):
            for x in range(k * (w // max(1, len(out))) + 4, (k + 1) * (w // max(1, len(out))) - 4):
                for c in range(3):
                    top[c][y * w + x] = rgb[c]
        cc_draw_num(top, w, k * (w // max(1, len(out))) + 8, 10, str(o["n"]))
    os.makedirs(a.outdir, exist_ok=True)
    viz = os.path.join(a.outdir, "colors.png")
    imgops.save_rgb(viz, w, h + sw, top[0] + oR, top[1] + oG, top[2] + oB)
    print(json.dumps({"colors": out, "neutralShare": round(neutral, 3), "viz": viz,
                      "next": "recolor.py plan IMAGE AREA OUTDIR --target #hex, AREA round the object you want changed"}))


def cc_draw_num(chans, w, x0, y0, text, k=3):
    for j, ch in enumerate(text):
        bits = imgops.FONT.get(ch)
        if not bits:
            continue
        for r in range(5):
            for c in range(3):
                if bits[r * 3 + c] == "1":
                    for yy in range(k):
                        for xx in range(k):
                            i = (y0 + r * k + yy) * w + x0 + j * 4 * k + c * k + xx
                            if 0 <= i < len(chans[0]):
                                for q in chans:
                                    q[i] = 0.0


# ---------------------------------------------------------------- plan

def solve(pix, p0, target, space, keys):
    """Coordinate search on the integer params `keys` of p0 (in place) minimising CIEDE2000 between the result's
    median Lab and the target."""
    sub = p0 if p0.get("colorize") else p0[next(n for n in NAMES if n in p0)]
    lim = {"hue": (-180, 180), "saturation": (-100, 100), "lightness": (-100, 100)}
    if p0.get("colorize"):
        lim = {"hue": (0, 359), "saturation": (0, 100), "lightness": (-100, 100)}

    def cost():
        out = [huesat(*q, p0) for q in pix]
        return cc.de2000(med_lab(out, space), target)

    best = cost()
    for step in (16, 8, 4, 2, 1):
        moved = True
        while moved:
            moved = False
            for k in keys:
                for d in (step, -step):
                    old = sub[k]
                    v = old + d
                    if k == "hue" and p0.get("colorize"):
                        v %= 360
                    elif not lim[k][0] <= v <= lim[k][1]:
                        continue
                    sub[k] = v
                    c = cost()
                    if c < best - 1e-6:
                        best, moved = c, True
                    else:
                        sub[k] = old
    return best


def cmd_plan(a):
    target, trgb = parse_target(a.target, a.space)
    W, H = cc.full_size(os.path.abspath(os.path.expanduser(a.image)))
    cfg, (x0, y0, x1, y1) = area_of(a.area, W, H)
    pad = int(math.ceil(a.feather * 2)) + 2
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    bw, bh = x1 - x0, y1 - y0
    os.makedirs(a.outdir, exist_ok=True)
    od = lambda n: os.path.join(a.outdir, n)
    src = os.path.abspath(os.path.expanduser(a.image))
    k = max(1.0, max(bw, bh) / a.max_side)  # analysis copy of the area's box
    cw, ch = max(1, round(bw / k)), max(1, round(bh / k))
    ana = cc.tmp("ana.png")
    cc.cli_run(src, [("image.crop", {"x": x0, "y": y0, "width": bw, "height": bh})]
               + ([("image.imageSize", {"width": cw, "height": ch, "resample": "bilinear"})] if k > 1 else []), ana)
    cw, ch, R, G, B = imgops.load(ana)
    k = bw / cw

    def user_mask(width, height, scale_to):
        out = cc.tmp("um.png")
        cmds = [("image.crop", {"x": x0, "y": y0, "width": bw, "height": bh})]
        if scale_to:
            cmds.append(("image.imageSize", {"width": width, "height": height, "resample": "bilinear"}))
        cc.cli_run(os.path.abspath(os.path.expanduser(a.mask)), cmds, out)
        return imgops.load(out)[2]

    poly = imgops.raster(scaled_cfg(cfg, x0, y0, k), 0, 0, cw, ch)
    if a.mask:
        um = [v / 255 for v in user_mask(cw, ch, k > 1)]
        poly = [min(p, u) for p, u in zip(poly, um)]
    M = [min(1.0, max(0.0, v)) for v in soft(poly, cw, ch, a.feather / k)]
    inside = [i for i in range(cw * ch) if M[i] > 0.5]
    if len(inside) < 50:
        sys.exit("error: the area holds fewer than 50 pixels of the photo")
    hues = {}
    for i in inside:
        Hh, S, L = _hsl(R[i], G[i], B[i])
        if S >= 0.08 and max(R[i], G[i], B[i]) - min(R[i], G[i], B[i]) >= 6:
            hues[i] = Hh
    labs_in = med_lab([(R[i], G[i], B[i]) for i in inside], a.space)
    fams = families(list(hues.values()))
    f = fams[0] if fams else None
    if a.point and fams:  # the colour the user pointed at, like clicking one of Adobe's colour circles
        px, py = (float(v) for v in a.point.split(","))
        j = min(cw * ch - 1, max(0, int((py - y0) / k)) * cw + min(cw - 1, max(0, int((px - x0) / k))))
        hp = _hsl(R[j], G[j], B[j])[0]
        f = next((q for q in fams if in_family(hp, q)), None)
        if f is None:
            sys.exit(f"error: the colour at {a.point} is near neutral or in no hue family of the area: --mode colorize")
    obj = [i for i in hues if f and in_family(hues[i], f)]
    fam_lab = med_lab([(R[i], G[i], B[i]) for i in obj], a.space) if obj else (0, 0, 0)
    mode = a.mode
    if mode == "auto":
        mode = "range" if obj and (len(obj) >= 0.2 * len(inside) or a.point) and math.hypot(*fam_lab[1:]) >= 15 \
            else "colorize"
    warn = []
    if mode == "range":
        if not obj:
            sys.exit("error: the area has no colour to catch (near neutral): use --mode colorize")
        centre = circ_pct([hues[i] for i in obj], f[0] * 5 + 2.5, (50,))[0]
        lo, hi = circ_pct([hues[i] for i in obj], centre, (a.spread, 100 - a.spread))
        if (hi - lo) % 360 > 150:
            warn.append(f"the object's hues spread {round((hi - lo) % 360)} degrees: a wide range catches much else; "
                        "consider --mode colorize with a tight mask")
        rng = [round(lo - a.falloff) % 360, round(lo) % 360, round(hi) % 360, round(hi + a.falloff) % 360]
        narrowed = narrow_for_skin(rng, R, G, B, M, obj, a.space) if not a.keep_range and not skin_target(fam_lab) \
            else None
        if narrowed:
            rng, note = narrowed
            warn.append(note)
        name = range_name(centre)
        params = {name: {"hue": 0, "saturation": 0, "lightness": 0, "range": rng}}
        th = _hsl(*trgb)[0]
        params[name]["hue"] = int(round(((th - centre + 180) % 360) - 180))
        objpix = [(R[i], G[i], B[i]) for i in obj]
    else:
        similar = 12 if a.similar is None else a.similar
        if similar > 0:  # Color Range's fuzziness: off the object's own colour (a*, b*), the mask fades out
            a0, b0 = labs_in[1], labs_in[2]
            for i in range(cw * ch):
                if M[i] > 0:
                    _, aa, bb = imgops.lab(R[i], G[i], B[i], space=a.space)
                    d = math.hypot(aa - a0, bb - b0)
                    M[i] *= 1.0 if d <= similar else max(0.0, 1 - (d - similar) / (0.5 * similar))
            inside = [i for i in range(cw * ch) if M[i] > 0.5]
            if len(inside) < 50:
                sys.exit(f"error: --similar {similar:g} leaves fewer than 50 pixels in the mask (the area holds several "
                         "colours, none of them the median): tighten the area or --mask, or raise --similar (0 = off)")
        th, ts, _ = _hsl(*trgb)
        params = {"colorize": True, "hue": int(round(th)) % 360, "saturation": max(1, min(100, round(ts * 100))),
                  "lightness": 0}
        obj = inside
        objpix = [(R[i], G[i], B[i]) for i in obj]
    sample = objpix[::max(1, len(objpix) // 2500)]
    before = med_lab(objpix, a.space)
    de = solve(sample, params, target, a.space, ("hue", "saturation", "lightness"))
    # the whole area at the analysis scale: after, and what the layer touches
    aR, aG, aB = apply(R, G, B, M, params)
    after = med_lab([(aR[i], aG[i], aB[i]) for i in obj], a.space)
    de = cc.de2000(after, target)
    eff, skin_caught, missed, caught_out = [0.0] * (cw * ch), 0, 0, 0
    sub = None if params.get("colorize") else params[next(n for n in NAMES if n in params)]
    for i in range(cw * ch):
        wgt = 1.0 if sub is None else effect(R[i], G[i], B[i], sub)
        eff[i] = wgt * M[i]
        if M[i] <= 0.5 and wgt > 0.1 and sub is not None:
            caught_out += 1
        if eff[i] > 0.1 and skin_like(R[i], G[i], B[i], a.space) and not skin_target(before):
            skin_caught += 1
    objset = set(obj)
    hue_w = {i: (1.0 if sub is None else weight(sub["range"], _hsl(R[i], G[i], B[i])[0])) for i in obj}
    missed = sum(1 for i in obj if hue_w[i] < 0.5)
    dull = sum(1 for i in obj if hue_w[i] >= 0.5 and eff[i] < 0.5 * M[i])
    Lb = [imgops.lum(R[i], G[i], B[i]) for i in range(cw * ch)]
    La = [imgops.lum(aR[i], aG[i], aB[i]) for i in range(cw * ch)]
    Mo = [1.0 if i in objset else 0.0 for i in range(cw * ch)]
    cr = corr(detail(Lb, cw, ch, Mo), detail(La, cw, ch, Mo))
    rc = rel_contrast(cr, Lb, La, Mo)
    full_cov = sum(1 for i in obj if eff[i] >= 0.99) / len(obj)
    scatter = tone_scatter([(R[i], G[i], B[i]) for i in obj], [(aR[i], aG[i], aB[i]) for i in obj], a.space)
    if de > 3:
        dl = target[0] - after[0]
        dc = math.hypot(*target[1:]) - math.hypot(*after[1:])
        why = (f"lightness {abs(dl):.0f} L* {'short' if dl > 0 else 'over'}" if abs(dl) >= abs(dc) else
               f"chroma {abs(dc):.0f} {'short: more than Saturation +100 gives' if dc > 0 else 'over'}")
        warn.append(f"deltaE00 {de:.1f} to the target ({why}): Hue/Saturation moves hue and chroma well and lightness "
                    "only a little. Tell the user how close it gets, or ask for a photo of the real colourway")
    if abs(target[0] - before[0]) > 25:
        warn.append(f"the target is {abs(target[0] - before[0]):.0f} L* {'lighter' if target[0] > before[0] else 'darker'} "
                    "than the object: past about 25 L* Lightness blows or flattens the shading and dull shadows lag "
                    "behind (blotches): look at before_after.png at 100 %")
    if scatter > 4:
        warn.append(f"tone scatter {scatter:.1f} L*: pixels of the same tone came out different (dull folds and shadows "
                    "move less than bright cloth), which reads as blotches")
    if rc is not None and rc < 0.7:
        warn.append(f"detail contrast fell to {rc:.2f} of the original (for its new tone): the shading is flattened")
    if skin_caught > 0.002 * len(inside):
        warn.append(f"{skin_caught} skin-like pixels inside the mask are caught (red in before_after.png): add exclude "
                    "polygons over faces, hands, lips, or narrow the range")
    if missed > 0.05 * len(obj):
        warn.append(f"{missed / len(obj):.0%} of the object's pixels have hues outside the range's full half (cyan): "
                    "widen it (--spread 1, --falloff 20) or check them by eye")
    if mode == "colorize":
        warn.append("Colorize sets one hue for everything under the mask: --similar drops skin and coloured patches, "
                    "but other near-neutrals (a grey sleeve over jeans, a white backdrop, a black sole) look alike to "
                    "it, so the area's edge or --mask must keep them out: look at before_after.png")
    # outputs: mask at full size, a full-resolution window for the exact preview
    small = od("mask_small.png")
    imgops.save_gray(small, cw, ch, M)
    cc.cli_run(small, [("image.imageSize", {"width": bw, "height": bh, "resample": "bilinear"})] if k > 1 else [],
               od("mask.png"))
    os.remove(small)
    # the verify window: up to 600 px of the object round its densest part
    oxs = sorted(i % cw for i in obj); oys = sorted(i // cw for i in obj)
    cx, cy = oxs[len(oxs) // 2] * k, oys[len(oys) // 2] * k
    vw, vh = min(bw, a.window), min(bh, a.window)
    vx = int(min(max(0, cx - vw / 2), bw - vw)); vy = int(min(max(0, cy - vh / 2), bh - vh))
    win = cc.tmp("win.png")
    cc.cli_run(src, [("image.crop", {"x": x0 + vx, "y": y0 + vy, "width": vw, "height": vh})], win)
    _, _, wR, wG, wB = imgops.load(win)
    mwin = cc.tmp("mwin.png")
    cc.cli_run(od("mask.png"), [("image.crop", {"x": vx, "y": vy, "width": vw, "height": vh})], mwin)
    wM = [v / 255 for v in imgops.load(mwin)[2]]
    pR, pG, pB = apply(wR, wG, wB, wM, params)
    imgops.save_rgb(od("preview.png"), vw, vh, pR, pG, pB)
    # before | after | effect
    vR, vG, vB = [], [], []
    for i in range(cw * ch):
        g = 40 + 200 * eff[i]
        c = (g, g, g)
        if eff[i] > 0.1 and skin_like(R[i], G[i], B[i], a.space) and not skin_target(before):
            c = (255, 40, 40)
        elif i in objset and hue_w[i] < 0.5:
            c = (0, 220, 255)
        vR.append(c[0]); vG.append(c[1]); vB.append(c[2])
    gap = 6
    tw = cw * 3 + gap * 2
    TR, TG, TB = [255.0] * (tw * ch), [255.0] * (tw * ch), [255.0] * (tw * ch)
    for y in range(ch):
        for j, (q1, q2, q3) in enumerate(((R, G, B), (aR, aG, aB), (vR, vG, vB))):
            o = y * tw + j * (cw + gap)
            TR[o:o + cw] = q1[y * cw:(y + 1) * cw]; TG[o:o + cw] = q2[y * cw:(y + 1) * cw]
            TB[o:o + cw] = q3[y * cw:(y + 1) * cw]
    imgops.save_rgb(od("before_after.png"), tw, ch, TR, TG, TB)
    label = (f"Recolour to {a.target}" if a.name is None else a.name)
    spec = {"center": [x0 + bw / 2, y0 + bh / 2], "crop": [x0 + vx, y0 + vy, vw, vh], "preview": "preview.png",
            "tolerance": 0.6, "layers": [{"name": label, "adjustment": "hueSaturation", "params": params, "mask": "mask.png"}]}
    json.dump(spec, open(od("layers.json"), "w"), indent=1)
    res = {"mode": mode, "params": params, "target": {"lab": [round(v, 1) for v in target], "hex": hexof(trgb)},
           "before": {"lab": [round(v, 1) for v in before], "hex": hexof(imgops.lab_to_rgb(*before, space=a.space))},
           "after": {"lab": [round(v, 1) for v in after], "hex": hexof(imgops.lab_to_rgb(*after, space=a.space))},
           "deltaE00": round(de, 2), "objectShare": round(len(obj) / len(inside), 3),
           "fullEffect": round(full_cov, 3), "dullShare": round(dull / len(obj), 3), "toneScatter": round(scatter, 1), "detailCorr": round(cr[0], 3) if cr and cr[0] is not None else None,
           "detailContrast": round(rc, 2) if rc is not None else None,
           "rangeCatchesOutsideMask": caught_out, "skinCaught": skin_caught, "box": [x0, y0, bw, bh],
           "warnings": warn, "layers": od("layers.json"), "look": od("before_after.png")}
    json.dump(res, open(od("plan.json"), "w"), indent=1)
    print(json.dumps(res))


def narrow_for_skin(rng, R, G, B, M, obj, space, skin_hue=25):
    """Adobe's step: drag the range's edge on the skin side in until skin stops being caught, as long as the object
    keeps 85 % of its pixels at full hue weight. Returns (range, note) or None when nothing needed narrowing."""
    skin = [i for i in range(len(M)) if M[i] > 0.05 and skin_like(R[i], G[i], B[i], space)]
    hue = lambda i: _hsl(R[i], G[i], B[i])[0]
    sk_h = [hue(i) for i in skin]
    ob_h = [hue(i) for i in obj[::max(1, len(obj) // 4000)]]

    def caught(r):
        q = {"range": r}
        return sum(1 for i in skin if effect(R[i], G[i], B[i], q) > 0.1)

    n0 = caught(rng)
    if n0 <= 0.002 * sum(1 for v in M if v > 0.5):
        return None
    a, b, c, d = rng
    upper = (skin_hue - c) % 360 < (b - skin_hue) % 360  # skin lies past the range's upper edge
    r = list(rng)
    while True:
        if upper:
            if (r[3] - r[2]) % 360 > 2:
                r[3] = (r[3] - 2) % 360
            else:
                r[2], r[3] = (r[2] - 2) % 360, (r[3] - 2) % 360
        else:
            if (r[1] - r[0]) % 360 > 2:
                r[0] = (r[0] + 2) % 360
            else:
                r[0], r[1] = (r[0] + 2) % 360, (r[1] + 2) % 360
        if sum(1 for h in ob_h if weight(r, h) >= 0.99) < 0.85 * len(ob_h) or (r[2] - r[1]) % 360 < 4:
            break
        rng = list(r)
        if caught(rng) <= 0.1 * n0:
            break
    n1 = caught(rng)
    if rng == [a, b, c, d]:
        return None
    return rng, (f"range narrowed on the skin side to {rng} (Adobe's 'drag the far slider in'): skin-like pixels caught "
                 f"{n0} -> {n1}; paint the rest out with exclude polygons")


def tone_scatter(before, after, space, n=6000):
    """RMS in L* of the result's lightness about its mean for each before-lightness (2 L* bins): 0 when the object's
    tones map to new tones one to one, as a dye change does; high when the same tone lands in different places."""
    step = max(1, len(before) // n)
    bins = {}
    for p, q in zip(before[::step], after[::step]):
        bins.setdefault(int(imgops.lab(*p, space=space)[0] // 2), []).append(imgops.lab(*q, space=space)[0])
    sq = sum(sum((v - sum(vs) / len(vs)) ** 2 for v in vs) for vs in bins.values())
    return math.sqrt(sq / max(1, sum(len(vs) for vs in bins.values())))


def skin_target(lab):
    """The object itself is skin-coloured (a tan bag, a beige wall): skin-like pixels are then expected."""
    a, b = lab[1], lab[2]
    ang = math.degrees(math.atan2(b, a))
    return 25 <= ang <= 80 and 8 <= math.hypot(a, b) <= 45


# ---------------------------------------------------------------- check

def cmd_check(a):
    target, _ = parse_target(a.target, a.space)
    W, H = cc.full_size(os.path.abspath(os.path.expanduser(a.before)))
    W2, H2 = cc.full_size(os.path.abspath(os.path.expanduser(a.after)))
    if (W, H) != (W2, H2):
        sys.exit(f"error: before is {W}x{H}, after {W2}x{H2}")
    b, aft = cc.Image(a.before, a.max_side), cc.Image(a.after, a.max_side)
    cfg, _ = area_of(a.area, W, H)
    M = imgops.raster(scaled_cfg(cfg, 0, 0, b.s), 0, 0, b.w, b.h)
    n = b.w * b.h
    changed = [max(abs(b.R[i] - aft.R[i]), abs(b.G[i] - aft.G[i]), abs(b.B[i] - aft.B[i])) for i in range(n)]
    ring = imgops.maxf(M, b.w, b.h, max(2, round(a.feather / b.s) + 2))
    outside = [i for i in range(n) if ring[i] < 0.5]
    out_changed = sum(1 for i in outside if changed[i] > 2) / max(1, len(outside))
    moved = [i for i in range(n) if M[i] > 0.5 and changed[i] > 2]
    res = {"changedOutside": round(out_changed, 4), "movedInside": len(moved)}
    if moved:
        after = med_lab([(aft.R[i], aft.G[i], aft.B[i]) for i in moved], a.space)
        res["object"] = {"lab": [round(v, 1) for v in after], "deltaE00": round(cc.de2000(after, target), 2)}
        Lb = [imgops.lum(b.R[i], b.G[i], b.B[i]) for i in range(n)]
        La = [imgops.lum(aft.R[i], aft.G[i], aft.B[i]) for i in range(n)]
        Mo = [0.0] * n
        for i in moved:
            Mo[i] = 1.0
        cr = corr(detail(Lb, b.w, b.h, Mo), detail(La, b.w, b.h, Mo))
        rc = rel_contrast(cr, Lb, La, Mo)
        if cr:
            res["detailCorr"] = round(cr[0], 3) if cr[0] is not None else None
            res["detailContrast"] = round(rc, 2) if rc is not None else None
    sk = [i for i in range(n) if skin_like(b.R[i], b.G[i], b.B[i], a.space)]
    if sk:
        moved_sk = [i for i in sk if changed[i] > 2]
        res["skinPixelsChanged"] = round(len(moved_sk) / len(sk), 4)
    ok = out_changed < 0.001 and res.get("object", {}).get("deltaE00", 99) <= 3
    res["verdict"] = "ok" if ok else "check"
    print(json.dumps(res))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("colors", help="the prominent colours")
    p.add_argument("image"); p.add_argument("outdir")
    p.add_argument("--area"); p.add_argument("--n", type=int, default=6)
    p.add_argument("--space", choices=("srgb", "p3"), default="srgb")
    p.set_defaults(fn=cmd_colors)
    p = sub.add_parser("plan", help="solve a Hue/Saturation layer that takes an object to a target colour")
    p.add_argument("image"); p.add_argument("area"); p.add_argument("outdir")
    p.add_argument("--target", required=True, help="#RRGGBB or L,a,b (D50, as the Info panel reads)")
    p.add_argument("--mask", help="a grey PNG the photo's size, used inside the area (a selection, a cut-out mask)")
    p.add_argument("--point", help="X,Y on the object (full image): its hue family is the one changed")
    p.add_argument("--mode", choices=("auto", "range", "colorize"), default="auto",
                   help="auto: range when a hue family of chroma 15 or more fills a fifth of the area (or --point), else colorize")
    p.add_argument("--falloff", type=float, default=10, help="degrees the range fades over past the object's hues")
    p.add_argument("--keep-range", action="store_true", help="don't narrow the range away from skin")
    p.add_argument("--spread", type=float, default=2, help="percent of the object's hues left out at each end")
    p.add_argument("--feather", type=float, default=4, help="the mask's edge in px")
    p.add_argument("--similar", type=float, help="Colorize: the mask fades out over pixels more than this far from "
                   "the object's own colour in a*b* (default 12; 0 = off): skin, lips and coloured patches drop out")
    p.add_argument("--name", help="the layer's name (default: Recolour to TARGET)")
    p.add_argument("--max-side", type=int, default=1000, help="analysis size of the area's box")
    p.add_argument("--window", type=int, default=600, help="side of the full-resolution verify window")
    p.add_argument("--space", choices=("srgb", "p3"), default="srgb", help="the document's RGB space, for Lab")
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("check", help="measure a render against the original")
    p.add_argument("before"); p.add_argument("after"); p.add_argument("area")
    p.add_argument("--target", required=True)
    p.add_argument("--feather", type=float, default=4)
    p.add_argument("--max-side", type=int, default=1200)
    p.add_argument("--space", choices=("srgb", "p3"), default="srgb")
    p.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
