#!/usr/bin/env python3
"""Build a planning script's layers in a PhotoCraft document: masked adjustment layers, pixel layers from PNGs,
fill layers and filtered stamps, grouped, then checked against the script's predicted result.

  import_layers.py <dir>/layers.json [--above ID]                    the active document in the live app
  import_layers.py <dir>/layers.json --file photo.psd --out new.psd  headless (photocraft-cli serve), no window

layers.json is written by the planning scripts. File names in it are relative to its folder, which must be under
the app's automation read root (the home folder by default):

  {"center": [cx, cy],          where crop-sized PNGs go: the centre of the crop in the photo
   "crop": [x, y, w, h],        optional, with "preview" (the predicted result of that crop): verify the import
   "preview": "preview.png",
   "tolerance": 0.5,            optional: the mean |difference| verify accepts (more where a layer adds grain)
   "group": "Teeth & eyes",     optional: group the new layers under this name
   "layers": [                  bottom to top
     {"name": "Teeth", "adjustment": "curves", "params": {"blue": [[0, 0], [128, 140], [255, 255]]}, "mask": "teeth.png"},
     {"name": "Shadow", "image": "shadow.png", "blend": "Multiply", "opacity": 0.9},
     {"name": "Backdrop", "fill": "#ffffff"},
     {"name": "Dust", "stamp": [["filter.noise.dustAndScratches", {"radius": 3, "threshold": 6}]], "mask": "dust.png"}]}

Kinds: "adjustment" = layer.newAdjustmentLayer.<kind> with "params"; "image" = a pixel layer from a PNG (crop-sized,
placed at "center", or centred on its own "at"); "fill" = a Solid Color fill layer; "stamp" = Stamp Visible (the
whole visible image) with these commands run on it. Optional on every layer: "mask" (a grey PNG, crop-sized at
"center", becomes the layer mask), "blend", "opacity" (0..1), "visible", "clip" (clip to the layer below).

PNGs carry no colour profile and open as sRGB, and copying a layer into a photo with another profile (a Display P3
phone photo) converts its colours. So each PNG is first assigned the photo's own profile: same numbers, no
conversion. Grey masks are unaffected either way. In a Grayscale document the PNGs are made grey the same way, and
masks load from its "gray" channel.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc
import pngio


FAMILIES = (("prophoto", "prophoto-compat"), ("romm", "prophoto-compat"), ("adobe rgb", "adobe-rgb-compat"),
            ("display p3", "display-p3"),
            ("2020", "rec2020"), ("srgb", "srgb"), ("gray gamma 2.2", "gray-gamma-2.2"))


def walk(ls, depth=0):
    for l in ls:
        yield depth, l
        yield from walk(l.get("children") or [], depth + 1)


def build(c, spec, base, above=None, group=None):
    """Make spec's layers in the active document of connection c (pc.Control or pc.Headless); return their ids."""
    def call(method, params=None):
        r = c.call(method, params or {})
        if not r.get("ok"):
            sys.exit(f"error: {method} {json.dumps(params)[:200]}: {r.get('error')}")
        return r.get("result")

    def run(command, params=None):
        return call("engine.execute", {"command": command, "params": params or {}})

    def deselect():  # refused when nothing is selected, which is fine
        c.call("engine.execute", {"command": "select.deselect", "params": {}})

    main = call("ui.inspect")["session"]["active"]
    doc = run("document.inspect", {"document": main})
    print(f"document {main}: {doc['name']}")
    ids = [l["id"] for _, l in walk(doc["layers"])]
    if above is None:
        above = doc["layers"][0]["id"]
    elif above not in ids:
        sys.exit(f"error: no layer {above} in {doc['name']}")

    # a Grayscale document (most black & white scans) has one "Gray" channel and a grey profile: each PNG goes to
    # grey first with sgray, whose tone curve is sRGB's, so its numbers stay as they are
    gray = doc["channels"]["composite"] == "Gray"
    if not gray and doc["channels"]["composite"] != "RGB":
        sys.exit(f"error: {doc['name']} is {doc['channels']['composite']}; import_layers works in RGB and Grayscale "
                 "documents (image.mode.rgb on a copy first)")
    info = run("edit.profileInfo", {"profile": "document"})
    prof, builtins = info.get("profile") or {}, info.get("builtins", [])
    want = prof.get("description")
    assign = next((b["id"] for b in builtins if b.get("description") == want), None)
    if want and not assign:  # a standard profile embedded under its own name ("ProPhoto RGB"): PhotoCraft's twin of it
        same = {b["id"] for b in builtins if b.get("colorSpace") == prof.get("colorSpace")}
        assign = next((bid for key, bid in FAMILIES if key in want.lower() and bid in same), None)
    if want and not assign and any("image" in L for L in spec["layers"]):  # grey masks don't care
        print(f"warning: document profile {want!r} has no builtin twin; colours may shift on import", file=sys.stderr)

    def bring_in(png, at):
        """Open png, copy its layer into the main document centred on `at`; return the new layer's id."""
        call("app.open", {"path": os.path.join(base, png)})
        src = call("ui.inspect")["session"]["active"]
        src_gray = run("document.inspect", {"document": src})["channels"]["composite"] == "Gray"
        if gray and not src_gray:
            run("image.mode.grayscale", {"profile": "sgray"})
            src_gray = True
        if assign and src_gray == gray and assign != ("sgray" if gray else None):
            run("edit.assignProfile", {"profile": assign})
        src_layer = run("document.inspect", {"document": src})["layers"][0]["id"]
        run("document.activate", {"document": main})
        res = run("layer.copyToDocument", {"document": main, "source": src, "layers": [src_layer], "at": at})
        run("file.close", {"document": src})
        run("document.activate", {"document": main})
        return res["layers"][0]

    def load_mask(png):
        tmp = bring_in(png, spec["center"])
        run("select.loadSelection", {"channel": "gray" if gray else "red", "layer": tmp})
        run("layer.delete", {"layer": tmp})

    deselect()
    made, below = [], above
    for L in spec["layers"]:
        mask = L.get("mask")
        if "adjustment" in L or "fill" in L:
            if mask:
                load_mask(mask)
            run("layer.select", {"layer": below})
            if "adjustment" in L:
                lid = run(f"layer.newAdjustmentLayer.{L['adjustment']}", L.get("params", {}))["layer"]
            else:
                lid = run("layer.newFillLayer.solidColor", {"color": L["fill"]})["layer"]
        else:
            run("layer.select", {"layer": below})
            if "image" in L:
                lid = bring_in(L["image"], L.get("at", spec["center"]))
            elif "stamp" in L:
                lid = run("layer.stampVisible")["layer"]
                for cmd, params in L["stamp"]:
                    run("layer.select", {"layer": lid})
                    run(cmd, params)
            else:
                sys.exit(f"error: layer {L.get('name')!r} has no adjustment, image, fill or stamp")
            if mask:
                load_mask(mask)
                run("layer.layerMask.revealSelection", {"layer": lid})
        deselect()
        props = {"layer": lid, "name": L.get("name", f"Layer {len(made) + 1}")}
        props.update({k: L[k] for k in ("blend", "opacity", "visible") if k in L})
        run("layer.setProps", props)
        if L.get("clip"):
            run("layer.createClippingMask", {"layer": lid})
        made.append(lid)
        below = lid

    grp = None
    group = spec.get("group") if group is None else group
    if group and made:
        run("layer.select", {"layer": made[0]})
        for lid in made[1:]:
            run("layer.select", {"layer": lid, "mode": "add"})
        grp = run("layer.groupLayers", {"name": group})
    for depth, l in walk(run("document.inspect")["layers"]):
        print("  " * depth + f"{l['id']} {l['kind']} {l['name']} blend={l.get('blend')} mask={l.get('hasMask')}")
    return made, grp


