#!/usr/bin/env python3
"""Marketplace image specifications: built-in presets and a client's own spec.json, read by product_shot.py (where the
product goes) and cutout_check.py --deliverable (whether the finished file passes), so one specification drives both,
the way an e-commerce post-production studio encodes each client or marketplace once and runs every image through it.

  specs.py                     list the presets with their sources
  specs.py amazon              print a preset as a spec.json to start a client's own from
  specs.py my-spec.json        check a spec file and print it resolved

A spec is a JSON object; every key is optional (a preset or the defaults fill the rest):

  {"name": "Client A packshots",       shown in reports
   "base": "amazon",                    start from a preset or another spec file (relative to this one), then override
   "canvas": [2000, 2000],              the pixel size product_shot.py places the product on; with an "aspect" it
                                        doesn't have, its long side at that aspect
   "aspect": "1:1.44",                  a required width:height, checked to 2 decimals of long/short (Zalando: 1.445 fails)
   "exactCanvas": false,                the check demands exactly the canvas size
   "background": "#ffffff",             the backdrop colour product_shot.py fills (#rrggbb, #rgb, white or black)
   "pureBackground": true,              the check demands exactly this colour everywhere outside the product and shadow
   "fill": 0.85,                        product's longer extent as a share of the canvas, or of the safeAspect crop
                                        when there is one (placement target); with a reflection, of product and
                                        reflection together
   "fillRange": [0.85, 1.0],            allowed by the check, on the same measure
   "margins": [0.05, 0.05, 0.08, 0.05], instead of fill: top, right, bottom, left gaps (share of the canvas side, or px > 1)
   "align": "center",                   center | bottom (a common baseline, for shoes and catalogue grids) | top
   "bottom": 0.06,                      align bottom/top: gap under/over the product, share of the height
   "safeAspect": "5:4",                 the product is placed inside this centred crop (a thumbnail crop) and checked
   "minWidth": 500, "minHeight": 500, "minLongest": 1000, "minShortest": 0,    hard minimums
   "recommendedLongest": 1600, "recommendedShortest": 0,                      warnings only
   "formats": ["jpg", "png"],           allowed file types; the first is the deliverable's
   "quality": 95,                       JPEG quality of the export command product_shot.py suggests
   "maxBytes": 10000000, "maxMegapixels": 0, "recommendedMaxBytes": 0,
   "profile": "srgb",                   the only value: product_shot.py's steps convert to sRGB, the check expects sRGB
   "shadow": "real", "reflection": 0,   product_shot.py defaults: real | contact | none, reflection opacity (0 = none)
   "naming": "{name}-{preset}.{ext}",   suggested deliverable name; "nameRegex" makes the check enforce one
   "notes": ["…"], "source": "…", "url": "…", "official": true}

Where the numbers come from: Google Merchant Center, eBay, Shopify and Zalando from their own help pages (fetched
2026-10-20); Amazon from an Amazon staff post on the Seller Central forums (the official page G1881 needs a seller
login); Etsy from seller guides only (Etsy's help page could not be read). Check the marketplace's current help before
relying on a third-party number.
"""
import json
import os
import sys

DEFAULTS = {
    "name": "custom", "canvas": [2000, 2000], "aspect": None, "exactCanvas": False, "background": "#ffffff",
    "pureBackground": False,
    "fill": 0.85, "fillRange": None, "margins": None, "align": "center", "bottom": 0.06, "safeAspect": None,
    "minWidth": 0, "minHeight": 0, "minLongest": 0, "minShortest": 0, "recommendedLongest": 0, "recommendedShortest": 0,
    "formats": ["jpg", "png", "tif"], "quality": 95, "maxBytes": 0, "maxMegapixels": 0, "recommendedMaxBytes": 0,
    "profile": "srgb", "shadow": "real", "reflection": 0, "naming": "{name}-{preset}.{ext}", "nameRegex": None,
    "notes": [], "source": "", "url": "", "official": False,
}

