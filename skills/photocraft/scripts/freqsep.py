#!/usr/bin/env python3
"""Frequency separation, built and checked: texture (High) and tone (Low) on layers that add back up to the photo.

The photo's texture and its tone go on separate layers, with empty layers between them for evening tone and colour.

  freqsep.py radius crop.png X Y area.json [--sheet sheet.png]   which blur radius splits texture from tone here
  freqsep.py build --radius R --layer ID [--bits 16|8] [--median]             live: the active document in the app
  freqsep.py build --radius R --layer ID --file in.psd --out in-fs.psd        headless (photocraft-cli serve)

What it is for (the professional consensus): a cleanup and tone-evening tool used "very sparingly" in high-end work
(Lindsay Adler), not an everyday one (SLR Lounge calls it "oversold"): beauty, editorial and hero shots, after the
ordinary healing. Texture is fixed on High with hard-edged heals that sample High alone (a soft brush on High
smudges texture: Siyana Kasabova). Tone is evened on the layers between, softly, and colour on a Color-mode layer
(Michael Woloszynowicz). Low is never blurred further or painted (Victoria Behun): that melts shadows into
highlights, and the face's shape with them.

The group it builds, bottom to top, above the untouched photo:
  Low (Gaussian R px)    copy of the photo, blurred by R (--median: Median R, which keeps edges crisper)
  Tone                   empty, Normal: soft heals sampling Current & Below
  Colour                 empty, Color mode: paint sampled from clean skin nearby, 5-20 % opacity
  High (texture)         copy of the photo with Low taken out (Apply Image), Linear Light

Exactness, measured in PhotoCraft 0.7.0 on an 18 MP portrait: in 16-bit, Apply Image of Low inverted, Add, Scale 2,
Offset 0 renders the photo back exactly (mean 0, max 0 on an 18 MP portrait and a face crop). 8-bit can't be exact:
Linear Light needs High at 127.5 wherever the skin has no detail at the radius. The textbook Subtract, Scale 2,
Offset 128 renders every pixel 1-2 levels LIGHTER (+1.49 on average on a face); Offset 127, used here, renders those
pixels 1 level darker: about half of a face's pixels (mean -0.50), every pixel of a smooth gradient (-1.0). So the
document is converted to 16-bit first unless --bits 8. build renders the document with and without the group and
reports the difference ("identity"), and checks that the group shows at all: an opaque layer above it would make
"identical" mean nothing, so build refuses a source covered that way, and a render with High switched to Normal must
change the window.

--layer is the layer holding the finished pixels (after healing, the Healing layer), required when the document has
more than one pixel layer. The ids printed are this session's: a PSD saved and reopened has its layers renumbered
bottom-up, so read them again after reopening (the names are printed with them).

radius: the scale where pore texture ends and tone begins. `radius` measures the skin's detail energy per octave of
scale inside area.json: it falls through the texture scales, bottoms out, and rises again with blotches and the
face's shading. The bottom is where Low keeps none of the texture yet all of the tone (Ben Willmore: "the lowest
radius that still removes all fine detail"). Measured on portraits: 3 px on two faces about 950 px wide, 5 px on a
third with coarser skin, 5.5 px on a child's face 1900 px wide, 1 px on a 450 px face: about face width / 300 for
adult skin, which puts practitioners' 4-8 px at faces of 1200-2400 px. Measure, don't assume.
PhotoCraft's Gaussian Blur radius is the Gaussian's sigma (measured 0.96-1.01 x at radius 1 to 10).
"""
import argparse
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pc
import pngio

SCALES = [0.7, 1, 1.4, 2, 2.8, 4, 5.6, 8, 11.3, 16]