def verify(c, spec, base):
    """Render the document, crop it like the planner did and compare with its preview: mean |difference| and the
    signed bias per channel. A bias of a few levels where colour layers act means a colour conversion on import.
    The render is a flat copy (the app shows "Saved _verify_full.png … flattened"); the document is unchanged."""
    cli = pc.find_cli()
    if not cli:
        print("verify: skipped (needs photocraft-cli to crop the render)")
        return
    full, crop = os.path.join(base, "_verify_full.png"), os.path.join(base, "_verify_crop.png")
    r = c.call("app.save", {"path": full})
    if not r.get("ok"):
        print(f"verify: skipped (render failed: {r.get('error')})")
        return
    x, y, w, h = spec["crop"]
    subprocess.run([str(cli), "run", full, "--cmd", "image.crop", "--params",
                    json.dumps({"x": x, "y": y, "width": w, "height": h}), "--out", crop],
                   check=True, capture_output=True)
    _, _, A = pngio.read(crop)
    _, _, B = pngio.read(os.path.join(base, spec["preview"]))
    n = w * h
    absd = sum(abs(A[j][i][k] - B[j][i][k]) for j in range(h) for i in range(w) for k in range(3)) / (3 * n)
    bias = [sum(A[j][i][k] - B[j][i][k] for j in range(h) for i in range(w)) / n for k in range(3)]
    worst = max(abs(A[j][i][k] - B[j][i][k]) for j in range(h) for i in range(w) for k in range(3))
    ok = absd < spec.get("tolerance", 0.5) and max(abs(b) for b in bias) < 0.5
    print(json.dumps({"verify": "ok" if ok else "MISMATCH", "meanAbsDiff": round(absd, 3),
                      "bias": [round(b, 3) for b in bias], "maxDiff": worst}))
    for p in (full, crop):
        os.remove(p)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", help="layers.json from a planning script")
    ap.add_argument("--above", type=int, help="layer id to stack the new layers above (default: the top layer)")
    ap.add_argument("--group", help="group name (default: the spec's; '' for no group)")
    ap.add_argument("--file", help="headless: open this file with photocraft-cli serve instead of the live document")
    ap.add_argument("--out", help="headless: save the result here (.psd keeps the layers)")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    spec_path = os.path.abspath(a.spec)
    base = os.path.dirname(spec_path)
    spec = json.load(open(spec_path))
    if a.file:
        if not a.out:
            sys.exit("error: --file needs --out")
        c = pc.Headless()
        r = c.call("doc.open", {"path": os.path.abspath(os.path.expanduser(a.file))})
        if not r.get("ok"):
            sys.exit(f"error: cannot open {a.file}: {r.get('error')}")
    else:
        c = pc.Control(a.port)
    made, grp = build(c, spec, base, a.above, a.group)
    if "preview" in spec and "crop" in spec and not a.no_verify:
        verify(c, spec, base)
    if a.file:
        r = c.call("doc.save", {"path": os.path.abspath(os.path.expanduser(a.out))})
        if not r.get("ok"):
            sys.exit(f"error: cannot save {a.out}: {r.get('error')}")
        print(f"saved {a.out}")
    print(json.dumps({"group": grp, "layers": made}))
    c.close()


if __name__ == "__main__":
    main()
