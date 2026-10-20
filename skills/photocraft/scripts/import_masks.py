#!/usr/bin/env python3
"""Build the tone/colour half of a skin retouch in the live PhotoCraft document from skin_masks.py output:

  Skin retouch (group)
    Burn  (Curves, Luminosity, mask = burn.png)
    Dodge (Curves, Luminosity, mask = dodge.png)
    Skin colour (pixel layer = color_ref.png, Normal mode, mask = color.png)

usage: import_masks.py outdir --above <layer id> [--group NAME] [--port N]
       import_masks.py outdir --above <layer id> --file photo.psd --out photo-retouched.psd   (headless)

outdir must be under the app's automation read root (the home folder by default), since the app opens the PNGs.
Each mask goes in the same way: open the PNG as its own document, copy its layer into the photo at the crop's
centre, load that layer's red channel as the selection, delete the temporary layer, then create the layer (an
adjustment layer takes the selection as its mask). The PNG documents are closed again. Then the document is
rendered, cropped and compared with preview.png (import_layers.py does the work; it also writes layers.json).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import import_layers
import pc

ap = argparse.ArgumentParser()
ap.add_argument("outdir")
ap.add_argument("--above", type=int, required=True, help="layer id to stack the new layers above (the healing layer)")
ap.add_argument("--group", default="Skin retouch (D&B + colour)")
ap.add_argument("--file", help="headless: open this file with photocraft-cli serve instead of the live document")
ap.add_argument("--out", help="headless: save the result here")
ap.add_argument("--port", type=int)
a = ap.parse_args()

out = os.path.abspath(a.outdir)
meta = json.load(open(os.path.join(out, "masks.json")))
spec = {"center": meta["center"], "crop": meta["crop"], "preview": "preview.png", "group": a.group, "layers": [
    # the skin recoloured to the clean skin around it (already at each pixel's own luminance, so Normal mode
    # reproduces the preview exactly), only where the marks are
    {"name": "Skin colour (marks)", "image": "color_ref.png", "mask": "color.png", "blend": "Normal"},
    {"name": "Dodge", "adjustment": "curves", "params": {"points": meta["dodgeCurve"]}, "mask": "dodge.png", "blend": "Luminosity"},
    {"name": "Burn", "adjustment": "curves", "params": {"points": meta["burnCurve"]}, "mask": "burn.png", "blend": "Luminosity"},
]}
json.dump(spec, open(os.path.join(out, "layers.json"), "w"), indent=1)

if a.file:
    if not a.out:
        sys.exit("error: --file needs --out")
    c = pc.Headless()
    r = c.call("doc.open", {"path": os.path.abspath(os.path.expanduser(a.file))})
    if not r.get("ok"):
        sys.exit(f"error: cannot open {a.file}: {r.get('error')}")
else:
    c = pc.Control(a.port)
made, grp = import_layers.build(c, spec, out, a.above)
import_layers.verify(c, spec, out)
if a.file:
    r = c.call("doc.save", {"path": os.path.abspath(os.path.expanduser(a.out))})
    if not r.get("ok"):
        sys.exit(f"error: cannot save {a.out}: {r.get('error')}")
    print(f"saved {a.out}")
print(json.dumps({"group": grp, "layers": made}))
c.close()
