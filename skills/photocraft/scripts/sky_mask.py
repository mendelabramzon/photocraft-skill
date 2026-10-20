#!/usr/bin/env python3
"""Precise sky mask for a sky replacement: refines PhotoCraft's coarse select.sky region into a soft alpha that
follows rooftops, chimneys, spires and branches, and computes decontaminated edge colours, so the old sky doesn't
glow through as a halo around everything once the new sky is in.

select.sky in PhotoCraft 0.7.0 finds roughly where the sky is, but its edge is a smooth blob 10-20 px off: it
rounds chimneys, cuts into roofs, treats a whole tree as solid and can miss whole patches (a vignetted corner, the
pale band near the horizon). Here that blob only seeds the job:
- Sky it missed is added back where it continues the known sky with no edge in between.
- Around its border (a band of --band x the image width), in tree canopies near the sky, and around thin dark
  things inside the sky, every pixel is split into sky and foreground with a local colour model: the clean sky at
  that spot (a robust local plane fit of the sky around it, which follows the gradient toward the horizon) and the
  foreground beside it (clearly-not-sky pixels nearby; on thin things the most foreground-like of them).
  alpha = how far the pixel sits along the line from foreground colour to sky colour.
- Edge pixels are a mix of old sky and foreground; their foreground part is recovered from
  I = alpha*S + (1 - alpha)*F, so the composite becomes alpha*new sky + (1 - alpha)*F with no old sky left in it
  (what Photoshop calls decontaminating colours).
- Sky islands inside solid foreground (pale tiles, a window) are dropped; inside canopies they stay.
- If sky runs on to the bottom of the crop, the crop is taken taller and the matte solved again.

  sky_mask.py photo.jpg outdir [--area area.json] [--trees] [--shift 1] [--band 0.015] [--coarse mask.png] [--reuse]

Writes to outdir (under the home folder, so the app can open the PNGs):
  crop.png        the photo from the top down to below the skyline (the region every layer covers)
  coarse.png      select.sky's region, same crop
  alpha.png       the sky mask (white = sky): mask of the new sky layer
  edge.png        the crop with edge pixels decontaminated; edge_mask.png = where that layer acts
  viz.png         blue = sky, yellow = the alpha 0.5 contour, magenta = low-confidence pixels (the foreground is
                  the sky's colour there and the coarse mask decided), green = thin dark objects kept in the sky
  mask.json       crop, centre, stats, the photo's colour profile, warnings; read by sky_check.py
area.json (optional, full-image coords): {"sky": [poly, ...] a patch select.sky missed, "keep": [poly, ...]
  foreground the colour of the sky that must stay (a pale gable, snow, a white van)}
--trees: sky seen through branches all over the frame (looking up into trees): the canopy search covers the whole
crop and the sky colour is taken from the open patches between branches. Only for such photos: on an overcast day
a white wall or fence would pass for sky.
"""
import argparse
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc
import pngio
from imgops import box, components, downscale, gauss, load, maxf, minf, percentile, polygon_mask, save_gray, save_rgb
from skin_masks import local_plane


def cli_run(args):
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: photocraft-cli not found; `pc.py cli-info` names the one to install")
    r = subprocess.run([str(cli), "run"] + args, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"error: photocraft-cli run failed: {r.stderr[-400:]}")
    return [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]