def gauss_exact(src, w, h, s):
    """A true Gaussian (kernel to 3 sigma) for small sigmas, where three box passes quantise the radius too coarsely
    (sigma 0.7 and 1 came out identical); imgops.gauss above 6."""
    if s > 6:
        return imgops.gauss(src, w, h, s)
    r = int(math.ceil(3 * s))
    k = [math.exp(-0.5 * (i / s) ** 2) for i in range(-r, r + 1)]
    t = sum(k)
    k = [v / t for v in k]

    def rows(a, w, h):
        out = []
        for y in range(h):
            row = a[y * w:(y + 1) * w]
            pad = [row[0]] * r + row + [row[-1]] * r
            out.extend(sum(k[j] * pad[x + j] for j in range(2 * r + 1)) for x in range(w))
        return out

    a = imgops._transpose(rows(src, w, h), w, h)
    return imgops._transpose(rows(a, h, w), h, w)


def cmd_radius(a):
    w, h, R, G, B = imgops.load(a.crop)
    cfg = json.load(open(a.area))
    m = imgops.raster(cfg, a.x, a.y, w, h)
    edge = int(2 * SCALES[-1])
    idx = [i for i in range(w * h) if m[i] and edge <= i % w < w - edge and edge <= i // w < h - edge]
    if len(idx) < 400:
        sys.exit(f"error: only {len(idx)} skin pixels at least {edge} px inside the crop; crop wider around the area")
    L = [imgops.lum(r, g, b) for r, g, b in zip(R, G, B)]
    prev, prev_img, bands = 0.0, L, []
    for s in SCALES:
        img = gauss_exact(L, w, h, s)
        d = [prev_img[i] - img[i] for i in idx]
        mu = sum(d) / len(d)
        rms = math.sqrt(sum((v - mu) ** 2 for v in d) / len(d))
        # per octave, so the uneven steps compare: detail energy density at this scale
        bands.append((prev, s, rms, rms / math.sqrt(math.log2(s / prev)) if prev else rms))
        prev, prev_img = s, img
    dens = [b[3] for b in bands]
    k = min(range(1, len(bands) - 1), key=lambda i: dens[i])  # the first band (0-0.7) is mostly noise and JPEG
    # vertex of a parabola through the minimum and its neighbours, in log2(scale)
    xs = [math.log2(bands[j][1]) for j in (k - 1, k, k + 1)]
    ys = [dens[j] for j in (k - 1, k, k + 1)]
    den = (xs[0] - xs[1]) * (xs[0] - xs[2]) * (xs[1] - xs[2])
    A = (xs[2] * (ys[1] - ys[0]) + xs[1] * (ys[0] - ys[2]) + xs[0] * (ys[2] - ys[1])) / den
    Bq = (xs[2] ** 2 * (ys[0] - ys[1]) + xs[1] ** 2 * (ys[2] - ys[0]) + xs[0] ** 2 * (ys[1] - ys[2])) / den
    v = -Bq / (2 * A) if A > 0 else xs[1]
    radius = max(1.0, min(16.0, round(2 ** min(max(v, xs[0]), xs[2]) * 2) / 2))
    out = {"pixels": len(idx), "radius": radius,
           "quiet": [bands[k][0], bands[k][1]],
           "detailPerOctave": {f"{p:g}-{s:g}": round(dv, 2) for p, s, _, dv in bands}}
    warn = []
    if k + 1 >= len(bands) - 1 or dens[-1] < dens[k] * 1.2:
        warn.append("the detail energy doesn't rise again at large scales: the area may hold no tonal variation "
                    "(too small) or be mostly texture; draw it over plain cheek and forehead")
    if k <= 1:
        warn.append("the quietest scale is the finest one: pores are below a pixel at this size (a small face); "
                    "FS has little to separate, healing alone is the better tool")
    if warn:
        out["warnings"] = warn
    if a.sheet:  # the crop's luminance detail, then Low at radius / 1.5, radius, radius x 1.5 (local contrast x6)
        cli = str(pc.find_cli())
        tiles = []
        for r in (0, radius / 1.5, radius, radius * 1.5):
            src = a.crop
            if r:
                src = os.path.join(os.path.dirname(os.path.abspath(a.sheet)), f"_low{r:.2f}.png")
                subprocess.run([cli, "run", a.crop, "--cmd", "filter.blur.gaussianBlur", "--params",
                                json.dumps({"radius": round(r, 2)}), "--out", src], check=True, capture_output=True)
            _, _, R2, G2, B2 = imgops.load(src)
            L2 = [imgops.lum(*p) for p in zip(R2, G2, B2)]
            mu = imgops.gauss(L2, w, h, 12)
            tiles.append([max(0, min(255, int(128 + 6 * (p - q)))) for p, q in zip(L2, mu)])
            if r:
                os.remove(src)
        gap = 6
        W = 4 * w + 3 * gap
        img = [[(255, 255, 255)] * W for _ in range(h)]
        for t, v in enumerate(tiles):
            for y in range(h):
                for x in range(w):
                    g = v[y * w + x]
                    img[y][t * (w + gap) + x] = (g, g, g)
        pngio.write(a.sheet, W, h, img)
        out["sheet"] = "local contrast x6: the crop, then Low at radius / 1.5, radius, radius x 1.5"
    print(json.dumps(out))


def build(c, a):
    """Make the group in the active document of connection c (pc.Control or pc.Headless); return its ids."""
    def call(method, params=None):
        r = c.call(method, params or {})
        if not r.get("ok"):
            sys.exit(f"error: {method} {json.dumps(params)[:200]}: {r.get('error')}")
        return r.get("result")

    def run(command, params=None):
        return call("engine.execute", {"command": command, "params": params or {}})

    doc = run("document.inspect")
    if doc.get("mode") != "Rgb":
        sys.exit(f"error: {doc['name']} is {doc.get('mode')}; frequency separation here works in RGB (image.mode.rgb on a copy)")
    top = doc["layers"]  # top first
    pixels = [l for l in top if l["kind"] == "Pixel"]
    if a.layer is not None:
        layer = next((l for l in top if l["id"] == a.layer), None)
        if not layer or layer["kind"] != "Pixel":
            sys.exit(f"error: layer {a.layer} is not a top-level pixel layer; pass --layer <the photo's id>")
    elif len(pixels) == 1:
        layer = pixels[0]
    else:  # after healing it is the Healing layer, not the Background under it: say which
        sys.exit("error: several pixel layers (" + ", ".join(f"{l['id']} {l['name']!r}" for l in pixels) + "): pass "
                 "--layer with the one holding the finished pixels (after Step 2, the Healing layer)")
    photo = layer["id"]
    # an opaque layer above the source would hide the whole group (and the identity check would pass on nothing)
    for l in top[:top.index(layer)]:
        if (l.get("visible") and l["kind"] == "Pixel" and l.get("blend") == "Normal" and l.get("opacity", 1) >= 0.999
                and l.get("fill", 1) >= 0.999 and not l.get("hasMask") and l.get("bounds") == [0, 0, doc["width"], doc["height"]]):
            sys.exit(f"error: {l['name']!r} ({l['id']}) lies over {layer['name']!r} and covers it, so the group would be "
                     f"hidden under it: build from {l['name']!r} (--layer {l['id']}), or hide it first")
    depth = doc.get("depth", 8)
    converted = False
    if depth == 8 and a.bits == 16:
        run("image.mode.bits16")
        depth, converted = 16, True
    if depth not in (8, 16):
        sys.exit(f"error: a {depth}-bit document; convert to 16-bit first (image.mode.bits16)")
    name = f"{'Median' if a.median else 'Gaussian'} {a.radius:g} px"
    # a selection would confine the blur and Apply Image to it (refused when there is none, which is fine)
    c.call("engine.execute", {"command": "select.deselect", "params": {}})
    low = run("layer.duplicate", {"layer": photo})["layer"]
    run("layer.setProps", {"layer": low, "name": f"Low ({name})"})
    run("layer.select", {"layer": low})
    if a.median:
        run("filter.noise.median", {"radius": max(1, round(a.radius))})
    else:
        run("filter.blur.gaussianBlur", {"radius": a.radius})
    tone = run("layer.new.layer", {"name": "Tone (soft heals, Current & Below)"})["layer"]
    colour = run("layer.new.layer", {"name": "Colour (Color mode)"})["layer"]
    run("layer.setProps", {"layer": colour, "blend": "Color"})
    high = run("layer.duplicate", {"layer": photo})["layer"]  # lands right above the photo, under Low
    run("layer.moveTo", {"layer": high, "target": colour, "position": "above"})
    run("layer.setProps", {"layer": high, "name": "High (texture)"})
    run("layer.select", {"layer": high})
    if depth == 16:
        apply = {"source": {"layer": low, "channel": "composite", "invert": True}, "blending": "add", "scale": 2, "offset": 0}
    else:
        apply = {"source": {"layer": low, "channel": "composite"}, "blending": "subtract", "scale": 2, "offset": 127}
    run("image.applyImage", apply)
    run("layer.setProps", {"layer": high, "blend": "Linear Light"})
    run("layer.select", {"layer": low})
    for lid in (tone, colour, high):
        run("layer.select", {"layer": lid, "mode": "add"})
    group = run("layer.groupLayers", {"name": f"Frequency separation ({name})"})["layer"]
    run("layer.select", {"layer": high})
    names = {"group": f"Frequency separation ({name})", "low": f"Low ({name})", "tone": "Tone (soft heals, Current & Below)",
             "colour": "Colour (Color mode)", "high": "High (texture)", "photo": layer["name"]}
    return {"group": group, "low": low, "tone": tone, "colour": colour, "high": high, "photo": photo, "names": names,
            "depth": depth, "convertedTo16bit": converted, "applyImage": apply, "width": doc["width"], "height": doc["height"]}


def identity(c, ids, a):
    """Render the document with the group and without it and compare a window: FS with nothing done on it must give
    back the photo. Then, with High switched to Normal for one render, the window must change: if it doesn't, a layer
    above covers the group and "identical" proves nothing. The renders are flat copies; the document is unchanged."""
    cli = pc.find_cli()
    if not cli:
        return {"skipped": "needs photocraft-cli to crop the renders"}
    tmp = os.path.join(str(pc.HOME), "work", "_freqsep")
    os.makedirs(tmp, exist_ok=True)
    W, H = ids["width"], ids["height"]
    if a.check:
        x, y, w, h = a.check
    else:
        w, h = min(W, 1024), min(H, 1024)
        x, y = (W - w) // 2, (H - h) // 2

    def setp(layer, **kv):
        c.call("engine.execute", {"command": "layer.setProps", "params": {"layer": layer, **kv}})

    def render(tag):
        full, crop = os.path.join(tmp, f"_full{tag}.png"), os.path.join(tmp, f"_crop{tag}.png")
        r = c.call("app.save", {"path": full})
        if not r.get("ok"):
            return None
        subprocess.run([str(cli), "run", full, "--cmd", "image.crop", "--params",
                        json.dumps({"x": x, "y": y, "width": w, "height": h}), "--out", crop], check=True, capture_output=True)
        px = pngio.read(crop)[2]
        os.remove(full)
        os.remove(crop)
        return px

    A = render("on")
    setp(ids["group"], visible=False)
    B = render("off")
    setp(ids["group"], visible=True)
    setp(ids["high"], blend="Normal")
    P = render("probe")
    setp(ids["high"], blend="Linear Light")
    if A is None or B is None or P is None:
        return {"skipped": "a render failed"}
    d = [A[j][i][k] - B[j][i][k] for j in range(h) for i in range(w) for k in range(3)]
    mean = sum(abs(v) for v in d) / len(d)
    bias = sum(d) / len(d)
    worst = max(abs(v) for v in d)
    shows = sum(abs(A[j][i][k] - P[j][i][k]) for j in range(h) for i in range(w) for k in range(3)) / len(d)
    # 16-bit is exact. 8-bit can't be: Linear Light needs High at 127.5 where there's no detail, so Offset 127 renders
    # every such pixel 1 level darker (a smooth gradient: all of them) and textured skin about half of them
    ok = (mean < 0.1 and worst <= 1) if ids["depth"] == 16 else (mean <= 1.0 and abs(bias) <= 1.0 and worst <= 2)
    out = {"identity": "ok" if ok and shows > 1 else "MISMATCH", "window": [x, y, w, h], "meanAbsDiff": round(mean, 3),
           "bias": round(bias, 3), "maxDiff": worst, "exactShare": round(sum(1 for v in d if v == 0) / len(d), 3),
           "groupShows": round(shows, 1)}
    if shows <= 1:
        out["error"] = ("the group doesn't show in the render (High in Normal mode changed the window by "
                        f"{shows:.1f} levels): a layer above covers it")
    return out


def cmd_build(a):
    if a.file:
        if not a.out:
            sys.exit("error: --file needs --out")
        c = pc.Headless()
        r = c.call("doc.open", {"path": os.path.abspath(os.path.expanduser(a.file))})
        if not r.get("ok"):
            sys.exit(f"error: cannot open {a.file}: {r.get('error')}")
    else:
        c = pc.Control(a.port)
    ids = build(c, a)
    out = {k: ids[k] for k in ("group", "low", "tone", "colour", "high", "photo", "names", "depth", "convertedTo16bit",
                               "applyImage")}
    out["radius"], out["blur"] = a.radius, "median" if a.median else "gaussian"
    if not a.no_verify:
        out.update(identity(c, ids, a))
    if a.file:
        r = c.call("doc.save", {"path": os.path.abspath(os.path.expanduser(a.out))})
        if not r.get("ok"):
            sys.exit(f"error: cannot save {a.out}: {r.get('error')}")
        out["saved"] = a.out
    out["ids"] = ("valid in this session: saving and reopening a PSD renumbers the layers bottom-up, so after reopening "
                  "read them again (document.inspect, or select.findLayers {\"name\": \"High (texture)\"})")
    out["next"] = [f"texture: plan_heals.py ... --layer {ids['high']} ('High (texture)') --hardness 95 --fallback skip "
                   "(samples High alone), then pc.py script",
                   f"tone: soft heals on {ids['tone']} ('Tone (soft heals, Current & Below)'), sampleLayer currentAndBelow, "
                   "hardness 0-20",
                   f"colour: paint on {ids['colour']} ('Colour (Color mode)') at 5-20 % opacity with colours sampled from "
                   "clean skin nearby",
                   "never blur or paint Low; toggle the group to compare"]
    notes = []
    if ids["convertedTo16bit"]:
        notes.append("the document is now 16-bit (layered files twice the size; JPEG and PNG exports stay 8-bit)")
    if ids["depth"] == 8:
        notes.append("8-bit: the render is up to 1 level darker than the photo (every pixel where the skin has no detail "
                     "at this radius, about half of them on textured skin); 16-bit is exact")
    if notes:
        out["note"] = "; ".join(notes)
    print(json.dumps(out))
    c.close()
    if out.get("identity") == "MISMATCH":
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("radius", help="measure where texture ends and tone begins on this skin")
    p.add_argument("crop", help="full-resolution crop around the skin area (image.crop), at least 32 px wider all round")
    p.add_argument("x", type=int); p.add_argument("y", type=int)
    p.add_argument("area", help='area.json: {"skin": polygon(s) of plain cheek and forehead, "exclude": [...]}, full-image coords')
    p.add_argument("--sheet", help="PNG: the crop's detail, then Low at three radii, to look at")
    p.set_defaults(fn=cmd_radius)
    p = sub.add_parser("build", help="make the Frequency separation group and check it reproduces the photo")
    p.add_argument("--radius", type=float, required=True, help="blur radius in px (radius says which)")
    p.add_argument("--bits", type=int, choices=(8, 16), default=16, help="16 (default) converts an 8-bit document first")
    p.add_argument("--median", action="store_true", help="Low with Median instead of Gaussian Blur (crisper edges)")
    p.add_argument("--layer", type=int, help="the layer holding the finished pixels, e.g. Healing (required when "
                                             "the document has more than one pixel layer)")
    p.add_argument("--check", type=int, nargs=4, metavar=("X", "Y", "W", "H"), help="identity window (default: centre 1024 px)")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--file", help="headless: open this file with photocraft-cli serve instead of the live document")
    p.add_argument("--out", help="headless: save here (.psd keeps the layers)")
    p.add_argument("--port", type=int)
    p.set_defaults(fn=cmd_build)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
