#!/usr/bin/env python3
"""Check a cutout the way a clipping-path studio does: on white, black and a saturated colour, edge by edge.

A cutout fails in a few typical ways, and each one leaves a measurable trace at the edge:
  fringe      edge pixels still carry the old backdrop's colour, so on a new background they show as a light or
              dark outline (a white rim around a dark product put on black, a green glow in hair from a green wall)
  too wide    the mask runs past the edge: a line of backdrop at full opacity ("backdrop inside")
  too tight   the mask cuts into the subject: pixels just outside it still look like the subject ("cut into")
  edge type   a feathered product edge reads as blurry, a binary one as jagged; hair needs a soft edge
  leftovers   specks of backdrop or dust kept as islands, backdrop showing through gaps that were never cut out

For every edge pixel the script estimates the subject colour F just inside it and the old backdrop colour B just
outside it (in the original), then composites the cut onto each check background N and measures how far the result
lies from the clean line between F and N, in levels. That is the visible fringe: zero when the edge is clean, or
when N happens to look like the old backdrop (contamination is invisible there), large on a contrasting N.

usage: cutout_check.py cut.png orig.png outdir [--origin X Y] [--bg #ffffff] [--kind product|soft] [--spots 6]
       cutout_check.py --deliverable final.jpg outdir [--min-side 1600] [--fill 0.85]

cut.png   the cut subject as RGBA, the same frame as orig.png: hide every layer but the masked one and export a PNG
orig.png  the original (backdrop visible), same size; both may be crops, --origin is their place in the photo
outdir    sheet.png (the cutout on white, black, grey and a saturated colour, plus 3x zooms of the worst spots on
          black | white, numbered like "spots" in the stats), edges.png (edge map: red = fringe, blue = cut into)
--deliverable checks a finished flat image for a marketplace: exact-white background share and where it isn't,
          size, product fill and centring, and the embedded colour profile.
"""
import argparse
import json
import math
import os
import struct
import subprocess
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pngio
from imgops import FONT


# ---------------------------------------------------------------- helpers shared with product_shot.py

def sat(vals, w, h):
    """Summed-area table with a zero row and column, for O(1) window sums."""
    W = w + 1
    S = [0.0] * (W * (h + 1))
    for y in range(h):
        acc, row, base, prev = 0.0, y * w, (y + 1) * W, y * W
        for x in range(w):
            acc += vals[row + x]
            S[base + x + 1] = S[prev + x + 1] + acc
    return S


def win(S, w, h, x, y, r):
    """Sum over the (2r+1) square around (x, y), clipped to the image."""
    x0, y0, x1, y1 = max(0, x - r), max(0, y - r), min(w, x + r + 1), min(h, y + r + 1)
    W = w + 1
    return S[y1 * W + x1] - S[y0 * W + x1] - S[y1 * W + x0] + S[y0 * W + x0]


def rect(S, w, h, x0, y0, x1, y1):
    """Sum over x0 <= x < x1, y0 <= y < y1, clipped to the image."""
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    W = w + 1
    return S[y1 * W + x1] - S[y0 * W + x1] - S[y1 * W + x0] + S[y0 * W + x0]


def bbox(mask, w, h):
    """[x0, y0, x1, y1] (inclusive) of the truthy pixels, or None."""
    xs = ys = None
    for y in range(h):
        row = mask[y * w:(y + 1) * w]
        if any(row):
            ys = (ys[0], y) if ys else (y, y)
            a = next(i for i, v in enumerate(row) if v); b = w - 1 - next(i for i, v in enumerate(reversed(row)) if v)
            xs = (min(xs[0], a), max(xs[1], b)) if xs else (a, b)
    return None if ys is None else [xs[0], ys[0], xs[1], ys[1]]


def sub(vals, w, x0, y0, x1, y1):
    """The [x0..x1] x [y0..y1] window of a flat image."""
    return [v for y in range(y0, y1 + 1) for v in vals[y * w + x0:y * w + x1 + 1]]


