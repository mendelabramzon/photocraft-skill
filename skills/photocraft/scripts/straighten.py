#!/usr/bin/env python3
"""Straighten a photo the way an architectural photographer does: level the horizon, make converging verticals
vertical, and crop away the empty corners, all measured from the photo's own lines instead of eyeballed.

It renders a reduced copy with photocraft-cli, finds the straight line segments (gradient-orientation region
growing, then a weighted line fit per segment) and estimates the camera's tilt:
  roll    the sideways tilt: from the horizon (a sea horizon is exact), or from the verticals
  pitch   the up/down tilt: from where the verticals converge (their vanishing point)
Then it plans the PhotoCraft steps:
  rotation only      image.crop with an angle: rotates and crops in one step, to the largest rectangle with the
                     photo's aspect ratio and no empty corners
  perspective        edit.transform with a quad: the exact homography of turning the camera level, K R K^-1 with the
                     focal length from EXIF (so proportions stay right, like a shift lens), then image.crop

Why a real camera model and not a keystone squeeze: pulling the top corners apart by eye fixes the lean but leaves
the building squat or stretched. Rotating a virtual camera with the photo's own focal length keeps windows square
and circles round. --amount keeps some convergence on steep upward shots (pitch correction only; the roll is always
fixed fully), so tall buildings don't look top-heavy.

usage: straighten.py photo.jpg outdir [--mode auto|horizon|rotate|verticals] [--amount A] [--focal MM]
                     [--aspect keep|free|W:H] [--crop centre|max] [--level X1,Y1,X2,Y2] [--plumb X1,Y1,X2,Y2]
                     [--distortion D] [--smart] [--keep-pixels] [--verify]
  auto       verticals if the photo has plenty (architecture, interiors), else a straight horizon; nothing when
             there are no reliable lines, the photo is already straight, or the shot is steeply up/down (deliberate)
  horizon    rotation only, from the longest straight near-level line, a soft sea horizon, or --level
  rotate     rotation only, from the verticals (keeps intended convergence)
  verticals  roll + pitch from the vertical vanishing point (or from 2+ --plumb lines)
  --verify   only measure (run it on the corrected export): residual tilt, and the lean of the verticals at the
             frame edges (edgeLean)

Writes outdir/steps.json (for pc.py script, live or headless with --open/--save), lines.png (green: verticals used,
blue: horizon, yellow: other near-level lines), preview.png (predicted result with a grid), and one JSON line.
Coordinates are full-image pixels (continuous: the image spans 0..W, 0..H), like PhotoCraft's params.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc
import pngio
from imgops import gauss, lum

FRAME_DIAG_MM = 43.27  # 35 mm film diagonal: "35 mm equivalent" focal lengths refer to it


# ---------------------------------------------------------------- input

def cli_json(cli, *args):
    out = subprocess.run([str(cli), *args], capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"error: photocraft-cli {' '.join(args[:2])}: {out.stderr.strip()[:300]}")
    return out.stdout


def lens_step(distortion):
    """filter.lensCorrection that removes barrel (positive) or pincushion (negative) distortion; autoScale fills
    the frame again when pincushion correction pulls the edges in."""
    return {"command": "filter.lensCorrection", "params": {"distortion": distortion, "edge": "edgeExtension",
                                                           "autoScale": True}}


def render(photo, outdir, max_side, distortion=0.0):
    """(W, H, analysis png path, w, h): the photo's size and a reduced copy rendered by the CLI (after the lens
    distortion fix, when there is one, so lines are measured once they're straight)."""
    cli = pc.find_cli()
    if not cli:
        sys.exit("error: photocraft-cli not found; `pc.py cli-info` names the one to install")
    info = json.loads(cli_json(cli, "info", photo, "--compact"))
    W, H = info["width"], info["height"]
    path = os.path.join(outdir, "analysis.png")
    cmds = []
    if distortion:
        st = lens_step(distortion)
        cmds += ["--cmd", st["command"], "--params", json.dumps(st["params"])]
    if max(W, H) > max_side:
        w = max(1, round(W * max_side / max(W, H)))
        cmds += ["--cmd", "image.imageSize", "--params", json.dumps({"width": w})]
    if cmds:
        cli_json(cli, "run", photo, *cmds, "--out", path)
    else:
        cli_json(cli, "convert", photo, path)
    w, h, _ = pngio.read(path)
    return W, H, path, w, h