def prepare(a, out, extra=0):
    """crop.png (photo) and coarse.png (select.sky as a grey mask) from the top of the photo to below the skyline."""
    sky_cmd = ["--cmd", "select.sky", "--params", json.dumps({"threshold": a.threshold, "softness": a.softness})]
    # the selection as a grey image: keep it in a channel, black fill, the channel as selection, white fill on it
    export = [["select.saveSelection", {"name": "sky"}], ["select.deselect", {}],
              ["layer.newFillLayer.solidColor", {"color": "#000000"}], ["select.loadSelection", {"channel": "sky"}],
              ["layer.newFillLayer.solidColor", {"color": "#ffffff"}]]
    info = cli_run([a.photo, "--cmd", "document.inspect", "--cmd", "edit.profileInfo", "--params", '{"profile": "document"}'])
    W, H = info[0]["result"]["width"], info[0]["result"]["height"]
    profile = (info[1]["result"].get("profile") or {}).get("description")
    if a.coarse:  # a mask made elsewhere (painted, or from another tool) instead of select.sky
        cw, chh, CM = pngio.read(a.coarse)
        if (cw, chh) != (W, H):
            sys.exit(f"error: --coarse is {cw}x{chh}, the photo {W}x{H}")
        rows = [y for y in range(chh) if any(p[0] > 127 for p in CM[y])]
        if not rows:
            sys.exit("error: --coarse mask is empty")
        sky = {"bounds": [0, rows[0], W, rows[-1] - rows[0] + 1], "selected": True, "coverage": None}
    else:
        sky = cli_run([a.photo] + sky_cmd)[0]["result"]
        if not sky.get("selected"):
            sys.exit("error: select.sky found no sky; draw it with area.json {\"sky\": [...]} instead")
    band = max(8, round(a.band * W))
    bottom = sky["bounds"][1] + sky["bounds"][3]
    if a.area:
        cfg = json.load(open(a.area))
        for poly in cfg.get("sky", []):
            bottom = max(bottom, max(p[1] for p in poly))
    H2 = min(H, bottom + 2 * band + round(0.1 * H) + extra)  # select.sky often stops short of the pale sky at the horizon
    H2 -= H2 % 2
    crop = ["--cmd", "image.crop", "--params", json.dumps({"x": 0, "y": 0, "width": W, "height": H2})]
    cli_run([a.photo] + crop + ["--out", os.path.join(out, "crop.png")])
    if a.coarse:
        cli_run([a.coarse] + crop + ["--out", os.path.join(out, "coarse.png")])
    else:
        steps = sky_cmd[:]
        for c, p in export:
            steps += ["--cmd", c, "--params", json.dumps(p)]
        cli_run([a.photo] + steps + crop + ["--out", os.path.join(out, "coarse.png")])
    return {"photo": os.path.abspath(a.photo), "width": W, "height": H, "crop": [0, 0, W, H2], "profile": profile,
            "skyBounds": sky["bounds"], "coverage": sky.get("coverage")}


