#!/usr/bin/env python3
"""Borrow a feature from another frame of the same shoot: open closed eyes with the eyes from a frame where they're
open, swap a smile, replace a head in a group shot. Measures what a retoucher would otherwise eyeball, and plans the
PhotoCraft steps. Read references/feature-swap.md first.

  feature_swap.py donors TARGET [--dir DIR ...] [--within MIN] [--any-camera] [--max N]
  feature_swap.py align  --pair DX,DY=TX,TY [--pair ...] [--affine] [--layer ID]
  feature_swap.py mask   --eye IX,IY=OX,OY [--eye ...] [--layer ID] [--replace] [--steps FILE]
                         [--viz IMAGE ... --out viz.png]
  feature_swap.py tone   WITHOUT WITH (--eye IX,IY=OX,OY ... | --sample X,Y[,R] ...) [--per-eye] [--white X,Y[,R]]
                         [--layer ID] [--steps FILE]

donors  the images next to TARGET (and in --dir) from the same camera, nearest in capture time first, with size and
        colour profile (Spotlight metadata). Frames minutes apart are the candidates; edits of a file (its name plus
        -suffix) carry the original's capture time and are labelled as such.
align   the transform that puts each donor point on its target point: rotation + uniform scale + shift, least
        squares over all pairs (--affine: a full affine, 3+ pairs; it can shear, so only when the similarity leaves
        large errors). Donor points are the donor file's own pixels, which is where the donor layer sits after
        layer.copyToDocument with the default offset [0, 0]. Prints edit.transform params and the error at each pair.
        Fit both eyes together: their spacing and tilt then come from one real face. A few px of error is normal
        when the target's eyes are closed or squinting (that moves the corners); fitting each eye to its own corners
        copies the squint's tilt onto the open eye.
mask    the layer mask for eyes: an almond along each eye from its inner corner (nose side) to its outer corner, in
        the target's pixels, sized from the eye's width. It covers the open eye with its lashes and lid margin, and
        the target's closed lash line under it at full opacity out past the corners, but not the socket shading,
        brow or under-eye of the donor. Writes select.lasso + layer.layerMask.revealSelection steps for pc.py
        script; --viz draws the outline (yellow: the selection edge, cyan: where it is fully opaque) on crops of the
        given images, e.g. an export with the donor visible and one without, to check before applying.
tone    measures skin around the feature in two exports of the target document, same size and alignment: WITHOUT
        (donor layer hidden) and WITH (donor visible, no mask yet). Per channel, a Curves that scales the donor like
        a change of exposure (the darks keep their ratio to the skin, so lashes and iris keep their contrast) takes
        the donor's skin to the target's. It reports what is left at each sample, whether the donor's eye highlights
        clip, and what the curve does to an eye white (--white), and prints steps for a Curves layer clipped to the
        donor, so the match stays editable. --per-eye: one curve per eye, each masked to a soft box around its eye,
        for light that differs across the face. Measure in the target document: a donor in another colour profile
        (Display P3 vs sRGB) was converted when it was copied in, so its file's numbers no longer apply.

Coordinates are full-image pixels of the target document unless stated otherwise.
"""
import argparse
import atexit
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pc
import pngio

TMP = tempfile.mkdtemp(prefix="feature_swap-")
atexit.register(shutil.rmtree, TMP, True)
IMAGES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp", ".psd", ".dng", ".nef", ".cr2", ".cr3",
          ".arw", ".raf", ".orf", ".rw2"}
# Skin samples around an eye for `tone --eye`, in eye widths: u along inner -> outer corner, v up (toward the brow).
# Below the eye and toward the nose; above it, brow hair and the lid crease differ too much between frames.
EYE_SAMPLES = [(0.15, -0.55), (0.5, -0.6), (0.9, -0.55), (-0.35, 0.0)]


def die(msg):
    sys.exit(f"error: {msg}")


def point(s, radius=None):
    try:
        v = [float(t) for t in s.split(",")]
    except ValueError:
        v = []
    if len(v) not in (2, 3):
        die(f"expected X,Y or X,Y,R, got {s!r}")
    return v if len(v) == 3 or radius is None else v + [radius]


def pair(s):
    a, sep, b = s.partition("=")
    if not sep:
        die(f"expected X1,Y1=X2,Y2, got {s!r}")
    return point(a)[:2], point(b)[:2]