PRESETS = {
    "amazon": {
        "name": "Amazon main image", "canvas": [2000, 2000], "background": "#ffffff", "pureBackground": True,
        "fill": 0.87, "fillRange": [0.85, 1.0], "minLongest": 1000, "recommendedLongest": 1600,
        "formats": ["jpg", "png", "tif"], "maxBytes": 10_000_000,
        "notes": ["pure white RGB 255,255,255; product fills 85 % or more of the frame (read as the longer side): "
                  "placed at 87 % for a margin over the minimum",
                  "1000 px on the longest side enables zoom",
                  "no props, text, graphics, watermarks or illustrations; the actual product sold",
                  "how soft a ground shadow Amazon tolerates is not published: keep it faint and neutral",
                  "10 MB: the post says 10GB, almost certainly a typo; seller guides say under 10 MB"],
        "source": "Amazon staff post (TaylorR_Amazon), Seller Central forums; help page G1881 needs a login",
        "url": "https://sellercentral.amazon.com/seller-forums/discussions/t/13af96ea-6b07-4bf9-8dbe-a13292c2e3b1",
        "official": False},
    "google": {
        "name": "Google Merchant Center", "canvas": [1500, 1500], "background": "#ffffff", "pureBackground": False,
        "fill": 0.82, "fillRange": [0.75, 0.90], "minWidth": 500, "minHeight": 500,
        "formats": ["jpg", "webp", "png", "gif", "bmp", "tif"], "maxBytes": 16_000_000, "maxMegapixels": 64,
        "notes": ["the product fills no less than 75 % and no more than 90 % of the image",
                  "at least 500 x 500 px for all products from 31 January 2027; about 1500 x 1500 recommended",
                  "no borders, promotional overlays, watermarks, barcodes, or logos added in post-production",
                  "no background colour is required: an unobstructed, clean view",
                  "the file extension must match the real format"],
        "source": "Google Merchant Center help, image_link", "url": "https://support.google.com/merchants/answer/6324350",
        "official": True},
    "ebay": {
        "name": "eBay listing photo", "canvas": [1600, 1600], "background": "#ffffff", "pureBackground": False,
        "fill": 0.85, "minLongest": 500, "recommendedLongest": 1600, "formats": ["jpg", "png", "tif"],
        "notes": ["at least 500 px on the longest side (1600 is the usual target for zoom: seller guides)",
                  "no added borders, text, artwork, marketing material or watermarks of any kind"],
        "source": "eBay picture policy", "url": "https://www.ebay.com/help/policies/listing-policies/picture-policy?id=4370",
        "official": True},
    "shopify": {
        "name": "Shopify product media", "canvas": [2048, 2048], "background": "#ffffff", "pureBackground": False,
        "fill": 0.85, "formats": ["jpg", "png", "webp", "tif", "gif"], "maxBytes": 20_000_000, "maxMegapixels": 20,
        "notes": ["2048 x 2048 usually displays best for square product images",
                  "keep one aspect ratio across a collection so the grid lines up",
                  "colour profiles are dropped on display: deliver sRGB",
                  "product media allows 25 MP, the theme image page 20 MP: 20 is the safe limit"],
        "source": "Shopify help: product media types; theme images",
        "url": "https://help.shopify.com/en/manual/products/product-media/product-media-types", "official": True},
    "etsy": {
        "name": "Etsy listing photo", "canvas": [3000, 2250], "background": "#ffffff", "pureBackground": False,
        "fill": 0.8, "safeAspect": "5:4", "minShortest": 635, "recommendedShortest": 2000,
        "formats": ["jpg", "png", "gif"], "recommendedMaxBytes": 1_000_000,
        "notes": ["about 2000 px on the shortest side, 4:3 or 1:1",
                  "search thumbnails crop to about 5:4: keep the product inside the centred 5:4 area",
                  "seller guides only (Etsy's own help page could not be read): check it before relying on these"],
        "source": "seller guides (Outfy, Merchize, Aiarty), not Etsy", "url": "https://www.outfy.com/blog/etsy-listing-photo-size-guide/",
        "official": False},
    "zalando": {
        "name": "Zalando packshot", "canvas": [1801, 2600], "aspect": "1:1.44", "background": "#ffffff",
        "pureBackground": False, "fill": 0.8, "fillRange": [0.75, 0.85], "minWidth": 762, "minHeight": 1100,
        "recommendedLongest": 2600, "formats": ["jpg"], "maxBytes": 20_000_000,
        "notes": ["width:height exactly 1:1.44 (1.445 is rejected); 1801 x 2600 best practice, 762 x 1100 minimum",
                  "designer and premium brands: at least 1800 x 2600",
                  "JPEG only; Zalando turns white packshot backgrounds light grey itself",
                  "the article covers about 80 % of the frame, centred; bags centred in the lower third",
                  "no visible mannequin in packshots (rejection code 123): a ghost-mannequin composite",
                  "blurry images are rejected even at the right size"],
        "source": "Zalando Partner University: image guidelines",
        "url": "https://partner.zalando.com/university/article/zalando-image-guidelines", "official": True},
}


