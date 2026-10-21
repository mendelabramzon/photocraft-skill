# Cutouts, background removal and product photos for marketplaces

Read this before cutting a subject out of its background or making a marketplace product image. It is the full
version of the recipe in SKILL.md: how clipping-path studios and e-commerce retouchers work, and how to do the same
in PhotoCraft with `cutout_check.py` (judges the cut, builds the edge-colour layers, checks the deliverable),
`channel_mask.py` (the channel route for hair and fur), `product_shot.py` (shadow, reflection, glass, backdrop and
canvas) and `specs.py` (marketplace specifications, read by both).

## Contents
- What separates a professional cutout from a cheap one
- The layer stack you're building
- Step 1: set up and choose the spec
- Step 2: select by edge type
- Step 3: check the cut
- Step 4: fix the edge colour
- Step 5: shadow, reflection, backdrop and canvas
- Glass and other transparent products
- Step 6: check the deliverable
- Step 7: save
- Marketplace specs and a client's own spec
- Before the cut: props, lens fringing, dust, colour, ghost mannequins
- Tuning and false hits

## What separates a professional cutout from a cheap one

- **Masks, never erasers.** The cut lives in a layer mask on a copy of the photo; the original stays underneath,
  so any edge can be fixed later.
- **The edge type decides the method.** Hard, geometric edges (bottles, boxes, electronics) get a crisp path-like
  edge; hair, fur, wool, sheer fabric and glass get a pixel mask; mixed shots need both (Pixelz, the best-documented
  outsourcer: its best paths are "still made by actual humans… using the Photoshop Pen tool", automatic ones "can get
  inaccurate near edges"). A hard edge on fur reads as a sticker. A hard product edge is crisp with one pixel of
  anti-aliasing, traced slightly inside the edge; a feathered one reads as blurry, a binary one as jagged.
- **Hair: the channel route when Refine fails.** Select and Mask fails where the backdrop is close to the hair's
  colour (Adobe Community); retouchers then mask from the R, G or B channel with the most strand-to-backdrop
  contrast, crushed toward black and white (PHLEARN, Planet Photoshop). `channel_mask.py` does that per pixel.
- **Fix the edge's colour, not only the mask.** A halo is backdrop colour trapped in edge pixels. Decontaminate
  Colors at full strength looks overprocessed and bakes its result in (PHLEARN); the forum experts' "far more
  controllable" alternative is a layer clipped to the cutout in Color mode painted with the subject's edge colour,
  and Luminosity mode for a bright edge on a dark cutout (Adobe Community). `cutout_check.py --edge-fix` builds both.
- **Glass is never cut with a binary mask.** On white it goes in Multiply so the white drops out, with a Screen copy
  for the highlights (TutKit, Tuts+). `product_shot.py --transparent`.
- **No backdrop visible at 200 %.** The retailer test (GS1 New Zealand's clipping-path checklist: "At 200%
  magnification, no background/white space can be seen around the edge of the product"). Check the cut on white,
  black and a saturated colour: a halo only shows against the opposite tone.
- **Keep everything that belongs to the product.** Automatic selection drops low-contrast parts (a silver buckle on
  grey paper, a watch crown, white paws on white) and parts touching the frame. Look at the whole silhouette first.
- **A product needs its shadow, built in layers.** Dropped on white without one it floats. Pros stack Multiply
  layers sampled from the product's own dark tones, never #000: a tight contact shadow where it touches, a wider,
  softer cast shadow, and for glossy goods and footwear a flipped, fading reflection (Clipping Expert Asia; the
  Drop Shadow style alone "doesn't cut it": Photoshop Essentials). Pixelz sells natural, drop and reflection
  shadows as separate options: keep each on its own layer so one can go per marketplace.
- **One spec drives placement and the check.** Studios encode each client or marketplace once: background, fill or
  margins, alignment, shadow, format, colour space, naming (Pixelz order specifications), and run every image through
  it. Marketplaces disagree more than vendor guides admit (the table below).
- **Colour first.** If the backdrop isn't neutral, the product's colours aren't right either: fix white balance
  before cutting (`product_shot.py` warns when the backdrop has a cast). Colour is judged against the physical
  product or a swatch.
- **A catalogue is a set.** Same canvas, same fill, same baseline, same shadow style for every product.

## The layer stack you're building

    Edge tone / Edge colour   clipped to Product, Luminosity / Color, mask = the edge band (cutout_check --edge-fix)
    Defringe (edge)           (if fringing) Hue/Saturation clipped to Product, mask = a 6 px border of its outline
    Product                   copy of the photo, the cut as its layer mask (refineEdge newLayerWithMask, or channel_mask)
    Product on white          group (product_shot.py + import_layers.py)
      Opaque parts            (glass only) the photo masked to labels and caps
      Glass (highlights)      (glass only) Screen
      Glass (transmission)    (glass only) Multiply: photo / clean backdrop
      Shadow (real|contact)   pixel layer, Multiply: exactly white where there's no shadow
      Reflection              (optional) the product mirrored about its ground line, fading, Normal at 15-30 %
      White backdrop          Solid Color fill (#ffffff, or the spec's colour: "Backdrop")
    Objects                   (if props) duplicate of the photo with the prop and its shadow cloned away, below the cut
    Background                the photo, untouched (covered by the backdrop)

## Step 1: set up and choose the spec

Work in a folder under the home directory, e.g. `~/.photocraft-skill/work/<photo>/` (the app only opens files
under its read root). Open the photo, confirm a profile dialog if one appears, and note the Background's layer id.
Decide the deliverable now: a transparent PNG, or a marketplace image. `python3 specs.py` lists the presets
(amazon, google, ebay, shopify, etsy, zalando) with their sources; `specs.py zalando > client.json` starts a
client's own spec ("Marketplace specs" below).

Props (a shoe tree, a stand, a hanger) go before the cut: Amazon allows none on a main image, and left in they read as
shadow or as a missing part later. Remove them, with their own shadow, on an "Objects" layer ("Before the cut"
below); then the cut, and every `orig.png` the scripts read, comes from the cleaned document (export it with that
layer visible), never from `cli convert photo.jpg`. Lens fringing is fixed on the cut ("Before the cut").

## Step 2: select by edge type

| Edge | Select | Refine into a masked copy |
|---|---|---|
| Hard product on a plain backdrop | `select.subject {}` | `select.refineEdge {"radius": 1, "contrast": 25, "output": "newLayerWithMask"}`: edge 0.9–1.6 px wide on four products (select.subject alone: 2.7–3.1 px, soft) |
| Dark product on a light sweep (shoes, bags, electronics) | the backdrop route below: select.subject cuts off thin dark parts | as above |
| White product, or a blown backdrop | `select.magicWand {"x": 5, "y": 5, "tolerance": 8, "contiguous": true}` + `select.inverse {}`, or `select.object {"rect": [0, 0, W, H]}` (select.subject took only the grey parts of a white controller) | as above |
| Hair, fur on a contrasting backdrop | `select.subject {}` | `{"radius": 8, "smartRadius": true, "output": "newLayerWithMask"}`, then the edge colour (Step 4). `"decontaminate": true, "amount": 100` in the same step is the quick, baked-in option (on a kitten it took the fringe on black from p95 27 to 2.8; radius 16 overshot) |
| Hair against a backdrop close in colour, or where Refine leaves a blobby or grey outline | the refined cut above as the rough cut | `channel_mask.py` (below) |
| Glass, clear plastic | a cut of its outline (`select.subject`, or a traced `select.lasso`) | `product_shot.py --transparent` replaces the opaque cut |
| Mixed (a model with loose hair, a product with fur trim) | both | the hard route, then channel_mask.py with `--area` round the soft part |

Look at the selection (screenshot, or Step 3's sheet), then repair it:
- Missing parts: `select.object {"rect": [x, y, w, h], "mode": "add"}` around them (it brought back a buckle and a
  crown). For white on white, trace a polygon with `scripts/grid.py` coordinates and
  `select.lasso {"points": [[x, y], …], "mode": "add"}`. `select.quick` floods into a white backdrop there.
- Extras (part of the contact shadow, a prop): the same commands with `"mode": "subtract"`.

`newLayerWithMask` adds a copy with the mask ("Background copy") and hides the layer it was refined from (the Background,
or the "Objects" layer after a prop removal). Rename the copy "Product" (`layer.setProps`). Only if Step 3 says the mask runs past the edge: `shiftEdge` moves it in whole pixels (at radius
1, -10 does nothing and -15 to -25 all move it one pixel; recheck `cutInto`). `select.modify.contract` gives a binary
(jagged) edge unless refineEdge runs after it.

### The backdrop route for dark products on a light sweep

On a black shoe on a light grey sweep, select.subject + refineEdge (radius 1, contrast 25) cut off the lace tips above
the eyelets, the heel's rounded collar corner and the toe's outer edge line, in all three attempts; `select.object`
in add mode didn't bring them back, and the check's `cutInto` (0.045) looked fine. Selecting the backdrop instead
worked, because a light sweep is easy to select and everything that isn't it is the product:

    select.magicWand {"x": X, "y": Y, "tolerance": 40, "contiguous": true}                  # on the sweep
    select.magicWand {"x": X2, "y": Y2, "tolerance": 40, "contiguous": true, "mode": "add"}  # a warmer or darker patch of it
    select.inverse {}
    select.lasso {"points": [[0, 0], [W, 0], [W, yR], [xR, yR], [xL, yL], [0, yL]], "mode": "intersect"}
    select.subject {"mode": "add"}
    select.refineEdge {"radius": 1, "contrast": 25, "output": "newLayerWithMask"}

The lasso keeps only what lies above a line just over the sole (its points follow that line), so the floor shadow,
which the wand counts as "not backdrop", stays out; select.subject then adds the sole and body back. Result:
`cutInto` 0.008 (was 0.045), and the shadow's darkest point 0.52 (was 0.81, the cut-off lace tips, which printed as
five soft grey blobs above the laces on the white deliverable). product_shot.py now flags that case (Step 5).

### The channel route for hair and fur

    python3 channel_mask.py orig.png cut.png chan/ [--band 12] [--area hair.json]
    python3 cutout_check.py chan/cut.png orig.png check/ --kind soft --edge-fix
    python3 import_layers.py chan/layers.json --above <Background id>     # "Product (channel mask)"; hide the old cut

It picks the channel with the most consistent strand-to-backdrop contrast in a band of `--band` px each side of the
rough cut's edge (green or blue on the test photos), and solves each band pixel's coverage in it against the clean
backdrop behind it (fitted under the subject, so a lit sweep's gradient doesn't matter) and the hair colour next to
it: alpha = (backdrop - pixel) / (backdrop - hair). Coverage under `--black-point` goes to 0 (the Levels crush);
deeper inside the rough cut, its alpha fills the holes a channel reads into highlights. Smooth pixels that are
only a darker copy of the backdrop's colour are the subject's shadow on the sweep, not fur, and stay out. `band.png`
shows the band (red = solved, blue = kept the rough cut: too little contrast there). It needs clear backdrop beyond
the band to fit the backdrop from (under 500 px, or 1 % of the frame, it stops: export a wider frame), and a rough cut
with transparency (or a grey mask). The import's verify only checks placement and colour, since the photo masked
over itself always matches: the mask is judged with cutout_check.py on `chan/cut.png`, which holds exactly that mask.

- On a synthetic cut with known alpha (hair strands and a body over a green gradient, from a binary rough cut), the
  alpha came within 0.032 of the truth on average over the edge (0.056 on the strands); Refine Edge (radius 8, smart
  radius) from the same selection 0.039 (0.067). With Step 4 the true fringe on black was p95 4.0 levels, Refine Edge
  with decontaminate 10.8.
- On a studio portrait (dark hair on light grey; green channel, 145 levels of contrast) it kept more strands than
  Refine Edge, with an edge 3.6 px wide (Refine: 4.4), under 1 % cut into the hair and no haze. Strands crossing 50 %
  coverage show up as many small "islands" in the check: that's hair, not specks.
- On a grey kitten on a light floor it cut into the fur less (`cutInto` 0.048 against 0.125) but read the soft shadow
  under the paws as fur (`haze` 0.54 against 0.08): give `--area` round the fur away from the floor there.
- `--black-point` (0.1): coverage below it goes to 0. With only the noise floor (0.02) the faintest strands of a JPEG
  portrait came out as streaky grey haze; at 0.2–0.3 strands start to go. Lower it (0.03) for clean studio files.
- `--band` (12) must reach the strands: on the synthetic, strands up to 70 px long needed 20 (at 10, the error stayed
  0.074). Loose or frizzy hair: 20–40.

The strands it finds still carry the backdrop's colour: always run Step 4 on its cut.

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
numbered worst spots on black | white), `edges.png` (red = fringe, blue = cut into the subject, yellow boxes = stray
islands, listed with their coordinates in `islands.boxes`), and `advice`.

| Measure | Good | Means when bad |
|---|---|---|
| `fringe.deliverable.p95` (on `--bg`) | ≤ 6 levels | old backdrop shows on the new background: Step 4 |
| `fringe.black.p95` | ≤ 15 if it may go on dark | light rim (often a glossy edge reflecting a white sweep: real, fine on white) |
| `backdropInside` | ≤ 0.03 | the mask runs past the edge: a line of backdrop at full opacity |
| `cutInto` | ≤ 0.08 (soft ≤ 0.2) | the mask cuts into the subject |
| `edge.width.median` | 0.7–2 px product, 3–7 px fur | soft (feathered or no contrast) or binary |
| `edge.jagged` | ≤ 0.15 | binary edge: refine with radius 1 |
| `islands.largeParts` | 0 | the selection missed what joins the parts |

Calibration on synthetic cuts with known alpha: clean edge p95 1–2 levels, raw (not decontaminated) 10–20,
feathered 30–45, one pixel too wide 75–90; the p95 tracks the true fringe computed from the real subject colour. The
check can't know what you meant to keep: always look at `sheet.png` at fit-to-screen for missing parts.

## Step 4: fix the edge colour

    python3 cutout_check.py cut.png orig.png check/ --kind soft --edge-fix
    $PC exec layer.setProps '{"layer": <Background id>, "visible": true}'      # the import's verify renders over it
    python3 import_layers.py check/edgefix/layers.json --above <Product id>

Headless, refineEdge's `newLayerWithMask` left the Background hidden in the saved PSD, so show it in a copy first:

    # show.json: [{"command": "layer.setProps", "params": {"layer": <Background id>, "visible": true}}]
    $PC script show.json --open photo-cut.psd --save photo-cut-bg.psd
    python3 import_layers.py check/edgefix/layers.json --file photo-cut-bg.psd --out photo-cut-fixed.psd --above <Product id>

Hide the Background again for a transparent export; under product_shot.py's backdrop it doesn't show anyway.

"Edge colour" is a pixel layer holding, for every semi-transparent edge pixel, the subject colour the check
estimated behind it (the matting solution, or the strand's stronger neighbours for faint pixels), in **Color** mode,
clipped to the Product layer (clipping follows the Product's mask too: tested) and masked to those pixels. "Edge
tone" is the same in **Luminosity** mode, added when subject and old backdrop differ in brightness (a dark product or
dark hair shot on white: a light rim). Together they replace the backdrop's share of each edge pixel; apart, each can
be turned down, painted out or switched off. Opaque pixels are never touched: backdrop at full opacity is a mask that
runs too wide (`backdropInside`), fixed on the mask.

- On a synthetic cut with exact alpha (hair strands and a body over a green gradient), the true fringe went from
  p95 13.8 levels on black, 10.6 on white and 20.1 on magenta to 1.0 on all three (mean 0.3). Refine Edge's
  decontaminate on the same selection left 6.0, 5.6 and 7.1 (amount 100) and 7.0 on black at amount 50.
- On the real hair and kitten test photos the check's own estimate fell from p95 19.2 (hair, on black) and 24.3
  (kitten, on a saturated colour) to about 2, where decontaminate left 21.6 and 13.7. That estimate shares the fix's
  matting, so it isn't an independent measure: judge the zooms. At 2x on blue the fixed hair lost the grey outline
  decontaminate kept.
- The import verifies exactly (kitten, shoe and watch: mean difference 0.0). On a photo whose profile has no builtin
  twin (an Apple RGB portrait) the import converts the edge colours a little: mean 0.08, a few pixels up to 20 levels,
  still "verify ok".
- It can't fix a wrong mask: on feathered, binary or too-wide synthetic cuts the fringe stays (feathered p95 35 → 22).
  Fix the mask first (Step 2), then the colour.
- A shoe's and a watch's remaining fringe on black (p95 16–33) is their glossy opaque rim reflecting the white sweep,
  which is real and fine on white.

`check/edgefix/cut_fixed.png` is the fixed cut, for re-running the check, for a transparent PNG or as composite.py's
element. It carries the input cut's colour profile (copied from cut.png, or orig.png), so a tool reading it converts
it properly: composite.py took an Adobe RGB (1998) cut_fixed.png into an sRGB plate ("converted": "Adobe RGB (1998) ->
srgb"), where an untagged one would pass for sRGB and skip the conversion. channel_mask.py's `cut.png` keeps the
photo's profile the same way; the PNGs that import_layers opens stay untagged (they take the document's profile, and
a tagged PNG can stop the live app with a profile-mismatch dialog).

## Step 5: shadow, reflection, backdrop and canvas

    python3 product_shot.py orig.png cut.png ps/ [--preset amazon|google|ebay|shopify|etsy|zalando | --spec client.json]
                            [--shadow real|contact|none] [--reflection [0.25]] [--background #ffffff]
                            [--size 2000] [--aspect 1:1] [--fill 0.85 | --margins T,R,B,L] [--align center|bottom|top]
                            [--name shoe]

- `--preset` / `--spec` set the canvas, fill, alignment and backdrop at once and write the resolved `ps/spec.json`,
  which Step 6 checks against. Explicit options override them (`--fill` replaces a spec's margins). A spec's
  `"aspect"` wins over a canvas that hasn't it (`{"base": "shopify", "aspect": "4:5"}` places on 1638 x 2048).
- The real shadow and the glass route are measured against the backdrop around the product: a frame cropped so
  tight that under 200 px of clear backdrop lie 4+ px from the cut stops with a message (export a wider frame);
  `--shadow contact|none` work without it.
- `--shadow real` (default) keeps the photo's own shadow: the photo divided by the clean backdrop behind it. The
  backdrop is fitted robustly (8 rounds: on a synthetic sweep with a 35 % shadow, 4 rounds left the fit 15–22 levels
  low under the shadow's faint tail and lost it; 8 rounds came within 2–7, and the extracted shadow's error fell from
  12.4 to 4.5 levels on average), its noise is cut off so bare areas become exactly 255, only shadow connected to the
  product is kept, and inside 3 px of the mask the shadow is continued from further out, so product pixels a tight
  mask left behind don't print as a dark outline. Neutral grey by default (`--color-shadow` keeps its tint).
- `--shadow contact` paints one when the photo has none: a tight dark line along the base plus a soft spread. The
  base is the lower convex hull of the silhouette (where an object resting on a surface touches it, side or 3/4
  view): it bridges an arch or the gap between legs, so every foot is grounded and nothing hangs in mid-air (a
  sitting kitten's paws each get theirs).
- `--reflection 0.25` adds the glossy-surface look for footwear and shiny goods: the product mirrored about the line
  it stands on, column by column (a 3/4 view's faces each mirror about their own bottom edge), fading to nothing
  within `--reflection-length` (0.3) of its height, slightly blurred, on its own "Reflection" layer under the shadow
  at that opacity. Centred or top-aligned, the product and its reflection are scaled and placed together, so both
  stay on the canvas: `--fill` is then their share (`fillWithReflection`, which the check compares with `--fill`
  when the spec has no marketplace range), and a tall product's own fill drops. A marketplace's range is about the
  product alone: a bottle at Google's 0.82 came out at 0.65, which the check fails against Google's 75 % minimum
  (drop the reflection or shorten `--reflection-length`); a wide shoe on Amazon kept its 0.85. With `--align bottom` give it room (`--bottom 0.25`). Checked on a console in
  3/4 view (its ports mirror and fade) and a shoe (a soft dark band).
- `--background #f2efe9` (or `#fff`, `white`, `black`) puts a coloured backdrop in place of white; the Multiply shadow
  works on any colour.
- `--fill 0.85 --size 2000` scales the product's longer side to 85 % of a 2000 px square; `--margins 0.1,0.05,0.05,0.05`
  fits it inside those gaps instead (top, right, bottom, left, shares of the side or px); `--align bottom` stands every
  product of a set on the same baseline (shoes). A `safeAspect` in the spec (Etsy's 5:4 thumbnail crop) is the box
  everything happens in: the product is scaled to it (fill is its share of that crop, as the check measures it;
  `fillOfCanvas` is the share of the whole canvas), aligned in it, and the margins are cut down to it.

Read `viz.png` (photo | fitted backdrop | shadow: the middle panel is the clean backdrop the shadow is measured
against, interpolated under the product), `final.png` (predicted deliverable) and the stats. A part of the product
the cut left out lands in the "shadow" and prints as a grey patch on white, so act on:
- `missingParts`: fine detail inside the shadow (it caught a buckle, a crown, white paws, ear tufts). Detail within
  3 px of the mask is ignored on a hard product, 8 px with `--kind soft` (fur tips past a soft mask are normal); a
  thin dark outline the cut left along a sole or a rim shows up too: look at the box at 200 %.
- `shadowAboveGround`: smooth dark blobs (over 0.5 of the light taken) well above the line the product stands on,
  with the darkest value: dark parts of the product left out, which the detail test misses. On the black shoe the
  select.subject cut flagged four lace tips at 0.66–0.81, and `missingParts` the heel's collar corner and the toe's
  edge line: the three places a 200 % crop had shown. The backdrop route's cut flagged none, shadow max 0.52.
- a shadow maximum over 0.7 (warned): a shadow on a lit sweep rarely gets that dark.
Fix the cut and rerun. Then, in order:

    $PC script ps/prep.json        # only if not empty: grows the canvas before any fill layer exists
    python3 import_layers.py ps/layers.json --above <id>   # the top layer under the Product (the Background, or the
                                                           # Objects layer: the backdrop would cover a retouch below it)
    $PC script ps/steps.json       # crop and resample to the canvas, convert to sRGB

`nextHeadless` in the output lists the same steps in files, with no window (`pc.py script … --open … --save`,
`import_layers.py … --file … --out`).

The import must say `"verify": "ok"` (every preset, reflection, backdrop colour and margin case tested: mean
difference 0.0). Order matters: a fill layer covers only the canvas it was made on, so if the canvas grows (or a
crop reaches past it) after the backdrop exists, the new area is transparent. A JPEG hides that (transparency is
composited over white); a PNG doesn't.

## Glass and other transparent products

    python3 product_shot.py orig.png cut.png ps/ --transparent [--opaque 548,96,652,126] [--preset …]
    $PC exec layer.setProps '{"layer": <Product id>, "visible": false}'     # the glass layers replace the opaque cut
    python3 import_layers.py ps/layers.json --above <Background id>

Glass shows what is behind it. The photo divided by the clean backdrop behind each pixel is the glass's
transmission, colour by colour (a green bottle stays green): as a Multiply layer it reproduces the glass exactly
over white and lets a coloured backdrop show through it, tinted. What is brighter than the backdrop (highlights)
goes on a Screen layer. The shadow seen through the glass is in the transmission already, so the shadow layer stops
at the glass. Labels, caps and other opaque parts would take the backdrop's colour that way: give them as
`--opaque` (an area.json or a rectangle), and they stay as photographed.

On a synthetic bottle with known transmission (thicker, darker walls, a green tint, a highlight stripe, an opaque
cap) over a 232–248 studio sweep: on white the glass came within 1.7 levels of the truth on average (p95 3.1), where
the ordinary opaque cut was 16.4 off (it keeps the sweep's grey seen through the glass); the cap was exact with
`--opaque`; on a dark blue backdrop the body was within 1.1. The highlight stripe is lost on a dark backdrop (72
levels off): a highlight can't register above a near-white sweep, so the photo doesn't hold it. Add highlights by
hand on a Screen layer for dark backdrops, or shoot glass on a darker sweep. Not tested on a real glass photo: look
at the result at 200 %. `stats.glass.transmissionMedian` under 0.35 means the object is mostly opaque: use the
normal cut.

## Step 6: check the deliverable

    python3 cutout_check.py --deliverable photo-amazon.jpg check/ --spec ps/spec.json     # or --preset amazon

- `pass` and `failed`: every requirement of the spec as `checks` {ok, value, want}: size and minimums, the exact
  aspect (Zalando 1:1.44, to two decimals: 1801 x 2600 passes, 1.445 fails), fill inside the allowed range, centring
  or the bottom baseline, margins, the thumbnail safe area, a pure backdrop where the spec demands it (Amazon), file
  type by content and extension (a PNG renamed .jpg fails), bytes and megapixels, the sRGB profile (Display P3 fails;
  untagged is a warning). With product_shot.py's spec.json, fill and centring are measured on the box it placed the
  product in, `placement` confirms the product is there (a flat image can't always tell a soft shadow or a
  reflection from the product), and `inCanvas` fails a plan that put part of it off the canvas. Without a plan,
  `inCanvas` fails a product touching the frame's edge (cut off), unless the spec's margins allow 0.
- `background.pureWhite` near 0.99 and `borderPure` 1.0 on white. A coloured backdrop is matched within 3 levels
  (JPEG moves it).
- `offWhite.touchingBorder` 0: off-white running to the border is a backdrop that wasn't replaced (an unretouched
  shoe photo: 882k pixels) or a shadow running off the canvas (lower `--fill`). `offWhite.specks` 0: dust or leftovers
  (single 246–249 pixels in a shadow's tail count). `speckBoxes` and `borderBoxes` give where ([x, y, w, h, pixels],
  biggest first). `edgeAndShadow` is fine: JPEG ringing within its 8x8 block and the shadow's soft tail.
- `deliverable.png` (up to 1200 px) maps it: orange = edge and shadow, magenta = touching the border, blue = specks,
  each speck ringed in blue, since single pixels vanish at that scale.
- `metadata`: what the file's EXIF gives away. `pc.py cli convert` carries the master's EXIF into the JPEG (a phone
  photo kept its camera, its settings and its GPS position); the check warns, and the clean route is Step 7's.

## Step 7: save

- Layered: `app.save {"path": "…/photo-white.psd"}`, a new name next to the original. Save once before Step 5's
  `steps.json` too if the uncropped, full-resolution cutout may be wanted later.
- The marketplace file, without the camera's EXIF or GPS: `deliver.py photo-amazon.psd out --preset web --size
  2000x2000 --quality 95 --name shoe-amazon` (at the canvas size it doesn't resample or sharpen; `--metadata
  copyright`, the screen default, keeps only the creator and copyright). Tested: an sRGB 2000 x 2000 JPEG that passed
  the Amazon check with no metadata left. `$PC cli convert photo-white.psd shoe-amazon.jpg --quality 95` works too but
  keeps the master's EXIF (`app.save` ignores quality). product_shot's `deliverAs` suggests the name from the spec's
  `naming` (`{name}-{preset}.{ext}`; `--name` sets the product name), its `next` the commands with the spec's
  `quality`.
- **Two marketplaces from one cut:** `steps.json` crops the document to one canvas, so keep the uncropped layered file
  (the cut, or the document after the import) and run each preset's plan from it: product_shot once per preset
  (`ps_amazon/`, `ps_zalando/`), each preset's prep, import and steps on a copy of that uncropped PSD (headless: the
  same `--open`/`--file` source, a different `--save`/`--out`), never on the other preset's cropped result.
- Transparent PNG of the cutout: hide the Background and the "Product on white" group, `$PC export cutout.png`.

## Marketplace specs and a client's own spec

| Preset | Canvas | Background | Fill | Minimum | Other | Source |
|---|---|---|---|---|---|---|
| `amazon` | 2000 x 2000 | pure 255,255,255 | ≥ 85 % (placed at 87 %) | 1000 px longest (zoom) | JPEG/PNG/TIFF, < 10 MB; no props, text, watermarks | Amazon staff post (help page G1881 needs a login) |
| `google` | 1500 x 1500 | any clean view | 75–90 % | 500 x 500 from 31 Jan 2027 | ≤ 16 MB, ≤ 64 MP; no overlays, watermarks, added logos | Google Merchant Center help (official) |
| `ebay` | 1600 x 1600 | any | (85 %) | 500 px longest | no borders, added text or watermarks | eBay picture policy (official) |
| `shopify` | 2048 x 2048 | any | (85 %) | — | < 20 MB, ≤ 20 MP, sRGB; one aspect across a collection | Shopify help (official) |
| `etsy` | 3000 x 2250 (4:3) | any | 80 % of the centred 5:4 thumbnail crop | 635 px shortest (2000 recommended) | ~1 MB recommended | seller guides only (Etsy's page couldn't be read) |
| `zalando` | 1801 x 2600 | white (Zalando greys it itself) | ~80 %, centred | 762 x 1100 | exactly 1:1.44, JPEG only, < 20 MB; no visible mannequin | Zalando Partner University (official) |

A client's spec is the same keys in a JSON file, starting from a preset (any case) or another spec file with
`"base"` (a path relative to the spec): canvas, aspect, background, pureBackground, fill and fillRange or margins,
align and bottom, safeAspect, minimums and recommended sizes, formats, quality, maxBytes, maxMegapixels, profile
(only "srgb": product_shot's steps convert to sRGB), shadow, reflection, naming and nameRegex (`specs.py` documents
each; a malformed one, a loop of bases or a typo in a preset name stops with a message).
`product_shot.py --spec client.json` places by it, `cutout_check.py --deliverable … --spec ps/spec.json` checks by it.
A third-party number (Amazon's, Etsy's) is worth checking against the marketplace's current help before a big batch.

## Before the cut: props, lens fringing, dust, colour, ghost mannequins

- **Props** (a shoe tree's knob, a stand, a hanger): on an "Objects" layer (a duplicate of the photo, object-removal.md),
  clone stamp and Patch from donors in the same light, rebuilding edges first (a collar rim, the lining line), and the
  prop's own shadow on the sweep with it. Content-Aware Fill was unpredictable on a shoe tree's knob: a good collar
  rim, but a coloured ghost in the backdrop, a brass sliver left and a 5 px step in the outline. Then cut from that
  document and export `orig.png` with the Objects layer visible: a `cli convert` of the untouched photo still holds
  the prop, which product_shot reads as shadow or a missing part.
- **Lens fringing**, a purple 1–2 px line on a dark edge against the bright sweep and green on highlights: on a shoe
  it was mostly the purple kind lens-correction sliders don't fix (they shift colour channels radially, for lateral
  fringing: redCyan −15 halved the green, a* −9.8 to −4.7, but left the purple at 8.4 of 10.7; blueYellow greened a
  highlight). A narrow desaturation at the edge, after the cut, did better:

      select.loadSelection {"channel": "mask", "layer": <Product id>}
      select.modify.border {"radius": 6}
      layer.select {"layer": <Product id>}
      layer.newAdjustmentLayer.hueSaturation {"magentas": {"saturation": -100}, "blues": {"saturation": -100},
                                              "cyans": {"saturation": -100}}
      layer.setProps {"name": "Defringe (edge)", "clipped": true}
      select.deselect {}

  It took the purple from a* 10.7 / b* −13.4 to 7.6 / −9.7 and the green from −9.8 to −6.6, touching only a 6 px band
  of the outline (10,345 px); border 10 changed little more. Keep the colours a product really has out of it (a
  purple strap: give the hue ranges or the border a smaller radius, or paint the mask).
- **Cleanup before the cut,** on its own layer: dust first, then scratches, inspected at 200–400 %, then a final pass
  at 100 % (Clipping Expert Asia's jewellery workflow; `plan_spots.py` finds dust on plain areas, see
  object-removal.md). Metal and gems rarely share an exposure: shoot 2–3 and mask the better one in.
- **Colour against the product,** not the screen: a physical swatch under neutral light, with a tolerance agreed
  with the client (Racklify). Correct the backdrop to neutral first (color-grade.md); product_shot warns on a cast.
- **Ghost mannequin:** a second shot of the garment's inside back (the neck and label) goes under the front shot,
  masked along the collar, so the collar doesn't read as a flat sticker (FASHN). Zalando rejects visible mannequins
  (code 123). In PhotoCraft: both shots into one document (`layer.copyToDocument`), the inside shot below, aligned
  (`edit.transform`, or `edit.autoAlignLayers` for a tripod pair), a lasso mask along the collar's back edge, and a
  Curves layer darkening the inside a little for depth.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| A buckle, crown, paw or leg missing; `missingParts` boxes | select.subject drops low-contrast parts and parts touching the frame | `select.object` rect in add mode, or a traced `select.lasso` add; rerun |
| `shadowAboveGround` boxes, or a shadow maximum over 0.7; grey blobs above a dark product on the white deliverable | dark thin parts (lace tips, straps, a rounded corner) left out of the cut, read as shadow | the backdrop route (Step 2) on dark products on a light sweep; rerun product_shot |
| A prop shows on the deliverable, or turns up as shadow or a missing part | the prop was left in the photo, or `orig.png` came from the untouched file | remove it on an Objects layer first, export orig.png from that document |
| A purple or green 1–2 px line along the edge | lens fringing, not backdrop | the edge-masked Hue/Saturation layer ("Before the cut") |
| `metadata` warning on the deliverable | `cli convert` kept the master's camera EXIF (and GPS) | `deliver.py … --size WxH --quality 95` (Step 7) |
| The second marketplace's file is cropped wrong | its plan ran on the first preset's cropped result | each preset from the uncropped PSD (Step 7) |
| `largeParts` > 0 (a white product in pieces) | subject and backdrop alike | select the backdrop: magicWand + inverse, or object on the full frame |
| "N stray island(s)" | specks of backdrop kept in the mask | `islands.boxes` and the yellow boxes in edges.png say where; delete on the mask unless they're hair |
| Light rim on black around a dark product shot on white | white backdrop in edge pixels, or the gloss reflecting the sweep | fine on white; for dark backgrounds Step 4 (Edge tone). The gloss is opaque and stays: it's real |
| Grey outline round hair on a coloured background | backdrop colour in the strands | Step 4; not more decontaminate |
| Hair outline blobby, strands missing | Refine Edge can't separate strands from a backdrop close in colour | `channel_mask.py`; a wider `--band` for loose hair |
| channel_mask: haze along the floor under fur or feet | the contact shadow reads as half-transparent fur where it isn't smooth | `--area` round the hair or fur away from the floor; keep the rough cut there |
| channel_mask: warning "only N levels between the hair and the backdrop" | grey or blonde hair on a light backdrop, or a backdrop the hair's colour | keep the soft Refine Edge result, paint the outline by hand, or reshoot on a contrasting backdrop |
| channel_mask: holes in the hair near the edge | highlights read as transparent in one channel | they fill from half the band inside the rough edge; a wider `--band`, or paint the mask |
| Grey haze under the product on a coloured background | the contact shadow went into the mask | subtract it from the selection before refining |
| Soft, slightly blurred product edge (width ~3 px) | refine without contrast | `refineEdge` radius 1, contrast 25 |
| White blob between legs on a coloured background | `select.quick` flooded into a white backdrop | trace with `select.lasso` |
| `shiftEdge` -10 does nothing; -15 cuts in | it moves whole pixels at radius 1 | use it only when `backdropInside` > 0.03; recheck `cutInto` |
| Matting commands change nothing | `layer.matting.*` need transparency | apply the mask on a copy first, or use Step 4 instead |
| Transparent corners in the PNG deliverable | the canvas grew after the fill layer was made | run `prep.json` before the import |
| `offWhite.touchingBorder` > 0 | shadow runs off the canvas, or backdrop left | lower `--fill` or `--reach`; check the cut |
| `backdrop is not neutral` warning | cool or warm backdrop light | correct white balance first; the product carries the same cast |
| `enlarged` warning | product smaller than the canvas needs | a smaller `--size`, or a higher-resolution original |
| Reflection cut off at the bottom | `--align bottom` leaves no room | `--align center`, or `--bottom 0.25` |
| Deliverable `fill` fails but the plan said it fits | a third-party spec's stricter range (Amazon ≥ 0.85) after an override (`--fill 0.8`) | the spec wins: raise `--fill`, give the shadow room another way |
| Glass looks grey or dirty on white | the opaque cut was used | `--transparent`, the Product layer hidden |
| A glass label turns the backdrop's colour | labels are opaque | `--opaque` round them |