def crop(path, x, y, w, h):
    """Full-resolution pixels of a rectangle of any image photocraft-cli reads: rows of (r, g, b)."""
    cli = pc.find_cli()
    if not cli:
        die("photocraft-cli not found; `pc.py cli-info` names the one to install")
    out = os.path.join(TMP, f"{len(os.listdir(TMP))}.png")
    r = subprocess.run([str(cli), "run", os.path.expanduser(path), "--cmd", "image.crop", "--params",
                        json.dumps({"x": x, "y": y, "width": w, "height": h}), "--out", out],
                       capture_output=True, text=True)
    if r.returncode or not os.path.exists(out):
        die(f"photocraft-cli could not crop {path}: {(r.stderr or r.stdout).strip()[:300]}")
    return pngio.read(out)[2]


# ---------------------------------------------------------------- donors

MD = sorted(["kMDItemAcquisitionModel", "kMDItemContentCreationDate", "kMDItemPixelHeight", "kMDItemPixelWidth",
             "kMDItemProfileName"])  # mdls -raw prints values in attribute-name order, whatever order they're asked in


def metadata(paths):
    """{path: {camera, time, size, profile}} from Spotlight (macOS); file times when there's no capture date."""
    out = {}
    for i in range(0, len(paths), 200):
        chunk = paths[i:i + 200]
        vals = []
        try:
            r = subprocess.run(["mdls", "-raw", *[x for k in MD for x in ("-name", k)], *chunk],
                               capture_output=True, text=True, timeout=120)
            vals = r.stdout.split("\0") if r.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired):
            pass
        for j, p in enumerate(chunk):
            v = dict(zip(MD, vals[j * len(MD):(j + 1) * len(MD)])) if len(vals) >= (j + 1) * len(MD) else {}
            v = {k: (None if x.strip() in ("", "(null)") else x.strip()) for k, x in v.items()}
            when = None
            try:
                when = datetime.strptime(v.get("kMDItemContentCreationDate") or "", "%Y-%m-%d %H:%M:%S %z").timestamp()
            except ValueError:
                pass
            out[p] = {"camera": v.get("kMDItemAcquisitionModel"),
                      "time": when if when is not None else os.path.getmtime(p),
                      "size": f"{v['kMDItemPixelWidth']}x{v['kMDItemPixelHeight']}"
                      if v.get("kMDItemPixelWidth") and v.get("kMDItemPixelHeight") else "?",
                      "profile": v.get("kMDItemProfileName") or "?"}
    return out


def cmd_donors(a):
    target = os.path.abspath(os.path.expanduser(a.target))
    if not os.path.isfile(target):
        die(f"{target} not found")
    files = [target]
    for d in [os.path.dirname(target)] + [os.path.abspath(os.path.expanduser(d)) for d in a.dir]:
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.splitext(name)[1].lower() in IMAGES and p not in files and os.path.isfile(p):
                files.append(p)
    meta = metadata(files)
    stems = {os.path.splitext(os.path.basename(p))[0] for p in files}
    target_stem = os.path.splitext(os.path.basename(target))[0]
    t = meta[target]
    rows = []
    for p in files[1:]:
        m = meta[p]
        if not a.any_camera and t["camera"] and m["camera"] != t["camera"]:
            continue
        dt = (m["time"] - t["time"]) / 60
        if a.within is not None and abs(dt) > a.within:
            continue
        stem = os.path.splitext(os.path.basename(p))[0]
        base = next((s for s in sorted(stems, key=len, reverse=True)
                     if s != stem and stem.startswith(s) and stem[len(s)] in "-_ "), None)
        if stem.startswith(target_stem) and stem[len(target_stem):][:1] in ("-", "_", " "):
            continue  # an edit of the target itself: the same frame
        rows.append((abs(dt), base is not None, dt, p, m, base))
    rows.sort(key=lambda r: r[:2])
    when = datetime.fromtimestamp(t["time"]).strftime("%Y-%m-%d %H:%M:%S")
    print(f"target  {os.path.basename(target)}  {t['camera'] or '?'}  {t['size']}  {t['profile']}  {when}")
    if not t["camera"] and not a.any_camera:
        print("        (no camera in its metadata: listing every image; capture times may be file times)")
    print(f"{'apart':>8}  {'file':<34} {'camera':<16} {'size':<11} profile")
    for _, _, dt, p, m, base in rows[:a.max]:
        note = f"   edit of {base}" if base else ""
        apart = (f"{dt:+.1f}m" if abs(dt) < 120 else f"{dt / 60:+.1f}h" if abs(dt) < 2880 else f"{dt / 1440:+.0f}d")
        print(f"{apart:>8}  {os.path.basename(p):<34} {(m['camera'] or '?'):<16} {m['size']:<11} {m['profile']}{note}")
    if len(rows) > a.max:
        print(f"... {len(rows) - a.max} more (--max)")
    if not rows:
        print("no other frames from this camera here; try --dir, --any-camera, or ask the user for the shoot's folder")