NAMED = {"white": "ffffff", "black": "000000"}


def hex_rgb(s):
    """'#f2efe9', '#fff', 'white' -> (r, g, b); anything else exits with a message."""
    t = str(s).strip()
    t = NAMED.get(t.lower(), t).lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6 or any(c not in "0123456789abcdefABCDEF" for c in t):
        sys.exit(f"error: colour {s!r}: give #rrggbb, #rgb, white or black")
    return tuple(int(t[k:k + 2], 16) for k in (0, 2, 4))


def parse_margins(m):
    """'0.1,0.05,0.05,0.05' or a list -> [top, right, bottom, left]: shares of the canvas side (<= 1) or px (> 1)."""
    try:
        v = [float(x) for x in (m.split(",") if isinstance(m, str) else m)]
    except (TypeError, ValueError):
        v = None
    if not v or len(v) != 4 or any(x < 0 for x in v):
        sys.exit(f"error: margins {m!r}: give four gaps, top,right,bottom,left (shares of the side like 0.05, or px)")
    return v


def parse_aspect(s):
    """'4:5' or '1:1.44' -> (w, h) floats."""
    try:
        w, h = (float(v) for v in str(s).split(":"))
    except ValueError:
        w = h = 0
    if w <= 0 or h <= 0:
        sys.exit(f"error: aspect {s!r}: give width:height, like 4:5 or 1:1.44")
    return w, h


def aspect_of(spec):
    """The canvas shape as (w, h): the spec's "aspect" if given, else its canvas."""
    if spec.get("aspect"):
        return parse_aspect(spec["aspect"])
    return float(spec["canvas"][0]), float(spec["canvas"][1])


def aspect_ok(spec, w, h):
    """None when the spec requires no shape; else whether w x h has it, to two decimals of the long/short ratio,
    which is how Zalando's 1:1.44 is checked (1801 x 2600 = 1.4437 passes, 1.445 fails)."""
    if not spec.get("aspect"):
        return None
    aw, ah = aspect_of(spec)
    if (aw <= ah) != (w <= h) and aw != ah:
        return False
    return round(max(w, h) / min(w, h), 2) == round(max(aw, ah) / min(aw, ah), 2)