def exif_focal35(path):
    """(35 mm-equivalent focal length, how it was found) from a JPEG's or TIFF's EXIF, or (None, None)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read(1 << 20)
            if data[:4] in (b"II*\x00", b"MM\x00*"):  # TIFF: the EXIF directory can sit anywhere in the file
                data += fh.read(255 << 20)
    except OSError:
        return None, None
    tiff = None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 4 < len(data) and data[i] == 0xFF:
            marker, ln = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
            if marker == 0xE1 and data[i + 4:i + 10] == b"Exif\x00\x00":
                tiff = data[i + 10:i + 2 + ln]
                break
            if marker == 0xDA:
                break
            i += 2 + ln
    elif data[:4] in (b"II*\x00", b"MM\x00*"):
        tiff = data
    if not tiff or len(tiff) < 8:
        return None, None
    end = "<" if tiff[:2] == b"II" else ">"
    u16 = lambda o: int.from_bytes(tiff[o:o + 2], "little" if end == "<" else "big")
    u32 = lambda o: int.from_bytes(tiff[o:o + 4], "little" if end == "<" else "big")

    def ifd(off):
        tags = {}
        if off + 2 > len(tiff):
            return tags
        for k in range(u16(off)):
            e = off + 2 + 12 * k
            if e + 12 > len(tiff):
                break
            tag, typ, cnt = u16(e), u16(e + 2), u32(e + 4)
            if typ == 3:
                tags[tag] = u16(e + 8)
            elif typ == 4:
                tags[tag] = u32(e + 8)
            elif typ == 5 and cnt >= 1:
                o = u32(e + 8)
                if o + 8 <= len(tiff) and u32(o + 4):
                    tags[tag] = u32(o) / u32(o + 4)
        return tags

    try:
        ifd0 = ifd(u32(4))
        ex = ifd(ifd0[0x8769]) if 0x8769 in ifd0 else {}
    except (KeyError, IndexError, ValueError):
        return None, None
    if ex.get(0xA405):
        return float(ex[0xA405]), "exif35"
    fl, xres, unit = ex.get(0x920A), ex.get(0xA20E), ex.get(0xA210)
    px, py = ex.get(0xA002), ex.get(0xA003)
    if fl and xres and px and py and unit in (2, 3, 4, 5):
        mm = {2: 25.4, 3: 10.0, 4: 1.0, 5: 0.001}[unit] / xres  # mm per pixel on the sensor
        return fl * FRAME_DIAG_MM / (mm * math.hypot(px, py)), "exif+sensor"
    return None, None


# ---------------------------------------------------------------- line segments

def segments(Y, w, h, grad_min, min_len, tau=22.5):
    """Straight segments: dicts with endpoints, length, angle (0..180, y down), line moments. Continuous coords."""
    S = gauss(Y, w, h, 0.8)
    N = w * h
    gx = [0.0] * N; gy = [0.0] * N
    for y in range(1, h - 1):
        up = S[(y - 1) * w:y * w]; mid = S[y * w:(y + 1) * w]; dn = S[(y + 1) * w:(y + 2) * w]
        sv = [u + 2 * m + d for u, m, d in zip(up, mid, dn)]
        dv = [d - u for u, d in zip(up, dn)]
        b = y * w
        gx[b + 1:b + w - 1] = [(sv[x + 1] - sv[x - 1]) / 8 for x in range(1, w - 1)]
        gy[b + 1:b + w - 1] = [(dv[x - 1] + 2 * dv[x] + dv[x + 1]) / 8 for x in range(1, w - 1)]
    mag = [math.hypot(a, b) for a, b in zip(gx, gy)]
    cand = [i for i in range(N) if mag[i] > grad_min]
    ang = {i: math.atan2(gx[i], -gy[i]) for i in cand}  # level-line angle (along the edge)
    used = bytearray(N)
    tol = math.radians(tau)
    segs = []
    for s in sorted(cand, key=mag.__getitem__, reverse=True):
        if used[s]:
            continue
        used[s] = 1
        reg = [s]
        th = ang[s]; sc, ss = math.cos(th), math.sin(th)
        k = 0
        while k < len(reg):
            p = reg[k]; k += 1
            for q in (p - w - 1, p - w, p - w + 1, p - 1, p + 1, p + w - 1, p + w, p + w + 1):
                if 0 <= q < N and not used[q] and mag[q] > grad_min:
                    d = (ang[q] - th + math.pi) % (2 * math.pi) - math.pi
                    if -tol < d < tol:
                        used[q] = 1; reg.append(q)
                        sc += math.cos(ang[q]); ss += math.sin(ang[q]); th = math.atan2(ss, sc)
        if len(reg) < min_len:
            continue
        m0 = mx = my = mxx = myy = mxy = 0.0
        for p in reg:
            wt = mag[p]; x = p % w + 0.5; y = p // w + 0.5
            m0 += wt; mx += wt * x; my += wt * y; mxx += wt * x * x; myy += wt * y * y; mxy += wt * x * y
        seg = fit({"m": [m0, mx, my, mxx, myy, mxy]})
        if seg["length"] >= min_len and seg["rms"] <= 1.5:
            seg["contrast"] = m0 / len(reg)
            segs.append(seg)
    return segs


def fit(seg):
    """Line through weighted moments: centre, direction, angle (0..180), rms width, half-length."""
    m0, mx, my, mxx, myy, mxy = seg["m"]
    cx, cy = mx / m0, my / m0
    sxx, syy, sxy = mxx / m0 - cx * cx, myy / m0 - cy * cy, mxy / m0 - cx * cy
    t = 0.5 * math.atan2(2 * sxy, sxx - syy)
    c, s = math.cos(t), math.sin(t)
    along = sxx * c * c + 2 * sxy * c * s + syy * s * s
    across = max(0.0, sxx * s * s - 2 * sxy * c * s + syy * c * c)
    half = math.sqrt(3 * max(along, 0.0))  # a uniform segment of length L has variance L^2 / 12
    seg.update({"c": (cx, cy), "d": (c, s), "angle": math.degrees(t) % 180, "rms": math.sqrt(across),
                "length": 2 * half, "p0": (cx - c * half, cy - s * half), "p1": (cx + c * half, cy + s * half)})
    return seg


def manual_segment(spec, sx, sy):
    x0, y0, x1, y1 = (float(v) for v in spec.split(","))
    x0, x1, y0, y1 = x0 * sx, x1 * sx, y0 * sy, y1 * sy
    L = math.hypot(x1 - x0, y1 - y0)
    c, s = (x1 - x0) / L, (y1 - y0) / L
    return {"c": ((x0 + x1) / 2, (y0 + y1) / 2), "d": (c, s), "angle": math.degrees(math.atan2(s, c)) % 180,
            "length": L, "p0": (x0, y0), "p1": (x1, y1), "rms": 0.0, "manual": True,
            "m": None}


# ---------------------------------------------------------------- estimates

def vanishing_point(segs, cx, cy, scale, tol_deg=1.0):
    """Robust vertical vanishing point (homogeneous, in coords centred on (cx, cy) / scale) of near-vertical segments:
    RANSAC over pairs of the longest, then iteratively reweighted least squares on the angular error."""
    def line(sg):
        (x0, y0), (x1, y1) = sg["p0"], sg["p1"]
        a = ((x0 - cx) / scale, (y0 - cy) / scale, 1.0); b = ((x1 - cx) / scale, (y1 - cy) / scale, 1.0)
        l = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
        n = math.hypot(l[0], l[1])
        return (l[0] / n, l[1] / n, l[2] / n)

    def err(sg, v):
        """Angle (deg) between the segment and the line from its centre to v."""
        mx, my = (sg["c"][0] - cx) / scale, (sg["c"][1] - cy) / scale
        dx, dy = (v[0] - mx * v[2], v[1] - my * v[2])
        if math.hypot(dx, dy) < 1e-12:
            return 90.0
        c = abs(dx * sg["d"][0] + dy * sg["d"][1]) / math.hypot(dx, dy)
        return math.degrees(math.acos(min(1.0, c)))

    lines = [line(s) for s in segs]
    top = sorted(range(len(segs)), key=lambda i: -segs[i]["length"])[:40]
    best, bv = -1.0, None
    for ii in range(len(top)):
        for jj in range(ii + 1, len(top)):
            a, b = lines[top[ii]], lines[top[jj]]
            v = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            n = math.sqrt(sum(x * x for x in v))
            if n < 1e-12:
                continue
            v = tuple(x / n for x in v)
            score = sum(s["length"] * max(0.0, 1 - (err(s, v) / tol_deg) ** 2) for s in segs)
            if score > best:
                best, bv = score, v
    if bv is None:
        return None, []
    v = bv
    for _ in range(6):
        inl = [i for i, s in enumerate(segs) if err(s, v) < 2 * tol_deg]
        if len(inl) < 2:
            break
        M = [[0.0] * 3 for _ in range(3)]
        for i in inl:
            s, l = segs[i], lines[i]
            mx, my = (s["c"][0] - cx) / scale, (s["c"][1] - cy) / scale
            r2 = (v[0] - mx * v[2]) ** 2 + (v[1] - my * v[2]) ** 2  # distance^2 to v: weights distance -> angle
            wt = s["length"] / max(r2, 1e-9)
            for p in range(3):
                for q in range(3):
                    M[p][q] += wt * l[p] * l[q]
        v = smallest_eigvec(M, v)
    inl = [i for i, s in enumerate(segs) if err(s, v) < 2 * tol_deg]
    return v, inl


def edge_lean(v, ex):
    """Lean in degrees (positive: the top leans right) of a true vertical at height centre and x = ex (centred,
    scaled coords), as the vanishing point v draws it: the convergence a viewer sees at that edge of the frame."""
    dx, dy = v[0] - ex * v[2], v[1]
    if dy > 0 or (dy == 0 and dx < 0):
        dx, dy = -dx, -dy
    return round(math.degrees(math.atan2(dx, -dy)), 3) if (dx or dy) else 0.0


def fit_rms(segs, inl, v, cx, cy, scale):
    """Length-weighted rms angle (deg) between the inlier verticals and the lines to the vanishing point."""
    tot = acc = 0.0
    for i in inl:
        s = segs[i]
        mx, my = (s["c"][0] - cx) / scale, (s["c"][1] - cy) / scale
        dx, dy = v[0] - mx * v[2], v[1] - my * v[2]
        c = abs(dx * s["d"][0] + dy * s["d"][1]) / max(math.hypot(dx, dy), 1e-12)
        acc += s["length"] * math.degrees(math.acos(min(1.0, c))) ** 2; tot += s["length"]
    return round(math.sqrt(acc / tot), 3) if tot else 0.0


def smallest_eigvec(M, guess):
    """Eigenvector of the smallest eigenvalue of a symmetric 3x3 matrix (inverse iteration from guess)."""
    A = [row[:] for row in M]
    tr = sum(A[i][i] for i in range(3))
    for i in range(3):
        A[i][i] += 1e-12 * (tr + 1e-30)
    v = list(guess)
    for _ in range(30):
        x = solve3(A, v)
        if x is None:
            break
        n = math.sqrt(sum(t * t for t in x))
        x = [t / n for t in x]
        if sum(a * b for a, b in zip(x, v)) < 0:
            x = [-t for t in x]
        if max(abs(a - b) for a, b in zip(x, v)) < 1e-13:
            v = x
            break
        v = x
    return tuple(v)


def solve3(A, b):
    (a, bb, c), (d, e, f), (g, h, i) = A
    det = a * (e * i - f * h) - bb * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-300:
        return None
    inv = [[(e * i - f * h), (c * h - bb * i), (bb * f - c * e)],
           [(f * g - d * i), (a * i - c * g), (c * d - a * f)],
           [(d * h - e * g), (bb * g - a * h), (a * e - bb * d)]]
    return [sum(inv[r][k] * b[k] for k in range(3)) / det for r in range(3)]


def horizon(segs, w, tol=10.0):
    """Longest straight near-level line, merged from collinear pieces (a sea horizon broken by boats or waves):
    (angle in degrees, span as a fraction of the width, merged segment) or None."""
    hs = sorted((s for s in segs if min(s["angle"], 180 - s["angle"]) < tol and s["m"]), key=lambda s: -s["length"])
    clusters = []
    for s in hs:
        for cl in clusters:
            f = cl["fit"]
            nx, ny = -f["d"][1], f["d"][0]
            dist = max(abs((p[0] - f["c"][0]) * nx + (p[1] - f["c"][1]) * ny) for p in (s["p0"], s["p1"]))
            da = abs((s["angle"] - f["angle"] + 90) % 180 - 90)
            if dist < 2.5 and da < 1.5:
                cl["parts"].append(s)
                cl["fit"] = fit({"m": [sum(t) for t in zip(*(q["m"] for q in cl["parts"]))]})
                break
        else:
            clusters.append({"parts": [s], "fit": fit({"m": list(s["m"])})})
    best = None
    for cl in clusters:
        f = cl["fit"]
        ts = [((p[0] - f["c"][0]) * f["d"][0] + (p[1] - f["c"][1]) * f["d"][1]) for q in cl["parts"] for p in (q["p0"], q["p1"])]
        span = (max(ts) - min(ts)) * abs(f["d"][0]) / w
        cl["span"] = span
        if best is None or span > best["span"]:
            best = cl
    if not best:
        return None
    f = best["fit"]
    a = math.degrees(math.atan2(f["d"][1], f["d"][0]))
    a = (a + 90) % 180 - 90
    return {"angle": a, "span": best["span"], "parts": best["parts"]}


def soft_horizon(Y, w, h, max_angle=15.0):
    """A soft, low-contrast horizon (sea haze, plains), which the segment finder misses: per column, candidate edges
    in two copies smoothed along x (sparkle averages out, a near-level boundary survives): brightness, and texture
    energy on a log scale (smooth sky above, textured water below). Then the straight line most columns agree on (RANSAC by count,
    so a faint but consistent horizon beats strong random waves). Same shape as horizon(), or None."""
    B = max(3, w // 60)
    L = gauss(Y, w, h, 1.5)
    # texture on a log scale: sky -> water is a jump from ~1 to ~10, bigger than any change within the water
    T = [math.log(0.5 + t) for t in gauss([abs(a - b) for a, b in zip(Y, gauss(Y, w, h, 2.0))], w, h, 2.0)]
    step = max(1, w // 300)
    xs_col = list(range(B, w - B, step))
    tmax = math.tan(math.radians(max_angle))
    rnd = random.Random(1)
    best = None
    for C in (L, T):
        cols = []  # per sampled column: the x-smoothed profile
        for x in xs_col:
            cols.append([sum(C[y * w + x - B:y * w + x + B + 1]) / (2 * B + 1) for y in range(h)])
        pts = []
        for x, col in zip(xs_col, cols):
            g = [0.0, 0.0] + [col[y + 2] - col[y - 2] for y in range(2, h - 2)] + [0.0, 0.0]
            peaks = sorted((y for y in range(3, h - 3) if abs(g[y]) >= abs(g[y - 1]) and abs(g[y]) > abs(g[y + 1])),
                           key=lambda y: -abs(g[y]))[:10]
            for y in peaks:
                a, b, c = abs(g[y - 1]), abs(g[y]), abs(g[y + 1])
                off = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0  # sub-pixel peak
                pts.append((x + 0.5, y + off + 0.5, abs(g[y]), 1 if g[y] > 0 else -1))
        if len(pts) < 20:
            continue

        def inliers(sl, x0, y0, sign, tol=1.5):
            got = {}
            for x, y, st, sg in pts:
                if sg == sign and abs(y - (y0 + sl * (x - x0))) < tol and st > got.get(x, (0, 0, 0))[2]:
                    got[x] = (x, y, st)
            return list(got.values())

        for _ in range(1500):
            p, q = rnd.sample(pts, 2)
            if abs(q[0] - p[0]) < w / 4 or p[3] != q[3]:
                continue
            sl = (q[1] - p[1]) / (q[0] - p[0])
            if abs(sl) > tmax:
                continue
            n = len(inliers(sl, p[0], p[1], p[3]))
            if best is None or n > best[0]:
                best = (n, sl, p[0], p[1], p[3], pts)
    if not best:
        return None
    n, sl, x0, y0, sign, pts = best
    for _ in range(3):  # weighted least squares on the inliers
        got = {}
        for x, y, st, sg in pts:
            if sg == sign and abs(y - (y0 + sl * (x - x0))) < 1.5 and st > got.get(x, (0, 0, 0))[2]:
                got[x] = (x, y, st)
        inl = list(got.values())
        sw = sum(t[2] for t in inl); mx = sum(t[2] * t[0] for t in inl) / sw; my = sum(t[2] * t[1] for t in inl) / sw
        sxx = sum(t[2] * (t[0] - mx) ** 2 for t in inl); sxy = sum(t[2] * (t[0] - mx) * (t[1] - my) for t in inl)
        sl, x0, y0 = sxy / sxx, mx, my
    xs = sorted(t[0] for t in inl)
    covered = len(xs) / len(range(B, w - B, step))
    if covered < 0.6:
        return None
    seg = {"p0": (xs[0], y0 + sl * (xs[0] - x0)), "p1": (xs[-1], y0 + sl * (xs[-1] - x0)), "m": None}
    return {"angle": math.degrees(math.atan(sl)), "span": round(covered, 2), "parts": [seg], "soft": True}


def contradicted(hz, segs, w):
    """True if long near-level lines run at other angles than the horizon (receding perspective lines, a facade
    seen at an angle): then the 'horizon' is likely one of them, not a level reference."""
    parts = {id(p) for p in hz["parts"]}
    own = sum(p["length"] for p in hz["parts"] if p.get("m"))
    off = sum(s["length"] for s in segs if id(s) not in parts and s["length"] > 0.1 * w
              and min(s["angle"], 180 - s["angle"]) < 15
              and abs((s["angle"] - hz["angle"] + 90) % 180 - 90) > 2.0)
    return off > max(own, 0.3 * w)


# ---------------------------------------------------------------- geometry

def matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def apply(Hm, x, y):
    u = Hm[0][0] * x + Hm[0][1] * y + Hm[0][2]
    v = Hm[1][0] * x + Hm[1][1] * y + Hm[1][2]
    t = Hm[2][0] * x + Hm[2][1] * y + Hm[2][2]
    return u / t, v / t


def inverse(M):
    (a, b, c), (d, e, f), (g, h, i) = M
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


def camera_tilt(v, scale, f):
    """(roll, pitch) in degrees from the vertical vanishing point v (centred / scale coords) and focal f (same px).
    roll: rotate the rays by this about the optical axis (positive = clockwise on screen) to make the verticals
    point straight down; pitch: then about the horizontal axis to make them parallel."""
    d = (v[0] * scale / f, v[1] * scale / f, v[2])
    if d[1] < 0:
        d = tuple(-t for t in d)
    roll = math.degrees(math.atan2(d[0], d[1]))
    pitch = math.degrees(math.atan2(-d[2], math.hypot(d[0], d[1])))
    return roll, pitch


def rotation(roll, pitch, yaw=0.0):
    """R = Ry(yaw) Rx(pitch) Rz(roll), angles in degrees: first the roll, then the pitch, then (about the axis that
    is now vertical, so verticals stay vertical) the yaw."""
    r, p, q = math.radians(roll), math.radians(pitch), math.radians(yaw)
    Rz = [[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]]
    Rx = [[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]]
    Ry = [[math.cos(q), 0, math.sin(q)], [0, 1, 0], [-math.sin(q), 0, math.cos(q)]]
    return matmul(Ry, matmul(Rx, Rz))


def frontal_yaw(lines, W, H, f, roll, pitch):
    """Yaw (deg) that makes lines which should be level and parallel (a facade or back wall seen square-on) level,
    once roll and pitch are corrected: their vanishing point, sent to infinity left-right. Like Guided Upright."""
    K = [[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]]
    H1 = matmul(matmul(K, rotation(roll, pitch)), inverse(K))
    M = [[0.0] * 3 for _ in range(3)]
    for spec in lines:
        x0, y0, x1, y1 = (float(v) for v in spec.split(","))
        (u0, v0), (u1, v1) = apply(H1, x0, y0), apply(H1, x1, y1)
        a, b = (u0 - W / 2) / f, (v0 - H / 2) / f
        c, d = (u1 - W / 2) / f, (v1 - H / 2) / f
        l = (b - d, c - a, a * d - b * c)
        n = math.sqrt(sum(t * t for t in l))
        for i in range(3):
            for j in range(3):
                M[i][j] += l[i] * l[j] / (n * n)
    v = smallest_eigvec(M, (1.0, 0.0, 0.0))  # ray direction of the vanishing point (K^-1 applied already)
    if v[0] < 0:
        v = tuple(-t for t in v)
    return math.degrees(math.atan2(v[2], v[0]))


def rectify(W, H, f, roll, pitch, amount, yaw=0.0):
    """Homography (full-res continuous coords) turning the camera level: H = K R K^-1, R = rotation(roll,
    amount * pitch, yaw), scaled so the image centre keeps its pixel size."""
    K = [[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]]
    Hm = matmul(matmul(K, rotation(roll, pitch * amount, yaw)), inverse(K))
    # local area scale at the centre -> 1
    e = 0.5
    (x0, y0), (x1, y1), (x2, y2) = apply(Hm, W / 2, H / 2), apply(Hm, W / 2 + e, H / 2), apply(Hm, W / 2, H / 2 + e)
    k = 1 / math.sqrt(abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)) / (e * e))
    return matmul([[k, 0, 0], [0, k, 0], [0, 0, 1]], Hm)


def largest_rect(quad, aspect):
    """Largest axis-aligned rectangle inside a convex quad (clockwise corners) with width/height = aspect:
    an LP in (centre x, centre y, half-height t), solved exactly over its vertices. -> (x0, y0, x1, y1)."""
    n = len(quad)
    area2 = sum(quad[i][0] * quad[(i + 1) % n][1] - quad[(i + 1) % n][0] * quad[i][1] for i in range(n))
    cons = []  # a*cx + b*cy + c*t <= d
    for i in range(n):
        (x0, y0), (x1, y1) = quad[i], quad[(i + 1) % n]
        nx, ny = (y1 - y0), -(x1 - x0)  # outward normal for a clockwise (y-down) polygon
        if area2 < 0:
            nx, ny = -nx, -ny
        L = math.hypot(nx, ny); nx, ny = nx / L, ny / L
        cons.append((nx, ny, abs(nx) * aspect + abs(ny), nx * x0 + ny * y0))
    best = None
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                A = [list(cons[q][:3]) for q in (i, j, k)]
                sol = solve3(A, [cons[q][3] for q in (i, j, k)])
                if sol is None or sol[2] <= 0:
                    continue
                if all(a * sol[0] + b * sol[1] + c * sol[2] <= d + 1e-6 for a, b, c, d in cons):
                    if best is None or sol[2] > best[2]:
                        best = sol
    cx, cy, t = best
    return cx - aspect * t, cy - t, cx + aspect * t, cy + t


def centred_rect(quad, centre, aspect=None):
    """Largest axis-aligned rectangle inside a convex quad centred on `centre` (where the photo's centre lands, so
    the composition stays): width/height = aspect, or the largest area when aspect is None. -> (x0, y0, x1, y1)."""
    n = len(quad)
    area2 = sum(quad[i][0] * quad[(i + 1) % n][1] - quad[(i + 1) % n][0] * quad[i][1] for i in range(n))
    cons = []  # |nx| a + |ny| b <= d, with a, b the half-width and half-height
    for i in range(n):
        (x0, y0), (x1, y1) = quad[i], quad[(i + 1) % n]
        nx, ny = (y1 - y0), -(x1 - x0)
        if area2 < 0:
            nx, ny = -nx, -ny
        L = math.hypot(nx, ny); nx, ny = nx / L, ny / L
        cons.append((abs(nx), abs(ny), nx * (x0 - centre[0]) + ny * (y0 - centre[1])))
    if aspect:
        b = min(d / (p * aspect + q) for p, q, d in cons)
        a = aspect * b
    else:
        cands = []
        for p, q, d in cons:  # best a*b on each constraint line, and the corners where two meet
            if p > 1e-9 and q > 1e-9:
                cands.append((d / (2 * p), d / (2 * q)))
        for i in range(n):
            for j in range(i + 1, n):
                (p1, q1, d1), (p2, q2, d2) = cons[i], cons[j]
                det = p1 * q2 - p2 * q1
                if abs(det) > 1e-12:
                    cands.append(((d1 * q2 - d2 * q1) / det, (p1 * d2 - p2 * d1) / det))
        a, b = max(((a, b) for a, b in cands if a > 0 and b > 0 and all(p * a + q * b <= d + 1e-6 for p, q, d in cons)),
                   key=lambda t: t[0] * t[1])
    return centre[0] - a, centre[1] - b, centre[0] + a, centre[1] + b


def rotated_crop(W, H, angle, aspect):
    """Largest rectangle (width/height = aspect) centred in a W x H photo rotated by angle: (w, h)."""
    a = math.radians(abs(angle))
    h = min(W / (aspect * math.cos(a) + math.sin(a)), H / (aspect * math.sin(a) + math.cos(a)))
    return aspect * h, h


def free_rect(quad, W, H):
    """Largest-area rectangle of any aspect inside quad: scan aspect ratios around the photo's, refine."""
    best = None
    r0 = W / H
    for k in range(-40, 41):
        r = r0 * math.exp(k * 0.02)
        x0, y0, x1, y1 = largest_rect(quad, r)
        a = (x1 - x0) * (y1 - y0)
        if best is None or a > best[0]:
            best = (a, (x0, y0, x1, y1))
    return best[1]