# ---------------------------------------------------------------- align

def solve3(A, b):
    M = [row[:] + [v] for row, v in zip(A, b)]
    for i in range(3):
        k = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[k] = M[k], M[i]
        if abs(M[i][i]) < 1e-9:
            die("the donor points are on one line: an affine fit needs 3+ points that aren't")
        for r in range(3):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [x - f * y for x, y in zip(M[r], M[i])]
    return [M[i][3] / M[i][i] for i in range(3)]


def fit(pairs, affine):
    """[a, b, c, d, e, f] with x' = a x + c y + e, y' = b x + d y + f (edit.transform's matrix, verified in 0.7.0)."""
    P = [p for p, _ in pairs]
    n = len(pairs)
    if affine:
        A = [[sum(p[0] * p[0] for p in P), sum(p[0] * p[1] for p in P), sum(p[0] for p in P)],
             [sum(p[0] * p[1] for p in P), sum(p[1] * p[1] for p in P), sum(p[1] for p in P)],
             [sum(p[0] for p in P), sum(p[1] for p in P), n]]
        a, c, e = solve3(A, [sum(p[0] * q[0] for p, q in pairs), sum(p[1] * q[0] for p, q in pairs),
                             sum(q[0] for _, q in pairs)])
        b, d, f = solve3(A, [sum(p[0] * q[1] for p, q in pairs), sum(p[1] * q[1] for p, q in pairs),
                             sum(q[1] for _, q in pairs)])
        return [a, b, c, d, e, f]
    pm = sum(complex(*p) for p in P) / n
    qm = sum(complex(*q) for _, q in pairs) / n
    den = sum(abs(complex(*p) - pm) ** 2 for p in P)
    if den < 1e-9:
        die("the donor points coincide")
    k = sum((complex(*q) - qm) * (complex(*p) - pm).conjugate() for p, q in pairs) / den
    t = qm - k * pm
    return [k.real, k.imag, -k.imag, k.real, t.real, t.imag]


def apply(M, p):
    return M[0] * p[0] + M[2] * p[1] + M[4], M[1] * p[0] + M[3] * p[1] + M[5]


def cmd_align(a):
    pairs = [pair(s) for s in a.pair]
    if len(pairs) < (3 if a.affine else 2):
        die(f"need at least {3 if a.affine else 2} --pair")
    M = fit(pairs, a.affine)
    a_, b_, c_, d_ = M[:4]
    T = a_ * a_ + b_ * b_ + c_ * c_ + d_ * d_
    det = a_ * d_ - b_ * c_
    s1 = math.sqrt(max(0.0, (T + math.sqrt(max(0.0, T * T - 4 * det * det))) / 2))
    s2 = abs(det) / s1 if s1 else 0.0
    rows = []
    for p, q in pairs:
        x, y = apply(M, p)
        rows.append({"donor": p, "target": q, "placed": [round(x, 1), round(y, 1)],
                     "error": round(math.hypot(x - q[0], y - q[1]), 2)})
    rms = math.sqrt(sum(r["error"] ** 2 for r in rows) / len(rows))
    scale = math.sqrt(abs(det))
    rot = math.degrees(math.atan2(b_ - c_, a_ + d_))
    warn = []
    if det <= 0:
        warn.append("the fit mirrors the donor: the pairs are probably in different orders")
    if not 0.33 <= scale <= 3 or abs(rot) > 25:
        warn.append("scale or rotation is extreme: check that each --pair joins the same landmark in both photos")
    if len(pairs) == 2 and not a.affine:
        warn.append("two pairs always fit exactly; add a third landmark to see the real error")
    if rms > 4 and len(pairs) > 2:
        warn.append(f"errors of {rms:.1f} px: the pose differs between the frames. Some is normal (closing or "
                    "squinting moves the eye corners, the outer ones most), so look at the result first. Don't fit "
                    "each eye to its own corners: that copies the squint's tilt onto the open eye")
    if a.affine and s2 and s1 / s2 > 1.08:
        warn.append(f"the affine stretches the donor {100 * (s1 / s2 - 1):.0f}% more in one direction than the other, "
                    "which distorts the eyes; prefer the similarity (leave out --affine)")
    params = {"matrix": [round(v, 6) for v in M[:4]] + [round(M[4], 3), round(M[5], 3)]}
    if a.layer is not None:
        params = {"layer": a.layer, **params}
    print(json.dumps({"transform": params, "model": "affine" if a.affine else "similarity",
                      "scale": round(scale, 4), "rotationDeg": round(rot, 2),
                      "note": "rotation is clockwise on screen; run: pc.py exec edit.transform '<transform>'",
                      "pairs": rows, "rmsError": round(rms, 2), "warnings": warn}, indent=1))