def edge_distance(inside, w, h, cap=16):
    """Chessboard distance to the other side of the mask edge, per pixel (1 = touches it), capped."""
    dist = [0] * (w * h)
    frontier = []
    for y in range(h):
        for x in range(w):
            i = y * w + x
            v = inside[i]
            for dy in (-1, 0, 1):
                yy = y + dy
                if 0 <= yy < h:
                    for dx in (-1, 0, 1):
                        xx = x + dx
                        if 0 <= xx < w and inside[yy * w + xx] != v:
                            break
                    else:
                        continue
                    break
            else:
                continue
            dist[i] = 1
            frontier.append(i)
    d = 1
    while frontier and d < cap:
        d += 1
        nxt = []
        for i in frontier:
            x, y, v = i % w, i // w, inside[i]
            for dy in (-1, 0, 1):
                yy = y + dy
                if 0 <= yy < h:
                    for dx in (-1, 0, 1):
                        xx = x + dx
                        j = yy * w + xx
                        if 0 <= xx < w and not dist[j] and inside[j] == v:
                            dist[j] = d
                            nxt.append(j)
        frontier = nxt
    return [v if v else cap for v in dist]


def to_png(path, tmpdir):
    """A PNG path for any image: JPEG/TIFF/WebP go through photocraft-cli convert (keeps the pixel values)."""
    if path.lower().endswith(".png"):
        return path
    import pc
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: reading non-PNG files needs photocraft-cli (pc.py cli-info)")
    out = os.path.join(tmpdir, "_" + os.path.splitext(os.path.basename(path))[0] + ".png")
    subprocess.run([str(cli), "convert", path, out], check=True, capture_output=True)
    return out


def icc_description(path):
    """The embedded ICC profile's description (JPEG APP2 or PNG iCCP), '' if none."""
    data = open(path, "rb").read()
    prof = b""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        pos = 8
        while pos < len(data):
            ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
            if typ == b"iCCP":
                chunk = data[pos + 8:pos + 8 + ln]
                prof = zlib.decompress(chunk[chunk.index(b"\0") + 2:])
                break
            pos += 12 + ln
    elif data[:2] == b"\xff\xd8":
        pos, parts = 2, {}
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker, ln = data[pos + 1], struct.unpack(">H", data[pos + 2:pos + 4])[0]
            seg = data[pos + 4:pos + 2 + ln]
            if marker == 0xE2 and seg[:12] == b"ICC_PROFILE\0":
                parts[seg[12]] = seg[14:]
            if marker == 0xDA:
                break
            pos += 2 + ln
        prof = b"".join(parts[k] for k in sorted(parts))
    if len(prof) < 132:
        return ""
    n = struct.unpack(">I", prof[128:132])[0]
    for k in range(n):
        sig, off, size = struct.unpack(">4sII", prof[132 + 12 * k:144 + 12 * k])
        if sig != b"desc":
            continue
        t = prof[off:off + size]
        if t[:4] == b"desc":
            m = struct.unpack(">I", t[8:12])[0]
            return t[12:12 + m].split(b"\0")[0].decode("latin-1")
        if t[:4] == b"mluc":
            ln, so = struct.unpack(">II", t[20:28])
            return t[so:so + ln].decode("utf-16-be", "replace")
    return "?"


# ---------------------------------------------------------------- the cutout check

def seg_dist(p, a, b):
    """Distance from point p to the segment a-b in RGB, per channel (/ sqrt 3), and the signed lightness offset."""
    d = [b[k] - a[k] for k in range(3)]
    dd = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
    t = 0.0 if dd < 1e-9 else max(0.0, min(1.0, sum((p[k] - a[k]) * d[k] for k in range(3)) / dd))
    q = [a[k] + t * d[k] for k in range(3)]
    e = [p[k] - q[k] for k in range(3)]
    return math.sqrt(e[0] * e[0] + e[1] * e[1] + e[2] * e[2]) / math.sqrt(3), imgops.lum(*e)


