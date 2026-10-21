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

usage: cutout_check.py cut.png orig.png outdir [--origin X Y] [--bg #ffffff] [--kind product|soft] [--spots 6] [--edge-fix]
       cutout_check.py --deliverable final.jpg outdir [--preset NAME | --spec spec.json] [--min-side 1600] [--fill 0.85]

cut.png   the cut subject as RGBA, the same frame as orig.png: hide every layer but the masked one and export a PNG
orig.png  the original (backdrop visible), same size; both may be crops, --origin is their place in the photo
outdir    sheet.png (the cutout on white, black, grey and a saturated colour, plus 3x zooms of the worst spots on
          black | white, numbered like "spots" in the stats), edges.png (edge map: red = fringe, blue = cut into)
--edge-fix also writes outdir/edgefix/: the controllable alternative to Decontaminate Colors (which bakes its result
          in and looks overprocessed at full strength). "Edge colour" is a pixel layer of the subject colour estimated
          behind every edge pixel, in Color blend mode, and "Edge tone" the same in Luminosity (only when subject and
          old backdrop differ in brightness: a dark product shot on white), both clipped to the cut layer and masked to
          its semi-transparent edge pixels, so each can be dialled down, painted out or switched off. Import with the Background
          visible: import_layers.py outdir/edgefix/layers.json --above <cut layer id>; cut_fixed.png is the fixed cut.
--deliverable checks a finished flat image: background (exactly the spec's colour where the spec demands it, and where
          it isn't), size and exact aspect, product fill (inside the spec's range) and centring or baseline, file type,
          bytes and megapixels, and the embedded colour profile. --preset/--spec (specs.py; product_shot.py writes the
          spec.json it placed the product by) decide what passes; "pass" is false when any hard check fails.
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
import specs
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


def copy_colour_chunks(src, dst):
    """Copy PNG src's colour-space chunks (iCCP, or sRGB / gAMA / cHRM) into PNG dst, right after its IHDR, so a PNG
    written from src's pixels says what colours they are: PhotoCraft's exports carry the document's profile (an Adobe
    RGB photo's cut.png does), the planners' PNGs carry none, and a tool reading the file (composite.py) would take it
    for sRGB. The chunks go over byte for byte, CRCs included. Returns the profile's description, or None."""
    def chunks(data):
        pos = 8
        while pos + 8 <= len(data):
            ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
            yield typ, data[pos:pos + 12 + ln]
            pos += 12 + ln
    try:
        s = open(src, "rb").read()
    except OSError:
        return None
    if s[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    keep = [c for t, c in chunks(s) if t in (b"iCCP", b"sRGB", b"gAMA", b"cHRM")]
    if not keep:
        return None
    d = open(dst, "rb").read()
    end = 8 + 12 + struct.unpack(">I", d[8:12])[0]  # IHDR is always the first chunk
    open(dst, "wb").write(d[:end] + b"".join(keep) + d[end:])
    return icc_description(dst) or "sRGB"


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


def exif_info(path):
    """What a JPEG's (APP1) or PNG's (eXIf) EXIF gives away: the camera, its settings, a GPS position, a thumbnail of
    the unretouched original. {} when it has none. `pc.py cli convert` carries the master's EXIF into the file."""
    data = open(path, "rb").read()
    tiff = None
    if data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker, ln = data[pos + 1], struct.unpack(">H", data[pos + 2:pos + 4])[0]
            if marker == 0xE1 and data[pos + 4:pos + 10] == b"Exif\0\0":
                tiff = data[pos + 10:pos + 2 + ln]
                break
            if marker == 0xDA:
                break
            pos += 2 + ln
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        pos = 8
        while pos + 8 <= len(data):
            ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
            if typ == b"eXIf":
                tiff = data[pos + 8:pos + 8 + ln]
                break
            pos += 12 + ln
    if not tiff or len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return {}
    end = "<" if tiff[:2] == b"II" else ">"
    u16 = lambda o: struct.unpack(end + "H", tiff[o:o + 2])[0]
    u32 = lambda o: struct.unpack(end + "I", tiff[o:o + 4])[0]

    def ifd(off):
        out, nxt = {}, 0
        if 8 <= off and off + 2 <= len(tiff):
            n = u16(off)
            for k in range(n):
                e = off + 2 + 12 * k
                if e + 12 > len(tiff):
                    break
                out[u16(e)] = (u16(e + 2), u32(e + 4), e + 8)
            if off + 2 + 12 * n + 4 <= len(tiff):
                nxt = u32(off + 2 + 12 * n)
        return out, nxt

    def text(entry):
        typ, cnt, vo = entry
        o = vo if cnt <= 4 else u32(vo)
        return tiff[o:o + cnt].split(b"\0")[0].decode("latin-1", "replace").strip() if typ == 2 else ""

    ifd0, nxt = ifd(u32(4))
    info = {}
    camera = " ".join(t for t in (text(ifd0[k]) for k in (0x010F, 0x0110) if k in ifd0) if t)
    if camera:
        info["camera"] = camera
    if 0x8769 in ifd0 and any(t in ifd(u32(ifd0[0x8769][2]))[0] for t in (0x829A, 0x829D, 0x8827, 0x920A)):
        info["cameraSettings"] = True  # exposure time, f-number, ISO, focal length
    if 0x8825 in ifd0 and any(t in ifd(u32(ifd0[0x8825][2]))[0] for t in (0x0002, 0x0004)):
        info["gps"] = True
    if nxt and 0x0201 in ifd(nxt)[0]:
        info["thumbnail"] = True
    return info


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
    frame = (w, h, x0, y0, R, G, B, A) if a.edge_fix else None
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
    # --edge-fix: the subject colour behind each semi-transparent edge pixel, how much to fix it, and the lightness gap
    # to the old backdrop. Opaque pixels are left alone: on a synthetic cut with exact alpha, recolouring opaque rim
    # pixels that merely leaned toward the backdrop flattened real texture (fringe p95 38 levels there); backdrop at
    # full opacity is a mask that runs too wide ("backdropInside"), fixed on the mask, not by colour.
    fixF, fixW, fixD = {}, {}, {}
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
            if a.edge_fix:
                fixF[i], fixW[i] = Fs, 1.0
        if i in fixF:
            fixD[i] = abs(imgops.lum(*Bk) - imgops.lum(*Fs))
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
    island_boxes = []
    for c in sorted(islands, key=len, reverse=True)[:12]:  # yellow boxes in edges.png, so they can be found
        xs = [i % W for i in c]; ys = [i // W for i in c]
        bx0, by0, bx1, by1 = max(0, min(xs) - 3), max(0, min(ys) - 3), min(W - 1, max(xs) + 3), min(H - 1, max(ys) + 3)
        for x in range(bx0, bx1 + 1):
            edges[by0][x] = edges[by1][x] = (255, 220, 0)
        for y in range(by0, by1 + 1):
            edges[y][bx0] = edges[y][bx1] = (255, 220, 0)
        island_boxes.append([min(xs) + ox, min(ys) + oy, max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(c)])
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
    fix = ("import outdir/edgefix/layers.json --above <cut layer id>, with the Background visible (Edge colour/tone "
           "layers)" if a.edge_fix else "rerun with --edge-fix and import outdir/edgefix/layers.json --above <cut layer id> "
           "with the Background visible (Edge colour/tone layers)")
    if fd.get("p95", 0) > 6:
        advice.append(f"visible fringe on {a.bg}: {fix}; or, baked in, select.refineEdge decontaminate; look at the "
                      "numbered spots")
    elif fb.get("p95", 0) > 15:
        advice.append(f"fringe shows on dark backgrounds only (old light backdrop, or a glossy opaque rim reflecting it, "
                      f"which is real): fine on white; if the cutout will also go on dark, {fix}. A purple or green 1-2 px "
                      "line along the product's edge is lens fringing, not backdrop: a Hue/Saturation layer clipped to "
                      "the cut and masked to its outline (cutout.md: lens fringing)")
    if islands and not big:
        advice.append(f"{len(islands)} stray island(s), {sum(len(c) for c in islands)} px, at {[b[:4] for b in island_boxes[:6]]} "
                      "(yellow boxes in edges.png): delete them on the mask unless they are hair strands")
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
        "islands": {"count": len(islands), "pixels": sum(len(c) for c in islands), "largeParts": len(big),
                    "boxes": island_boxes[:8]},
        "holes": holes[:8], "haze": round(haze, 3),
        "spots": [[x + ox, y + oy, round(v, 1)] for v, x, y in spots],
        "checkColour": "#%02x%02x%02x" % bgs["colour"], "lowContrastSkipped": round(skipped / max(1, len(band)), 3),
        "advice": advice,
    }
    if a.edge_fix:
        stats["edgeFix"] = write_edge_fix(a, frame, W, H, ox, oy, R, G, B, A, OR, OG, OB, fixF, fixW, fixD, spots)
    print(json.dumps(stats))


def write_edge_fix(a, frame, W, H, ox, oy, R, G, B, A, OR, OG, OB, fixF, fixW, fixD, spots):
    """outdir/edgefix: Edge colour (Color) and, for a brightness fringe, Edge tone (Luminosity) layers of the subject
    colour behind each semi-transparent edge pixel, masked to them, clipped to the cut layer; a preview of the frame as
    the document will show it (the cut layer over the Background, both visible) and cut_fixed.png for a re-check."""
    d = os.path.join(a.outdir, "edgefix")
    os.makedirs(d, exist_ok=True)
    N = W * H
    q = lambda v: float(max(0, min(255, int(v + 0.5))))
    F = [list(R), list(G), list(B)]
    wm = [0.0] * N
    for i, f in fixF.items():
        for c in range(3):
            F[c][i] = f[c]
        wm[i] = fixW[i]
    F = [[q(v) for v in ch] for ch in F]
    wm = [round(min(1.0, max(0.0, v)) * 255) / 255 for v in wm]
    # Color mode keeps each edge pixel's own lightness: right for a colour fringe (green spill in hair). A light rim
    # round a dark subject (or a dark one round a light subject) is a lightness fringe, which needs Luminosity too
    gaps = sorted(fixD[i] for i in fixF if fixW[i] >= 0.5)
    tone = bool(gaps) and gaps[len(gaps) // 2] > 15
    imgops.save_rgb(os.path.join(d, "edge_colour.png"), W, H, *F)
    imgops.save_gray(os.path.join(d, "edge_mask.png"), W, H, wm)
    fixed = []
    for i in range(N):
        c = (R[i], G[i], B[i])
        if wm[i]:
            f = (F[0][i], F[1][i], F[2][i])
            c = imgops.blend("color", c, f, wm[i])
            if tone:
                c = imgops.blend("luminosity", c, f, wm[i])
        fixed.append(c)
    # the fixed cut over the whole frame, for re-running the check (not an independent measure: it uses the same
    # estimate of the subject colour; look at the zooms)
    fw, fh, x0, y0, FR, FG, FB, FA = frame
    FR, FG, FB = list(FR), list(FG), list(FB)
    for y in range(H):
        for x in range(W):
            j = (y0 + y) * fw + x0 + x
            FR[j], FG[j], FB[j] = fixed[y * W + x]
    imgops.save_rgb(os.path.join(d, "cut_fixed.png"), fw, fh, FR, FG, FB, FA)
    # the input cut's colour profile (or the original's), so the fixed cut is the same colours wherever it goes
    prof = copy_colour_chunks(a.cut, os.path.join(d, "cut_fixed.png")) or copy_colour_chunks(a.orig, os.path.join(d, "cut_fixed.png"))
    # verify window: around the worst spot, at most 640 px
    cw, ch = min(640, W), min(640, H)
    sx, sy = (spots[0][1], spots[0][2]) if spots else (W // 2, H // 2)
    vx, vy = int(min(max(0, sx - cw // 2), W - cw)), int(min(max(0, sy - ch // 2), H - ch))
    pv = [[], [], []]
    for y in range(vy, vy + ch):
        for x in range(vx, vx + cw):
            i = y * W + x
            o = imgops.blend("normal", (OR[i], OG[i], OB[i]), fixed[i], A[i])
            for c in range(3):
                pv[c].append(o[c])
    imgops.save_rgb(os.path.join(d, "preview.png"), cw, ch, *pv)
    layers = [{"name": "Edge colour", "image": "edge_colour.png", "mask": "edge_mask.png", "blend": "Color", "clip": True}]
    if tone:
        layers.append({"name": "Edge tone", "image": "edge_colour.png", "mask": "edge_mask.png", "blend": "Luminosity", "clip": True})
    json.dump({"center": [ox + W / 2, oy + H / 2], "crop": [ox + vx, oy + vy, cw, ch], "preview": "preview.png",
               "layers": layers}, open(os.path.join(d, "layers.json"), "w"), indent=1)
    return {"pixels": sum(1 for v in wm if v > 0), "tone": tone, "profile": prof,
            "lumGap": round(gaps[len(gaps) // 2], 1) if gaps else None,
            "next": "Background visible, then import_layers.py <outdir>/edgefix/layers.json --above <cut layer id>"}


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

MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"II*\x00", "tif"), (b"MM\x00*", "tif"), (b"GIF8", "gif"),
         (b"BM", "bmp"))


def file_type(path):
    """What the bytes are (jpg, png, tif, webp, gif, bmp), whatever the extension says."""
    head = open(path, "rb").read(12)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return next((t for m, t in MAGIC if head.startswith(m)), "?")


def check_deliverable(a):
    os.makedirs(a.outdir, exist_ok=True)
    spec = specs.resolve(a.spec or a.preset) if (a.spec or a.preset) else None
    bgc = specs.hex_rgb(spec["background"]) if spec and spec.get("background") else (255, 255, 255)
    png = to_png(a.deliverable, a.outdir)
    w, h, R, G, B = imgops.load(png)
    N = w * h
    # backdrop candidates: within 15 levels of the backdrop colour in every channel (white: all channels >= 240)
    white = [1 if max(abs(R[i] - bgc[0]), abs(G[i] - bgc[1]), abs(B[i] - bgc[2])) <= 15 else 0 for i in range(N)]
    # background = backdrop colour connected to the border; anything it can't reach is content (product, shadow)
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
    # exact for white (JPEG keeps a flat 255 exact); a coloured backdrop moves 1-3 levels in JPEG's colour subsampling
    tol = 0 if bgc == (255, 255, 255) else 3
    pure = [1 if max(abs(R[i] - bgc[0]), abs(G[i] - bgc[1]), abs(B[i] - bgc[2])) <= tol else 0 for i in range(N)]
    nbg = sum(bg)
    off = [i for i in range(N) if bg[i] and not pure[i]]
    border = [i for i in set(list(range(w)) + list(range(N - w, N)) + list(range(0, N, w)) + list(range(w - 1, N, w)))]
    content = [0 if bg[i] else 1 for i in range(N)]
    # the product: clearly off the backdrop colour, but not a shadow, which is smooth, darker and the backdrop's own
    # hue (a cast shadow beside the product otherwise widens its box: 0.11 off centre on a bottle with a side shadow)
    Lm = [imgops.lum(R[i], G[i], B[i]) for i in range(N)]
    m1, m2 = imgops.box(Lm, w, h, 1), imgops.box([v * v for v in Lm], w, h, 1)
    bl = imgops.lum(*bgc)

    def shadowish(i):
        if Lm[i] >= bl or m2[i] - m1[i] * m1[i] > 2.25:  # brighter than the backdrop, or textured (sd > 1.5)
            return False
        k = Lm[i] / max(1.0, bl)  # a shadow scales the backdrop colour
        return max(abs(R[i] - k * bgc[0]), abs(G[i] - k * bgc[1]), abs(B[i] - k * bgc[2])) <= 10

    core = [1 if not bg[i] and (max(abs(R[i] - bgc[0]), abs(G[i] - bgc[1]), abs(B[i] - bgc[2])) > 30
                                or max(R[i], G[i], B[i]) - min(R[i], G[i], B[i]) > 25) and not shadowish(i) else 0
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

    def boxes_of(pixels, n):
        """Boxes [x, y, w, h, pixels] of the 8-connected groups of these pixels, biggest first, at most n."""
        m = bytearray(N)
        for i in pixels:
            m[i] = 1
        out = []
        for c in sorted(imgops.components(m, w, h), key=len, reverse=True)[:n]:
            xs = [i % w for i in c]; ys = [i // w for i in c]
            out.append([min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1, len(c)])
        return out
    speck_boxes, border_boxes = boxes_of(specks, 12), boxes_of(touching, 6)
    k = max(1, math.ceil(max(w, h) / 1200))
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
    vw_, vh_ = len(viz[0]), len(viz)
    for bx, by, bw_, bh_, _ in speck_boxes:  # a blue ring round every speck: single pixels vanish at this scale
        cx, cy, r = (bx + bw_ / 2) / k, (by + bh_ / 2) / k, max(8.0, max(bw_, bh_) / k + 4)
        for t in range(0, 360, 4):
            x, y = int(cx + r * math.cos(math.radians(t))), int(cy + r * math.sin(math.radians(t)))
            if 0 <= x < vw_ and 0 <= y < vh_:
                viz[y][x] = (0, 90, 255)
    pngio.write(os.path.join(a.outdir, "deliverable.png"), vw_, vh_, viz)
    prof = icc_description(a.deliverable)
    meta = exif_info(a.deliverable)
    min_side = a.min_side if a.min_side is not None else (spec["minLongest"] if spec else 1600)
    fill_min = a.fill if a.fill is not None else (spec["fill"] if spec and not spec.get("margins") else 0.85)
    pfill = max((kb[2] - kb[0] + 1) / w, (kb[3] - kb[1] + 1) / h) if kb else 0.0
    stats = {
        "size": [w, h], "longest": max(w, h), "sizeOk": max(w, h) >= min_side,
        "background": {"colour": "#%02x%02x%02x" % bgc, "pixels": nbg, "pureWhite" if bgc == (255, 255, 255) else "pure":
                       round((nbg - len(off)) / max(1, nbg), 4),
                       "offWhite": {"edgeAndShadow": len(near), "touchingBorder": len(touching), "specks": len(specks),
                                    "speckBoxes": speck_boxes, "borderBoxes": border_boxes},
                       "borderPure": round(sum(pure[i] for i in border) / len(border), 4)},
        "content": fill_of(cb), "product": fill_of(kb),
        "fillOk": bool(kb) and pfill >= fill_min - 0.005,
        "profile": prof or "none (untagged: browsers assume sRGB)",
        "metadata": meta,
    }
    if spec:
        stats.update(spec_checks(a, spec, w, h, kb, pfill, prof, stats))
    print(json.dumps(stats))


def spec_checks(a, spec, w, h, kb, pfill, prof, st):
    """Every requirement of the spec as {"ok", "value", "want"}; "pass" when all hard ones hold. Recommended sizes and
    file sizes, and an untagged profile, are warnings. With the box product_shot.py placed the product in, fill and
    centring are measured on that box, and "placement" checks the product really is there."""
    checks, warn = {}, []

    def chk(name, ok, value, want):
        checks[name] = {"ok": bool(ok), "value": value, "want": want}

    planned = spec.get("productInCanvas")
    if planned and [w, h] == list(spec["canvas"]) and kb:
        px, py, pw, ph = planned
        # the plan itself must keep the product on the canvas (a tall product's neck at y < 0 is cut off)
        chk("inCanvas", px >= -1 and py >= -1 and px + pw <= w + 1 and py + ph <= h + 1, planned, [0, 0, w, h])
        ix = max(0, min(kb[2] + 1, px + pw) - max(kb[0], px)) * max(0, min(kb[3] + 1, py + ph) - max(kb[1], py))
        chk("placement", ix >= 0.9 * pw * ph, round(ix / max(1, pw * ph), 3), ">= 0.9 of the planned box holds product")
        kb = [px, py, px + pw - 1, py + ph - 1]
        pfill = max(pw / w, ph / h)
        st["planned"] = {"bbox": planned, "fill": round(pfill, 3),
                         "centreOffset": [round(((kb[0] + kb[2]) / 2 - (w - 1) / 2) / w, 3), round(((kb[1] + kb[3]) / 2 - (h - 1) / 2) / h, 3)]}
    elif kb:  # no plan: a product touching the frame's edge is cut off (unless the spec's margins allow 0)
        zero = spec.get("margins") and min(spec["margins"]) == 0
        chk("inCanvas", zero or (kb[0] > 0 and kb[1] > 0 and kb[2] < w - 1 and kb[3] < h - 1), st["product"]["bbox"],
            "not touching the frame's edge")
    box = st.get("planned") or st["product"] or {}

    mins = {"minWidth": w, "minHeight": h, "minLongest": max(w, h), "minShortest": min(w, h)}
    need = {k: spec.get(k) or 0 for k in mins}
    if a.min_side is not None:
        need["minLongest"] = a.min_side
    chk("size", all(mins[k] >= need[k] for k in mins), [w, h], {k: v for k, v in need.items() if v})
    for k, v in (("recommendedLongest", max(w, h)), ("recommendedShortest", min(w, h))):
        if spec.get(k) and v < spec[k]:
            warn.append(f"{k[11:].lower()} side {v} px is under the recommended {spec[k]}")
    asp = specs.aspect_ok(spec, w, h)
    if asp is not None:
        chk("aspect", asp, round(max(w, h) / min(w, h), 4), spec["aspect"])
    if spec.get("exactCanvas"):
        chk("canvas", [w, h] == list(spec["canvas"]), [w, h], spec["canvas"])
    if spec.get("margins"):
        mt, mr, mb, ml = (v * (h if k in (0, 2) else w) if v <= 1 else v for k, v in enumerate(spec["margins"]))
        gaps = [kb[1], w - 1 - kb[2], h - 1 - kb[3], kb[0]] if kb else [0, 0, 0, 0]
        chk("margins", kb and all(g >= m - 0.005 * max(w, h) for g, m in zip(gaps, (mt, mr, mb, ml))), gaps,
            [round(v) for v in (mt, mr, mb, ml)])
    if not spec.get("margins") or spec.get("fillRange"):
        lo, hi = spec.get("fillRange") or [spec["fill"], 1.0]
        if a.fill is not None:
            lo = a.fill
        if kb and spec.get("safeAspect"):  # placed against the thumbnail's crop, so measured against it too
            sw, sh = specs.parse_aspect(spec["safeAspect"])
            pfill = max((kb[2] - kb[0] + 1) / min(w, h * sw / sh), (kb[3] - kb[1] + 1) / min(h, w * sh / sw))
        if spec.get("fillWithReflection") is not None and not spec.get("fillRange") and a.fill is None:
            # no marketplace range: --fill was the target for product and reflection together, so check that
            chk("fill", lo - 0.005 <= spec["fillWithReflection"] <= hi + 0.005,
                {"product": round(pfill, 3), "withReflection": spec["fillWithReflection"]}, [lo, hi])
        else:
            chk("fill", kb and lo - 0.005 <= pfill <= hi + 0.005, round(pfill, 3), [lo, hi])
    if kb and spec.get("align") in ("bottom", "top"):
        y0s, hs = 0.0, float(h)  # the gap is measured in the thumbnail crop when there is one, as it was placed
        if spec.get("safeAspect") and not spec.get("margins"):
            sw, sh = specs.parse_aspect(spec["safeAspect"])
            hs = min(h, w * sh / sw)
            y0s = (h - hs) / 2
        want = spec.get("bottom", 0.06)
        if spec.get("margins"):
            m = spec["margins"][2 if spec["align"] == "bottom" else 0]
            want = m if m <= 1 else m / h
        g = ((y0s + hs) - 1 - kb[3]) / hs if spec["align"] == "bottom" else (kb[1] - y0s) / hs
        chk("baseline", abs(g - want) <= 0.01, round(g, 3), round(want, 3))
        chk("centred", abs(box["centreOffset"][0]) <= 0.01, box["centreOffset"][0], 0)
    elif kb and not spec.get("margins"):
        if spec.get("reflection"):  # the product and its reflection are centred together: only across
            chk("centred", abs(box["centreOffset"][0]) <= 0.01, box["centreOffset"][0], 0)
        else:
            chk("centred", max(abs(v) for v in box["centreOffset"]) <= 0.01, box["centreOffset"], [0, 0])
    if kb and spec.get("safeAspect"):
        sw, sh = specs.parse_aspect(spec["safeAspect"])
        fw, fh = min(w, h * sw / sh), min(h, w * sh / sw)
        x0, y0 = (w - fw) / 2, (h - fh) / 2
        chk("safeArea", kb[0] >= x0 - 0.5 and kb[2] + 1 <= x0 + fw + 0.5 and kb[1] >= y0 - 0.5 and kb[3] + 1 <= y0 + fh + 0.5,
            box["bbox"], [round(x0), round(y0), round(fw), round(fh)])
    if spec.get("pureBackground"):
        b = st["background"]["offWhite"]
        chk("background", st["background"]["borderPure"] == 1.0 and b["touchingBorder"] == 0 and b["specks"] == 0,
            {"borderPure": st["background"]["borderPure"], "touchingBorder": b["touchingBorder"], "specks": b["specks"]},
            {"colour": spec["background"], "everywhere": "outside the product and its shadow"})
    ext = os.path.splitext(a.deliverable)[1].lower().lstrip(".")
    ext = {"jpeg": "jpg", "tiff": "tif"}.get(ext, ext)
    real = file_type(a.deliverable)
    chk("format", real in spec["formats"] and ext == real, {"extension": ext, "content": real}, spec["formats"])
    size_b = os.path.getsize(a.deliverable)
    if spec.get("maxBytes"):
        chk("fileSize", size_b <= spec["maxBytes"], size_b, spec["maxBytes"])
    if spec.get("recommendedMaxBytes") and size_b > spec["recommendedMaxBytes"]:
        warn.append(f"{size_b} bytes, over the recommended {spec['recommendedMaxBytes']}")
    if spec.get("maxMegapixels"):
        chk("megapixels", w * h <= spec["maxMegapixels"] * 1e6, round(w * h / 1e6, 2), spec["maxMegapixels"])
    if spec.get("profile") == "srgb":
        if not prof:
            warn.append("no embedded profile: browsers and marketplaces assume sRGB; embed it (export from an sRGB document)")
        else:
            chk("profile", "srgb" in prof.lower().replace(" ", ""), prof, "sRGB")
    meta = st.get("metadata") or {}
    if meta:
        what = [f"the camera ({meta['camera']})" if meta.get("camera") else "", "its settings" if meta.get("cameraSettings") else "",
                "a GPS position" if meta.get("gps") else "", "a thumbnail of the unretouched original" if meta.get("thumbnail") else ""]
        warn.append(f"the file carries the master's EXIF: {', '.join(t for t in what if t)}. A marketplace needs none of it "
                    "(GPS tells where it was shot): export with deliver.py (--metadata copyright keeps only the creator and "
                    "copyright) instead of pc.py cli convert")
    if spec.get("nameRegex"):
        import re
        chk("name", re.fullmatch(spec["nameRegex"], os.path.basename(a.deliverable)), os.path.basename(a.deliverable), spec["nameRegex"])
    return {"spec": {"name": spec["name"], "preset": spec.get("preset"), "official": spec.get("official"), "source": spec.get("url")},
            "checks": checks, "pass": all(c["ok"] for c in checks.values()), "warnings": warn,
            "failed": [k for k, c in checks.items() if not c["ok"]]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="cut.png orig.png outdir, or (with --deliverable FILE) outdir")
    ap.add_argument("--origin", type=int, nargs=2, default=[0, 0], help="where the cut/orig frame sits in the photo")
    ap.add_argument("--bg", default="#ffffff", help="the background the cutout will go on (its fringe is reported as 'deliverable')")
    ap.add_argument("--min-contrast", type=float, default=12, help="levels: edges where subject and old backdrop are closer than this are skipped")
    ap.add_argument("--kind", choices=["product", "soft"], default="product", help="hard-edged product, or hair/fur (soft edges expected)")
    ap.add_argument("--spots", type=int, default=6)
    ap.add_argument("--zoom", type=int, default=3)
    ap.add_argument("--edge-fix", action="store_true", help="also write outdir/edgefix: Color/Luminosity edge layers, the controllable decontaminate")
    ap.add_argument("--deliverable", help="check a finished flat image instead of a cut")
    ap.add_argument("--preset", choices=sorted(specs.PRESETS), help="deliverable: a marketplace's requirements (specs.py)")
    ap.add_argument("--spec", help="deliverable: a spec.json (product_shot.py writes the one it placed the product by)")
    ap.add_argument("--min-side", type=int, help="deliverable: longest side at least (default: the spec's, else 1600)")
    ap.add_argument("--fill", type=float, help="deliverable: product share of the frame's longer side, at least (default: the spec's, else 0.85)")
    a = ap.parse_args()
    if a.preset and a.spec:
        ap.error("--preset or --spec, not both")
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
