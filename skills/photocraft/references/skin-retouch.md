# Skin retouch: clean but natural

Read this before retouching skin. It is the full version of the recipe in SKILL.md: how professional
retouchers work, and how to do the same in PhotoCraft with the planning scripts.

## Contents
- What separates a professional retouch from a cheap one
- The layer stack you're building
- Step 1: set up and map the skin
- Step 2: heal the blemishes (texture)
- Step 3: dodge & burn and colour evening (tone and colour)
- Step 4: check like a retoucher
- Step 5: save
- Tuning and false hits

## What separates a professional retouch from a cheap one

These are the points the retouching literature agrees on (PhLearn, SLR Lounge, Fstoppers, PetaPixel,
Pratik Naik's high-end workflow, Zoner):

- **Order: big to small, texture before tone.** Clean up blemishes first, then even tone (dodge &
  burn), then colour, then judge the whole. D&B over unhealed acne just paints around it.
- **Remove what's temporary, keep what's the person.** Heal active acne, whiteheads, scabs, scratches,
  flakes, stray hairs on the skin. Keep moles, freckles, scars, stubble, the hairline, pores, smile
  lines, and the face's shape, unless the user asks otherwise. For men keep more texture and stubble.
- **Never blur skin.** Blur, surface blur, "smoothing" and high-pass softening layers read as plastic.
  Pores must run continuously across cheek, jaw and nose, with no smooth patches. Healing copies real
  texture from nearby; D&B and colour only change tone and hue at blotch scale, so texture is untouched.
- **Healing: small dabs, nearby sources.** A brush a little bigger than the blemish, sourced from clean
  skin close by with the same light and texture, never repeating one source (clone patterns).
- **Dodge & burn is what makes skin look clean.** After healing, what still reads as "bad skin" is
  uneven tone: post-acne marks, shadows of bumps, blotches. The standard tool is two Curves adjustment
  layers, one lightening (Dodge) and one darkening (Burn), in **Luminosity** blend mode so they don't
  shift colour, with masks painted only where a spot is darker or lighter than its surroundings.
  Retouchers judge it on a *check layer*: black & white plus a contrast curve, which shows blotches
  that colour hides (`compare.py --check` gives the same view).
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

## The layer stack you're building

    Skin retouch (D&B + colour)   group, Pass Through
      Burn                        Curves [0,0][128,96][255,255], Luminosity, mask = burn.png
      Dodge                       Curves [0,0][128,160][255,255], Luminosity, mask = dodge.png
      Skin colour (marks)         pixel layer = the skin recoloured to the clean skin around it, Normal, mask = color.png
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

    python3 plan_heals.py crop.png ref10.png X Y area.json --threshold 7 --max-size 10 \
        --ref-small ref3.png --layer <Healing id> --steps heal.json --overlay overlay.png
    $PC exec layer.select '{"layer": <Healing id>}'
    $PC script heal.json

It finds blemish pixels (redness counts 3× darkness, so pores and stubble survive), covers each with
as many ≤10 px Healing Brush dabs as needed (hardness 80), each sourced from clean, tone-matched skin
within ~20 px. Hundreds of dabs run in under a second.

- Read `overlay.png` before running. Rings must sit only on blemishes. See "Tuning and false hits".
- Always pass `--ref-small ref3.png`. Then no source may contain a whitehead or dark pore
  (`--source-max-speck`), so a heal never copies a white dot onto a cleaned spot.
- **Rim-lit or side-lit skin:** small bumps (closed comedones, flakes) show as light specks. Add
  `--bright-weight 0.7`.
- **Whitehead pass**, after the pimples are gone: light bumps only, in the acne zone (its own small
  `area_acne.json`):

      plan_heals.py crop.png ref10.png X Y area_acne.json --dark-weight 0 --bright-weight 1 \
          --ref-small ref3.png --threshold 6 --min-area 5 --max-size 7 …

  Calibrate it: run the same settings on a clean patch of the same skin. It should find 0–2 there.
  If it finds more, raise `--threshold`, or it will strip natural texture. Then re-plan once more.
- **A blemish the detector misses** (a scab that is half light, half dark; a spot on the lip edge):
  `--add X,Y,D`. Keep only the steps near it if the rest of that area isn't meant to be healed.
- Repeat: `$PC export` (to a path under home), re-crop, rebuild the references, re-plan. Usually 2–3
  passes until it finds only a handful. Look at a before/after at 3× after each pass
  (`compare.py crop.png crop_after.png cmp.png --rect … --scale 3`).
- What's left after healing is tone and colour (soft marks, redness). Don't chase it with more or
  bigger heals at partial opacity; that's Step 3's job.

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

## Step 4: check like a retoucher

- Before/after at 1× of the whole face and 2–3× of the worked areas, plus the `--check` view.
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

## Step 5: save

- Layered: `app.save {"path": "…/photo-retouched.psd"}` (new name, next to the original).
- JPEG: `app.save` ignores a `quality` param and writes about q90. For the deliverable, render the PSD
  with the CLI at the original's quality: `$PC cli convert photo-retouched.psd photo-retouched.jpg
  --quality 95`. The colour profile (e.g. Display P3) is kept.
- An export taken right after a save can come back stale (old pixels). Re-export, or check a pixel
  against `document.pixel` before trusting it.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Rings all over a lit patch of neck/nape | Hair follicles and short hairs, not acne | Exclude that area |
| A line of rings along the edge of light or shadow | The median reference lags behind the edge | `--max-gradient` (default 2) does this; lower it to 1.5 |
| Rings on knit, collar, zip | Fabric texture | Pull the polygon in or add an exclusion box |
| Rings on pores everywhere | Threshold too low for this photo's noise | Raise `--threshold` (8–10) |
| Light bumps survive on rim-lit skin | Detector only scores dark and red | `--bright-weight 0.7 --ref-small ref3.png` |
| **White dots where the acne was ("scars")** | Whiteheads left between the healed pimples, or a heal that copied a light speck | Whitehead pass (Step 2); always `--ref-small` so sources are speck-free |
| **Grey-blue "bruises" where the pimples were** | The mark lost its red but kept its darkness; or the colour layer's pixels were converted on import (sRGB PNG → P3 photo) | `skin_masks.py` fixes tone and colour by one fraction; `import_masks.py` assigns the photo's profile. Check with `compare.py --marks` and the colour-bias check |
| Dark blob with a hard edge at the area border | A shadow (under the earlobe, the jaw) runs into the area and got lifted inside only | Leave shadows out of `area_db.json`; `--max-dev` keeps big deviations out |
| Green/magenta bands along a region edge or the jawline | A form shadow or highlight inside the tone area | Tighter `area_db.json` (marks only), or lower `--edge` |
| Marks still visible after Step 3 | Marks broader than ~2.5 × sigma, or strength low | `--sigma` up (≤ 3 % face width), strength up to 0.85 |
| Skin looks flat or airbrushed | Too strong or too broad | strength 0.6–0.7, smaller sigma, raise `--threshold` |
