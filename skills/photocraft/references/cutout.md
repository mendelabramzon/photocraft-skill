# Cutouts, background removal and product photos on white

Read this before cutting a subject out of its background or making a marketplace product image. It is the full
version of the recipe in SKILL.md: how clipping-path studios and e-commerce retouchers work, and how to do the same
in PhotoCraft with `cutout_check.py` (judges the cut) and `product_shot.py` (shadow, white backdrop, canvas).

## Contents
- What separates a professional cutout from a cheap one
- The layer stack you're building
- Step 1: set up
- Step 2: select by edge type
- Step 3: check the cut
- Step 4: shadow, white backdrop and canvas
- Step 5: check the deliverable
- Step 6: save
- Tuning and false hits

## What separates a professional cutout from a cheap one

- **Masks, never erasers.** The cut lives in a layer mask on a copy of the photo; the original stays underneath,
  so any edge can be fixed later.
- **Each edge gets the treatment its type needs.** A hard product edge is crisp with one pixel of anti-aliasing,
  traced slightly inside the edge so no backdrop comes along. A feathered product edge reads as blurry and a binary
  one as jagged. Hair and fur need a soft edge built with an edge-aware radius ("smart radius" uses a small radius on
  simple edges and a larger one on complex ones) and colour decontamination, which restores the subject's colour
  where the backdrop tinted it (Adobe's Refine Edge / Select and Mask docs).
- **No backdrop visible at 200 %.** That is the retailer test (GS1 New Zealand's clipping-path checklist for
  Countdown and Foodstuffs: "At 200% magnification, no background/white space can be seen around the edge of the
  product", the path smooth "with no visible jagged or rough edge"). Retouchers check the cut on white, black and a
  saturated colour, because a halo only shows against the opposite tone.
- **Keep everything that belongs to the product.** Automatic subject selection drops low-contrast parts: a silver
  buckle on grey paper, a watch crown, white paws on a white backdrop, the jeans at the frame's edge. Look at the
  whole silhouette on a dark background before anything else.
- **A product needs its shadow.** Dropped on white without one it floats like a sticker. Keep the real contact
  shadow (as a Multiply layer) or paint a soft one along the base; keep it faint and the same across a catalogue.
  Guides disagree on how much shadow Amazon tolerates on a main image; they agree heavy or coloured shadows risk
  rejection, so faint and neutral is the safe choice.
- **Pure white means 255, 255, 255 everywhere.** Amazon's main image: "Pure white background (RGB 255,255,255)",
  product filling "85% or more of the frame", at least 1000 px on the longest side for zoom, JPEG, TIFF or PNG
  (Amazon staff, Seller Central forums). eBay: at least 500 px on the longest side, 1600 px recommended for zoom.
  Shopify: uploads up to 20 MB and 20 megapixels (help.shopify.com); a 2048 x 2048 px square is the usual target.
  Etsy: about 2000 px on the shortest side. The last three come from seller guides: check the marketplace's own
  help before relying on them. Deliver in sRGB.
- **Colour first.** If the backdrop isn't neutral, the product's colours aren't right either: fix white balance
  before cutting (`product_shot.py` warns when the backdrop has a cast).
- **A catalogue is a set.** Same canvas, same fill, same baseline, same shadow style for every product.

## The layer stack you're building

    Product                 copy of the photo, the cut as its layer mask (refineEdge output newLayerWithMask)
    Product on white        group (import_layers.py)
      Shadow (real)         pixel layer, Multiply: photo / clean backdrop, exactly white where there's no shadow
      White backdrop        Solid Color fill #ffffff
    Background              the photo, untouched (covered by the white)

## Step 1: set up

Work in a folder under the home directory, e.g. `~/.photocraft-skill/work/<photo>/` (the app only opens files
under its read root). Open the photo, confirm a profile dialog if one appears, and note the Background's layer id.
Decide the deliverable now: transparent PNG, or a marketplace image (canvas size, aspect, fill, alignment).

## Step 2: select by edge type

1. Make the selection.
   - Most subjects on a plain backdrop: `select.subject {}`.
   - A clean, blown-out backdrop, or a white product on white (select.subject took only the grey parts of a white
     controller): select the backdrop and invert,
     `select.magicWand {"x": 5, "y": 5, "tolerance": 8, "contiguous": true}` then `select.inverse {}`;
     or `select.object {"rect": [0, 0, W, H]}`.
2. Look at it (screenshot, or Step 3's sheet), then repair it:
   - Missing parts: `select.object {"rect": [x, y, w, h], "mode": "add"}` around them (it brought back a buckle and
     a crown). For white on white, trace a polygon with `scripts/grid.py` coordinates and
     `select.lasso {"points": [[x, y], …], "mode": "add"}`. `select.quick` floods into a white backdrop there.
   - Extras (part of the contact shadow, a prop): the same commands with `"mode": "subtract"`.
3. Refine into a masked copy:
   - Hard product: `select.refineEdge {"radius": 1, "contrast": 25, "output": "newLayerWithMask"}`. Measured edge
     width 0.9–1.6 px on four products; select.subject alone gives 2.7–3.1 px, which looks soft on a product.
   - Hair and fur: `select.refineEdge {"radius": 8, "smartRadius": true, "decontaminate": true, "amount": 100,
     "output": "newLayerWithMask"}`. On a kitten it took the fringe on black from p95 27 to 2.8 levels; radius 16
     overshot (haze, fur cut into).
   `newLayerWithMask` adds "Background copy" with the mask and hides the Background. Rename it "Product"
   (`layer.setProps`).
4. Only if Step 3 says the mask runs past the edge: `shiftEdge` moves it in whole pixels. At radius 1, -10 does
   nothing and -15 to -25 all move it one pixel; recheck `cutInto` afterwards. `select.modify.contract` gives a
   binary (jagged) edge unless refineEdge runs after it.
5. Colour fringe that decontaminate didn't fix: `layer.matting.removeWhiteMatte` / `removeBlackMatte` (subject
   shot on white / black) or `layer.matting.colorDecontaminate {"amount": 100, "radius": 4}`. They act on
   transparency only, so run them on a copy whose mask is applied (`layer.duplicate`, `layer.layerMask.apply`);
   on a masked layer they change nothing.

## Step 3: check the cut

Export the cut as RGBA (only the Product layer visible) and the original (Product hidden), same frame:

    $PC exec layer.setProps '{"layer": <Background id>, "visible": false}'
    $PC export ~/.photocraft-skill/work/<photo>/cut.png
    $PC exec layer.setProps '{"layer": <Background id>, "visible": true}'
    $PC cli convert photo.jpg ~/.photocraft-skill/work/<photo>/orig.png
    # headless: pc.py script hide.json --open photo-cut.psd --save cut.png, hide.json hiding the Background
    python3 cutout_check.py cut.png orig.png check/ --kind product      # --kind soft for hair and fur

For every edge pixel it estimates the subject colour just inside (for semi-transparent pixels, from the matting
equation I = aF + (1 - a)B with the cut's own alpha) and the old backdrop just outside, composites the cut on each
check background and measures how far the result lies from the clean subject-to-background line, in levels: the
visible fringe. Read `sheet.png` (the cut on white, black, grey and a saturated colour, then 3x zooms of the
numbered worst spots on black | white), `edges.png` (red = fringe, blue = cut into the subject), and `advice`.

| Measure | Good | Means when bad |
|---|---|---|
| `fringe.deliverable.p95` (on `--bg`) | ≤ 6 levels | old backdrop shows on the new background: decontaminate |
| `fringe.black.p95` | ≤ 15 if it may go on dark | light rim (often a glossy edge reflecting a white sweep: real, fine on white) |
| `backdropInside` | ≤ 0.03 | the mask runs past the edge: a line of backdrop at full opacity |
| `cutInto` | ≤ 0.08 (soft ≤ 0.2) | the mask cuts into the subject |
| `edge.width.median` | 0.7–2 px product, 3–7 px fur | soft (feathered or no contrast) or binary |
| `edge.jagged` | ≤ 0.15 | binary edge: refine with radius 1 |
| `islands.largeParts` | 0 | the selection missed what joins the parts |

Calibration on synthetic cuts with known alpha: clean edge p95 1–2 levels, raw (not decontaminated) 10–20,
feathered 30–45, one pixel too wide 75–90; the p95 tracks the true fringe computed from the real subject colour. The check can't know what
you meant to keep: always look at `sheet.png` at fit-to-screen for missing parts.

## Step 4: shadow, white backdrop and canvas

    python3 product_shot.py orig.png cut.png ps/ [--shadow real|contact|none] [--size 2000] [--aspect 1:1]
                            [--fill 0.85] [--align center|bottom] [--opacity 1]

- `--shadow real` (default) keeps the photo's own shadow: the photo divided by the clean backdrop behind it. The
  backdrop is fitted robustly (shadows are darker outliers, so they don't pull it), its noise is cut off so bare
  areas become exactly 255, only shadow connected to the product is kept, and inside 3 px of the mask the shadow
  is continued from further out, so product pixels a tight mask left behind don't print as a dark outline.
  Neutral grey by default (`--color-shadow` keeps its tint).
- `--shadow contact` paints one when the photo has none: a tight dark line along the base plus a soft spread. The
  base is the lower convex hull of the silhouette (where an object resting on a surface touches it, side or 3/4
  view), so every foot is grounded and nothing hangs in mid-air.
- `--fill 0.85 --size 2000` scales the product's longer side to 85 % of a 2000 px square; `--align bottom` stands
  every product of a set on the same baseline.

Read `viz.png` (photo | fitted backdrop | shadow layer), `final.png` (predicted deliverable) and the stats. Act on
`missingParts`: fine detail inside the "shadow" is a part of the subject the cut left out (it caught a buckle, a
crown, white paws, ear tufts; fur tips within 8 px of the mask are ignored). Fix the cut and rerun. Then, in order:

    $PC script ps/prep.json        # only if not empty: grows the canvas before any fill layer exists
    python3 import_layers.py ps/layers.json --above <Background id>   # below the Product layer; verifies the render
    $PC script ps/steps.json       # crop and resample to the canvas, convert to sRGB

The import must say `"verify": "ok"`. Order matters: a fill layer covers only the canvas it was made on, so if the
canvas grows (or a crop reaches past it) after the White backdrop exists, the new area is transparent. A JPEG
hides that (transparency is composited over white); a PNG doesn't.

## Step 5: check the deliverable

    python3 cutout_check.py --deliverable photo-white.jpg check/ --min-side 1600 --fill 0.85

- `background.pureWhite` near 0.99 and `borderPure` 1.0.
- `offWhite.touchingBorder` 0: off-white running to the border is a backdrop that wasn't replaced (an unretouched
  shoe photo: 882k pixels) or a shadow running off the canvas. `offWhite.specks` 0: dust or leftovers.
  `edgeAndShadow` is fine: JPEG ringing within its 8x8 block and the shadow's soft tail.
- `product.fill` ≥ the target, `centreOffset` near 0, `sizeOk`, `profile` sRGB IEC61966-2.1.
- `deliverable.png` maps it: orange = edge and shadow, magenta = touching the border, blue = specks.

## Step 6: save

- Layered: `app.save {"path": "…/photo-white.psd"}`, a new name next to the original. Save once before Step 4's
  `steps.json` too if the uncropped, full-resolution cutout may be wanted later.
- JPEG: `$PC cli convert photo-white.psd photo-white.jpg --quality 95` (`app.save` ignores quality).
- Transparent PNG of the cutout: hide the Background and the "Product on white" group, `$PC export cutout.png`.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| A buckle, crown, paw or leg missing; `missingParts` boxes | select.subject drops low-contrast parts and parts touching the frame | `select.object` rect in add mode, or a traced `select.lasso` add; rerun |
| `largeParts` > 0 (a white product in pieces) | subject and backdrop alike | select the backdrop: magicWand + inverse, or object on the full frame |
| Light rim on black around a dark product shot on white | white backdrop in edge pixels, or the gloss reflecting the sweep | fine on white; for dark backgrounds decontaminate or Remove White Matte. Contracting doesn't help on gloss (`cutInto` jumps) |
| Grey haze under the product on a coloured background | the contact shadow went into the mask | subtract it from the selection before refining |
| Soft, slightly blurred product edge (width ~3 px) | refine without contrast | `refineEdge` radius 1, contrast 25 |
| White blob between legs on a coloured background | `select.quick` flooded into a white backdrop | trace with `select.lasso` |
| `shiftEdge` -10 does nothing; -15 cuts in | it moves whole pixels at radius 1 | use it only when `backdropInside` > 0.03; recheck `cutInto` |
| Matting commands change nothing | they need transparency | apply the mask on a copy first |
| Transparent corners in the PNG deliverable | the canvas grew after the fill layer was made | run `prep.json` before the import |
| `offWhite.touchingBorder` > 0 | shadow runs off the canvas, or backdrop left | lower `--fill` or `--reach`; check the cut |
| `backdrop is not neutral` warning | cool or warm backdrop light | correct white balance first; the product carries the same cast |
| `enlarged` warning | product smaller than the canvas needs | a smaller `--size`, or a higher-resolution original |
