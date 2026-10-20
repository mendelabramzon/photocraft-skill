# Eyes and teeth: fresh but natural

Read this before whitening teeth or retouching eyes. It's the portrait finish that goes with the skin retouch:
cleaner, less yellow teeth, cleaner eye whites and a little life in the iris, measured against the photo's own light
so nobody looks retouched. `scripts/eyes_teeth.py` builds the masks and solves the curves; `scripts/import_layers.py`
puts them in the document and checks the result against the prediction.

## Contents
- What separates professional eye and teeth work from a cheap one
- The layer stack you're building
- Step 1: set up and map the regions
- Step 2: plan the layers
- Step 3: build them in the document
- Step 4: red-eye (only if there is any)
- Step 5: check like a professional
- Step 6: save
- Tuning and false hits

## What separates professional eye and teeth work from a cheap one

From Kristina Sherk's "Top three signs of over retouching" (KelbyOne Insider), SLR Lounge's "How to whiten teeth in
Photoshop", Nathaniel Dodson's eye retouch (tutvid), a dentist's guide to how white is too white (Dr. Frangella), and
what held up in testing on six portraits:

- **Colour first, brightness second.** "Sometimes it's more about fixing the color than it is the brightness" (Sherk).
  Teeth: take part of the yellow out; SLR Lounge starts at yellow saturation −40 and warns "de-saturate too much and
  you're left with gray". A brightness boost alone makes teeth glow.
- **Teeth are never whiter than the eye whites.** "The whiteness of your teeth should not exceed the shade of the
  whites of your eyes (in most people)" (Frangella). Teeth also stay a little yellow: neutral or blue-white teeth read
  as fake, and in testing even bleached-looking teeth measured b* 3–8.
- **Teeth only.** Gums, lips, tongue and the dark gaps stay out of the mask. The gradation stays (back teeth darker,
  translucent edges). Stains, tartar and dark fillings are healing work, and part of the person: ask before removing.
- **Eye whites: clean, rarely brighter.** "When I retouch eye whites, I rarely brighten them" (Sherk): remove veins,
  take out red, move slightly away from yellow, lighten at most next to the iris. "When people over-whiten the corners
  of the eye whites, they end up making the round eyeball look flat." Never pure white.
- **Iris: light it from across the catchlight.** "Add extra emphasis to the side of the iris that is directly across
  from the catchlight" and "feather in darkness for the edge of the iris" (tutvid). Keep the catchlights; never
  recolour or enlarge an iris.
- **Sharpen iris and lashes only,** never the skin around them, and never so much that a catchlight gets a dark halo.
- **Respect the light.** A golden-hour or tungsten portrait has warm eye whites and warm teeth because the light is
  warm. Neutralising them makes eyes and teeth grey-blue against warm skin. Measure the teeth against the eye whites,
  which carry the same light.
- **Both eyes alike, everything subtle, all on named layers** that can be turned down. At 1× the result should look
  like the same person, rested.

## The layer stack you're building

    Eyes & teeth                group, Pass Through
      Sharpen eyes              Stamp Visible + Unsharp Mask (amount 80, radius iris/30), mask = sharpen.png
      Iris                      Curves [0,0][128,160][255,255], Luminosity, mask = iris.png
      Limbal ring               Curves [0,0][128,96][255,255], Luminosity, mask = limbal.png
      Eye whites (lift)         Curves [0,0][128,160][255,255], Luminosity, mask = whites_lift.png
      Eye whites (colour)       Curves red/green/blue (solved), Normal, mask = sclera.png
      Teeth                     Curves red/green/blue (solved), Normal, mask = teeth.png
      Eye whites (veins)        pixel layer = the clean white under the veins, Normal, mask = veins.png
    Eyes heal (only for red-eye or hand heals)
    Skin retouch, Healing, Background

## Step 1: set up and map the regions

Work in a folder under the home directory, e.g. `~/.photocraft-skill/work/<photo>/`.

1. Do the skin retouch first if there is one. This group goes on top: its sharpening stamp merges everything below
   it, and its colours are measured on the finished skin.
2. Export the current state (`$PC export ~/.photocraft-skill/work/<photo>/state.png`), then crop the face with the
   CLI, eyes and mouth together, at full resolution and with even width and height (the masks are centred on the crop):

       $PC cli run state.png --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' --out crop.png