# ---------------------------------------------------------------- drawing

def draw_line(img, w, h, p0, p1, col, thick=1):
    x0, y0 = p0; x1, y1 = p1
    n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
    for i in range(n + 1):
        t = i / n
        x, y = int(x0 + (x1 - x0) * t), int(y0 + (y1 - y0) * t)
        for dy in range(-thick + 1, thick):
            for dx in range(-thick + 1, thick):
                if 0 <= x + dx < w and 0 <= y + dy < h:
                    img[y + dy][x + dx] = col


def warp_preview(P, w, h, Hfull, sx, sy, rect, out_w):
    """The predicted result: the crop `rect` (full-res) of the photo under Hfull, sampled from the analysis copy."""
    x0, y0, x1, y1 = rect
    k = out_w / (x1 - x0)
    ow, oh = out_w, max(1, int((y1 - y0) * k))
    Hi = inverse(Hfull)
    img = []
    for j in range(oh):
        row = []
        for i in range(ow):
            X, Y = apply(Hi, x0 + (i + 0.5) / k, y0 + (j + 0.5) / k)
            u, v = X * sx - 0.5, Y * sy - 0.5
            iu, iv = int(math.floor(u)), int(math.floor(v))
            if 0 <= iu < w - 1 and 0 <= iv < h - 1:
                fu, fv = u - iu, v - iv
                a, b, c, d = P[iv][iu], P[iv][iu + 1], P[iv + 1][iu], P[iv + 1][iu + 1]
                row.append(tuple(int((a[q] * (1 - fu) + b[q] * fu) * (1 - fv) + (c[q] * (1 - fu) + d[q] * fu) * fv + 0.5)
                                 for q in range(3)))
            else:
                row.append((255, 0, 255))  # would be empty: the crop should never show this
        img.append(row)
    for g in range(1, 8):  # grid every 1/8 of the width / height
        X = int(ow * g / 8); Yg = int(oh * g / 8)
        for j in range(oh):
            img[j][X] = tuple((p + 255) // 2 for p in img[j][X])
        for i in range(ow):
            img[Yg][i] = tuple((p + 255) // 2 for p in img[Yg][i])
    return ow, oh, img


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("photo"); ap.add_argument("outdir")
    ap.add_argument("--mode", default="auto", choices=["auto", "horizon", "rotate", "verticals"])
    ap.add_argument("--amount", default="auto",
                    help="fraction of the pitch (convergence) to correct, 0..1; auto = 1 up to 10 deg of pitch, easing "
                         "to 0.85 at 20 deg so steep upward shots keep a little convergence. Roll is always fixed fully")
    ap.add_argument("--focal", type=float, help="35 mm-equivalent focal length in mm (default: EXIF, else 28)")
    ap.add_argument("--aspect", default="keep", help="crop: keep (the photo's), free (largest area) or W:H")
    ap.add_argument("--crop", default="centre", choices=["centre", "max"],
                    help="centre: keep the photo's centre in the middle (the composition stays); max: the largest "
                         "clean rectangle anywhere (more pixels, but a steep correction can shift the framing)")
    ap.add_argument("--level", action="append", default=[], metavar="X1,Y1,X2,Y2",
                    help="a line that should be level (full-image coords); repeatable. One: the horizon for a rotation. "
                         "Two or more on a facade or back wall seen square-on, with verticals: also turn the camera "
                         "square to it (yaw), so those lines come out level too")
    ap.add_argument("--plumb", action="append", default=[], metavar="X1,Y1,X2,Y2",
                    help="a line that should be vertical; one gives the roll, two or more the vanishing point too")
    ap.add_argument("--distortion", type=float, default=0.0,
                    help="first remove lens distortion with filter.lensCorrection (positive = barrel, the bowing of "
                         "wide lenses; try 5..30 and keep the value with the lowest verticals fitRms)")
    ap.add_argument("--max-side", type=int, default=1600, help="analysis size (px, long side)")
    ap.add_argument("--grad", type=float, default=6.0, help="edge strength (levels/px) a line needs")
    ap.add_argument("--min-length", type=float, default=0.04, help="shortest segment, as a fraction of the long side")
    ap.add_argument("--vertical-tol", type=float, default=30.0, help="degrees from vertical a 'vertical' may lean")
    ap.add_argument("--smart", action="store_true", help="convert to a smart object first: the original stays embedded, "
                                                         "the lens fix becomes an editable smart filter")
    ap.add_argument("--keep-pixels", action="store_true", help="crop with deleteCroppedPixels false (Reveal All gets them back)")
    ap.add_argument("--verify", action="store_true", help="only measure the photo (e.g. the corrected export)")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    W, H, apath, w, h = render(a.photo, a.outdir, a.max_side, a.distortion)
    sx, sy = w / W, h / H
    _, _, P = pngio.read(apath)
    Y = [lum(*p) for row in P for p in row]
    min_len = max(12, a.min_length * max(w, h))
    segs = segments(Y, w, h, a.grad, min_len)
    f35, fsrc = (a.focal, "given") if a.focal else exif_focal35(a.photo)
    if not f35:
        f35, fsrc = 28.0, "assumed"
    f_full = f35 * math.hypot(W, H) / FRAME_DIAG_MM
    f_an = f35 * math.hypot(w, h) / FRAME_DIAG_MM
    cx, cy, scale = w / 2, h / 2, max(w, h) / 2

    # verticals: detected, or the plumb lines given
    plumbs = [manual_segment(s, sx, sy) for s in a.plumb]
    vcand = plumbs or [s for s in segs if abs(s["angle"] - 90) < a.vertical_tol]
    vp, inl = (None, [])
    if len(vcand) >= 2:
        vp, inl = vanishing_point(vcand, cx, cy, scale)
    vlen = sum(vcand[i]["length"] for i in inl)
    vert = None
    if vp and (plumbs or (len(inl) >= 4 and vlen >= 1.2 * h)):
        roll_v, pitch_v = camera_tilt(vp, scale, f_an)
        vert = {"roll": roll_v, "pitch": pitch_v, "segments": len(inl), "length": round(vlen / h, 2),
                "edgeLean": [edge_lean(vp, -w / 2 / scale), edge_lean(vp, w / 2 / scale)],
                "fitRms": fit_rms(vcand, inl, vp, cx, cy, scale),
                "vp": None if abs(vp[2]) < 1e-9 else [round((vp[0] / vp[2] * scale + cx) / sx, 1),
                                                       round((vp[1] / vp[2] * scale + cy) / sy, 1)]}
    elif len(plumbs) == 1:
        s = plumbs[0]
        lean = -(s["angle"] - 90)
        vert = {"roll": lean, "pitch": 0.0, "segments": 1, "length": round(s["length"] / h, 2),
                "edgeLean": [lean, lean], "fitRms": 0.0, "vp": None}

    levels = [manual_segment(s, sx, sy) for s in a.level]
    if levels:
        L = max(levels, key=lambda s: s["length"])
        ang = (L["angle"] + 90) % 180 - 90
        hz = {"angle": ang, "span": round(L["length"] / w, 2), "parts": levels, "manual": True}
    else:
        hz = horizon(segs, w)
        if not hz or hz["span"] < 0.5:
            soft = soft_horizon(Y, w, h)
            if soft and (not hz or soft["span"] > hz["span"]):
                hz = soft
    hz_ok = hz is not None and (hz.get("manual") or hz["span"] >= 0.6 or (hz["span"] >= 0.3 and not contradicted(hz, segs, w)))

    # decide
    mode, reason = a.mode, ""
    if mode == "auto":
        long_hz = hz_ok and (hz.get("manual") or hz["span"] >= 0.6)
        if vert and abs(vert["pitch"]) > 25 and not plumbs:
            mode, reason = "none", (f"steep {abs(vert['pitch']):.0f} deg shot up or down: the convergence looks "
                                    "deliberate; --mode verticals forces it, --mode rotate fixes only the roll")
        elif vert and (plumbs or len(levels) >= 2 or vert["length"] >= 2.5 or (vert["length"] >= 1.5 and not long_hz)):
            mode, reason = "verticals", f"{vert['segments']} verticals ({vert['length']} x the image height)"
        elif hz_ok:
            mode, reason = "horizon", f"straight horizon across {hz['span']:.0%} of the width"
        elif vert:
            mode, reason = "verticals", f"only {vert['segments']} verticals: check the result"
        else:
            mode, reason = "none", "no reliable straight lines; give --level or --plumb lines"
    if mode == "horizon" and not hz_ok:
        sys.exit("error: no straight horizon found (span < 30 %); give --level X1,Y1,X2,Y2")
    if mode in ("rotate", "verticals") and not vert:
        sys.exit("error: not enough verticals; give two or more --plumb lines")
    if mode == "verticals" and vert and (vert["vp"] is None or abs(vert["pitch"]) < 0.3) and len(levels) < 2:
        mode, reason = "rotate", (reason + "; " if reason else "") + "verticals are parallel: rotation only"
    tilt = {"horizon": abs(hz["angle"]) if hz else 0, "rotate": abs(vert["roll"]) if vert else 0,
            "verticals": max(abs(vert["roll"]), abs(vert["pitch"])) if vert else 0}.get(mode, 0)
    if mode != "none" and tilt < 0.05 and not a.verify:
        mode, reason = "none", f"already straight (largest tilt {tilt:.3f} deg)"

    stats = {"size": [W, H], "analysis": [w, h], "focal35": round(f35, 1), "focalSource": fsrc, "segments": len(segs),
             "horizon": None if not hz else {"angle": round(hz["angle"], 3), "span": round(hz["span"], 2),
                                             "pieces": len(hz["parts"]), "soft": bool(hz.get("soft")),
                                             "usable": bool(hz_ok)},
             "verticals": None if not vert else {k: (round(v, 3) if isinstance(v, float) else v) for k, v in vert.items()}}

    # overlay of what was measured
    img = [list(row) for row in P]
    for s in segs:
        if min(s["angle"], 180 - s["angle"]) < 10:
            draw_line(img, w, h, s["p0"], s["p1"], (255, 220, 0))
    if hz:
        for s in hz["parts"]:
            draw_line(img, w, h, s["p0"], s["p1"], (40, 120, 255), 2)
    for i in inl:
        draw_line(img, w, h, vcand[i]["p0"], vcand[i]["p1"], (0, 230, 60), 2)
    pngio.write(os.path.join(a.outdir, "lines.png"), w, h, img)

    if a.verify:
        stats["verify"] = True
        print(json.dumps(stats))
        return
    if mode == "none":
        stats.update({"mode": mode, "reason": reason})
        print(json.dumps(stats))
        return

    aspect = W / H
    if a.aspect not in ("keep", "free"):
        p, q = a.aspect.split(":"); aspect = float(p) / float(q)
    steps = [{"command": "layer.smartObjects.convertToSmartObject", "params": {}}] if a.smart else []
    if a.distortion:
        steps.append(lens_step(a.distortion))
    if mode in ("horizon", "rotate"):
        ang = hz["angle"] if mode == "horizon" else -vert["roll"]
        # image.crop's angle turns the crop box clockwise around its centre, so the content turns counter-clockwise
        # by the same angle: a horizon falling to the right (positive angle, y down) needs exactly that angle
        if a.aspect == "free":
            r = math.radians(ang)
            quad = [apply([[math.cos(r), math.sin(r), 0], [-math.sin(r), math.cos(r), 0], [0, 0, 1]], x - W / 2, y - H / 2)
                    for x, y in ((0, 0), (W, 0), (W, H), (0, H))]
            x0, y0, x1, y1 = free_rect(quad, W, H)
            cw, ch = x1 - x0, y1 - y0
        else:
            cw, ch = rotated_crop(W, H, ang, aspect)
        inset = 2 + (0.01 * min(cw, ch) if a.distortion < 0 else 0)  # resampled edge; pincushion fix leaves slivers
        cw, ch = int(cw - inset), int(ch - inset)
        crop = {"x": round(W / 2 - cw / 2), "y": round(H / 2 - ch / 2), "width": cw, "height": ch, "angle": round(ang, 3)}
        if a.keep_pixels:
            crop["deleteCroppedPixels"] = False
        steps.append({"command": "image.crop", "params": crop})
        r = math.radians(-ang)
        Hfull = [[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]]
        Hfull = matmul([[1, 0, W / 2], [0, 1, H / 2], [0, 0, 1]], matmul(Hfull, [[1, 0, -W / 2], [0, 1, -H / 2], [0, 0, 1]]))
        rect = (crop["x"], crop["y"], crop["x"] + cw, crop["y"] + ch)
        stats.update({"mode": mode, "reason": reason, "rotate": round(ang, 3)})
    else:
        amount = a.amount
        if amount == "auto":
            p = abs(vert["pitch"])
            amount = 1.0 if p <= 10 else 0.85 if p >= 20 else 1.0 - 0.15 * (p - 10) / 10
        amount = float(amount)
        yaw = frontal_yaw(a.level, W, H, f_full, vert["roll"], vert["pitch"] * amount) if len(a.level) >= 2 else 0.0
        Hm = rectify(W, H, f_full, vert["roll"], vert["pitch"], amount, yaw)
        depth = [Hm[2][0] * x + Hm[2][1] * y + Hm[2][2] for x, y in ((0, 0), (W, 0), (W, H), (0, H))]
        if min(depth) < 0.2 * max(depth):
            sys.exit(f"error: a {abs(vert['pitch'] * amount):.0f} deg correction is too strong for this field of view "
                     "(the frame would wrap round); lower --amount or use --mode rotate")
        quad = [apply(Hm, x, y) for x, y in ((0, 0), (W, 0), (W, H), (0, H))]
        if a.crop == "centre":
            x0, y0, x1, y1 = centred_rect(quad, apply(Hm, W / 2, H / 2), None if a.aspect == "free" else aspect)
        else:
            x0, y0, x1, y1 = free_rect(quad, W, H) if a.aspect == "free" else largest_rect(quad, aspect)
        # centre the result on the canvas, so the transform alone already looks right in the app
        dx, dy = W / 2 - (x0 + x1) / 2, H / 2 - (y0 + y1) / 2
        Hm = matmul([[1, 0, dx], [0, 1, dy], [0, 0, 1]], Hm)
        quad = [[round(x + dx, 2), round(y + dy, 2)] for x, y in quad]
        inset = 2 + (0.01 * min(x1 - x0, y1 - y0) if a.distortion < 0 else 0)
        cw, ch = int(x1 - x0 - inset), int(y1 - y0 - inset)
        crop = {"x": round(W / 2 - cw / 2), "y": round(H / 2 - ch / 2), "width": cw, "height": ch}
        if a.keep_pixels:
            crop["deleteCroppedPixels"] = False
        steps.append({"command": "edit.transform", "params": {"rect": [0, 0, W, H], "quad": quad}})
        steps.append({"command": "image.crop", "params": crop})
        Hfull = Hm
        rect = (crop["x"], crop["y"], crop["x"] + cw, crop["y"] + ch)
        stats.update({"mode": mode, "reason": reason, "roll": round(vert["roll"], 3), "pitch": round(vert["pitch"], 3),
                      "amount": round(amount, 3), "yaw": round(yaw, 3), "quad": quad})
    stats["crop"] = [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]
    stats["kept"] = round((rect[2] - rect[0]) * (rect[3] - rect[1]) / (W * H), 3)
    json.dump(steps, open(os.path.join(a.outdir, "steps.json"), "w"), indent=1)
    ow, oh, prev = warp_preview(P, w, h, Hfull, sx, sy, rect, min(1200, w))
    pngio.write(os.path.join(a.outdir, "preview.png"), ow, oh, prev)
    stats["steps"] = os.path.join(a.outdir, "steps.json")
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
