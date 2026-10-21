# Skin retouch: clean but natural

Read this before retouching skin. It is the full version of the recipe in SKILL.md: how professional
retouchers work, and how to do the same in PhotoCraft with the planning scripts.

## Contents
- What separates a professional retouch from a cheap one
- Choose the tier
- The layer stack you're building
- Step 1: set up and map the skin
- Step 2: heal the blemishes (texture)
- Step 2b (beauty and hero shots): frequency separation
- Step 3: dodge & burn and colour evening (tone and colour)
- Step 3b: soften lines, folds and under-eye shadows (age kept)
- Step 4: flyaway hair
- Step 5: check like a retoucher
- Step 6: save
- Tuning and false hits

## What separates a professional retouch from a cheap one

These are the points the retouching literature agrees on (PhLearn, SLR Lounge, Fstoppers, PetaPixel,
Pratik Naik's high-end workflow, Zoner):

- **Order: big to small, texture before tone.** Clean up blemishes first, then even tone (dodge &
  burn), then colour, then judge the whole. D&B over unhealed acne just paints around it.
- **Remove what's temporary, keep what's the person.** The "2-week rule" (Fstoppers): anything that would
  be gone in two weeks goes (active acne, whiteheads, scabs, scratches, flakes, stray hairs on the skin, lint);
  what's permanent stays (moles, freckles, scars, stubble, the hairline, pores, smile lines, the face's
  shape), unless the user asks otherwise. For men keep more texture and stubble.
- **Never blur skin.** Blur, surface blur, "smoothing" and high-pass softening layers read as plastic.
  Pores must run continuously across cheek, jaw and nose, with no smooth patches. Healing copies real
  texture from nearby; D&B and colour only change tone and hue at blotch scale, so texture is untouched.
- **Healing: small dabs, nearby sources.** A brush a little bigger than the blemish, sourced from clean
  skin close by with the same light and texture, never repeating one source (clone patterns).