def resolve(name_or_path, _seen=(), _dir=None):
    """A preset name (any case) or a spec.json path -> a complete spec (DEFAULTS <- its base <- the file's own keys).
    A "base" can be a preset or another spec file, relative to the file naming it. Bad specs exit with a message."""
    if not name_or_path:
        spec = dict(DEFAULTS)
        spec["preset"] = None
        return spec
    key = str(name_or_path)
    if key.lower() in PRESETS:
        spec = dict(DEFAULTS)
        spec.update(PRESETS[key.lower()])
        spec["preset"] = key.lower()
        return spec
    path = os.path.expanduser(key)
    if _dir and not os.path.isabs(path):
        path = os.path.join(_dir, path)
    real = os.path.realpath(path)
    if real in _seen:
        sys.exit(f"error: spec {key!r} is its own base (directly or through another spec)")
    if not os.path.isfile(path):
        sys.exit(f"error: no preset or spec file {key!r} (presets: {', '.join(PRESETS)})")
    try:
        own = json.load(open(path))
    except ValueError as e:
        sys.exit(f"error: {path}: not valid JSON ({e})")
    if not isinstance(own, dict):
        sys.exit(f"error: {path}: a spec is a JSON object of keys ({{\"base\": \"amazon\", …}}), not a {type(own).__name__}")
    spec = resolve(own.get("base"), _seen + (real,), os.path.dirname(real))
    spec.update(own)
    spec["preset"] = own.get("preset") or (spec.get("preset") if own.get("base") else None) \
        or os.path.splitext(os.path.basename(path))[0]
    validate(spec, path)
    return spec


def validate(spec, where):
    """Exit with a message on keys that would otherwise fail deep inside a script."""
    def bad(k, want):
        sys.exit(f"error: {where}: {k} {spec.get(k)!r}: {want}")
    c = spec.get("canvas")
    if not (isinstance(c, list) and len(c) == 2 and all(isinstance(v, (int, float)) and v >= 1 for v in c)):
        bad("canvas", "give [width, height] in px")
    if spec.get("fill") is not None and not (isinstance(spec["fill"], (int, float)) and 0 < spec["fill"] <= 1):
        bad("fill", "a share of the canvas, 0 to 1")
    r = spec.get("fillRange")
    if r is not None and not (isinstance(r, list) and len(r) == 2 and all(isinstance(v, (int, float)) for v in r) and r[0] <= r[1]):
        bad("fillRange", "give [lowest, highest] shares")
    if spec.get("margins") is not None:
        spec["margins"] = parse_margins(spec["margins"])
    if spec.get("align") not in ("center", "bottom", "top"):
        bad("align", "center, bottom or top")
    for k in ("aspect", "safeAspect"):
        if spec.get(k):
            parse_aspect(spec[k])
    hex_rgb(spec.get("background") or "#ffffff")
    if not (isinstance(spec.get("formats"), list) and spec["formats"]):
        bad("formats", "a list of file types, like [\"jpg\", \"png\"]")


def canvas_size(spec, size=None, aspect=None):
    """(W, H) of the canvas: the spec's canvas; a long side `size` and/or `aspect` given as overrides; and when the
    spec's canvas hasn't the spec's own "aspect" ({"base": "shopify", "aspect": "4:5"}), its long side at that aspect."""
    cw, ch = int(spec["canvas"][0]), int(spec["canvas"][1])
    if size is None and aspect is None and aspect_ok(spec, cw, ch) is not False:
        return cw, ch
    aw, ah = parse_aspect(aspect) if aspect else aspect_of(spec)
    long_side = size or max(cw, ch)
    return (long_side, round(long_side * ah / aw)) if aw >= ah else (round(long_side * aw / ah), long_side)


def suggested_name(spec, base):
    ext = spec["formats"][0] if spec.get("formats") else "jpg"
    return spec.get("naming", "{name}-{preset}.{ext}").format(name=base, preset=spec.get("preset") or "custom", ext=ext)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    if len(sys.argv) < 2:
        for k, p in PRESETS.items():
            print(f"{k:8s} {p['name']}: {p['canvas'][0]} x {p['canvas'][1]}, fill {p['fill']}"
                  f"{' ' + str(p['fillRange']) if p.get('fillRange') else ''}, "
                  f"{'pure ' if p.get('pureBackground') else ''}{p['background']}; "
                  f"{'official' if p['official'] else 'third-party'}: {p['url']}")
        return
    print(json.dumps(resolve(sys.argv[1]), indent=1))


if __name__ == "__main__":
    main()
