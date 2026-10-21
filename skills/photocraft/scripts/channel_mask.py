#!/usr/bin/env python3
"""Mask hair and fur from the colour channel that separates them best from the backdrop: the channel route.

Retouchers mask hair from a channel (PHLEARN, Planet Photoshop): they pick the R, G or B channel with the most
contrast between the strands and the backdrop (often blue: skin and warm hair go darkest there), copy it, crush it
toward black and white with Levels, paint the solid inside white and the clean backdrop black, and load it as the
mask. Select and Mask's own hair refinement fails exactly where that works: a backdrop close to the hair in colour but
not in one channel. This does the same by measurement, per pixel: in the chosen channel, a pixel's coverage is how far
it sits between the clean backdrop behind it (fitted under the subject, so a lit sweep's gradient doesn't matter) and
the hair colour next to it (spread out from the solid inside), alpha = (backdrop - pixel) / (backdrop - hair). Then it
is crushed like the Levels move, but only at the black end: coverage under 0.1 (or the backdrop's noise) goes to 0.
A single channel reads a highlight on the hair as half transparent, which retouchers paint over; here the rough cut
fills such holes, from half the band inside its edge inward. The solid inside and the clear outside come from the
rough cut.

usage: channel_mask.py orig.png rough.png outdir [--origin X Y] [--band 12] [--area AREA] [--channel auto|red|green|blue]

orig.png   the photo (export with the cut layer hidden, or the original file as PNG)
rough.png  a rough cut, same frame: an RGBA export of select.subject (+ refineEdge), or a grey mask PNG (white = subject)
outdir     mask.png (the new mask), cut.png (the photo with that mask, RGBA: run cutout_check.py on it, then --edge-fix:
           the strands still carry the backdrop's colour), layers.json ("Product (channel mask)": the photo as a pixel
           layer with that mask, for import_layers.py --above <Background id>; its verify checks placement and colour
           only, since the photo masked over itself always matches: judge the mask with cutout_check.py on cut.png,
           which holds exactly that mask), band.png (the band solved, red; where it fell back to the rough cut, blue).
--area     only solve inside this area.json polygon (the hair), keep the rough cut's edge elsewhere (a collar, a shoulder)
--band     px each side of the rough cut's edge where strands are solved: 12 for short hair, 20-40 for loose or frizzy hair
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
from cutout_check import bbox, copy_colour_chunks, edge_distance
from product_shot import fit_backdrop, upsample

NAMES = ("red", "green", "blue")


def smooth_field(vals, wts, w, h, sigma):
    """Normalised convolution at a quarter of the resolution: the weighted mean of vals around each pixel, spread
    into where wts is 0 (the hair colour carried out from the solid inside into the band)."""
    k = max(1, int(sigma // 4))
    num, cw, ch = imgops.downscale([v * t for v, t in zip(vals, wts)], w, h, k)
    den, _, _ = imgops.downscale(wts, w, h, k)
    s = max(1.0, sigma / k)
    num, den = imgops.gauss(num, cw, ch, s), imgops.gauss(den, cw, ch, s)
    f = [n / d if d > 1e-4 else 0.0 for n, d in zip(num, den)]
    return upsample(f, cw, ch, w, h), upsample(den, cw, ch, w, h)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("orig"); ap.add_argument("rough"); ap.add_argument("outdir")
    ap.add_argument("--origin", type=int, nargs=2, default=[0, 0], help="where the frame sits in the photo")
    ap.add_argument("--band", type=int, default=12, help="px each side of the rough edge where strands are solved")
    ap.add_argument("--area", help="solve only inside this area.json (full-image coordinates); the rough edge elsewhere")
    ap.add_argument("--channel", choices=("auto",) + NAMES, default="auto")
    ap.add_argument("--min-contrast", type=float, default=20, help="levels between backdrop and hair in the channel, below which a pixel keeps the rough cut")
    ap.add_argument("--min-speck", type=int, default=30, help="px: smaller islands not joined to the subject are dropped")
    ap.add_argument("--black-point", type=float, help="alpha below this goes to 0 (default 0.1, or the backdrop's noise if higher)")
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)

    w, h, R, G, B = imgops.load(a.orig)
    w2, h2, MR, MG, MB, A0 = imgops.load_rgba(a.rough)
    if (w, h) != (w2, h2):
        sys.exit(f"error: orig is {w}x{h} but rough is {w2}x{h2}; export both from the same frame")
    if min(A0) >= 0.999:  # no transparency: it must be a grey mask PNG, not a flat photo
        if any(abs(r - g) > 1 or abs(g - b) > 1 for r, g, b in zip(MR, MG, MB)):
            sys.exit("error: rough.png has no transparency and isn't a grey mask: export the cut layer alone (Background "
                     "hidden) as an RGBA PNG, or a mask as grey (white = subject)")
        A0 = [v / 255 for v in MR]
    N = w * h
    inside = [1 if v >= 0.5 else 0 for v in A0]
    if not bbox(inside, w, h):
        sys.exit("error: the rough cut is empty")
    band = a.band
    dist = edge_distance(inside, w, h, cap=band + 2)
    core = [1.0 if inside[i] and dist[i] > band else 0.0 for i in range(N)]
    far = [1 if not inside[i] and dist[i] > band else 0 for i in range(N)]
    unknown = [i for i in range(N) if dist[i] <= band]
    if a.area:
        cfg = json.load(open(a.area))
        polys = cfg.get("area") or cfg.get("skin") or cfg.get("hair")
        am = imgops.polygon_mask(polys, a.origin[0], a.origin[1], w, h, cfg.get("exclude", []))
        unknown = [i for i in unknown if am[i] > 0.5]
    if not unknown:
        sys.exit("error: no band to solve (empty --area, or a rough cut with no edge)")
    nfar = sum(far)
    if nfar < max(500, 0.01 * N):  # the backdrop is fitted from what lies beyond the band: too little, and it guesses
        sys.exit(f"error: only {nfar} px of clear backdrop more than --band {band} px from the rough edge: export a wider "
                 "frame round the subject, or a smaller --band")

    # the clean backdrop behind every pixel, and the hair colour next to every band pixel
    (BR, BG, BB), noise = fit_backdrop(R, G, B, far, w, h)
    chans, backs = (R, G, B), (BR, BG, BB)
    fields = []
    for ch in chans:
        f, den = smooth_field(ch, core, w, h, 2 * band)
        fields.append(f)
    near_core = den  # where the hair colour is known (a band far from any solid inside isn't)

    # the channel with the most consistent strand-to-backdrop contrast in the band
    sample = unknown[::max(1, len(unknown) // 20000)]
    scores = {}
    for c, name in enumerate(NAMES):
        d = [backs[c][i] - fields[c][i] for i in sample if near_core[i] > 0.02]
        if not d:
            scores[name] = {"contrast": 0.0, "consistency": 0.0, "score": 0.0}
            continue
        med = sorted(abs(v) for v in d)[len(d) // 2]
        cons = abs(sum(1 if v > 0 else -1 for v in d)) / len(d)
        scores[name] = {"contrast": round(med, 1), "consistency": round(cons, 2), "score": round(med * cons, 1)}
    best = max(NAMES, key=lambda n: scores[n]["score"]) if a.channel == "auto" else a.channel
    c = NAMES.index(best)
    I, Bk, F = chans[c], backs[c], fields[c]

    alpha = [1.0 if v else 0.0 for v in core]
    for i in range(N):
        if not core[i] and not far[i]:
            alpha[i] = A0[i]  # the rough cut where nothing is solved (outside --area)
    def cast_shadow(i):
        """Outside the rough cut, a pixel that is smooth and just a darker copy of the backdrop's colour is the
        subject's shadow on the sweep, not a strand: a channel alone reads it as half-transparent fur (a kitten's
        soft shadow came out as a haze over 1.2-1.7x the cut's perimeter). Strands are thin, so never smooth."""
        x, y = i % w, i // w
        if inside[i] or not (0 < x < w - 1 and 0 < y < h - 1):
            return False
        v = [I[j] for j in (i - w - 1, i - w, i - w + 1, i - 1, i, i + 1, i + w - 1, i + w, i + w + 1)]
        m = sum(v) / 9
        if sum((t - m) ** 2 for t in v) / 9 > max(1.5, 2.5 * noise) ** 2:
            return False
        lb, li = imgops.lum(BR[i], BG[i], BB[i]), imgops.lum(R[i], G[i], B[i])
        k = li / max(1.0, lb)
        return li < lb and max(abs(R[i] - k * BR[i]), abs(G[i] - k * BG[i]), abs(B[i] - k * BB[i])) <= 6

    raw, fell, shadows = {}, 0, 0
    for i in unknown:
        d = Bk[i] - F[i]
        if abs(d) < a.min_contrast or near_core[i] <= 0.02:
            fell += 1
            continue
        if cast_shadow(i):
            alpha[i] = 0.0
            shadows += 1
            continue
        raw[i] = (Bk[i] - I[i]) / d

    # the Levels crush at the black end: 0.1, or 3 sigma of the clear backdrop's noise in this channel's alpha units
    # if that is higher. On a real JPEG portrait the noise floor alone (0.02) left the faintest strands as streaky
    # grey haze; 0.1 cleared it and kept the strands, 0.2-0.3 started to lose them. On a noise-free synthetic the
    # alpha error went from 0.016 to 0.032. (Measured on the band itself the black point is polluted: the fur in its
    # outer half put it at 0.35 on a kitten and erased the fur; a white point from the inner half, where highlights
    # read as transparent, hardened hair to a 1.4 px edge.)
    dmed = sorted(abs(Bk[i] - F[i]) for i in raw)[len(raw) // 2] if raw else 1.0
    lo = a.black_point if a.black_point is not None else min(0.3, max(0.1, 3 * noise / max(1.0, dmed)))
    for i, v in raw.items():
        al = min(1.0, max(0.0, (v - lo) / (1 - lo)))
        if inside[i] and dist[i] > band // 2:  # deeper inside the rough cut: its alpha fills highlight holes
            al = max(al, A0[i] * min(1.0, (dist[i] - band // 2) / max(1, band - band // 2)))
        alpha[i] = al

    # islands not joined to the subject: specks of backdrop texture, dust
    sub = [1 if v > 0.1 else 0 for v in alpha]
    comps = imgops.components(sub, w, h)
    dropped = 0
    for comp in comps:
        if len(comp) < a.min_speck and not any(core[j] for j in comp):
            for j in comp:
                alpha[j] = 0.0
            dropped += len(comp)

    alpha = [round(min(1.0, max(0.0, v)) * 255) / 255 for v in alpha]
    imgops.save_gray(os.path.join(a.outdir, "mask.png"), w, h, alpha)
    imgops.save_rgb(os.path.join(a.outdir, "cut.png"), w, h, R, G, B, alpha)
    imgops.save_rgb(os.path.join(a.outdir, "orig.png"), w, h, R, G, B)
    # the photo's colour profile on the cut, so it is the same colours wherever it goes (composite.py converts by it).
    # Not on the PNGs import_layers opens: those take the document's profile, and a tagged PNG can stop the live app
    # with a profile-mismatch dialog.
    copy_colour_chunks(a.orig, os.path.join(a.outdir, "cut.png"))
    # band.png: the photo dimmed, solved band pixels red (by alpha), fallbacks blue, at most 1200 px
    k = max(1, math.ceil(max(w, h) / 1200))
    vw, vh = w // k, h // k
    solved, fallback = set(raw), set(unknown) - set(raw)
    VR, VG, VB = [], [], []
    for y in range(vh):
        for x in range(vw):
            i = y * k * w + x * k
            l = 0.4 * imgops.lum(R[i], G[i], B[i])
            VR.append(l + 155 * alpha[i] if i in solved else l)
            VG.append(l)
            VB.append(l + 120 if i in fallback else l)
    imgops.save_rgb(os.path.join(a.outdir, "band.png"), vw, vh, VR, VG, VB)
    ox, oy = a.origin
    cw, ch = min(640, w), min(640, h)
    bb = bbox([1 if i in solved else 0 for i in range(N)], w, h) or [0, 0, w - 1, h - 1]
    vx = int(min(max(0, (bb[0] + bb[2]) / 2 - cw / 2), w - cw)); vy = int(min(max(0, (bb[1] + bb[3]) / 2 - ch / 2), h - ch))
    imgops.save_rgb(os.path.join(a.outdir, "preview.png"), cw, ch,
                    *[[chn[y * w + x] for y in range(vy, vy + ch) for x in range(vx, vx + cw)] for chn in (R, G, B)])
    json.dump({"center": [ox + w / 2, oy + h / 2], "crop": [ox + vx, oy + vy, cw, ch], "preview": "preview.png",
               "layers": [{"name": "Product (channel mask)", "image": "orig.png", "mask": "mask.png"}]},
              open(os.path.join(a.outdir, "layers.json"), "w"), indent=1)

    warnings = []
    contrast = scores[best]["contrast"]
    if contrast < 25:
        warnings.append(f"only {contrast:.0f} levels between the hair and the backdrop in the best channel ({best}): light or grey "
                        "hair on a light backdrop, or a backdrop the hair's colour. No channel separates the strands; keep a "
                        "soft refineEdge result (smartRadius), paint the outline by hand, or reshoot on a contrasting backdrop")
    if scores[best]["consistency"] < 0.8:
        warnings.append("the subject is lighter than the backdrop in some places and darker in others in this channel (a "
                        "white collar and dark hair against grey): give --area round the hair only")
    share = fell / max(1, len(unknown))
    if share > 0.3:
        warnings.append(f"{100 * share:.0f}% of the band kept the rough cut (contrast under --min-contrast there): see band.png")
    stats = {"channel": best, "scores": scores, "band": band, "blackPoint": round(lo, 3),
             "solved": len(raw), "keptRough": fell, "castShadow": shadows, "specksDropped": dropped, "backdropNoise": round(noise, 2),
             "warnings": warnings,
             "next": ["cutout_check.py <outdir>/cut.png orig.png <dir> --kind soft --edge-fix   (strands keep the backdrop's colour)",
                      "import_layers.py <outdir>/layers.json --above <Background id>, then hide the old cut layer"]}
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