def expand(f, ww, wh, k, w, h):
    """Nearest-neighbour upsample of a work-resolution field (downscaled by k) to w x h."""
    xs = [min(x // k, ww - 1) for x in range(w)]
    out = []
    for y in range(h):
        base = min(y // k, wh - 1) * ww
        out.extend([f[base + x] for x in xs])
    return out


def grow_sparse(mask, w, h, r):
    """Dilate a sparse 0/1 mask by a (2r+1) square, touching only the neighbourhoods of its set pixels."""
    out = list(mask)
    for i in [i for i, v in enumerate(mask) if v]:
        x, y = i % w, i // w
        for yy in range(max(0, y - r), min(h, y + r + 1)):
            base = yy * w
            for xx in range(max(0, x - r), min(w, x + r + 1)):
                out[base + xx] = 1.0
    return out


def bilinear(f, ww, wh, k, w, idx):
    """Bilinear samples of a work-resolution field at the given full-resolution pixel indices."""
    out = []
    for i in idx:
        x, y = (i % w + 0.5) / k - 0.5, (i // w + 0.5) / k - 0.5
        x = 0.0 if x < 0 else ww - 1.0 if x > ww - 1 else x
        y = 0.0 if y < 0 else wh - 1.0 if y > wh - 1 else y
        x0, y0 = int(x), int(y)
        x1, y1 = min(x0 + 1, ww - 1), min(y0 + 1, wh - 1)
        tx, ty = x - x0, y - y0
        a, b = f[y0 * ww + x0], f[y0 * ww + x1]
        c, d = f[y1 * ww + x0], f[y1 * ww + x1]
        out.append((a + (b - a) * tx) * (1 - ty) + (c + (d - c) * tx) * ty)
    return out


def solve(a, out, meta):
    """The matte for one crop; returns the stats (mask.json) and whether sky reaches the crop's bottom row."""
    meta_path = os.path.join(out, "mask.json")
    ox, oy = meta["crop"][0], meta["crop"][1]

    w, h, R, G, B = load(os.path.join(out, "crop.png"))
    _, _, M0, _, _ = load(os.path.join(out, "coarse.png"))
    N = w * h
    M0 = [v / 255 for v in M0]
    keep = [0.0] * N
    if a.area:
        cfg = json.load(open(a.area))
        if cfg.get("sky"):
            add = polygon_mask(cfg["sky"], ox, oy, w, h)
            M0 = [max(m, s) for m, s in zip(M0, add)]
        kp = cfg.get("keep", []) + cfg.get("exclude", [])
        if kp:
            keep = polygon_mask(kp, ox, oy, w, h)
            M0 = [m * (1 - k) for m, k in zip(M0, keep)]

    # ---- work resolution: trimap and the clean-sky colour field
    k = max(1, math.ceil(max(w, h) / 960))
    Rw, ww, wh = downscale(R, w, h, k); Gw = downscale(G, w, h, k)[0]; Bw = downscale(B, w, h, k)[0]
    Mw = downscale(M0, w, h, k)[0]
    NW = ww * wh
    keep_w = downscale(keep, w, h, k)[0]
    band_w = max(2, round(a.band * meta["width"] / k))
    skyb = [1.0 if v > 0.5 else 0.0 for v in Mw]
    sky_def = minf(skyb, ww, wh, band_w)
    fg_def = minf([1 - v for v in skyb], ww, wh, band_w)
    if sum(sky_def) < 50:
        sys.exit("error: almost no definite sky left after the band; lower --band or add area.json sky polygons")
    sig = max(6.0, a.sky_scale * band_w)

    def sky_field(sky_def):
        """Clean-sky colour at every work pixel: a robust local plane fit of the definite sky (clouds, the sun,
        birds and wires don't pull it), blended far from any sky to a broad average of it, and where even that has
        no support, to the sky just above the skyline. It's smooth, so it's fitted at half the work resolution.
        Returns (field, distance of each work pixel to it, sky noise)."""
        kf = 2 if min(ww, wh) >= 160 else 1
        Rf, fw, fh = downscale(Rw, ww, wh, kf); Gf = downscale(Gw, ww, wh, kf)[0]; Bf = downscale(Bw, ww, wh, kf)[0]
        sdf = [1.0 if v > 0.99 else 0.0 for v in downscale(sky_def, ww, wh, kf)[0]]
        sg = sig / kf
        wt = sdf[:]
        for it in range(2):
            Sn = local_plane([Rf, Gf, Bf], wt, fw, fh, sg)
            ef = [math.sqrt((r - s0) ** 2 + (g - s1) ** 2 + (b - s2) ** 2)
                  for r, g, b, s0, s1, s2 in zip(Rf, Gf, Bf, Sn[0], Sn[1], Sn[2])]
            vals = sorted(v for v, m in zip(ef, sdf) if m > 0.5)
            c = 2.5 * max(1.0, vals[len(vals) // 2] * 1.4826)
            wt = [m / (1 + (v / c) ** 2) for m, v in zip(sdf, ef)]
        m0 = gauss(wt, fw, fh, sg)
        m4 = gauss(wt, fw, fh, 4 * sg)
        low = [r for r in range(fh) if any(sdf[r * fw:(r + 1) * fw])]
        rows = low[-max(1, len(low) // 10):]
        ref = [percentile([ch[r * fw + x] for r in rows for x in range(fw) if sdf[r * fw + x]], 50) for ch in (Rf, Gf, Bf)]
        Sw = []
        for ch, sn, r0 in zip((Rf, Gf, Bf), Sn, ref):
            avg = gauss([v * q for v, q in zip(ch, wt)], fw, fh, 4 * sg)
            col = []
            for i in range(fw * fh):
                far = avg[i] / m4[i] if m4[i] > 1e-3 else r0
                t = min(1.0, m0[i] / 0.15)
                col.append(t * sn[i] + (1 - t) * far)
            Sw.append(bilinear(col, fw, fh, kf, ww, range(NW)))
        e = [math.sqrt((r - s0) ** 2 + (g - s1) ** 2 + (b - s2) ** 2) for r, g, b, s0, s1, s2 in zip(Rw, Gw, Bw, *Sw)]
        ev = sorted(v for v, m in zip(e, sky_def) if m > 0.5)
        return Sw, e, ev[len(ev) // 2] * 1.4826

    Sw, e, sky_noise = sky_field(sky_def)
    Lw = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(Rw, Gw, Bw)]
    var = box([v * v for v in Lw], ww, wh, 2); mean = box(Lw, ww, wh, 2)
    tex = [math.sqrt(max(0.0, v - m * m)) for v, m in zip(var, mean)]
    t_tex = 4 * sky_noise / 3 + 3
    Ls = gauss(Lw, ww, wh, 1.5)  # on raw pixels the gradient is mostly noise and breaks the sky into specks
    if a.trees:
        # Looking up through branches select.sky finds little, and its sky can be another colour than the sky
        # behind the trees. The open patches between branches are the brightest smooth pixels around: refit the
        # sky field on them.
        top = maxf(Ls, ww, wh, 12)
        patch = [1.0 if (Ls[i] >= top[i] - max(2 * sky_noise, 4) and tex[i] < t_tex and keep_w[i] < 0.5) else 0.0
                 for i in range(NW)]
        patch = minf(patch, ww, wh, 1)
        sky_def = [max(p, s_) for p, s_ in zip(patch, sky_def)]
        Sw, e, sky_noise = sky_field(sky_def)

    SLf = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(*Sw)]

    def sky_hue(i, slack=1.0):
        """Sky-like by hue and not too dark: vignetting darkens a corner's sky by tens of levels, and an overcast
        sky darkens toward the horizon, but the hue stays."""
        dc = math.sqrt((Rw[i] - Lw[i] - Sw[0][i] + SLf[i]) ** 2 + (Gw[i] - Lw[i] - Sw[1][i] + SLf[i]) ** 2
                       + (Bw[i] - Lw[i] - Sw[2][i] + SLf[i]) ** 2)
        return dc < slack * max(3 * sky_noise, 10) and Lw[i] > 0.5 * SLf[i]

    # sky select.sky missed (a corner, a band beside a tower): smooth, sky-coloured pixels reachable from the
    # definite sky without crossing an edge. A wall or roof against the sky has an edge, so the growth stops there.
    grad = [0.0] * NW
    for y in range(1, wh - 1):
        for x in range(1, ww - 1):
            i = y * ww + x
            grad[i] = math.hypot(Ls[i + 1] - Ls[i - 1], Ls[i + ww] - Ls[i - ww]) / 2
    # above the soft gradients of the clouds themselves; a roof, a tree or a far hill against the sky is a far steeper step
    g_thr = max(3.0, 1.5 * percentile([grad[i] for i in range(NW) if sky_def[i] > 0.5][::3], 95))
    # Continuity (no edge on the way) is the real test. Above the lowest known sky in its column, where foreground
    # rarely is, any smooth pixel may join (a corner darkened by vignetting is far off the sky colour extrapolated
    # from elsewhere). Below it, smooth pixels of the sky's hue: a clear sky pales toward the horizon and an
    # overcast one darkens (CIE overcast sky: a third of the zenith's luminance at the horizon), so brightness
    # can't be the test, while a roof, a tree or a far hill meets the sky with an edge that stops the growth.
    y_low = [-1] * ww
    for i, sb in enumerate(skyb):
        if sb > 0.5:
            y_low[i % ww] = max(y_low[i % ww], i // ww)
    cand = [1 if (sb < 0.5 and keep_w[i] < 0.5 and tex[i] < t_tex and grad[i] < g_thr
                  and (i // ww < y_low[i % ww] or sky_hue(i, 1.5)))
            else 0 for i, sb in enumerate(skyb)]
    grown = [0] * NW
    stack = [i for i in range(NW) if skyb[i] > 0.5]
    seen = bytearray(1 if skyb[i] > 0.5 else 0 for i in range(NW))
    while stack:
        i = stack.pop()
        x, y = i % ww, i // ww
        for j in ((i - 1) if x > 0 else -1, (i + 1) if x < ww - 1 else -1, i - ww, i + ww):
            if 0 <= j < NW and not seen[j]:
                seen[j] = 1
                if cand[j]:
                    grown[j] = 1
                    stack.append(j)
    n_grown = sum(grown) * k * k
    if n_grown:
        skyb = [max(sb, float(g_)) for sb, g_ in zip(skyb, grown)]
        sky_def = minf(skyb, ww, wh, band_w)
        if a.trees:
            sky_def = [max(p, s_) for p, s_ in zip(patch, sky_def)]
        fg_def = minf([1 - v for v in skyb], ww, wh, band_w)
        # the grown sky was checked pixel by pixel (smooth, continuous with the sky), so it may inform the sky
        # field right up to its edges: a narrow strip of darker sky near the horizon would otherwise get the
        # colour of the brighter sky far above it and be taken for foreground
        Sw, e, sky_noise = sky_field([max(s_, g_) for s_, g_ in zip(sky_def, minf([float(v) for v in grown], ww, wh, 2))])
        SLf = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(*Sw)]
    # foreground select.sky took for sky (a tree top), beyond the band: textured and clearly darker than the sky.
    # Smooth dark patches are clouds and stay sky.
    t_hi_w = max(6 * sky_noise, 18.0)
    intr = [1.0 if (sd > 0.5 and SLf[i] - Lw[i] > t_hi_w and tex[i] > 2 * t_tex) else 0.0
            for i, sd in enumerate(sky_def)]
    intr = maxf(intr, ww, wh, max(2, band_w // 2))

    # porous foreground (tree canopies, railings) near the sky: sky-like and darker pixels close together. "Near"
    # is within --canopy of the sky; with --trees it is the whole frame (sky seen through branches, looking up),
    # which is only safe when that's what the photo is: on an overcast day a white wall or fence passes for sky.
    # "Sky-like" two ways: tight (matches the sky field) and loose (sky hue, any brightness above half the sky's).
    # The loose test also passes grey roofs and white window frames on an overcast day, so it only finds holes
    # whose border is foliage, and the canopy itself with --trees.
    tight = [1.0 if v < max(3 * sky_noise, 6) else 0.0 for v in e]
    loose = [1.0 if (t_ > 0.5 or sky_hue(i)) else 0.0 for i, t_ in enumerate(tight)]
    can_r = max(2, round(a.canopy * meta["width"] / k))
    near_sky = [1.0] * NW if a.trees else maxf(skyb, ww, wh, can_r)
    frac = box(loose if a.trees else tight, ww, wh, 2)
    porous = [1.0 if (n > 0.5 and s_ < 0.5 and 0.04 < f < 0.96 and t > t_tex) else 0.0
              for n, s_, f, t in zip(near_sky, skyb, frac, tex)]
    # holes in a canopy: sky-like patches of the coarse foreground whose border is mostly porous foliage (a wall
    # or roof the colour of the sky borders the sky or smooth surfaces instead)
    hole = [1 if (sb < 0.5 and n > 0.5 and kp < 0.5 and sk > 0.5 and p < 0.5) else 0
            for sk, sb, n, kp, p in zip(loose, skyb, near_sky, keep_w, porous)]
    for comp in components(hole, ww, wh):
        cs = set(comp)
        edge_px = por = 0
        for i in comp:
            x, y = i % ww, i // ww
            for j in ((i - 1) if x > 0 else -1, (i + 1) if x < ww - 1 else -1, i - ww, i + ww):
                if 0 <= j < NW and j not in cs:
                    edge_px += 1
                    por += porous[j] > 0.5
        if edge_px and por >= 0.4 * edge_px:
            for i in comp:
                porous[i] = 1.0
    if a.trees:  # every sky-like pixel gets solved; the colour model decides
        porous = [1.0 if (p > 0.5 or (lo > 0.5 and kp < 0.5)) else 0.0 for p, lo, kp in zip(porous, loose, keep_w)]
    porous = maxf(porous, ww, wh, 1)
    # Inside a canopy the sky seen through the holes can be darker than the sky field says (vignetting, a darker
    # cloud behind the tree): take its level from the brightest sky-like pixel nearby, so a hole there is solved
    # against its own sky and comes out fully sky instead of 60 % of it. With --trees the field rests on little
    # sky, so it may be raised as well.
    lmax = maxf([Ls[i] if (porous[i] > 0.5 and sky_hue(i)) else 0.0 for i in range(NW)], ww, wh, 10 if a.trees else 6)
    for i in range(NW):
        if porous[i] > 0.5 and lmax[i] > 0 and (lmax[i] < SLf[i] or a.trees):
            f = lmax[i] / SLf[i]
            for ch in Sw:
                ch[i] *= f
    # big sky-like areas left as foreground: sky seen through trees the canopy search didn't reach
    left = [1 if (skyb[i] < 0.5 and porous[i] < 0.5 and loose[i] > 0.5 and Lw[i] > 0.8 * SLf[i] and keep_w[i] < 0.5)
            else 0 for i in range(NW)]
    big_left = sum(len(c_) for c_ in components(left, ww, wh) if len(c_) > NW // 400)
    unknown_w = [1.0 if (sd < 0.5 and fd < 0.5) or p > 0.5 or q > 0.5 else 0.0
                 for sd, fd, p, q in zip(sky_def, fg_def, porous, intr)]
    sky_def = [0.0 if q > 0.5 else v for v, q in zip(sky_def, intr)]

    # ---- full resolution
    U = [v > 0.5 for v in expand(unknown_w, ww, wh, k, w, h)]
    SD = [v > 0.5 for v in expand(sky_def, ww, wh, k, w, h)]
    FD = [v > 0.5 for v in expand(fg_def, ww, wh, k, w, h)]
    SMOOTH = [v > 0.5 for v in expand([1.0 if (sb > 0.5 and t < t_tex) else 0.0 for sb, t in zip(skyb, tex)], ww, wh, k, w, h)]
    SLw = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(*Sw)]
    SLn = expand(SLw, ww, wh, k, w, h)
    L = [0.3 * r + 0.59 * g + 0.11 * b for r, g, b in zip(R, G, B)]
    # thin dark things inside the sky (antennas, wires, birds, lamp posts): darker than the sky AND than their own
    # surroundings. Broad dark clouds aren't locally darker, bright clouds and the sun are lighter: both stay sky.
    t_hi = max(6 * sky_noise, 18.0)
    Lloc = box(L, w, h, 4)
    thin = [1.0 if SD[i] and SLn[i] - L[i] > t_hi and Lloc[i] - L[i] > t_hi / 2 else 0.0 for i in range(N)]
    thin = grow_sparse(thin, w, h, 2)
    for i in range(N):
        if thin[i]:
            U[i] = True
    alpha = [1.0 if SD[i] else 0.0 for i in range(N)]
    Fd = [list(R), list(G), list(B)]
    lowconf = [0.0] * N
    ys = [i // w for i in range(N) if U[i]]
    if ys:
        # the expensive filters run on the rows that hold unknown pixels (plus a margin) only
        y0, y1 = max(0, min(ys) - 40), min(h, max(ys) + 41)
        lo_i, hi_i = y0 * w, y1 * w
        hb = y1 - y0
        idx = [i for i in range(lo_i, hi_i) if U[i]]
        S0, S1, S2 = (bilinear(f, ww, wh, k, w, idx) for f in Sw)
        Rb, Gb, Bb = R[lo_i:hi_i], G[lo_i:hi_i], B[lo_i:hi_i]
        Lb, SLb, FDb = L[lo_i:hi_i], SLn[lo_i:hi_i], FD[lo_i:hi_i]
        # foreground seeds: the definite foreground, and pixels clearly not sky (far from the sky colour and not
        # lighter than it); F = their local colour, from close by where there are any, else from further away
        Sfull = [(0.0, 0.0, 0.0)] * (hi_i - lo_i)
        for j, i in enumerate(idx):
            Sfull[i - lo_i] = (S0[j], S1[j], S2[j])
        seed = []
        for j in range(hi_i - lo_i):
            if not U[lo_i + j]:  # definite foreground; inside a canopy the coarse "foreground" is part sky
                seed.append(1.0 if FDb[j] else 0.0)
                continue
            s = Sfull[j]
            dd = math.sqrt((Rb[j] - s[0]) ** 2 + (Gb[j] - s[1]) ** 2 + (Bb[j] - s[2]) ** 2)
            seed.append(1.0 if dd > t_hi and Lb[j] < SLb[j] + 2 * sky_noise and not SMOOTH[lo_i + j] else 0.0)
        wn, wf = gauss(seed, w, hb, 3.0), gauss(seed, w, hb, 12.0)
        # On a thin dark thing (a finial, an aerial, a twig) every pixel is part sky, so the plain average of the
        # seeds around is itself too light and its edge keeps a pale outline. Where seeds are sparse, lean on the
        # most foreground-like of them (weighted by their distance from the sky colour, squared); where they are
        # dense (a roof, a wall) keep the plain average, so a pale wall beside a dark window keeps its own colour.
        dS = [0.0] * (hi_i - lo_i)
        for j in range(hi_i - lo_i):
            if seed[j]:
                sv = Sfull[j] if U[lo_i + j] else None
                if sv is None:
                    dS[j] = (SLb[j] - Lb[j]) if SLb[j] > Lb[j] else 1.0
                else:
                    dS[j] = math.sqrt((Rb[j] - sv[0]) ** 2 + (Gb[j] - sv[1]) ** 2 + (Bb[j] - sv[2]) ** 2)
        ws = [q * d_ * d_ for q, d_ in zip(seed, dS)]
        wsn = gauss(ws, w, hb, 3.0)
        F = []
        for ch in (Rb, Gb, Bb):
            v = [q * c for q, c in zip(seed, ch)]
            near, far = gauss(v, w, hb, 3.0), gauss(v, w, hb, 12.0)
            strong = gauss([q * c for q, c in zip(ws, ch)], w, hb, 3.0)
            col = []
            for j in range(hi_i - lo_i):
                if wn[j] > 0.05:
                    avg = near[j] / wn[j]
                    t_ = min(1.0, wn[j] / 0.6)  # seed density: ~1 inside solid foreground, low on thin things
                    col.append(t_ * avg + (1 - t_) * (strong[j] / wsn[j] if wsn[j] > 1e-6 else avg))
                else:
                    col.append(far[j] / wf[j] if wf[j] > 1e-3 else -1.0)
            F.append(col)
        Msoft = gauss(expand(skyb, ww, wh, k, w, h)[lo_i:hi_i], w, hb, 1.5)  # the coarse mask, grown
        clean, lo = a.clean, 1 - a.clean
        for j, i in enumerate(idx):
            b_ = i - lo_i
            f0, f1, f2 = F[0][b_], F[1][b_], F[2][b_]
            s0, s1, s2 = S0[j], S1[j], S2[j]
            if f0 < 0:  # no foreground anywhere near: sky, unless the pixel itself is clearly not sky
                alpha[i] = 0.0 if seed[b_] else 1.0
                continue
            q0, q1, q2 = s0 - f0, s1 - f1, s2 - f2
            n2 = q0 * q0 + q1 * q1 + q2 * q2
            if n2 < a.min_contrast ** 2:
                al = Msoft[b_]
                lowconf[i] = 1.0
            else:
                al = ((R[i] - f0) * q0 + (G[i] - f1) * q1 + (B[i] - f2) * q2) / n2
            al = (al - lo) / (clean - lo)
            al = 0.0 if al < 0 else 1.0 if al > 1 else al
            if keep[i] > 0.5:
                al = 0.0
            alpha[i] = al
            if 0 < al < 1:
                # the pixel's foreground part: solve I = al*S + (1-al)*F while the pixel is mostly foreground,
                # trust the local foreground colour as it becomes mostly sky (the solve gets unstable there)
                t = min(1.0, max(0.0, (al - 0.4) / 0.5))
                for c, (I, s, fl) in enumerate(((R[i], s0, f0), (G[i], s1, f1), (B[i], s2, f2))):
                    fs = (I - al * s) / (1 - al)
                    # never lighter than both the pixel and the local foreground: a sky estimate a few levels off
                    # would otherwise make a faint twig a light streak against a darker new sky (darker is fine:
                    # a thin dark thing really is darker than any of its pixels)
                    fs = min(fs, max(I, fl) + 6)
                    fs = 0.0 if fs < 0 else 255.0 if fs > 255 else fs
                    Fd[c][i] = (1 - t) * fs + t * fl
            elif al == 1.0:
                Fd[0][i], Fd[1][i], Fd[2][i] = f0, f1, f2
    # sky islands not connected to the sky are only believable inside a tree canopy or a railing; elsewhere they
    # are light patches of foreground (pale tiles, a window) and go, with any partial alpha away from the sky edge
    POR = expand(porous, ww, wh, k, w, h)
    solid = [1 if alpha[i] > 0.5 else 0 for i in range(N)]
    keepc = [0] * N
    for comp in components(solid, w, h):
        if any(SD[i] or POR[i] > 0.5 for i in comp):
            for i in comp:
                keepc[i] = 1
    def by_kept_sky(i, r=2):
        x, y = i % w, i // w
        return any(keepc[yy * w + xx] for yy in range(max(0, y - r), min(h, y + r + 1))
                   for xx in range(max(0, x - r), min(w, x + r + 1)))
    for i in range(N):
        if U[i] and POR[i] < 0.5 and not keepc[i] and alpha[i] > 0 and (alpha[i] > 0.5 or not by_kept_sky(i)):
            alpha[i] = 0.0
    if a.shift > 0:
        # Shift Edge: the sky takes a pixel or two of the foreground's edge, and the old sky in it goes too. Fine
        # twigs and aerials get thinner by as much.
        alpha = maxf(alpha, w, h, round(a.shift))
    for i in range(N):
        if keep[i] > 0.5:
            alpha[i] = 0.0
    edge = [1.0 if (U[i] and alpha[i] < 1.0) else 0.0 for i in range(N)]
    edge = grow_sparse(edge, w, h, 1)

    save_gray(os.path.join(out, "alpha.png"), w, h, alpha)
    save_gray(os.path.join(out, "edge_mask.png"), w, h, edge)
    save_rgb(os.path.join(out, "edge.png"), w, h, Fd[0], Fd[1], Fd[2])
    # viz: sky tinted blue, contour yellow, low confidence magenta, kept thin objects green
    vz = []
    for i in range(N):
        x, y = i % w, i // w
        al = alpha[i]
        r, g, b = R[i] * (1 - 0.45 * al) + 40 * 0.45 * al, G[i] * (1 - 0.45 * al) + 110 * 0.45 * al, B[i] * (1 - 0.45 * al) + 255 * 0.45 * al
        if lowconf[i] and 0 < al < 1:
            r, g, b = 255, 0, 255
        cross = (al >= 0.5) != ((alpha[i + 1] if x + 1 < w else al) >= 0.5) or (al >= 0.5) != ((alpha[i + w] if y + 1 < h else al) >= 0.5)
        if cross:
            r, g, b = 255, 230, 0
        if thin[i] and al < 0.5:
            r, g, b = 0, 230, 60
        vz.append((r, g, b))
    save_rgb(os.path.join(out, "viz.png"), w, h, [v[0] for v in vz], [v[1] for v in vz], [v[2] for v in vz])

    n_u = sum(U)
    warnings = []
    if big_left > 0.03 * NW and not a.trees:
        warnings.append(f"{100 * big_left / NW:.0f} % of the crop looks like sky but stays foreground: sky through "
                        "branches? Check viz.png; if so rerun with --trees (or add area.json sky polygons)")
    touches = meta["crop"][3] < meta["height"] and sum(1 for v in alpha[(h - 1) * w:] if v > 0.5) > w // 50
    if touches:
        warnings.append("sky reaches the bottom of the crop: the old sky below it stays; check viz.png and the photo")
    stats = {
        "source": meta, "crop": meta["crop"], "center": [ox + w / 2, oy + h / 2],
        "coverage": round(sum(alpha) / N, 4), "coarseCoverage": round(sum(M0) / N, 4),
        "solved": n_u, "grownSky": n_grown, "partial": sum(1 for v in alpha if 0 < v < 1),
        "lowConfidence": int(sum(lowconf)), "thinKept": int(sum(1 for i in range(N) if thin[i] and alpha[i] < 0.5)),
        "skyNoise": round(sky_noise, 2), "work": [ww, wh, k], "band": band_w * k,
        "params": {k2: getattr(a, k2) for k2 in ("threshold", "softness", "band", "canopy", "clean", "min_contrast", "trees", "shift")},
        "warnings": warnings,
    }
    json.dump(stats, open(meta_path, "w"), indent=1)
    return stats, touches


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("photo"); ap.add_argument("outdir")
    ap.add_argument("--threshold", type=float, default=50, help="select.sky threshold (higher = stricter)")
    ap.add_argument("--softness", type=float, default=50, help="select.sky edge softness")
    ap.add_argument("--area", help="area.json with sky / keep polygons (full-image coords)")
    ap.add_argument("--coarse", help="a grey sky mask the size of the photo to start from, instead of select.sky")
    ap.add_argument("--band", type=float, default=0.015, help="half-width of the refined border, x image width: "
                    "covers how far select.sky's edge can be off (rounded chimneys, cut roofs)")
    ap.add_argument("--canopy", type=float, default=0.12, help="x image width: how far into the foreground to look "
                    "for sky showing through trees")
    ap.add_argument("--trees", action="store_true", help="sky seen through branches anywhere in the frame (looking up "
                    "into trees, a forest skyline): search the whole crop for canopy, not only near select.sky's region")
    ap.add_argument("--clean", type=float, default=0.9, help="alpha above this counts as all sky, below 1 - this "
                    "(scaled) as all foreground: removes faint old-cloud ghosts and speckle")
    ap.add_argument("--min-contrast", type=float, default=14, help="RGB distance between sky and foreground colour "
                    "below which the colour model can't tell them apart; there the coarse mask decides")
    ap.add_argument("--sky-scale", type=float, default=1.5, help="clean-sky fit scale, x the band: smaller follows "
                    "cloud brightness closer to the skyline, larger is steadier")
    ap.add_argument("--shift", type=float, default=0, help="px the sky takes of the foreground's edge (Shift Edge), to "
                    "lose a pale line of old sky along roofs; thin things get thinner by as much")
    ap.add_argument("--reuse", action="store_true", help="keep crop.png/coarse.png from an earlier run")
    a = ap.parse_args()
    out = os.path.abspath(os.path.expanduser(a.outdir))
    os.makedirs(out, exist_ok=True)
    meta_path = os.path.join(out, "mask.json")
    if a.reuse and os.path.exists(meta_path) and os.path.exists(os.path.join(out, "coarse.png")):
        meta = json.load(open(meta_path))["source"]
    else:
        meta = prepare(a, out)
    for attempt in range(3):
        stats, touches = solve(a, out, meta)
        if not touches or meta["crop"][3] >= meta["height"]:
            break
        # sky runs on below the crop: the old sky there would stay under a hard seam. Take more and solve again.
        meta = prepare(a, out, extra=round(0.15 * meta["height"]) * (attempt + 1))
    print(json.dumps({k2: v for k2, v in stats.items() if k2 != "source"}))


if __name__ == "__main__":
    main()
