# Check like a retoucher: check views and QC measurements

Read this before delivering any retouch, removal, composite or grade. It covers the check views retouchers toggle
while they work (`compare.py --check`, and the same views as live layers in the document), and the measurements
in `scripts/qc.py` for what the eye misses or adapts to: changes outside the work area, seams, clone repeats and
banding. Every threshold below was measured on test photos; the false hits they still give are in the last table.

## Contents
- What separates professional QC from a quick look
- The check views
- Check layers in the live document
- What changed, and where (qc.py diff)
- Seams round a composite or patch (qc.py seams)
- Clone repeats (qc.py repeats)
- Banding (qc.py banding)
- Size and time
- Before delivery: the checklist
- Tuning and false hits

## What separates professional QC from a quick look

- **Check layers, toggled.** Practitioners judge tone on temporary "check" or "visualisation" layers at the top of
  the stack: a solar curve, a grey Color-mode layer or a Black & White adjustment, a negative (Andrew Haysom's
  active visualisation layers; Daeko's check-layer course). They are switched on and off while working, never left
  on, never exported.
- **The solar curve.** KelbyOne's version is a zigzag through four points at quarter intervals: every small tonal
  step becomes a band, so blemishes, dust, creases and uneven dodge & burn transitions jump out. Unmesh Dinda sets
  it to Luminosity so it doesn't throw colours. Viktor Fejes: healing doesn't work "through" the curve, so heal on a
  layer below it, sampling Current & Below.
- **Grey, not Black & White.** Chris Knight checks tone with a 50 % grey layer in Color mode rather than a Black &
  White adjustment, because B&W reweights the colours and so changes the very tones being judged.
- **Negative and saturation checks.** An inverted view (Fstoppers; Adobe's "invert a photo with a curve to find
  spots") makes specks on light skin, skies and backdrops obvious. Retouching Academy's finishing phase includes an
  over-saturation check for colour blotches.
- **Seams, halos and repeated texture are what scrutiny finds first.** The four agencies that withdrew the March 2024
  Kensington Palace family photo pointed at a misaligned sleeve and a hand: the seams of a multi-frame composite.
  After any composite, Patch or clone, check the edges and look for the same texture twice.
- **Measure what the eye adapts to.** A heal that strayed onto an eye, a fill smoother than its surroundings, a
  stretched sky that banded: easy to miss at fit-to-screen after an hour of looking, and each one measurable.

## The check views

    python3 compare.py before.png after.png cmp.png --rect x y w h --scale 3 --check solar,lum

One labelled before | after row per view; `--check` alone is `local` (wherever it stands), `--check all` gives all
five. `--scale` enlarges the region (3) or shrinks it (0.5: block means, for a whole face or frame).

| View | Shows | Use it for | Live layer (check_layers.json) |
|---|---|---|---|
| `local` | luminance minus its local mean, x `--gain` (5) | blotches and uneven tone; D&B judged at blotch scale | none |
| `solar` | the solar zigzag on luminance, grey | uneven D&B transitions, dust, creases, healing seams, banding | "Check: luminance" + "Check: solar" |
| `lum` | luminance alone (PhotoCraft's 0.3/0.59/0.11) | tonal evenness without colour; Knight's grey check | "Check: luminance" |
| `negative` | the colour negative | specks and dust on light skies, backdrops and skin | "Check: negative" |
| `sat` | chroma doubled round luminance, luminance kept | colour blotches, redness, colour fringes at mask edges | "Check: saturation" |

The solar curve maps luminance 0, 64, 128, 192, 255 to 0, 255, 0, 255, 0 through PhotoCraft's Curves spline, which
overshoots and clips between the points, so its peaks are flat. On the flanks (luminance 90-115, 140-185: most lit
skin) one level becomes 3 to 6; at the troughs and the clipped peaks it goes flat, so look at `lum` there.

`--marks X,Y[,R] …` (with `--origin` for crops) measures marks against the skin round them, before and after: how
much darker (dY, levels), redder and yellower each one is than the ring 3.5R-5.5R around it (R, its radius, is 4 by
default), each side by its median colour, so a speck or a few pores don't swing it. Each line also gives the `noise`:
the spread of the same disc measure at eight places on that ring, what this skin's texture and shading alone do to a
disc that size. A difference under about twice the noise is texture; near it, look at the `local` view at 5x before
working on the spot again. Over 14 marks on one healed face the noise ran 1.4-27 levels, so no fixed level works: a
spot read -6.2 against a noise of 1.6 before healing and -2.8 after; a healed one that read +9.0 ("lighter") had a
noise of 4.5 at r4 and read +8.3 against 8.3 at r6, and nothing shows there at 5x.

## Check layers in the live document

    python3 import_layers.py ${CLAUDE_SKILL_DIR}/scripts/check_layers.json        # live document
    python3 import_layers.py …/check_layers.json --file photo.psd --out photo-checks.psd   # headless

builds a "Check layers" group on top with four hidden layers. Turn one on with
`$PC exec layer.setProps '{"layer": <id>, "visible": true}'`, look (screenshot or export), turn it off again.

    Check layers              group, Pass Through, on top
      Check: negative         Invert
      Check: solar            Curves [0,0][64,255][128,0][192,255][255,0], Luminosity
      Check: luminance        Solid Color #808080, Color
      Check: saturation       Channel Mixer, red [170,-59,-11] green [-30,141,-11] blue [-30,-59,189]

- **Luminance + solar together** give exactly compare.py's `solar` view (mean 0.17 levels, max 1, on a studio
  portrait). Solar alone keeps the photo's colours with zigzag luminance. Each other layer alone matched its
  compare.py view within 1 level. Measured headless; the hidden group left the render identical (mean 0.0).
- **The saturation check is a Channel Mixer, not Hue/Saturation.** Each row is L + 2 (c - L) with PhotoCraft's
  luminance weights, so luminance stays and chroma doubles (exact). PhotoCraft's Hue/Saturation fit no formula (mean
  error 5 levels), so it can't be predicted; and a Channel Mixer stops at 200 %, which caps the gain at 2.
- **Hidden layers never export** and don't change a flat render. Delete the group (`layer.delete` with its id)
  before handing over a PSD if the client doesn't want it.
- **Heal below the group**, on its own layer, with `"sampleLayer": "currentAndBelow"` (the planners' steps carry
  it). With `"all"` a visible check layer gets sampled into the heal.

## What changed, and where (qc.py diff)

    python3 qc.py diff before.png after.png out/ [--area area.json] [--allowed-mask mask.png] [--origin X Y]
                      [--threshold 1] [--margin 3]

Prints the share of pixels that changed (any channel more than `--threshold` levels), how much (median, p95, max),
where (`places`: up to 8 boxes), the signed mean dL*, da*, db* over the changed pixels (`--space p3` for a P3
document), and with `--area` and/or `--allowed-mask` (a grey PNG of the same frame, white where changes belong: a
layer mask or a selection saved as a PNG) every change outside them (`outsideArea.boxes`: x, y, w, h, pixels, largest
change). `--margin` px of overstep are allowed, for feathered masks and dab rims. Each place's box is its own pixels'
extent.

It writes two pictures:
- `diff.png`, to look at: the after image in grey, changes yellow (a level or two) to red (24+ levels), changes
  outside the area magenta, the area cyan. It is at most 1200 px across: `pictureScale` in the JSON (0.2 for a
  24 MP frame: picture x = (frame x - origin x) x 0.2); the boxes in the JSON are full size.
- `changed.png`, full size, same frame: what was replaced, for `qc.py seams after.png out/changed.png out2/` after
  clone, Patch or heal work, which leaves no mask of its own. The changed pixels with gaps of a few px closed, grown
  `--grow` (2) px, and graded across the rim the way a soft brush blended it: from 0 at that grown edge to white
  where the change reaches its core level (`changedRim`, px in). A hard edge there instead put the bands inside the
  blend, and a clone from a lighter row went unflagged.

- Compare two renders of the same pipeline (PNG exports, or the original against a render). A JPEG re-encode of the
  same pixels changed 44 % of them by more than a level (median 2) and edges by up to 26; with a JPEG on one side use
  `--threshold 6`, and expect boxes along hair and edges.
- Test: five Spot Healing dabs inside a cheek polygon and two strays. All seven found; outside the area: the dab on
  the eye (171 px, largest change 158 levels: it healed the catchlight away) and the one on the backdrop (6 levels).
  The polygon as a mask PNG (`--allowed-mask`) gave the same two; a mask over the eye added to it left the backdrop's.
  3 s for 1.4 MP; a 2 x 3 px stray is reported as exactly that.

## Seams round a composite or patch (qc.py seams)

    python3 qc.py seams image.png mask.png out/ [--origin X Y] [--composite]
    python3 qc.py seams after.png diffout/changed.png out/           # after clone, Patch or heal work

MASK is grey, white where the image was replaced, same frame as the image: a donor layer's mask, the patched area,
a sky's `alpha.png`; an RGBA cut-out works too (its alpha is used when it has transparency). Along its edge, tile by
tile, the script compares the nearest fully replaced pixels with the nearest fully original ones: 8 px bands that
start where the feather ends. The feather is measured (`feather`: the distance from alpha 0.02 to 0.98 across the
edge) and sizes everything else: tiles are at least 32 px and 1.5 x the feather plus both bands (`tile`), and a
patch small enough for one tile is judged as one.

- **Grain ratio:** the spread of the 3x3 residual inside over outside. Below 0.5: smoother (a fill, a blurred
  heal); above 1.8: noisier. With `--composite` the tiles skip it, because a placed element is another material
  and its texture isn't grain: a shoe pasted into a room read "noisier" (1.39) while it was far cleaner. There the
  **noise floors** decide, the quietest 8 x 8 blocks of the element and of the plate around it (`noiseFloor`,
  `noiseFloorRatio`): that shoe 0.60 against 1.46 (0.41, "looks cleaner"), and 1.08 once `composite.py` had
  matched its grain. Two regions of one untouched photo differ as well (0.27-2.66 over 24 ellipses on 8 photos: a
  smooth sky against land, bokeh against skin, where texture everywhere reads as grain), so only below 0.45 and
  above 2.2 give advice, and that advice is to compare the two at 100 %.
- **Tone step:** for every edge point, smoothed luminance just inside minus just outside, less what the photo does
  over the same span on either side (a gradient, a sky paling toward the horizon). A tile is lighter or darker when
  the median step passes 3 levels and 1.5 x the spread of those control spans (the texture). A strip too narrow for
  the inside span uses the outside one alone. When no edge point could be measured, `step` is `null` with a
  `stepNote`, never 0. `--composite` skips it: a product or a sky is meant to differ from what's around it.
- **Sharpness:** at real edges (gradient maxima across a step of 12+ levels), the blur that explains the peak
  gradient. Pooled along the whole seam: `edgeBlur` [inside, outside] in px and `sharpRatio`.

Advice needs a third of the tiles agreeing, at least one (a fault runs along the edge; one or two odd tiles are the
photo's own texture, but on a small patch its only tile decides), or for sharpness a ratio under 0.85 or over 1.25
and 0.4 px apart. `seams.png`: the edge yellow, tiles green (clean), orange (one flag), red (more), then 3x zooms of
the worst tiles beside their `local` check view.

**Thin masks** (strands 1-3 px wide, as a flyaway fill leaves: nothing survives a 2 px erosion) have no inside band.
Seams then judges each strand (`"kind": "strands"`) against the original pixels 3-8 px from it, tile by tile: a plane
fitted to those takes out the gradient, the strands' median offset from it is a lighter or darker ghost line, and
their grain against the ring's a smooth line through grainy backdrop. A mask that leaves no tile for the bands falls
back to the same. Measured on three flyaway fills from a portrait (mask 862 fully and 2720 partly replaced px): the
planner's fills, no advice on any; the fills without grain, "smoother" on the two with backdrop grain (12 of 14 and
18 of 19 tiles); 6 levels lighter, "lighter lines" on all three; the strands left in, "darker lines" on all three.

**After clone, Patch or heal work** give it `changed.png` from `qc.py diff` (above). Measured: a clone from the same
row of a clear sky, no advice (step 1.6); from 200 px lower, "lighter" on 12 of 12 tiles; on sand, a clone from a
lighter row, "lighter" on 5 of 6. A clone that carries a dark streak up to the mask's edge reads "darker" there too:
that is the texture it brought, so look at the zoom.

Measured on six textures (sand, knit, grass, sky, rough ground, skin), a patch 90 px across with a 2 px feather:
- Untouched: no advice on any of the six; single tiles flagged in 11 of 48 (natural texture). Heal-like patches
  (donor texture over the target's own tone): advice on one of six, on skin, whose donor's texture measured finer
  (grain ratio 0.61).
- Blurred (2 px) and flat (6 px) patches: advice on all, grain ratio 0.00-0.26 (untouched 0.71-1.23).
- Patch 6 levels lighter: advice on sky, sand and skin; not in coarse knit, grass or rough ground, whose own texture
  swings 10-17 levels across any line and hides it from the eye too. 3 levels lighter: on sky and skin.
- Donor from a different light, uncorrected: advice on sky, sand and skin. Added noise (sigma 4): on sand, grass,
  sky and skin.
- Strips 8-40 px wide, 10 levels lighter: step 8.5-9.1, advice on all; blurred: "smoother" on all. A disk 28 px
  across: one tile; blurred 2 px, "smoother". Feathers of 10, 20, 30 and 50 px: tiles 39-98 px, a 10-level step read
  11.7-12.5 with advice; the same feathered masks on an untouched photo: no flag.
- `--composite` on a portrait with an inserted region blurred 0.8, 1.5, 2.5 px: sharpRatio 0.88, 0.74, 0.58
  (untouched 0.99), edge blur 1.44, 1.78, 2.41 px against the plate's 1.20; "softer" from 1.5 px. The plate blurred
  instead: 1.31, "sharper".
- 2-4 s for a seam round a region in a 1 MP frame. A frame over 12 MP (`--max-mp`) is read only round its edge,
  through the CLI: a patch in a 24 MP photo took 5 s and 550 MB.

## Clone repeats (qc.py repeats)

    python3 qc.py repeats after.png out/ --before before.png      # only what the edit changed
    python3 qc.py repeats after.png out/ --area area.json          # only this area

Corners (Harris) carry a 9 x 9 texture patch with its tone removed (a heal blends tone, not texture); each corner in
the checked part is matched against every corner of the image, and matches sharing one offset make a repeat. Each
repeat is labelled:
- **copy**: the same texture twice, exact (mean correlation 0.96+); `target` is its own extent, where its patches
  match exactly;
- **periodic**: 5 %+ of the corners in a ring round it (outside its own extent, grown 8 px) repeat at that offset
  too (brick, tiles, weave, a fence, identical windows);
- **similar**: not exact enough to call. Only copies count in the verdict.

A photo over `--max-mp` (3) is analysed on a copy k times smaller, made by the CLI, and everything it finds is
measured again at full size: the offset (searched k + 1 px round), the correlation and the ring. A copy by an offset
that isn't a multiple of k falls between the small copy's pixels (it correlated 0.84 instead of 0.995), so with
`--before` or `--area` the checked part is read again at every phase, k x k small crops 1 px apart, one of which
lines up with the source. A whole big photo is checked at one phase only, and says so (`note`).

`repeats.png`: copies red (target) and blue (source), the rest grey, then target | source at 3x.

- Made in PhotoCraft on sand and rough ground: a clone-stamp stroke and a Patch were found at their exact offsets
  (correlation 0.97-0.998); 60 Healing Brush dabs of 10 px, sources 14-24 px away, gave nothing; a content-aware
  fill on rough ground gave 7 copies (it copies chunks of texture verbatim, 0.996-1.0).
- Untouched, whole image: a meadow, a sky, sand, rough ground and a studio portrait gave no copy. Three buildings
  and a room gave 0-8: identical windows, a lattice, matching chairs and a few short curved edges really are near
  copies of each other. Check only the edit (`--before` or `--area`); then a clone on a brick wall was found alone
  (offset 150, 40; 0.996).
- A block copied by +600, +100 and by +599, +99 in a 4.2 MP photo (analysed at half size): both found with
  `--before` and with `--area`, at their exact offsets (0.998, 0.999). A clone stroke in a 24 MP photo (one third):
  found whole, 33 corners, its extent 449 x 205 px.
- With source and target both inside the area, each copy is reported once.
- 5 s per MP analysed: 4.6 s and 190 MB for a 4.2 MP photo with `--before`, 27 s and 745 MB for 24 MP (most of it the
  CLI making the small copy).

## Banding (qc.py banding)

    python3 qc.py banding final8.png out/ [--area area.json]

**Which file:** the 8-bit render of the finished document, at the size it will be seen (`$PC cli convert final.psd
final8.png`, or the delivered PNG or TIFF): banding is what survives into 8 bits. Not the layered 16-bit document, and
don't hold its counts against the original JPEG's: noise breaks the flat runs that steps are counted between, so a
noisier file always counts fewer (a finished portrait render read 3.39, 1.74 and 3.2 steps per 1000 smooth px in R, G
and B, its camera JPEG 0.60, 0.48 and 0.63, and neither has a banded region or any levels missing).

**Each region is judged on its own.** Smooth areas (little texture round a 3 px blur, a slope under 3 levels per px:
skies, backdrops, vignettes) are cut into regions, each connected area within a 768 px block, 2000+ px. A channel
bands in a region when all four hold:
- a comb: 30 %+ of the levels in the region's own range (2nd-98th percentile) are missing (`--missing 0.3`);
- stairs: 1+ step per 1000 of the region's pixels, a jump of 2-16 levels between two flat runs of 4+ px
  (`--stairs 1`);
- the step the missing levels leave (1 / share present: 2 levels when half are missing) is at least twice the
  region's noise in that channel (`--clear 2`): grain or JPEG noise that size dithers it away;
- and the step can be seen: one band, every such channel stepping at once, is at least ΔE 1.2 apart at the region's
  median colour (`--delta-e 1.2`; `--space p3` for a P3 file).

The verdict is "banding in N region(s)", "no visible banding" (regions lost levels, but the noise dithers the steps
or they are too small to see: keep noise reduction and smoothing off them), or "no banding". `worst` lists 8 regions
(box, pixels, median colour, `stepDeltaE`, and per channel `missing%`, `stairsPer1000`, `step`, `noise`, `clear`),
`banding.json` all of them; the image-wide `channels` figures are context only. `banding.png`: smooth areas blue,
steps the noise hides orange, steps in banded regions red.

- Untouched: four skies, a studio backdrop, a camera JPEG portrait and two synthetic gradients: no banding.
- A strong curve (100 to 30, 150 to 225: x3.9 in between) on two skies and the backdrop: banding in 3, 12 and 2
  regions, 50-75 % of levels missing, band steps of ΔE 1.23-2.91 (a posterised gradient: 3.58); on the sky looked at
  they show at 100 %. On a third sky it blew the sky out, leaving no smooth area. The same curve in a 16-bit document
  of the same JPEG: the same regions. Converting an 8-bit file to 16 bits doesn't bring back levels it never had.
- The strong curve on a gradient with fine grain: 73 % of levels missing, steps of 3.7 levels against a noise of 3.7:
  no visible banding, and none shows. That is the fix for a banded sky or backdrop: a gentler curve, the stretch from
  a 16-bit or raw source, or Add Noise 1-2 (gaussian, monochromatic) masked to the gradient.
- Two Curves layers in an 8-bit document, x0.5 then x2 (no change on paper): 49-50 % of levels missing in the skies,
  steps of 2 levels (ΔE 0.70-1.0 where they cleared the noise), not visible at 2x: "no visible banding". PhotoCraft
  rounds to 8 bits between adjustment layers; in 16 bits the pair changed nothing (0.0 levels in the render). Stacks
  of strong layers belong in 16 bits (`image.mode.bits16` first).
- White-balance renders of that portrait: 18-31 regions lost 30-77 % of their levels, none visible (steps under
  twice the noise, or ΔE 0.84-0.87 on the blue patch of a colour chart). The finished render: no banding.
- 2-4 s for 0.4-1 MP, 12 s for 3.4 MP, 57 s and 780 MB for 24 MP (worked in blocks, so memory stays bounded).

## Size and time

Pixels are held as bytes and masks as bit rows; seams and banding work in blocks and repeats on a copy of at most
3 MP, so memory stays well under a gigabyte for a 24 MP photo (measured: diff 570 MB, seams 550 MB, banding 780 MB,
repeats 745 MB, the CLI included). Time is pure Python: about 1 s per MP for diff, 2.5-4 s per MP for banding, 5 s for repeats
on a 4 MP photo and 27 s on 24 MP; seams depends on the length of the edge. Any PNG works (palette, interlaced, 1-, 2-, 4- and
16-bit), and so does anything photocraft-cli reads. For a quick check of one area of a big photo, crop it first with
the CLI and pass `--origin`, so every box still reads in the photo's coordinates:

    $PC cli run photo.jpg --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' --out crop.png

## Before delivery: the checklist

1. Before | after at fit-to-screen and at 100 % of every worked area (`compare.py`), each group switched off once.
2. The views: `solar` on retouched skin and skies (D&B transitions, dust, heal seams), `lum` for tonal evenness,
   `sat` for colour blotches and fringes, `negative` for specks on light areas.
3. `qc.py diff --area`: nothing changed outside the work area (eyes, lips, hair, the background, other people).
4. `qc.py seams` after every composite, Patch, fill, donor layer or new sky (`--composite` for a placed element);
   after clone, heal or Patch work on `changed.png` from `qc.py diff`; on a flyaway mask it checks the strands.
5. `qc.py repeats --before` after clone, Patch or content-aware fill.
6. `qc.py banding` on the 8-bit render after strong curves, a big white-balance move, or a new sky or backdrop.
7. Colour against the original: `color_check.py compare` (neutrals, skin angle, clipping).
8. At the output size: render the deliverable at its pixel size and look at 100 % (output sharpening halos, text).
9. Check layers hidden or deleted, layers named, the original untouched, files saved under new names.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| `diff` boxes along every edge | one side is a JPEG: re-encoding moves edges up to 26 levels | compare PNG renders, or `--threshold 6` |
| `diff` boxes just outside the area's edge | a feathered mask or a dab rim reaches past the polygon | `--margin 6`, or look: a few px is fine |
| `diff.png` smaller than the photo | the picture is at most 1200 px across | `pictureScale` maps it; `changed.png` is full size |
| `seams` flags single tiles on an untouched edge | coarse texture (knit, grass, gravel) varies that much on its own | judge the advice, which needs a third of the tiles |
| `seams` `step` null, `stepNote` | no edge point had fully replaced and fully original pixels within reach | crop wider round the patch; judge grain and the zooms |
| `seams` "lighter"/"darker" along a real edge | the mask follows an edge in the photo (a shadow, a fold) | that edge is real; look at the zoom |
| `seams` silent on a step in grass or knit | texture hides a 6-level step, from the eye too | accept, or check at 100 % |
| `seams` sharpness `null` | under 30 edge points per side (a smooth sky, skin) | grain ratio is the measure there |
| `seams` `"kind": "strands"` | the mask is strands too thin for bands each side (flyaways) | expected: each strand is judged against the backdrop round it |
| `seams` on `changed.png` flags a clone that looks clean | the clone brought a streak or a cloud wisp up to its edge | look at the zoom: it is there |
| `repeats` finds windows, tiles, railings | identical elements in the photo itself | `--before` or `--area`; read `kind` |
| `repeats` `note`: checked at 1/k size | a whole photo over 3 MP, one phase only | `--before` or `--area` (every phase), or `--max-mp` higher |
| `repeats` misses a clone on brick or tiles | cloning along the period matches the pattern around it: "periodic" | it's invisible for the same reason |
| `repeats` finds nothing after Healing Brush dabs | small dabs from different sources aren't repeats | expected; repeats come from clone, Patch, fill |
| `banding` "no smooth gradient big enough" | the area is textured or clipped (a curve blew the sky to 255) | check the clipping instead (`color_check.py`) |
| `banding` "no visible banding" | levels are missing, but the noise dithers the steps or a step is under ΔE 1.2 | nothing to fix; keep noise reduction off those regions |
| `banding` high `stairsPer1000`, "no banding" | flat runs in a clean render, no levels missing | the verdict is per region; counts are context |
| `--marks` reads a healed spot lighter or darker | the skin's own texture or shading at that size | compare with `noise`: under twice it is texture |
| Solar view all black or white on skin | skin sits in a trough or on a peak of the zigzag | look at `lum`, or brighten/darken first (Levels on a copy) |