- **Dodge & burn is what makes skin look clean.** After healing, what still reads as "bad skin" is
  uneven tone: post-acne marks, shadows of bumps, blotches. The standard tool is two Curves adjustment
  layers, one lightening (Dodge) and one darkening (Burn), in **Luminosity** blend mode so they don't
  shift colour, with masks painted only where a spot is darker or lighter than its surroundings.
  Retouchers judge it on *check layers* toggled on and off, never left on: a solar curve (a zigzag
  Curves layer, KelbyOne; in Luminosity so it doesn't flash colour, Unmesh Dinda) that turns small steps
  of tone into bands, and a grey view. Chris Knight uses a 50 % grey layer in Color mode rather than a
  Black & White layer, because B&W reweights colours and so changes the tones being judged.
  `compare.py --check solar,lum` renders those views of before and after (Step 5).
- **Frequency separation is a tool for the few, used sparingly.** "Very sparingly" in high-end work
  (Lindsay Adler); SLR Lounge calls it "oversold" and keeps it to beauty, editorial and hero shots. Done
  right it heals texture on the texture layer with hard-edged dabs and evens tone softly in between; done
  wrong (a soft brush on texture, a blurred or painted Low layer) it is the plastic look (the Fstoppers
  roundup of high-end retouchers: Siyana Kasabova, Victoria Behun, Conny Wallström, Julia Kuzmenko McKim).
- **Redness gets fixed with the tone, not instead of it.** A post-acne mark is darker *and* redder or
  purplish. Fix both locally, masked to the marks, by the same fraction. Taking the red out while the
  mark stays darker leaves a dark neutral patch, which on warm skin reads as a grey-blue bruise.
  Desaturating reds globally kills lips, ears and warm light.
- **Whiteheads are blemishes too.** Closed comedones (small light bumps) sit between the red pimples.
  Heal the pimples but leave them, and they become isolated white dots that read as scars.
- **Partial, not total.** Take away most of a mark, not all of it; skin has natural variation.
  Remove ~70–80 % of a mark and keep a dead zone, so small variations stay.
- **Protect the light.** Rim light, cheekbone highlights and form shadows are part of the photo, not
  blemishes. Corrections stop at the edges of light and shadow.
- **Non-destructive and named.** Original untouched at the bottom, a healing layer, then a group of
  adjustment layers with masks the user can tweak or switch off.
- **Check at 100 %, 200 % and fit-to-screen, against the original.** Toggling the retouch off should
  show "the same person on a good day".

## Choose the tier

Retouching is sold in tiers, and each tier is a contract of what gets touched (outsourcers price basic, mid
and premium retouching separately; SLR Lounge keeps frequency separation to beauty, editorial and hero shots).
Ask which one the user wants, or infer it from the use, and say what the tier leaves alone.

| Tier | For | Steps | Settings |
|---|---|---|---|
| Light | headshots, weddings, events, volume | Step 2 (1-2 passes), eyes and teeth subtle, Step 5 at 1x and 2x | temporary blemishes only; `--whiten 0.25` on teeth; lines left (Step 3b only if asked, lines 0.3) |
| Commercial | brand and corporate portraits, ads, lookbooks | Light + the whitehead pass, Step 3, Step 3b, Step 4, eyes and teeth in full, the check views | D&B strength 0.7-0.85; lines 0.4-0.5, under-eye 0.3-0.4, folds 0.2-0.3; flyaways `--keep 12` |
| Beauty / hero | beauty, editorial covers, hero ad images | Commercial + Step 2b, a second, finer D&B pass, check layers in the document, eyes sharpened | FS at the measured radius; D&B `--sigma` 0.7x on the second pass; lines up to 0.6-0.7, under-eye 0.5, never 1.0; flyaways `--keep 6-8` |

Every tier keeps the person: identity, moles, freckles, smile lines and the face's shape. Lines are softened,
never erased: a face with no lines at all reads as somebody else.

## The layer stack you're building

    Flyaways (keep 12 px)         pixel layer = clean backdrop + grain, mask = stray strands (Step 4)
    Soften lines                  group, Pass Through (Step 3b)
      Lines (50 %)                pixel layer = the skin with its lines filled, mask = the lines
      Under-eye (40 %)            pixel layer = the tear trough lifted to the skin round it, mask = the zone
      Folds (30 %)                pixel layer = the folds filled, mask = the folds
    Skin retouch (D&B + colour)   group, Pass Through
      Burn                        Curves [0,0][128,96][255,255], Luminosity, mask = burn.png
      Dodge                       Curves [0,0][128,160][255,255], Luminosity, mask = dodge.png
      Skin colour (marks)         pixel layer = the skin recoloured to the clean skin around it, Normal, mask = color.png
    Frequency separation (Gaussian 3 px)   group, beauty and hero tiers only (Step 2b)
      High (texture)              the Healing layer minus Low, Linear Light: hard-edged heals here
      Colour (Color mode)         empty: colour evening, soft, low opacity
      Tone (soft heals, ...)      empty: tone evening, sampling Current & Below
      Low (Gaussian 3 px)         the Healing layer blurred; never painted
    Healing                       duplicate of the photo with the healing dabs
    Background                    original, untouched

## Step 1: set up and map the skin

Scripts are in this skill's `scripts/`. Work in a folder under the home directory, e.g.
`~/.photocraft-skill/work/<photo>/`, because the app only opens files under its read root (not `/tmp`).

1. Open the photo, `layer.duplicate` the Background, rename the copy "Healing" (`layer.setProps`).
2. Crop the work region (face, neck, whatever skin is in scope) at full resolution, plus two
   references. Keep the crop width and height even (the masks are centred on the crop):

       $PC cli run photo.jpg --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' --out crop.png
       … same + --cmd filter.noise.median --params '{"radius":10}' --out ref10.png
       … same + --cmd filter.noise.median --params '{"radius":3}'  --out ref3.png

3. Map the skin. `python3 grid.py crop.png X Y grid.png --step 25 --scale 2` draws labelled
   full-image coordinates; read them off and write `area.json`:

       {"skin": [[x, y], …], "exclude": [[x0, y0, x1, y1], [[x, y], …], …]}

   The polygon follows the skin, a few px inside every edge. Leave out (or exclude): eyes, lashes and
   the lash shadow, brows, lips (heal a lip spot by hand instead), nostrils and the nose rim, ears
   (backlit ears glow red, which is correct), the hairline and the nape where short hairs grow,
   stubble edges, clothing (knit reads as hundreds of spots), jewellery, and **other people's skin**.
   Check it with `grid.py … --area area.json`. Take several looks at 2×; it's the step everything
   else depends on.

## Step 2: heal the blemishes (texture)

    python3 plan_heals.py crop.png ref10.png X Y area.json --max-size 10 --ref-small ref3.png \
        --layer <Healing id> --steps heal.json --overlay overlay.png
    $PC script heal.json

It finds blemish pixels (redness counts 3× darkness, so pores and stubble survive), covers each with
as many ≤10 px Healing Brush dabs as needed (hardness 80), each sourced from clean, tone-matched skin
within ~20 px. The steps start with a `layer.select` of `--layer`. Hundreds of dabs run in under a second.

- **The threshold sets itself.** A spot counts when its score passes 4.3 x the score's robust spread on the
  skin around it (per 64 px tile, at least 6): pores and grain set their own floor, and it differs across a
  face (a sharp 18 MP portrait's forehead measured 3.3, its cheeks 2.4). The first output line says what it
  chose. The old fixed 7 flagged nearly every pore on that portrait (892 spots, 3060 dabs, 38 % of them Spot
  Healing); the automatic one planned 51 spots and 106 dabs, all with a clean source. On an acne crop it rang
  the acne clusters and left plain skin alone (35 spots, 107 dabs, where 7 gave 147 and 539). `--threshold N`
  sets it by hand (lower is more thorough), `--noise-mult` scales the automatic one.
- **Moles and freckles are kept.** Each spot is classified: melanin (moles, freckles) darkens skin toward
  yellow-brown with a sharp edge, an inflamed or healing blemish shifts it toward red. Probable moles,
  freckles and dark pores are left out, listed with their positions (all in `heal_marks.json`) and drawn blue
  on the overlay. On the sharp portrait it kept 8 of the 9 marks a retoucher had protected by hand (the ninth,
  a faint reddish freckle, was planned); on the acne crop it also kept 8 brown spots of 43 (freckles, or old
  acne marks that Step 3 fades). Look at each: `--add X,Y,D` heals one that is a blemish, `--heal-marks` all.
- Read `overlay.png` before running: red = dabs, blue = kept marks, yellow = no clean source. Rings must sit
  only on blemishes; see "Tuning and false hits". It is 2x the crop, 1x above 800 px (`--overlay-scale`).
- Always pass `--ref-small ref3.png`. Then no source may contain a whitehead or dark pore, so a heal never
  copies a white dot onto a cleaned spot. That limit sets itself too: 5 x the skin's own spread there (at
  least 6), about its 99.8th percentile on four faces. A fixed 6 rejected nearly every source on sharp skin,
  where 2-26 % of clean pixels pass it. The output warns when over 20 % of the dabs have no clean source:
  widen the area so clean skin surrounds the marks, or raise `--source-max-speck`.
- `area.json` can hold several skin polygons, e.g. face and neck: `{"skin": [[[x, y], …], [[x, y], …]], …}`.
- **Rim-lit or side-lit skin:** small bumps (closed comedones, flakes) show as light specks. Add
  `--bright-weight 0.7`.
- **Whitehead pass**, after the pimples are gone: light bumps only, in the acne zone (its own small
  `area_acne.json`):

      plan_heals.py crop.png ref10.png X Y area_acne.json --dark-weight 0 --bright-weight 1 \
          --ref-small ref3.png --min-area 5 --max-size 7 …

  Its threshold calibrates itself on the bright side: on two clean 100 px patches of the sharp portrait it
  found 0 and 1 light bumps where the old fixed 6 found 123 and 125, and 13 on the acne crop where 6 found 434.
  Still check it: run the same settings with `--dry-run` (it reports and draws the overlay but writes no steps
  file; without it a run writes `--steps`, by default `steps.json` in the current folder) on a clean patch of
  the same skin. It should find 0–2 there; if it finds more, raise `--threshold`, or it will strip natural
  texture. Then re-plan once more.
- **A blemish the detector misses** (a scab that is half light, half dark; a spot on the lip edge):
  `--add X,Y,D`. Keep only the steps near it if the rest of that area isn't meant to be healed.
- **Healing on an empty layer** instead of the duplicate: `--sample currentAndBelow`. There is no Spot Healing
  fallback then, because Spot Healing can only sample the current layer or every visible layer, the ones above
  too (a spot healed under a visible Invert layer came out 41 levels off, measured). Spots with no clean source
  nearby are listed with their positions and drawn yellow on the overlay instead.
- Repeat: `$PC export` (to a path under home), re-crop, rebuild the references, re-plan. Usually 2–3
  passes until it finds only a handful. Look at a before/after at 3× after each pass
  (`compare.py crop.png crop_after.png cmp.png --rect … --scale 3`).
- What's left after healing is tone and colour (soft marks, redness). Don't chase it with more or
  bigger heals at partial opacity; that's Step 3's job.

## Step 2b (beauty and hero shots): frequency separation

What it adds to Steps 2 and 3: texture fixes that leave tone alone. A bump, a whitehead, flaky or crêpey
texture on otherwise even skin is healed on the texture layer only, so no flat or off-colour patch appears
where the dab went; blotches are evened on the layers in between, softly. Step 3's masks already do the
low-frequency evening FS is known for, so build it only when the tier or the user asks for it.

1. **Measure the radius** on plain cheek and forehead (an area.json like Step 1's, only those):

       python3 freqsep.py radius crop.png X Y area_fs.json --sheet fs_sheet.png

   It reports the skin's detail energy per octave of scale and picks the quietest scale, between texture
   and tone (Ben Willmore: "the lowest radius that still removes all fine detail"). Measured: 3 px on two
   faces about 950 px wide, 5 px on a third with coarser skin, 5.5 px on a child's face 1900 px wide, 1 px on
   a 450 px face (with a warning: pores are below a pixel there; healing alone is the better tool). That is
   about face width / 300 for adult skin; practitioners' 4-8 px "for a typical portrait" is the same rule
   for faces of 1200-2400 px. Look at the sheet: at the radius, Low shows no pores and edges (nostril,
   smile line) are still crisp; at 1.5x they soften.
2. **Build it on the healed layer**, so High and Low hold the healed skin:

       python3 freqsep.py build --radius R --layer <Healing id>                                   # live
       python3 freqsep.py build --radius R --layer <Healing id> --file healed.psd --out healed-fs.psd   # headless

   Always pass `--layer`: with more than one pixel layer it is required, and the Background under an opaque
   Healing layer is refused (a group built there would be hidden under Healing). 16-bit by default: the document
   is converted first (`image.mode.bits16`), because there Apply Image (Low, inverted, Add, Scale 2, Offset 0)
   gives the photo back exactly: mean 0, max 0 on an 18 MP portrait (15 s with the checks) and on a face crop.
   `--bits 8` keeps an 8-bit document, which can't be exact: Linear Light would need High at 127.5 wherever the
   skin has no detail at the radius. The textbook Subtract, Scale 2, Offset 128 renders every pixel 1-2 levels
   lighter in PhotoCraft (+1.49 on average on a face), so it uses Offset 127, which renders those pixels 1 level
   darker: about half of a face's pixels (mean -0.50), every pixel of a smooth gradient (-1.0); up to 1 level
   passes in 8-bit. The output's `identity` must say ok. It is checked with and without the group, and once with
   High in Normal mode, which must change the window (`groupShows`, 48-65 levels on the portraits): if nothing
   changes, a layer above covers the group, and it says MISMATCH. Toggling the group then shows only your edits.
   `--median` builds Low with Median (crisper edges). Step 3's import then goes `--above` the group's id.
   - **Layer ids are this session's.** Saving and reopening a PSD renumbers the layers bottom-up, so after a
     reopen read them again: `document.inspect`, or `select.findLayers {"name": "High (texture)"}` (it answers
     `{"selected": [id]}`). The output prints each id with its layer's name.
   - The planners' imports verify in a 16-bit document as in an 8-bit one (measured after a fix to how 16-bit
     renders are read): a pixel layer mean 0.003, a full-window White balance Curves layer mean 0 (max 1), the eyes
     and teeth stack mean 0.004 (max 3, as in 8-bit). Size: the 18 MP portrait with these layers was a 397 MB PSD
     (298 MB `.pcraft`, 159 MB in 8-bit); from a chat, deliver the flattened JPEG.
3. **Texture on High:** plan dabs as in Step 2 onto High, hard, sampling High alone, no spot-heal fallback:

       python3 plan_heals.py crop.png ref10.png X Y area.json --layer <High id> --hardness 95 --fallback skip \
           --ref-small ref3.png --steps heal_high.json --overlay overlay_high.png
       $PC script heal_high.json

   Measured on a synthetic pimple (a red halo plus a raised bump) on real cheek skin: on High the bump went
   to 13 % and its tone stayed (81 %); the same dabs on a duplicate of the photo took out both (bump 12 %, tone
   18 %). That split is the point: the tone is the next layers' job.
   - Sampling Current & Below on High reads the visible photo into a Linear Light layer: the spot came out
     57-66 levels lighter, a blown blob. Keep `--sample current` (the default).
   - Hard edges (Siyana Kasabova: a soft brush on High smudges texture): at hardness 50 the bump kept 29 % and
     the dab's texture was 0.68 of the skin's around it; at 95, 13 % and 0.76. Spot Healing on High smoothed it
     to 0.37, so `--fallback skip` leaves out dabs that have no clean source nearby. It prints their full-image
     positions and sizes, writes them all to `heal_high_skipped.json` and draws them yellow on the overlay (the
     planned dabs are red): heal those by hand with a source you choose. A spot you asked for with `--add` is
     always kept, as Spot Healing if nothing clean is near it; on High give it a source by hand instead.
   - The steps start with `layer.select` of the layer: after reopening a PSD the group is active, and paint
     commands fail then even with an explicit `layer`.
4. **Tone and colour in between:** soft heals on Tone (`sampleLayer` `currentAndBelow`, hardness 0-20) and
   paint sampled from clean skin nearby at 5-20 % opacity on Colour, whose Color mode evens colour without
   touching luminosity (Michael Woloszynowicz), along the light's gradations, never across them; or let
   Step 3's masks do it. Several conservative rounds rather than one strong one (Julia Kuzmenko McKim).
   Never blur or paint Low: it holds the face's shape (Victoria Behun), and the middle frequencies in it
   still show when the photo is seen small (Conny Wallström).

## Step 3: dodge & burn and colour evening (tone and colour)

1. Export the healed state with the retouch group hidden (or before it exists), crop it the same way.
2. Use a tighter area for this step (`area_db.json`), **only where the marks are** (for acne: cheek,
   jaw, chin). Leave out form shadows (under the jaw, under the earlobe, beside the nose) and the neck
   beside hair. A smooth shadow inside the area gets read as a blotch and lifted, and the jaw loses its
   shape.
3. Compute the masks:

       python3 skin_masks.py healed_crop.png X Y area_db.json ~/.photocraft-skill/work/<photo>/masks \
           --sigma 16 --strength 0.85 --threshold 1.5 --feather 8

   For each skin pixel it fits the clean skin around it (a robust local plane fit of R, G and B at
   `--sigma`, with blotches down-weighted). It then takes **one fraction** of the difference away, the
   same for tone (Dodge/Burn masks) and colour (Skin colour mask). So a mark becomes fainter, never
   "less red but still dark", which is the bruise look. Other safeguards:
   - Decisions use a copy smoothed at `--pre` 2 px, so pores and grain pass through untouched.
   - Nothing is lifted past the clean-skin level (`--margin`), so a healed centre doesn't become a
     light dot.
   - Deviations bigger than `--max-dev` (16 levels) are light or shadow, not marks, and are left alone.
   - The edges of light and shadow are protected (`--edge`).

   The masks are exact for PhotoCraft's Curves (a natural cubic spline through the points) and its
   Luminosity blend.
4. Read `viz.png` (green = dodge, magenta = burn, yellow = colour, exaggerated): it should be **spots
   and patches on marks**. Bands along an edge, a lit area lighting up, or a dark blob with a hard edge
   at the area border all mean the area includes a shadow or highlight; tighten it. Then compare
   `preview.png` with the healed crop:
   `compare.py healed_crop.png masks/preview.png cmp.png --rect … --scale 2 --check`, and
   `compare.py … --marks X,Y …` on a few marks. Each should end up slightly darker *and* slightly
   redder than its surroundings, like the original but fainter. If it's darker but neutral, or cooler,
   it will read as a bruise.
5. Build the layers in the live document:

       python3 import_masks.py ~/.photocraft-skill/work/<photo>/masks --above <Healing id>

   It opens each PNG and **assigns it the photo's colour profile** (an untagged PNG opens as sRGB, and
   copying it into a Display P3 photo would convert its colours: skin turns bluer). It then copies the
   PNG in at the crop's centre (`layer.copyToDocument`) and loads its red channel as the selection
   (`select.loadSelection`). Finally it deletes the temporary layer, creates the layer from the
   selection, closes the PNG document, and groups the three layers.