# ---------------------------------------------------------------- mask

def frame(I, O):
    """Eye width, unit vector inner -> outer corner, unit vector up (toward the brow, y decreasing)."""
    ex, ey = O[0] - I[0], O[1] - I[1]
    w = math.hypot(ex, ey)
    if w < 4:
        die(f"the eye corners {I} and {O} are {w:.1f} px apart; give the inner and the outer corner")
    u = (ex / w, ey / w)
    v = (u[1], -u[0])
    if v[1] > 0:
        v = (-v[0], -v[1])
    return w, u, v


def almond(I, O, a, shrink=0.0, k=24):
    """Lasso points of a superellipse along the eye; shrink (px) pulls every side in (the opaque core)."""
    w, u, v = frame(I, O)
    u0, u1 = -a.inner * w, (1 + a.outer) * w
    uc, A = (u0 + u1) / 2, (u1 - u0) / 2 - shrink
    up, down = a.up * w - shrink, a.down * w - shrink
    if min(A, up, down) <= 0:
        return w, []
    pts = []
    for i in range(2 * k):
        t = -1 + 2 * i / k if i <= k else 1 - 2 * (i - k) / k
        s = (1 - abs(t) ** a.round) ** (1 / a.round)
        uu, vv = uc + A * t, (up if i <= k else -down) * s
        if i in (0, k) or s > 0:
            pts.append([round(I[0] + uu * u[0] + vv * v[0], 1), round(I[1] + uu * u[1] + vv * v[1], 1)])
    return w, pts


