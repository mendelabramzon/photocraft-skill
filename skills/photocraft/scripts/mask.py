#!/usr/bin/env python3
"""Turn an area into a layer mask: a grey PNG for any layer in a layers.json ("mask": "mask.png"), so a look, a
mixer or a curve acts only where it should (or less there): a split tone at 30 % on skin, a colour fix on skin only,
local contrast everywhere but the face.

usage: mask.py AREA OUT.png --size W H [--origin X Y] [--feather 20] [--inside 1] [--outside 0] [--invert]

AREA     an area.json ({"skin": polygon(s), "exclude": [box or polygon, ...]}, full-image coordinates, as grid.py
         reads them) or a rectangle x0,y0,x1,y1
--size   the box the mask covers, in full-image pixels, from --origin (default 0 0): the photo's size for a mask
         over the whole document, or a crop's size
--inside / --outside   the mask's value inside the area and outside it (0..1): --inside 0.3 --outside 1 is a layer at
         30 % on the area and full strength elsewhere; --invert swaps them
--feather  px over which the edge fades (a Gaussian of feather / 2)
Prints the "center" a layers.json needs for this mask (where it goes in the document) and its size.
Big masks are drawn at up to 1500 px and scaled up by photocraft-cli, so a feathered mask over a 45 MP photo is
quick; the feather keeps the scaling invisible.

  mask.py AREA mask.png --size W H … --apply-to LAYER [--file in.psd --save out.psd]

--apply-to also makes it the layer mask of an existing layer (id or name) of the active document in the live app,
or headless of --file, saved to --save. It replaces any mask the layer has (a new adjustment layer always has a
white one). The PNG must be under the home folder (the app's read root).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pc


def area_cfg(spec):
    if os.path.exists(spec):
        cfg = json.load(open(spec))
        skin = cfg.get("skin") or cfg.get("area")
        if not skin:
            sys.exit(f"error: {spec} has no \"skin\" (or \"area\") polygon")
        return {"skin": skin, "exclude": cfg.get("exclude", [])}
    try:
        x0, y0, x1, y1 = (float(v) for v in spec.split(","))
    except ValueError:
        sys.exit(f"error: {spec} is neither an area.json nor a rectangle x0,y0,x1,y1")
    return {"skin": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "exclude": []}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("area"); ap.add_argument("out")
    ap.add_argument("--size", type=int, nargs=2, required=True, metavar=("W", "H"))
    ap.add_argument("--origin", type=float, nargs=2, default=[0, 0], metavar=("X", "Y"))
    ap.add_argument("--feather", type=float, default=20)
    ap.add_argument("--inside", type=float, default=1.0)
    ap.add_argument("--outside", type=float, default=0.0)
    ap.add_argument("--invert", action="store_true")
    ap.add_argument("--apply-to", metavar="LAYER", help="also make it the mask of this existing layer (id or name)")
    ap.add_argument("--file", help="--apply-to headless: the document to open (else the live app's active document)")
    ap.add_argument("--save", help="--apply-to headless: where to save it (.psd keeps layers)")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    if a.file and not a.save:
        ap.error("--file needs --save")
    W, H = a.size
    if W < 1 or H < 1:
        sys.exit("error: --size must be at least 1 x 1")
    inside, outside = (a.outside, a.inside) if a.invert else (a.inside, a.outside)
    if not (0 <= inside <= 1 and 0 <= outside <= 1):
        sys.exit("error: --inside and --outside are 0..1")
    cfg = area_cfg(a.area)
    k = max(1.0, max(W, H) / 1500)  # draw at most 1500 px across, then scale up
    w, h = max(1, round(W / k)), max(1, round(H / k))
    polys = cfg["skin"] if isinstance(cfg["skin"][0][0], (list, tuple)) else [cfg["skin"]]
    ox, oy = a.origin
    sc = lambda pts: [[(x - ox) / k, (y - oy) / k] for x, y in pts]
    ex = [sc(e) if isinstance(e[0], (list, tuple)) else [round((e[0] - ox) / k), round((e[1] - oy) / k),
                                                         round((e[2] - ox) / k), round((e[3] - oy) / k)]
          for e in cfg["exclude"]]
    m = imgops.raster({"skin": [sc(p) for p in polys], "exclude": ex}, 0, 0, w, h)
    if not any(m):
        sys.exit("error: the area doesn't overlap the box --origin/--size describe")
    if a.feather > 0:
        m = imgops.gauss(m, w, h, a.feather / 2 / k)
    vals = [outside + (inside - outside) * v for v in m]
    if (w, h) == (W, H):
        imgops.save_gray(a.out, W, H, vals)
    else:
        cli = pc.find_cli()
        if not cli:
            sys.exit("error: a mask over more than 1500 px is scaled up with photocraft-cli (`pc.py cli-info`)")
        small = os.path.join(tempfile.mkdtemp(prefix="mask-"), "small.png")
        imgops.save_gray(small, w, h, vals)
        r = subprocess.run([str(cli), "run", small, "--cmd", "image.imageSize", "--params",
                            json.dumps({"width": W, "height": H, "resample": "bilinear"}), "--out", a.out],
                           capture_output=True, text=True)
        if r.returncode or not os.path.exists(a.out):
            sys.exit(f"error: photocraft-cli: {(r.stderr or r.stdout).strip()[:300]}")
    share = sum(1 for v in m if v > 0.5) / len(m)
    res = {"mask": os.path.abspath(a.out), "size": [W, H], "center": [ox + W / 2, oy + H / 2],
           "areaShare": round(share, 4), "inside": inside, "outside": outside,
           "use": 'in a layers.json: "center" as above, and "mask": "<this file>" on the layer'}
    if a.apply_to:
        import import_layers
        if a.file:
            c = pc.Headless()
            r = c.call("doc.open", {"path": os.path.abspath(os.path.expanduser(a.file))})
            if not r.get("ok"):
                sys.exit(f"error: cannot open {a.file}: {r.get('error')}")
        else:
            c = pc.Control(a.port)
        res["appliedTo"], res["replacedMask"] = import_layers.apply_mask(c, a.out, res["center"], a.apply_to)
        if a.file:
            r = c.call("doc.save", {"path": os.path.abspath(os.path.expanduser(a.save))})
            if not r.get("ok"):
                sys.exit(f"error: cannot save {a.save}: {r.get('error')}")
            res["saved"] = os.path.abspath(os.path.expanduser(a.save))
        c.close()
        del res["use"]
    print(json.dumps(res))


if __name__ == "__main__":
    main()