6. Verify: export, crop, compare with `preview.png`. The mean difference should be < 0.2 levels, *and*
   there should be no colour bias where the colour mask is strong (check R, G and B separately). A
   bias of a few levels is a colour conversion on import.
   To redo with other settings, `layer.delete` the group (it takes its layers with it) and import again.

`--sigma` sets the largest mark that gets evened (~2.5 × sigma across): about 2–3 % of the face width,
12–16 px for a face 550 px wide. Lower it if form shading starts to flatten, raise it for broad marks.

## Step 3b: soften lines, folds and under-eye shadows (age kept)

The classic method (Adobe's Healing Brush on an empty layer sampling Current & Below; Scott Kelby, PhLearn):
take a line out completely on its own layer, then lower that layer's opacity so part of it comes back. The person
keeps their age and expression, the light keeps the face's shape, and the opacity stays a slider the client can
move. Under-eye bags get the same treatment: retouchers patch the tear-trough shadow from the cheek below, then
fade it to 30-50 %. Lifting the shadow is what makes a bag recede; reshaping the bag itself (Liquify) is a
different job, not this one.

`scripts/soften_lines.py` does that without hand dabs. A line is a narrow valley of tone: a grey closing (max,
then min) of a lightly smoothed copy, per channel, gives the skin level on both sides of it, so the valley's
redness goes with its darkness (the same fraction, as in Step 3). The layer is the photo plus that smooth lift:
pores, stubble and grain run on through it unchanged, nothing is blurred or copied, and the preview is exact.
Only long, thin valleys count as lines (a crow's-feet network joined at its roots too); pores, blemishes and
stubble are round or blotchy and stay. A valley deeper than `--max-depth` is a lash line, a brow, a glasses frame
or hair and is left (magenta in `viz.png`).

Do it last among the skin layers: the layer holds the finished skin plus the lift, so plan it on an export of
everything below it (healed, D&B'd), and plan it again if those layers change.

1. Export the current state and crop the face at full resolution, even width and height, with all the zones in
   it (one crop, one group). Measure the face width at eye level, cheek to cheek, on `grid.py`: every radius
   follows from it (lines 1/300 of it, folds 1/90, under-eye 1/45).
2. Draw the zones on `grid.py` (step 25, scale 2) in `area_lines.json`, ~10 px of skin round each line, one key
   per kind, each a list of polygons:

       {"lines":    [crow's feet, lines under the eye, forehead, neck],
        "folds":    [nasolabial folds, marionette lines, a deep neck crease],
        "undereye": [the tear trough: below the lower lashes and the lid's edge, above the cheek],
        "exclude":  [...]}

   Keep every zone off the eye, lashes, brows, lips, nostrils, the hairline and glasses frames (a line seen
   through a lens is fine, the frame's edge is not: start the zone 8-10 px clear of it). A fold zone lies on the
   fold, not on the stubble beside it.
3. Plan:

       python3 soften_lines.py face.png X Y area_lines.json ~/.photocraft-skill/work/<photo>/lines \
           --face-width 1500 [--opacity lines=0.5,undereye=0.4,folds=0.3]

   Read `viz.png`: green = lines softened, cyan = the under-eye lift (strongest in the middle, faded in from the
   zone's edge), magenta = deep valleys left, yellow = the zones. Green on stubble, a mole, a lash or a frame:
   pull the zone in or exclude it. Then `compare.py face.png lines/preview.png cmp.png --rect … --scale 3 --check
   solar,lum`: every line still there but fainter, pores continuous through it, no light line where a dark one
   was. The output gives per kind the radius, how many lines, and `depthP50`/`depthP95` (levels below the skin
   beside them, before opacity).
4. `python3 import_layers.py ~/.photocraft-skill/work/<photo>/lines/layers.json` (headless `--file in --out
   out.psd`) puts a "Soften lines" group on top; it must say `"verify": "ok"`. The opacities are the ones the
   tier calls for (the table above); change them with `layer.setProps {"layer": id, "opacity": 0.4}`, never by
   painting on the layers.
5. Check the whole face at fit and at 1x against the original: "the same person, rested". `qc.py diff
   before.png after.png <dir> --area all_zones.json --margin 12` (the zones as one `"skin"` list): nothing
   changed outside them.

Measured on a public-domain 3463 x 4329 portrait of a man in his late sixties with rimless glasses (face width
1500 px; radii 5, 17 and 33 px): a 700 x 600 crop round one eye (crow's feet and the crease under the frame as
lines, the tear trough inside the lens as under-eye) planned in 3.5 s, 7 lines; a 1050 x 1080 crop with the
forehead, the other eye's crow's feet and both nasolabial folds in 9.4 s, 25 lines and 3 fold pieces, a patch of
stubble left after the elongation test. Lines were 4-19 levels deep (P50-P95), the tear trough up to 22, the
folds up to 27: at the default opacities 2-10 levels of lift. Both imports verified (mean difference 0.00 and
0.01), and `qc.py diff` found nothing changed outside the zones. At `--max-depth` 28 the tear trough itself
counted as deep and was left, hence 50 for under-eye.

## Step 4: flyaway hair

Stray strands sticking out of the hair's silhouette on a plain backdrop. Unmesh Dinda's method for many
flyaways: paint the backdrop over them on a separate layer, then mask it so the hair's own silhouette comes
back. Keep some: with every strand gone the hair reads as a helmet (Tuts+), which looks fake.

1. Crop round the head at full resolution, even width and height, with backdrop all round: a whole head is
   fine, or the part with the strays (a tight crop runs in seconds, a 2 MP whole head in about a minute).
   Write area.json with `grid.py`: `"skin"` = a polygon round the head whose edge lies on clean backdrop (several
   polygons are fine), `"exclude"` = a polygon a few px inside the hair's edge, plus anything that must stay (an
   earring, glasses, a collar).
2. Plan the layer:

       python3 flyaways.py crop.png X Y area.json ~/.photocraft-skill/work/<photo>/fly [--keep 12] [--fade 10]

   The hair mass is the crop's median (radius `--median`, 4) wherever it stands off the local backdrop by more
   than 5x the backdrop's own spread there (per 64 px tile, at least 8), holes filled (highlights in the hair, a
   loop of hair: never cleaned). The threshold is local so the crop doesn't change it: one global threshold rose
   from 12.3 on a tight crop to 28.9 on the whole head of the same 18 MP portrait, faint wisps at the nape
   stopped counting as hair, joined the most obvious stray (a long strand 25-45 levels darker than the backdrop)
   into one shape, and it was dropped. Strands are thin things in the hair's polarity: darker than both the
   median and the backdrop for dark hair, lighter for light hair, so the light JPEG halo beside a dark strand
   doesn't join it into a blob. Thin means mostly gone after a 3x3 erosion, however tangled; compact shapes
   (dust, a clump) are left, and the big ones are listed, never dropped silently. Strands within `--keep` px of
   the mass stay, and the rest fade out over `--fade` px like a hair tip. The fill is the photo's own backdrop
   averaged round each strand (a vignette or a mottled backdrop stays), with the backdrop's grain baked in.
3. Read `viz.png` (red = removed, cyan = kept near the hair, yellow = the mass's edge, magenta = the zone, orange
   boxes = big shapes left, also listed in the output: a clump, dust, a mark on the backdrop; look at each), then
   compare the crop with `preview.png` at 2-3x (`compare.py crop.png fly/preview.png cmp.png --rect … --scale 3`):
   strands gone without a trace, the hair's edge as soft as before, nothing taken from inside the hair.
   **A strand that crosses onto skin, an ear or clothes** is painted out only where it lies on backdrop, so it
   would start abruptly at the ear's rim. Heal or clone the skin part first (`plan_heals.py --add X,Y,D` along
   it, or `paint.cloneStamp` along the strand from the skin beside it where it crosses the rim), then plan the
   flyaways; or keep the whole strand with an `"exclude"` polygon over its backdrop part.
4. `python3 import_layers.py ~/.photocraft-skill/work/<photo>/fly/layers.json` (headless: `--file photo.jpg
   --out photo-fly.psd`); it must say `"verify": "ok"`.

Measured on three studio portraits (white, light grey and mottled blue backdrops) and the white one inverted
(light hair on dark): at `--keep 12` it removed 18 and 21 strands on the white and grey backdrops (17 on the
inverted one) and 2 on the slicked-back hair against blue, with the hair mass untouched (0 of 165,288 pixels
changed), nothing outside the zone changed, the import exact (max 0; within 5 levels on an Apple RGB photo,
which has no builtin twin), 5-20 s a crop. On the whole head of an 18 MP portrait (1380 x 1420 px), where the
global threshold had kept the long stray (none of its 144 px removed) and left 2238 strand pixels beyond the
keep band, it now takes the stray from where it leaves the hair's clump, fading in (85 of the 144 px clear,
the rest tapering), leaves 65 strand pixels, and drops no shape silently; a tight crop of the same corner takes
it from 31 px further out, where the strand's thick base counts as hair. About 40 s for that 2 MP crop. `--keep` is about 1-2.5 % of the head's width: 12 kept the
fuzzy edge of a 1000 px wide head; on a 480 px head with gelled spikes, 6 took the long strays and kept the
spikes. Strands across skin, eyes or clothes are healing work (Step 2), not this.

## Step 5: check like a retoucher

- Before/after at 1× of the whole face and 2–3× of the worked areas, plus the check views:
  `compare.py before.png after.png cmp.png --rect … --scale 2 --check solar,lum` (solar curve and grey
  luminance, before and after). In the live app, `import_layers.py scripts/check_layers.json` adds the same as
  a hidden "Check layers" group at the top to toggle while working; heal on a layer below it with
  `currentAndBelow` (Viktor Fejes): sampling `all` with the solar layer showing copied its zigzag into the photo
  (a spot 71 levels darker, measured). Keep it hidden or delete it before saving.
- **No white dots:** on the check view, healed areas show no isolated light specks the original
  didn't have. Light bumps (≥4 px, > 6 levels over a radius-2 median) should go *down* in the worked
  area, never up.
- **No bruises:** `compare.py --marks` on the worst former marks shows each one fainter in tone *and*
  colour. Darker-but-neutral or cooler than its surroundings means fix it before delivering.
- Pores and grain continuous; no smooth patches, smears or repeated clone patterns.
- Light intact: rim light, highlights and form shadows the same as in the original.
- Identity intact: moles, stubble, lips, ears, eyes untouched; nothing reshaped.
- Nothing outside the skin changed: diff the export against the original outside the work region.
- Other skin of the same person in frame (hands, arms): treat temporary marks the same way; say what you
  did and what you kept.

## Step 6: save

- Layered: `app.save {"path": "…/photo-retouched.psd"}` (new name, next to the original).
- JPEG: `app.save` ignores a `quality` param and writes about q90. A full-size copy of the retouch at the
  original's quality: `$PC cli convert photo-retouched.psd photo-retouched.jpg --quality 95` (the colour
  profile, e.g. Display P3, is kept). Files for a client (web, social, print sizes, sRGB, output sharpening,
  a size cap) come from `deliver.py` (`references/deliver.md`).
- An export taken right after a save can come back stale (old pixels). Re-export, or check a pixel
  against `document.pixel` before trusting it.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Rings all over a lit patch of neck/nape | Hair follicles and short hairs, not acne | Exclude that area |
| A line of rings along the edge of light or shadow | The median reference lags behind the edge | `--max-gradient` (default 2) does this; lower it to 1.5 |
| Rings on knit, collar, zip | Fabric texture | Pull the polygon in or add an exclusion box |
| Rings on pores everywhere | An explicit `--threshold` too low for this skin's noise | Leave `--threshold` out (it sets itself per tile), or `--noise-mult 5` |
| A mole or freckle planned for healing (red ring on it) | A faint or reddish one the classifier calls a blemish | A small exclusion box over it in area.json |
| A blemish kept as a mark (blue) | Brown post-acne marks look like freckles | `--add X,Y,D` for that one, or `--heal-marks` |
| Over 20 % of the dabs are Spot Healing (the output says so) | No clean skin within ~20 px of the marks | Widen the area round them; `--source-max-speck` higher; on FS High `--fallback skip` |
| Light bumps survive on rim-lit skin | Detector only scores dark and red | `--bright-weight 0.7 --ref-small ref3.png` |
| **White dots where the acne was ("scars")** | Whiteheads left between the healed pimples, or a heal that copied a light speck | Whitehead pass (Step 2); always `--ref-small` so sources are speck-free |
| **Grey-blue "bruises" where the pimples were** | The mark lost its red but kept its darkness; or the colour layer's pixels were converted on import (sRGB PNG → P3 photo) | `skin_masks.py` fixes tone and colour by one fraction; `import_masks.py` assigns the photo's profile. Check with `compare.py --marks` and the colour-bias check |
| Dark blob with a hard edge at the area border | A shadow (under the earlobe, the jaw) runs into the area and got lifted inside only | Leave shadows out of `area_db.json`; `--max-dev` keeps big deviations out |
| Green/magenta bands along a region edge or the jawline | A form shadow or highlight inside the tone area | Tighter `area_db.json` (marks only), or lower `--edge` |
| Marks still visible after Step 3 | Marks broader than ~2.5 × sigma, or strength low | `--sigma` up (≤ 3 % face width), strength up to 0.85 |
| Skin looks flat or airbrushed | Too strong or too broad | strength 0.6–0.7, smaller sigma, raise `--threshold` |
| FS: the photo 1–2 levels lighter with the group on | 8-bit Apply Image at Offset 128 | `freqsep.py` (16-bit, or Offset 127 with `--bits 8`); `identity` says how close |
| FS: a blown, light blob where a dab went on High | The dab sampled the layers below (Current & Below, All) | `--sample current` (default) on High |
| FS: smooth patches on High | Soft brush or Spot Healing on the texture layer | `--hardness 95 --fallback skip`; heal the skipped spots (printed, yellow on the overlay) by hand from a chosen source |
| `freqsep.py`: "several pixel layers" or "… covers it" | No `--layer`, or the source lies under an opaque layer | `--layer` = the layer holding the finished pixels (Healing after Step 2) |
| `freqsep.py`: identity MISMATCH, "the group doesn't show" | A layer above hides the group (a masked or partly opaque one the first check can't see) | Build from that layer, or hide it |
| FS in 8-bit: smooth areas 1 level darker with the group on | 8-bit can't be exact (Linear Light would need 127.5) | 16-bit (the default) |
| plan_heals ids or the "next" ids point at the wrong layers | The PSD was saved and reopened: layers renumbered bottom-up | Read the ids again (`document.inspect`, `select.findLayers` by name) |
| FS: pores still in Low, or edges soft in it | Radius too small or too large for this face | `freqsep.py radius` on plain cheek and forehead; look at its sheet |
| A dark or light blotch where a heal went, check layers on | The heal sampled All with the solar layer showing | Heal with `currentAndBelow` below the check layers, or hide them |
| Lines: a crease or crow's foot not softened (no green on it) | Fainter than the threshold (3x the valley noise, 2 levels at least), or wider than the radius | Its zone on its own, `--threshold 2`; a wide crease belongs in `folds` |
| Lines: a light line where a dark one was | Opacity near 1, or the zone takes in a bright edge (rim light) | Opacity 0.4-0.6; keep the zone off lit edges |
| Lines: stubble, pores or a mole lightened | The zone covers stubble, or a mole sits in a line | Pull the zone onto the line; exclude the mole |
| Lines: the frame or lash line magenta, or a frame edge lightened | The zone touches it | Start the zone 8-10 px clear of frames and lashes |
| Under-eye: no change in the tear trough (a magenta notch) | Deeper than `--max-depth` (50) | `--max-depth 60` if the zone is clear of the lashes |
| Under-eye: the eye looks hollow or flat, "younger, someone else" | Opacity too high, or the zone reaches the lid | 0.3-0.4; the zone below the lid's edge only |
| Folds: the cheek loses its shape | A fold is a form shadow; too much opacity or too wide a zone | 0.2-0.3, the zone on the fold only |
| Flyaways: few strands found | Fainter than `--threshold` (4 levels, or 4x the noise beside the hair); light hair on a light backdrop | `--threshold 3`; blonde or grey on white has little contrast: say so |
| Flyaways: helmet look | `--keep` too small for this head | `--keep` 1-2.5 % of the head's width |
| Flyaways: a loop of hair kept | A loop around backdrop counts as hair (holes are never cleaned) | Heal or clone it by hand if it must go |
| Flyaways: "the backdrop varies" warning | Mottled or painted backdrop, a paper seam, a busy background | The fill follows it locally; check at 2x, keep the zone off the seam |
| Flyaways: an orange box, "large shapes … left" | Too thick for a strand: a clump of hair, dust, a mark on the backdrop | Look at it at 3x; clone or heal a clump by hand, dust with the dust tools |
| Flyaways: a strand starts abruptly at an ear or the skin | Only its backdrop part is painted | Heal or clone the skin part first, or exclude the strand to keep it whole |
| Flyaways: a different result on a tighter crop | The tile grid and how much of a strand's thick base counts as hair | Both take the stray part; crop with backdrop all round and compare at 3x |
