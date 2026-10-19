#!/usr/bin/env python3
"""Build the tone/colour half of a skin retouch in the live PhotoCraft document from skin_masks.py output:

  Skin retouch (group)
    Burn  (Curves, Luminosity, mask = burn.png)
    Dodge (Curves, Luminosity, mask = dodge.png)
    Skin colour (pixel layer = color_ref.png, Normal mode, mask = color.png)

usage: import_masks.py outdir --above <layer id> [--group NAME] [--port N]

outdir must be under the app's automation read root (the home folder by default), since the app opens the PNGs.
Each mask goes in the same way: open the PNG as its own document, copy its layer into the photo at the crop's
centre, load that layer's red channel as the selection, delete the temporary layer, then create the layer (an
adjustment layer takes the selection as its mask). The PNG documents are closed again.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc

ap = argparse.ArgumentParser()
ap.add_argument("outdir")
ap.add_argument("--above", type=int, required=True, help="layer id to stack the new layers above (the healing layer)")
ap.add_argument("--group", default="Skin retouch (D&B + colour)")
ap.add_argument("--port", type=int)
a = ap.parse_args()

out = os.path.abspath(a.outdir)
meta = json.load(open(os.path.join(out, "masks.json")))
center = meta["center"]
c = pc.Control(a.port)


def call(method, params=None):
    r = c.call(method, params or {})
    if not r.get("ok"):
        sys.exit(f"error: {method} {json.dumps(params)[:200]}: {r.get('error')}")
    return r.get("result")


def run(command, params=None):
    return call("engine.execute", {"command": command, "params": params or {}})


def session():
    return call("ui.inspect")["session"]


main = session()["active"]
doc = run("document.inspect", {"document": main})
print(f"document {main}: {doc['name']}")
if a.above not in [l["id"] for l in doc["layers"]]:
    sys.exit(f"error: no layer {a.above} in {doc['name']}")

# The PNGs carry no profile, so they open as sRGB, and copying a layer into a document with another profile
# (a phone photo in Display P3) CONVERTS its colours: skin comes out less red and bluer. Grey masks survive,
# colour pixels don't. So give each PNG the photo's own profile first (assign = same numbers, no conversion).
info = run("edit.profileInfo", {"profile": "document"})
want = (info.get("profile") or {}).get("description")
assign = next((b["id"] for b in info.get("builtins", []) if b.get("description") == want), None)
if want and not assign:
    print(f"warning: document profile {want!r} has no builtin twin; colours may shift on import", file=sys.stderr)


def bring_in(png):
    """Open png, copy its only layer into the main document centred on the crop; return the new layer id."""
    call("app.open", {"path": os.path.join(out, png)})
    src = session()["active"]
    if assign:
        run("edit.assignProfile", {"profile": assign})
    src_layer = run("document.inspect", {"document": src})["layers"][0]["id"]
    run("document.activate", {"document": main})
    res = run("layer.copyToDocument", {"document": main, "source": src, "layers": [src_layer], "at": center})
    run("file.close", {"document": src})
    run("document.activate", {"document": main})
    return res["layers"][0]


def load_mask(png):
    tmp = bring_in(png)
    run("select.loadSelection", {"channel": "red", "layer": tmp})
    run("layer.delete", {"layer": tmp})


made = []
# Skin colour: the skin recoloured to the clean skin around it (already at each pixel's own luminance, so
# Normal mode reproduces the preview exactly), only where the marks are
colour = bring_in("color_ref.png")
run("layer.setProps", {"layer": colour, "name": "Skin colour (marks)", "blend": "Normal"})
load_mask("color.png")
run("layer.layerMask.revealSelection", {"layer": colour})
run("select.deselect")
made.append(colour)

below = colour
for name, png, key in (("Dodge", "dodge.png", "dodgeCurve"), ("Burn", "burn.png", "burnCurve")):
    load_mask(png)
    run("layer.select", {"layer": below})
    lid = run("layer.newAdjustmentLayer.curves", {"points": meta[key]})["layer"]
    run("select.deselect")
    run("layer.setProps", {"layer": lid, "name": name, "blend": "Luminosity"})
    made.append(lid)
    below = lid

run("layer.select", {"layer": made[0]})
for lid in made[1:]:
    run("layer.select", {"layer": lid, "mode": "add"})
grp = run("layer.groupLayers", {"name": a.group})
layers = run("document.inspect")["layers"]


def walk(ls, depth=0):
    for l in ls:
        print("  " * depth + f"{l['id']} {l['kind']} {l['name']} blend={l.get('blend')} mask={l.get('hasMask')}")
        walk(l.get("children", []), depth + 1)


walk(layers)
print(json.dumps({"group": grp, "layers": made}))
c.close()