def draw(img, pts, x0, y0, s, col, dash=0):
    H, W = len(img), len(img[0])
    seq = pts + pts[:1]
    run = 0
    for (ax, ay), (bx, by) in zip(seq, seq[1:]):
        ax, ay, bx, by = (ax - x0) * s, (ay - y0) * s, (bx - x0) * s, (by - y0) * s
        n = int(max(abs(bx - ax), abs(by - ay))) + 1
        for i in range(n):
            run += 1
            if dash and (run // dash) % 2:
                continue
            x, y = int(ax + (bx - ax) * i / n), int(ay + (by - ay) * i / n)
            for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                if 0 <= x + dx < W and 0 <= y + dy < H:
                    img[y + dy][x + dx] = col


def viz(images, eyes, shapes, cores, out, s):
    xs = [p[0] for sh in shapes for p in sh]
    ys = [p[1] for sh in shapes for p in sh]
    m = 0.3 * (max(xs) - min(xs)) / max(1, len(shapes))
    x0, y0 = max(0, int(min(xs) - m)), max(0, int(min(ys) - m))
    w, h = int(max(xs) + m) - x0 + 1, int(max(ys) + m) - y0 + 1
    panels = []
    for path in images:
        P = crop(path, x0, y0, w, h)
        big = [[P[y // s][x // s] for x in range(len(P[0]) * s)] for y in range(len(P) * s)]
        for sh in shapes:
            draw(big, sh, x0, y0, s, (255, 215, 0))
        for co in cores:
            if co:
                draw(big, co, x0, y0, s, (0, 210, 255), dash=6)
        for I, O in eyes:
            for c in (I, O):
                draw(big, [[c[0] - 0.6, c[1] - 0.6], [c[0] + 0.6, c[1] - 0.6], [c[0] + 0.6, c[1] + 0.6],
                           [c[0] - 0.6, c[1] + 0.6]], x0, y0, s, (255, 40, 40))
        panels.append(big)
    H = max(len(p) for p in panels)
    W = sum(len(p[0]) for p in panels) + 8 * (len(panels) - 1)
    rows = [[(40, 40, 40)] * W for _ in range(H)]
    ox = 0
    for p in panels:
        for y, row in enumerate(p):
            rows[y][ox:ox + len(row)] = row
        ox += len(p[0]) + 8
    pngio.write(out, W, H, rows)
    return [x0, y0, w, h]


def cmd_mask(a):
    eyes = [pair(e) for e in a.eye]
    shapes, cores, feathers = [], [], []
    for I, O in eyes:
        w, pts = almond(I, O, a)
        f = max(1, round(a.feather * w))
        shapes.append(pts)
        cores.append(almond(I, O, a, shrink=f)[1])
        feathers.append(f)
    lid = {"layer": a.layer} if a.layer is not None else {}
    steps = [{"command": "layer.select", "params": lid}] if lid else []
    if a.replace:
        steps.append({"command": "layer.layerMask.delete", "params": lid})
    for i, (pts, f) in enumerate(zip(shapes, feathers)):
        steps.append({"command": "select.lasso", "params": {"points": pts, "mode": "add" if i else "replace", "feather": f}})
    steps.append({"command": "layer.layerMask.revealSelection", "params": lid})
    steps.append({"command": "select.deselect", "params": {}})
    if a.steps:
        with open(os.path.expanduser(a.steps), "w") as fh:
            json.dump(steps, fh)
    res = {"eyes": [{"inner": I, "outer": O, "width": round(frame(I, O)[0], 1), "featherPx": f}
                    for (I, O), f in zip(eyes, feathers)], "steps": a.steps or steps}
    if a.viz:
        if not a.out:
            die("--viz needs --out")
        res["viz"] = {"path": a.out, "crop": viz(a.viz, eyes, shapes, cores, a.out, a.scale), "scale": a.scale}
    print(json.dumps(res) if a.steps else json.dumps(res, indent=1))


# ---------------------------------------------------------------- tone

def disk(P, ox, oy, x, y, r):
    """Mean colour of a disk, without specks more than 3 MADs off its median luminance (a lash, a pore, a hair)."""
    pix = [P[j - oy][i - ox] for j in range(int(y - r), int(y + r) + 1) for i in range(int(x - r), int(x + r) + 1)
           if (i + 0.5 - x) ** 2 + (j + 0.5 - y) ** 2 <= r * r and 0 <= j - oy < len(P) and 0 <= i - ox < len(P[0])]
    if not pix:
        die(f"sample {x:g},{y:g} is outside the image")
    Y = [imgops.lum(*p) for p in pix]
    med = sorted(Y)[len(Y) // 2]
    mad = max(1.0, sorted(abs(v - med) for v in Y)[len(Y) // 2])
    keep = [p for p, v in zip(pix, Y) if abs(v - med) <= 3 * mad]
    return [sum(p[c] for p in keep) / len(keep) for c in range(3)]


def eye_samples(I, O):
    w, u, v = frame(I, O)
    return [[I[0] + (su * u[0] + sv * v[0]) * w, I[1] + (su * u[1] + sv * v[1]) * w, max(3.0, 0.07 * w)]
            for su, sv in EYE_SAMPLES]


def eye_box(I, O):
    """select.rect params for a soft box around one eye: the mask of that eye's own Curves layer (--per-eye)."""
    w, u, v = frame(I, O)
    cs = [(I[0] + (su * u[0] + sv * v[0]) * w, I[1] + (su * u[1] + sv * v[1]) * w)
          for su in (-0.3, 1.3) for sv in (-0.6, 0.6)]
    x0, y0 = min(c[0] for c in cs), min(c[1] for c in cs)
    x1, y1 = max(c[0] for c in cs), max(c[1] for c in cs)
    return {"x": round(x0), "y": round(y0), "width": round(x1 - x0), "height": round(y1 - y0),
            "feather": max(1, round(0.1 * w))}


def opening(P, ox, oy, I, O):
    """Per channel, the 98th percentile of the pixels inside the eye opening: the donor's eye whites and catchlight."""
    w, u, v = frame(I, O)
    pix = []
    for j in range(len(P)):
        for i in range(len(P[0])):
            dx, dy = i + ox + 0.5 - I[0], j + oy + 0.5 - I[1]
            if 0.1 * w < dx * u[0] + dy * u[1] < 0.9 * w and abs(dx * v[0] + dy * v[1]) < 0.15 * w:
                pix.append(P[j][i])
    return [imgops.percentile([p[c] for p in pix], 98) for c in range(3)] if pix else None


def fit_tone(rows, a, white=None, bright=None):
    """Curves taking the kept samples' donor colour to the target's: (curves, luts, highlight slope, warnings).
    white: the donor's eye white (RGB); bright: the 98th percentile of the donor's eye opening, per channel."""
    # A sample where the two frames disagree (brow hair, a lash, a shadow only one frame has) is left out.
    ratio = [imgops.lum(*s["target"]) / max(1.0, imgops.lum(*s["donor"])) for s in rows]
    mid = sorted(ratio)[len(ratio) // 2]
    for s, q in zip(rows, ratio):
        s["kept"] = abs(q / mid - 1) <= a.tolerance
    keep = [s for s in rows if s["kept"]]
    Tm = [sum(s["target"][c] for s in keep) / len(keep) for c in range(3)]
    Dm = [sum(s["donor"][c] for s in keep) / len(keep) for c in range(3)]
    curves, luts, warn = {}, [], []
    for c, name in enumerate(("red", "green", "blue")):
        x = min(250, max(5, round(Dm[c])))
        y = min(250, max(5, round(Dm[c] + a.amount * (Tm[c] - Dm[c]))))
        # gain: a second point halfway keeps everything below the skin at the skin's ratio, like a change of
        # exposure, so lashes, iris and lid crease keep their contrast to the skin. A single point bends the curve
        # and lifts the darks more than the skin (2.1x vs 1.8x on a donor 1.8x darker): the eye goes pale and flat.
        curves[name] = ([[0, 0], [round(x / 2), round(y / 2)], [x, y], [255, 255]] if a.shape == "gain"
                        else [[0, 0], [x, y], [255, 255]])
        lut = imgops.spline_lut(curves[name])
        luts.append(lut)
        if any(lut[i + 1] < lut[i] for i in range(255)):
            warn.append(f"the {name} curve bends back: the frames differ too much in exposure for one curve")
        clip = next((i for i in range(256) if lut[i] >= 255), 256)
        if (bright[c] >= clip) if bright else clip < 200:
            warn.append(f"{name} reaches 255 at donor value {clip}" + (f" and the donor's eye whites reach "
                        f"{bright[c]:.0f}: they go flat white" if bright else ": brighter donor pixels (eye whites, "
                        "catchlights) go flat there; check the whites (--white)"))
    for s in rows:
        after = [imgops.lut_f(luts[c], s["donor"][c]) for c in range(3)]
        s["deltaE"] = round(math.dist(imgops.lab(*after, space=a.space), imgops.lab(*s["target"], space=a.space)), 1)
        s["after"] = after
        for k in ("target", "donor", "after"):
            s[k] = [round(t) for t in s[k]]
    if len(keep) < len(rows):
        warn.append(f"{len(rows) - len(keep)} sample(s) left out: the frames disagree there (see kept: false)")
    if max(s["deltaE"] for s in keep) > 6:
        warn.append("kept samples still differ by more than 6 dE after the curve: the light falls differently across "
                    "the feature. With two eyes, --per-eye gives each its own curve; else sample next to the seam only")
    # How much of the donor's highlight contrast survives (eye whites, catchlights): the curve's slope up there.
    ref = (imgops.lum(*white) if white else imgops.lum(*bright) if bright
           else sum(imgops.lum(*s["donor"]) for s in keep) / len(keep) + 45)
    xr = int(min(247, max(8, ref)))
    slope = sum((luts[c][xr + 8] - luts[c][xr - 8]) / 16 for c in range(3)) / 3
    if slope < 0.6:
        warn.append(f"the curve keeps {slope:.0%} of the donor's highlight contrast: its eye whites will look flat. "
                    "A donor exposed closer to the target is better; otherwise judge by eye and add at most a gentle "
                    "composite curve (see feature-swap.md), never a strong one")
    return curves, luts, slope, warn


def cmd_tone(a):
    eyes = [pair(e) for e in a.eye]
    if a.per_eye and (a.sample or len(eyes) < 2):
        die("--per-eye takes two or more --eye and no --sample")
    groups = ([eye_samples(I, O) for I, O in eyes] if a.per_eye else
              [[point(s, 6.0) for s in a.sample] + [p for I, O in eyes for p in eye_samples(I, O)]])
    if not groups[0]:
        die("give --eye or --sample")
    white = point(a.white, 3.0) if a.white else None
    pts = [p for g in groups for p in g] + ([white] if white else []) + \
          [[*c, 0.25 * frame(I, O)[0]] for I, O in eyes for c in (I, O)]
    x0, y0 = max(0, int(min(p[0] - p[2] for p in pts)) - 2), max(0, int(min(p[1] - p[2] for p in pts)) - 2)
    x1, y1 = int(max(p[0] + p[2] for p in pts)) + 3, int(max(p[1] + p[2] for p in pts)) + 3
    Tp = crop(a.without, x0, y0, x1 - x0, y1 - y0)
    Dp = crop(a.with_, x0, y0, x1 - x0, y1 - y0)
    wd = disk(Dp, x0, y0, *white) if white else None
    wg = 0  # the group whose curve judges the eye white: the nearest eye
    if white and a.per_eye:
        wg = min(range(len(eyes)), key=lambda i: math.dist(white[:2], [(eyes[i][0][0] + eyes[i][1][0]) / 2,
                                                                       (eyes[i][0][1] + eyes[i][1][1]) / 2]))
    if a.per_eye:
        boxes = [eye_box(I, O) for I, O in eyes]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                p, q = boxes[i], boxes[j]
                if p["x"] < q["x"] + q["width"] and q["x"] < p["x"] + p["width"] and \
                        p["y"] < q["y"] + q["height"] and q["y"] < p["y"] + p["height"]:
                    die("the per-eye boxes overlap; match both eyes with one curve (leave out --per-eye)")
    lid = {"layer": a.layer} if a.layer is not None else {}
    out, steps, warn = [], [], []
    for gi, g in enumerate(groups):
        rows = [{"at": [round(x, 1), round(y, 1)], "r": round(r, 1), "target": disk(Tp, x0, y0, x, y, r),
                 "donor": disk(Dp, x0, y0, x, y, r)} for x, y, r in g]
        ge = eyes[gi:gi + 1] if a.per_eye else eyes
        br = [opening(Dp, x0, y0, I, O) for I, O in ge]
        br = [max(b[c] for b in br if b) for c in range(3)] if any(br) else None
        curves, luts, slope, w = fit_tone(rows, a, wd if gi == wg else None, br)
        name = a.name if len(groups) == 1 else f"{a.name} {gi + 1}"
        item = {"name": name, "curves": curves, "samples": rows, "highlightContrast": round(slope, 2)}
        if br:
            item["eyeHighlights"] = [round(t) for t in br]
        if white and gi == wg:
            after = [imgops.lut_f(luts[c], wd[c]) for c in range(3)]
            L, A, B = imgops.lab(*after, space=a.space)
            item["eyeWhite"] = {"donor": [round(t) for t in wd], "after": [round(t) for t in after],
                                "lab": [round(L, 1), round(A, 1), round(B, 1)]}
            if L > 93 or max(after) >= 253:
                w.append("the eye white goes to paper white: it will glow. Use --amount < 1 or a donor closer in exposure")
            if A > 7 or B > 18:
                w.append(f"the eye white turns {'pink' if A > 7 else 'orange'} (a* {A:.0f}, b* {B:.0f}); a white in "
                         "warm light reads at most about a* 4, b* 12. Check --white is on the white, not a lash")
            if B < -3:
                w.append(f"the eye white turns blue (b* {B:.0f})")
        out.append(item)
        warn += [f"{name}: {x}" for x in w] if len(groups) > 1 else w
        steps += [{"command": "layer.select", "params": lid}] if lid else []
        if a.per_eye:
            steps.append({"command": "select.rect", "params": boxes[gi]})
        steps += [{"command": "layer.newAdjustmentLayer.curves", "params": curves},
                  {"command": "layer.setProps", "params": {"clipped": True, "name": name}}]
        if a.per_eye:
            steps.append({"command": "select.deselect", "params": {}})
    if a.steps:
        with open(os.path.expanduser(a.steps), "w") as fh:
            json.dump(steps, fh)
    res = out[0] if len(out) == 1 else {"eyes": out}
    res["steps"] = a.steps or steps
    res["warnings"] = warn
    print(json.dumps(res, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="sub", required=True)

    p = sub.add_parser("donors", help="frames of the same shoot, nearest in capture time first")
    p.add_argument("target")
    p.add_argument("--dir", action="append", default=[], help="also look here (repeatable)")
    p.add_argument("--within", type=float, help="only frames this many minutes from the target")
    p.add_argument("--any-camera", action="store_true", help="also list images from other cameras or none")
    p.add_argument("--max", type=int, default=30)
    p.set_defaults(fn=cmd_donors)

    p = sub.add_parser("align", help="edit.transform params that put donor landmarks on target landmarks")
    p.add_argument("--pair", action="append", default=[], help="DX,DY=TX,TY: a donor point and where it goes")
    p.add_argument("--affine", action="store_true", help="full affine (3+ pairs) instead of rotation + scale + shift")
    p.add_argument("--layer", type=int, help="the donor layer's id, put into the params")
    p.set_defaults(fn=cmd_align)

    p = sub.add_parser("mask", help="select.lasso + reveal steps for an eye mask, from the eye corners")
    p.add_argument("--eye", action="append", default=[], required=True,
                   help="IX,IY=OX,OY: inner corner (nose side) = outer corner, target pixels (repeatable)")
    p.add_argument("--layer", type=int, help="the donor layer's id")
    p.add_argument("--replace", action="store_true", help="delete the layer's existing mask first")
    p.add_argument("--up", type=float, default=0.34, help="reach above the corner line, in eye widths")
    p.add_argument("--down", type=float, default=0.24, help="reach below the corner line, in eye widths")
    p.add_argument("--inner", type=float, default=0.06, help="past the inner corner, in eye widths")
    p.add_argument("--outer", type=float, default=0.14, help="past the outer corner, in eye widths")
    p.add_argument("--round", type=float, default=2.4, help="shape exponent: 2 = ellipse, higher = blunter ends")
    p.add_argument("--feather", type=float, default=0.07, help="feather, in eye widths")
    p.add_argument("--steps", help="write the steps here for pc.py script")
    p.add_argument("--viz", action="append", default=[], help="draw the outline on a crop of this image (repeatable)")
    p.add_argument("--out", help="where --viz writes its PNG")
    p.add_argument("--scale", type=int, default=4)
    p.set_defaults(fn=cmd_mask)

    p = sub.add_parser("tone", help="Curves that match the donor's skin to the target's, clipped to the donor")
    p.add_argument("without", help="export of the target document with the donor layer hidden")
    p.add_argument("with_", metavar="with", help="export with the donor layer visible, before its mask")
    p.add_argument("--eye", action="append", default=[], help="IX,IY=OX,OY: sample the skin around this eye")
    p.add_argument("--sample", action="append", default=[], help="X,Y[,R]: a skin sample (radius 6 by default)")
    p.add_argument("--white", help="X,Y[,R]: the donor's eye white as placed, to check what the curve does to it")
    p.add_argument("--amount", type=float, default=1.0, help="how much of the measured difference to correct")
    p.add_argument("--shape", choices=["gain", "smooth"], default="gain",
                   help="gain: darks scale like the skin (default); smooth: one point, lifts the darks more")
    p.add_argument("--tolerance", type=float, default=0.12, help="leave out samples this far off the median ratio")
    p.add_argument("--space", choices=["srgb", "p3"], default="srgb", help="the document's colour profile")
    p.add_argument("--per-eye", action="store_true",
                   help="one Curves per eye, each masked to a soft box around its eye (when the light differs)")
    p.add_argument("--layer", type=int, help="the donor layer's id (selected first, so the Curves lands above it)")
    p.add_argument("--name", default="Match donor tone", help="name of the Curves layer")
    p.add_argument("--steps", help="write the steps here for pc.py script")
    p.set_defaults(fn=cmd_tone)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