3. Map the regions with `grid.py` (eyes: `--step 10 --scale 3` on a small crop around each eye; teeth `--scale 2`) and
   write `regions.json` in full-image coordinates:

       {"eyes": [{"opening": [[x, y], …], "iris": [cx, cy, r]}, …],
        "teeth": [[x, y], …]  or  [[[x, y], …], [[x, y], …]],
        "exclude": [[x0, y0, x1, y1] or [[x, y], …], …]}

   - `opening`: along the lid margins, just inside the lashes. Leave out the pink caruncle in the inner corner and the
     wet lower lid margin.
   - `iris`: a rough circle is enough; the script finds the edge along rays and fits the circle within 0.35 r of the
     centre and ±20 % of the radius. On synthetic eyes it lands within about 0.1 px (median) from guesses up to 7 px
     off.
   - `teeth`: along the inner edge of the lips. Gums may be inside, they're gated out. With an open mouth, give the
     upper and lower rows as two polygons and leave the tongue out.
   - Either part may be missing: eyes only, or teeth only (eyes closed or squinting).
   - A photo in another profile (Apple RGB, Adobe RGB) looks too dark in the grid PNGs, which are written without a
     profile. Make a viewing copy with `sips --matchTo "/System/Library/ColorSync/Profiles/sRGB Profile.icc"`.

## Step 2: plan the layers

    python3 eyes_teeth.py crop.png X Y regions.json out [--light warm] [--space p3]

What it does:
- **Teeth mask**: polygon × lighter than the gaps (0.42 × the teeth's bright level) × no pinker than the lit teeth
  (a* ramp +6..+12): gums, lips, tongue and stains fall out. Small islands (a gum highlight) are dropped.
- **Teeth curve**: one curve per channel through the teeth's L* quartiles. With eye whites in the crop, `--whiten`
  (0.4) of the teeth's yellow above the eye whites' is taken out; teeth-only, `--whiten` of their b*. Floors: b* ≥ 6
  and ≥ the corrected whites + 1. The lift, at most 3 L*, comes only with yellow to take out and stops below the lit
  eye whites.
- **Eye whites**: opening minus the iris (2 px ramp); lashes out by lightness, skin and caruncle out by smoothed chroma.
  The colour layer takes out `--sclera-red` (0.5) of a* and `--sclera-yellow` (0.3) of b*, never past a slightly warm
  white. The lift layer adds `--sclera-lift` (3) L* beside the iris, fading to 40 % in the corners.
- **Veins**: thin lines more than `--vein-threshold` (5) levels redder than the white around them (broad pink areas
  are not veins) are replaced by that clean white at `--veins` (0.8).
- **Iris**: catchlights are found inside the iris and the pupil from the radial profile (assumed 0.4 r when a very
  dark iris hides it). The lift (`--iris-lift`, 5 L*) is strongest on the far side from the catchlight, off the pupil,
  catchlights and lashes. The limbal ring is darkened `--limbal` (2) L*.
- **Sharpen eyes**: iris and lashes (dark pixels just outside the opening), minus a ring round each catchlight.
  Unsharp Mask amount 80, radius iris/30 (0.5–1.5 px); `--no-sharpen` to leave it out.
- `--light warm` (golden hour, tungsten, candle): the whites keep the light's colour (`--sclera-red 0.15`,
  `--sclera-yellow 0`) and the teeth are whitened relative to them. The script prints a hint when the whites measure
  warm (b* > 12 or a* > 8). Look at the photo and decide: a warm light, or yellow eyes?
- `--space p3` for a Display P3 photo (`edit.profileInfo {"profile": "document"}` names it); other profiles measure
  approximately, but the targets are relative, so the result still holds.

Read, in this order: `regions.png` (the fitted iris, cyan, must sit on the iris edge; the pupil, blue, on the pupil),
`viz.png` (teeth cyan, whites yellow, veins red, iris green, limbal ring magenta, sharpen blue: each on its own
part only), then `compare.py crop.png out/preview.png cmp.png --rect … --scale 3 [--check]` for the eyes and the
teeth, and the whole face at 1×. `eyes_teeth.json` has the numbers (Step 5).

## Step 3: build them in the document

    python3 import_layers.py ~/.photocraft-skill/work/<photo>/out/layers.json