def check_colours(subject, backdrop):
    """White, black, mid grey, and the saturated colour farthest from both the subject and the old backdrop."""
    sats = [(255, 0, 255), (0, 200, 0), (0, 90, 255), (255, 60, 0)]
    far = max(sats, key=lambda c: min(sum((c[k] - subject[k]) ** 2 for k in range(3)),
                                      sum((c[k] - backdrop[k]) ** 2 for k in range(3))))
    return {"white": (255, 255, 255), "black": (0, 0, 0), "grey": (128, 128, 128), "colour": far}


def check_cut(a):
    w, h, R, G, B, A = imgops.load_rgba(a.cut)
    w2, h2, OR, OG, OB = imgops.load(a.orig)
    if (w, h) != (w2, h2):
        sys.exit(f"error: cut is {w}x{h} but orig is {w2}x{h2}; export both from the same frame")
    inside0 = [1 if v >= 0.5 else 0 for v in A]
    bb = bbox(inside0, w, h)
    if not bb:
        sys.exit("error: the cut is empty (no pixel with alpha >= 0.5)")
    m = 24  # work on the subject's box plus a margin
    x0, y0, x1, y1 = max(0, bb[0] - m), max(0, bb[1] - m), min(w - 1, bb[2] + m), min(h - 1, bb[3] + m)
    ox, oy = a.origin[0] + x0, a.origin[1] + y0
    R, G, B, A, OR, OG, OB = (sub(c, w, x0, y0, x1, y1) for c in (R, G, B, A, OR, OG, OB))
    W, H = x1 - x0 + 1, y1 - y0 + 1
    N = W * H
    inside = [1 if v >= 0.5 else 0 for v in A]
    dist = edge_distance(inside, W, H)
    partial = [1.0 if 0.02 < v < 0.98 else 0.0 for v in A]

    # edge type: partial pixels across the edge at each perimeter pixel; oblique edges with none are jagged
    Sp, Si = sat(partial, W, H), sat([float(v) for v in inside], W, H)
    perim = [i for i in range(N) if inside[i] and dist[i] == 1]
    widths, jag, oblique = [], 0, 0
    for i in perim:
        x, y = i % W, i // W
        widths.append(win(Sp, W, H, x, y, 3) / 7)
        xa, xb, ya, yb = max(0, x - 2), min(W, x + 3), max(0, y - 2), min(H, y + 3)
        rows = sum(1 for yy in range(ya, yb) if 0 < rect(Si, W, H, xa, yy, xb, yy + 1) < xb - xa)
        cols = sum(1 for xx in range(xa, xb) if 0 < rect(Si, W, H, xx, ya, xx + 1, yb) < yb - ya)
        if rows > 1 and cols > 1:  # an oblique or curved stretch, where a binary edge shows as steps
            oblique += 1
            if win(Sp, W, H, x, y, 2) == 0:
                jag += 1
    widths.sort()
    pw = lambda q: round(widths[min(len(widths) - 1, int(q * len(widths)))], 2) if widths else 0

    # local subject colour F (well inside, cut's colours) and old backdrop B (well outside, original's colours)
    core = [1.0 if A[i] >= 0.98 and inside[i] and dist[i] >= 3 else 0.0 for i in range(N)]
    far = [1.0 if A[i] <= 0.02 and not inside[i] and dist[i] >= 3 else 0.0 for i in range(N)]
    Sc = [sat(core, W, H)] + [sat([c[i] * core[i] for i in range(N)], W, H) for c in (R, G, B)]
    Sf = [sat(far, W, H)] + [sat([c[i] * far[i] for i in range(N)], W, H) for c in (OR, OG, OB)]

    def mean_at(S, x, y, radii):
        for r in radii:
            n = win(S[0], W, H, x, y, r)
            if n >= 4:
                return tuple(win(S[k], W, H, x, y, r) / n for k in (1, 2, 3))
        return None

    n_core, n_far = sum(core), sum(far)
    subj = tuple(sum(c[i] * core[i] for i in range(N)) / max(1, n_core) for c in (R, G, B))
    back = tuple(sum(c[i] * far[i] for i in range(N)) / max(1, n_far) for c in (OR, OG, OB))
    bgs = check_colours(subj, back)
    target = tuple(int(a.bg[k:k + 2], 16) for k in (1, 3, 5))
    bgs["deliverable"] = target

    band = [i for i in range(N) if A[i] > 0.02 and (partial[i] or (inside[i] and dist[i] <= 3))]
    # The subject colour behind each edge pixel. Partial pixels: solve the matting equation I = aF + (1-a)B for F
    # with the cut's own alpha (right for hair strands whose colour differs from the body), unless that F looks like
    # the backdrop, which is what a too-wide mask produces; then the nearby opaque subject colour is the reference.
    bks, refs, fhat = {}, {}, {}
    for i in band:
        x, y = i % W, i // W
        Bk = mean_at(Sf, x, y, (8, 16, 24))
        if Bk is None:
            continue
        bks[i] = Bk
        ref = mean_at(Sc, x, y, (4, 8, 12, 18))  # opaque subject at least 3 px in: never the (maybe dirty) rim itself
        if ref is not None:
            refs[i] = ref
        al = A[i]
        if 0.25 <= al < 0.98:
            f = tuple(min(255.0, max(0.0, ((OR, OG, OB)[k][i] - (1 - al) * Bk[k]) / al)) for k in range(3))
            far_enough = math.dist(f, Bk) >= (0.5 * math.dist(ref, Bk) if ref else a.min_contrast * math.sqrt(3))
            if far_enough:
                fhat[i] = f
    fr = {k: [] for k in bgs}
    sign = {k: 0.0 for k in bgs}
    vmax = [0.0] * N
    too_wide = too_wide_n = cut_into = cut_into_n = skipped = 0
    for i in band:
        Bk = bks.get(i)
        ref = refs.get(i)
        x, y = i % W, i // W
        al, C = A[i], (R[i], G[i], B[i])
        if al >= 0.98:
            if ref is None or math.dist(ref, Bk) / math.sqrt(3) < a.min_contrast:
                skipped += 1
                continue
            # opaque: only the part of its colour that leans toward the backdrop counts (texture doesn't)
            d = [Bk[j] - ref[j] for j in range(3)]
            t = sum((C[j] - ref[j]) * d[j] for j in range(3)) / sum(v * v for v in d)
            Fs, C = ref, tuple(ref[j] + max(0.0, t) * d[j] for j in range(3))
            if inside[i] and dist[i] <= 2:  # a full-opacity edge pixel that is really backdrop
                too_wide_n += 1
                too_wide += t > 0.5
        else:
            Fs = fhat.get(i)
            if Fs is None:  # faint pixel: the strand's colour from its stronger neighbours, else the opaque subject
                near = [fhat[j] for j in (yy * W + xx for yy in range(max(0, y - 2), min(H, y + 3))
                                          for xx in range(max(0, x - 2), min(W, x + 3))) if j in fhat]
                Fs = tuple(sum(f[k] for f in near) / len(near) for k in range(3)) if near else ref
            if Fs is None or Bk is None or math.dist(Fs, Bk) / math.sqrt(3) < a.min_contrast:
                skipped += 1
                continue
        worst = 0.0
        for k, Nc in bgs.items():
            act = tuple(al * C[j] + (1 - al) * Nc[j] for j in range(3))
            v, s = seg_dist(act, Fs, Nc)
            fr[k].append(v)
            sign[k] += s
            if k in ("white", "black", "colour", "deliverable"):
                worst = max(worst, v)
        vmax[i] = worst
    # just outside the mask: still looks like the subject in the original -> the cut went into it
    edge_out = [i for i in range(N) if not inside[i] and A[i] <= 0.02 and dist[i] == 1]
    marks = [0] * N
    for i in edge_out:
        x, y = i % W, i // W
        F = mean_at(Sc, x, y, (4, 8, 12, 18)); Bk = mean_at(Sf, x, y, (8, 16, 24))
        if F is None or Bk is None or math.dist(F, Bk) / math.sqrt(3) < a.min_contrast:
            continue
        d = [Bk[j] - F[j] for j in range(3)]
        t = sum(((OR[i], OG[i], OB[i])[j] - F[j]) * d[j] for j in range(3)) / sum(v * v for v in d)
        cut_into_n += 1
        if t < 0.35:
            cut_into += 1
            marks[i] = 1

    def summ(v):
        if not v:
            return None
        s = sorted(v)
        return {"mean": round(sum(s) / len(s), 2), "p95": round(s[int(0.95 * (len(s) - 1))], 1),
                "over8": round(sum(1 for x in s if x > 8) / len(s), 3)}

    # islands and holes
    comps = imgops.components(inside, W, H)
    comps.sort(key=len, reverse=True)
    islands = [c for c in comps[1:] if len(c) >= 2]
    outside = [1 - v for v in inside]
    holes = []
    for c in imgops.components(outside, W, H):
        xs = [i % W for i in c]; ys = [i // W for i in c]
        if min(xs) > 0 and min(ys) > 0 and max(xs) < W - 1 and max(ys) < H - 1 and len(c) >= 30:
            holes.append([min(xs) + ox, min(ys) + oy, max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(c)])
    haze = sum(1 for i in range(N) if 0.02 < A[i] < 0.5 and dist[i] >= 6) / max(1, len(perim))

    # worst spots: smoothed worst-background fringe, local maxima 40 px apart
    Sv, Sb = sat(vmax, W, H), sat([1.0 if vmax[i] > 0 else 0.0 for i in range(N)], W, H)
    cand = []
    for i in band:
        if vmax[i] > 0:
            x, y = i % W, i // W
            nb = win(Sb, W, H, x, y, 4)
            cand.append((win(Sv, W, H, x, y, 4) / nb if nb else 0, x, y))
    cand.sort(reverse=True)
    spots = []
    for v, x, y in cand:
        if v < 3 or len(spots) >= a.spots:
            break
        if all((x - sx) ** 2 + (y - sy) ** 2 > 1600 for _, sx, sy in spots):
            spots.append((v, x, y))

    os.makedirs(a.outdir, exist_ok=True)
    render_sheet(a, W, H, R, G, B, A, bgs, spots)
    edges = []
    for y in range(H):
        row = []
        for x in range(W):
            i = y * W + x
            g = int(128 * (1 - A[i]) + (0.3 * R[i] + 0.59 * G[i] + 0.11 * B[i]) * A[i] * 0.5 + 64 * A[i])
            if marks[i]:
                row.append((40, 80, 255))
            elif vmax[i] > 0:
                k = min(1.0, vmax[i] / 16)
                row.append((int(g * (1 - k) + 255 * k), int(g * (1 - k)), int(g * (1 - k))))
            else:
                row.append((g, g, g))
        edges.append(row)
    pngio.write(os.path.join(a.outdir, "edges.png"), W, H, edges)

    big = [c for c in islands if len(c) >= 0.02 * len(comps[0])]
    fd, fb = summ(fr["deliverable"]) or {}, summ(fr["black"]) or {}
    soft_share = sum(1 for v in widths if v > 2.5) / max(1, len(widths))
    advice = []
    if big:
        advice.append(f"the subject is in {len(big) + 1} large separate parts: the selection missed what joins them; add it "
                      "(select.lasso/select.object mode add) or select the backdrop instead (select.magicWand + select.inverse)")
    if too_wide / max(1, too_wide_n) > 0.03:
        advice.append("the mask runs past the edge (backdrop at full opacity): select.refineEdge shiftEdge -15 moves it one pixel in; recheck cutInto")
    if cut_into / max(1, cut_into_n) > (0.2 if a.kind == "soft" else 0.08):
        advice.append("the mask cuts into the subject: shiftEdge +15, or reselect that part")
    if a.kind == "product" and soft_share > 0.3:
        advice.append("the edge is soft for a hard product: select.refineEdge radius 1, contrast 25")
    if a.kind == "soft" and pw(0.5) < 2:
        advice.append("a hard edge on hair or fur: select.refineEdge radius 6-10 with smartRadius")
    if jag / max(1, oblique) > 0.15:
        advice.append("binary (jagged) edge: select.refineEdge radius 1 gives it one pixel of anti-aliasing")
    if fd.get("p95", 0) > 6:
        advice.append(f"visible fringe on {a.bg}: decontaminate (select.refineEdge decontaminate) or "
                      "layer.matting.removeWhiteMatte / removeBlackMatte on an applied copy; look at the numbered spots")
    elif fb.get("p95", 0) > 15:
        advice.append("fringe shows on dark backgrounds only (old light backdrop or a glossy rim reflecting it): fine on "
                      "white; decontaminate if the cutout will also go on dark")
    if islands and not big:
        advice.append(f"{len(islands)} stray island(s), {sum(len(c) for c in islands)} px: delete them on the mask unless they are hair strands")
    if holes:
        advice.append("holes in the subject: keep real gaps (handles, between legs), add back mistaken ones")
    if haze > (0.25 if a.kind == "soft" else 0.05):  # wisps past the edge are normal in fur
        advice.append("semi-transparent haze away from the edge: backdrop or shadow inside the mask (often under the product)")
    stats = {
        "subject": {"bbox": [bb[0] + a.origin[0], bb[1] + a.origin[1], bb[2] - bb[0] + 1, bb[3] - bb[1] + 1],
                    "colour": [round(v) for v in subj], "oldBackdrop": [round(v) for v in back]},
        "edge": {"perimeter": len(perim), "width": {"median": pw(0.5), "p90": pw(0.9)},
                 "soft": round(sum(1 for v in widths if v > 2.5) / max(1, len(widths)), 3),
                 "jagged": round(jag / max(1, oblique), 3)},
        "fringe": {k: summ(v) for k, v in fr.items()},
        "fringeTone": {k: ("light" if sign[k] > 0 else "dark") for k in ("white", "black")},
        "backdropInside": round(too_wide / max(1, too_wide_n), 3),
        "cutInto": round(cut_into / max(1, cut_into_n), 3),
        "islands": {"count": len(islands), "pixels": sum(len(c) for c in islands), "largeParts": len(big)},
        "holes": holes[:8], "haze": round(haze, 3),
        "spots": [[x + ox, y + oy, round(v, 1)] for v, x, y in spots],
        "checkColour": "#%02x%02x%02x" % bgs["colour"], "lowContrastSkipped": round(skipped / max(1, len(band)), 3),
        "advice": advice,
    }
    print(json.dumps(stats))


def render_sheet(a, W, H, R, G, B, A, bgs, spots):
    """2x2 composites (white, black, grey, colour) scaled to ~560 px, then the zoom tiles: black | white per spot."""
    k = max(1, math.ceil(max(W, H) / 560))
    tw, th = W // k, H // k
    gap = 8
    tile, z = 40, a.zoom
    zw = 2 * tile * z + gap
    cols = max(2, (2 * tw + gap) // (zw + gap))
    nrows = math.ceil(len(spots) / cols) if spots else 0
    SW = max(2 * tw + gap, cols * (zw + gap) - gap)
    SH = 2 * th + gap + (nrows * (tile * z + gap) + gap if spots else 0)
    img = [[(255, 255, 255)] * SW for _ in range(SH)]

    def comp(i, Nc):
        al = A[i]
        return (int(R[i] * al + Nc[0] * (1 - al) + .5), int(G[i] * al + Nc[1] * (1 - al) + .5), int(B[i] * al + Nc[2] * (1 - al) + .5))

    for n, key in enumerate(("white", "black", "grey", "colour")):
        px, py, Nc = (n % 2) * (tw + gap), (n // 2) * (th + gap), bgs[key]
        for y in range(th):
            for x in range(tw):
                img[py + y][px + x] = comp(y * k * W + x * k, Nc)
        if key == "white":  # thin frame so the white panel's extent shows
            for x in range(tw):
                img[py][px + x] = img[py + th - 1][px + x] = (200, 200, 200)
            for y in range(th):
                img[py + y][px] = img[py + y][px + tw - 1] = (200, 200, 200)
    for s, (_, sx, sy) in enumerate(spots):
        bx = (s % cols) * (zw + gap)
        by = 2 * th + 2 * gap + (s // cols) * (tile * z + gap)
        for half, Nc in enumerate((bgs["black"], bgs["white"])):
            for y in range(tile * z):
                yy = sy - tile // 2 + y // z
                for x in range(tile * z):
                    xx = sx - tile // 2 + x // z
                    if 0 <= xx < W and 0 <= yy < H:
                        img[by + y][bx + half * (tile * z + gap) + x] = comp(yy * W + xx, Nc)
        for d, ch in enumerate(str(s + 1)):  # spot number, top-left of the black half
            bits = FONT[ch]
            for r in range(5):
                for c in range(3):
                    if bits[r * 3 + c] == "1":
                        for dy in range(3):
                            for dx in range(3):
                                img[by + 4 + r * 3 + dy][bx + 4 + (d * 4 + c) * 3 + dx] = (255, 220, 0)
    pngio.write(os.path.join(a.outdir, "sheet.png"), SW, SH, img)


# ---------------------------------------------------------------- the deliverable check

def check_deliverable(a):
    os.makedirs(a.outdir, exist_ok=True)
    png = to_png(a.deliverable, a.outdir)
    w, h, R, G, B = imgops.load(png)
    N = w * h
    white = [1 if min(R[i], G[i], B[i]) >= 240 else 0 for i in range(N)]
    # background = near-white connected to the border; anything it can't reach is content (product, shadow)
    bg = bytearray(N)
    st = [i for i in list(range(w)) + list(range(N - w, N)) + list(range(0, N, w)) + list(range(w - 1, N, w)) if white[i]]
    for i in st:
        bg[i] = 1
    while st:
        i = st.pop()
        x, y = i % w, i // w
        for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, i - w, i + w):
            if 0 <= j < N and white[j] and not bg[j]:
                bg[j] = 1
                st.append(j)
    pure = [1 if R[i] == 255 and G[i] == 255 and B[i] == 255 else 0 for i in range(N)]
    nbg = sum(bg)
    off = [i for i in range(N) if bg[i] and not pure[i]]
    border = [i for i in set(list(range(w)) + list(range(N - w, N)) + list(range(0, N, w)) + list(range(w - 1, N, w)))]
    content = [0 if bg[i] else 1 for i in range(N)]
    core = [1 if not bg[i] and (min(R[i], G[i], B[i]) < 225 or max(R[i], G[i], B[i]) - min(R[i], G[i], B[i]) > 25) else 0
            for i in range(N)]
    cb, kb = bbox(content, w, h), bbox(core, w, h)

    def fill_of(b):
        if not b:
            return None
        bw, bh = b[2] - b[0] + 1, b[3] - b[1] + 1
        return {"bbox": [b[0], b[1], bw, bh], "fill": round(max(bw / w, bh / h), 3),
                "centreOffset": [round(((b[0] + b[2]) / 2 - (w - 1) / 2) / w, 3), round(((b[1] + b[3]) / 2 - (h - 1) / 2) / h, 3)]}

    # Off-white that runs to the frame's border is an uneven or dirty backdrop (a marketplace's check fails on it).
    # Off-white near the product is its edge's JPEG ringing (within an 8x8 block) or the shadow's soft tail (which
    # JPEG dithers into 254s among 255s), both fine. Anything else is a stray speck (dust, a leftover).
    offset = bytearray(N)
    for i in off:
        offset[i] = 1
    border_set = set(border)
    touching = set(i for i in off if i in border_set)
    st = list(touching)
    while st:
        i = st.pop()
        x, y = i % w, i // w
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                xx, yy = x + dx, y + dy
                j = yy * w + xx
                if 0 <= xx < w and 0 <= yy < h and offset[j] and j not in touching:
                    touching.add(j)
                    st.append(j)
    near = set()
    rest = [i for i in off if i not in touching]
    for _ in range(4):
        grew = False
        for i in rest:
            if i not in near:
                x, y = i % w, i // w
                if any(content[j] or j in near for j in (yy * w + xx for yy in range(max(0, y - 8), min(h, y + 9))
                                                         for xx in range(max(0, x - 8), min(w, x + 9)))):
                    near.add(i)
                    grew = True
        if not grew:
            break
    specks = [i for i in rest if i not in near]
    k = max(1, math.ceil(max(w, h) / 900))
    viz = []
    for y in range(0, h - h % k, k):
        row = []
        for x in range(0, w - w % k, k):
            i = y * w + x
            if bg[i] and not pure[i]:
                row.append((255, 170, 0) if i in near else (255, 0, 200) if i in touching else (0, 160, 255))
            elif bg[i]:
                row.append((255, 255, 255))
            else:
                l = int(0.3 * R[i] + 0.59 * G[i] + 0.11 * B[i])
                row.append((l // 2 + 60, l // 2 + 60, l // 2 + 60))
        viz.append(row)
    pngio.write(os.path.join(a.outdir, "deliverable.png"), len(viz[0]), len(viz), viz)
    prof = icc_description(a.deliverable)
    stats = {
        "size": [w, h], "longest": max(w, h), "sizeOk": max(w, h) >= a.min_side,
        "background": {"pixels": nbg, "pureWhite": round((nbg - len(off)) / max(1, nbg), 4),
                       "offWhite": {"edgeAndShadow": len(near), "touchingBorder": len(touching), "specks": len(specks)},
                       "borderPure": round(sum(pure[i] for i in border) / len(border), 4)},
        "content": fill_of(cb), "product": fill_of(kb),
        "fillOk": bool(kb) and max((kb[2] - kb[0] + 1) / w, (kb[3] - kb[1] + 1) / h) >= a.fill - 0.005,
        "profile": prof or "none (untagged: browsers assume sRGB)",
    }
    print(json.dumps(stats))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+", help="cut.png orig.png outdir, or (with --deliverable FILE) outdir")
    ap.add_argument("--origin", type=int, nargs=2, default=[0, 0], help="where the cut/orig frame sits in the photo")
    ap.add_argument("--bg", default="#ffffff", help="the background the cutout will go on (its fringe is reported as 'deliverable')")
    ap.add_argument("--min-contrast", type=float, default=12, help="levels: edges where subject and old backdrop are closer than this are skipped")
    ap.add_argument("--kind", choices=["product", "soft"], default="product", help="hard-edged product, or hair/fur (soft edges expected)")
    ap.add_argument("--spots", type=int, default=6)
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--deliverable", help="check a finished flat image instead of a cut")
    ap.add_argument("--min-side", type=int, default=1600, help="deliverable: longest side at least (Amazon zoom 1000, eBay 1600)")
    ap.add_argument("--fill", type=float, default=0.85, help="deliverable: product share of the frame's longer side")
    a = ap.parse_args()
    if a.deliverable:
        a.outdir = a.files[0]
        check_deliverable(a)
    else:
        if len(a.files) != 3:
            ap.error("needs cut.png orig.png outdir")
        a.cut, a.orig, a.outdir = a.files
        check_cut(a)


if __name__ == "__main__":
    main()