The group goes on top of the stack (or `--above <id>`), each PNG assigned the photo's profile. The document is then
rendered, cropped and compared with `preview.png`. Expect `"verify": "ok"`, meanAbsDiff ≈ 0.002–0.004, bias 0: the
preview is exact, the stamp and Unsharp Mask included. "Document profile 'c2' has no builtin twin" (a compact sRGB
profile from web downloads) is harmless when verify shows no bias. Headless: add `--file photo.jpg --out photo-eyes.psd`.
To redo, `layer.delete` the group and import again.

## Step 4: red-eye (only if there is any)

`paint.redEye` changes pixels, so do it first, on a copy, then export and plan. Pass the copy's id explicitly:

    $PC exec layer.duplicate                                    → {"layer": ID}
    $PC exec layer.setProps '{"layer": ID, "name": "Eyes heal"}'
    $PC exec paint.redEye '{"layer": ID, "target": "pixels", "points": [[x1, y1], [x2, y2]], "pupilSize": 50, "darken": 50}'

Check each pupil: `document.sampleColor {"x", "y", "size": 5}` gives RGB in 0..1; times 255 into `imgops.lab` it
should be L* < 25 and a* < 5. Still pink, raise `darken` to 80–100 and `pupilSize` to 100. If it turns blue
(b* < −5), back off. In testing the defaults left a strong red-eye pink (a* 24); 100/100 gave L* 21, a* 5, b* −6.

## Step 5: check like a professional

- `checks` in `eyes_teeth.json`: `teethYellowTakenOut` near what was asked (less when a floor applies);
  `teethWarmerThanWhites` true; `teethMinusWhitesL` not growing; `whitesLiftBesideIris` ≈ `--sclera-lift` with less
  overall (`whitesLift`); `whitesNotBlue` true; `irisLiftL` ≈ `--iris-lift`; `maxMaskStep` ≤ 0.35 for every mask (no
  hard edges); the import's verify ok.
- At 1×: the same person, rested. Teeth not glowing, not grey; the back teeth still darker; gums and lips unchanged.
- At 3×: eye corners still shaded (round eyeball), whites not white-white, veins faded not erased to flat patches,
  catchlights untouched and without a dark rim, no sharpening on the skin, both eyes treated alike.
- Against warm skin, teeth and whites must not look cooler than the light. If they do, it's `--light warm`.

## Step 6: save

As for the skin retouch: `app.save {"path": "…/photo-retouched.psd"}`, then the JPEG with
`$PC cli convert photo-retouched.psd photo-retouched.jpg --quality 95` (`app.save` ignores quality).

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| The cyan iris circle is off the edge | Very low contrast iris, or the drawn circle was more than 0.35 r off, so the fit was refused (`refined: false`) | Redraw the circle from a horizontal L* profile through the iris; `--no-refine` to force it |
| Teeth or eye whites look grey or blue against warm skin | The warm light got white-balanced out | `--light warm`; teeth only: `--whiten 0.2–0.25` |
| Shaded back teeth aren't whitened | In warm shadow they are as red as gums (a* 20–26, hue 43–52° against the gums' 27–43°) and fall out | Usually right: they read as shadow. A hue gate didn't separate them; it pulled in gums and lip skin |
| Gum line or a lip highlight whitened | Polygon reaches into the lips and a gum highlight survived | Pull the polygon in, or add an exclusion |
| Stains, tartar, a dark filling left as they were | Gated out on purpose | Heal by hand if the user wants them gone; ask first |
| Teeth unchanged | Already white (median b* at or below the floor) | Expected; don't force it |
| Veins left beside the caruncle or the lid margin | The chroma gate and a 2 px erosion keep that zone out | A few ≤ 5 px healing dabs by hand on Eyes heal |
| Waterline or caruncle turned white | The opening includes them | Draw the opening inside the lid margin, caruncle out |
| Dark rim round a catchlight | Sharpening reached it | Catchlights are kept out by default; lower `--sharpen-amount` |
| Pupil turns grey | `pupilSeen: false` on a very dark iris | `--iris-lift 2`, or 0 |
| Grids look dark, Lab numbers off | Profile other than sRGB/P3 (Apple RGB) | View through sips; the targets are relative, so results hold |
| Whites look flat | Lift too strong for this light | `--sclera-lift 1.5`, or turn the lift layer down |
