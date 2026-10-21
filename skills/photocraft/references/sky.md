# Sky replacement and sky enhancement

Read this before replacing or improving a sky (landscapes, real-estate exteriors, architecture). It is the full
version of the recipe in SKILL.md: what makes a replaced sky believable, and how to do it in PhotoCraft with
`scripts/sky_mask.py` (the mask) and `scripts/sky_check.py` (fit and harmonise, enhance in place, check).

## Contents
- What separates a professional sky from a cheap one
- The layer stack you're building
- Step 1: the mask
- Step 2: enhance or replace
- Step 3: choose and fit the new sky
- Step 4: build it
- Step 5: check like a professional
- Enhance instead of replace
- Reflections, and moving the sky later
- Save
- Tuning and false hits

## What separates a professional sky from a cheap one

The points the literature agrees on (Adobe's Sky Replacement help, PhLearn, Skylum's guides, real-estate editing
practice), and what testing in PhotoCraft 0.7.0 added:

- **Replace only what can't be saved.** A grey sky with cloud detail usually wants contrast and a graduated
  darkening, not a new sky. Replace when it's blown white or flat and colourless (`sky_check.py enhance` says
  which).
- **The light must match.** Sun direction and height: if the land is lit from the left, the sky's sun or brightest
  clouds belong on the left (mirror the sky with `--flip`). Time of day, which Skylum calls the single biggest
  factor. Light quality: an overcast scene has no shadows, so a sky with a blazing sun over it looks pasted.
  Overcast originals are the easy case; give them soft, diffuse skies.
- **The horizon must match.** The sky's horizon line, camera angle and cloud scale (clouds get smaller and flatter
  toward the horizon): a sky shot straight up doesn't fit a level view of a house. A clear sky gets paler and
  brighter toward the horizon; an overcast one is brightest overhead (CIE standard overcast sky: the horizon is a
  third of the zenith's luminance).
- **The edge is where it fails.** Thin details along the skyline (branches, aerials, chimneys, railings, cables)
  and pale outlines give a replacement away (Skylum). PhotoCraft's `select.sky` finds roughly where the sky is,
  but its edge is a smooth blob 10-20 px off: it rounds chimneys, cuts into roofs, treats a tree as solid, finds
  3 % of a sky seen through branches, and misses whole patches (a vignetted corner, the band of darker or paler
  sky near the horizon). `sky_mask.py` starts from it and fixes all of these.
- **Decontaminate the edge.** Edge pixels are a mix of old sky and foreground; laying the new sky over them leaves
  the old sky inside them as a light rim. Photoshop's Sky Replacement handles this with Shift Edge, Fade Edge and
  Color Adjustment; `sky_mask.py` recovers each edge pixel's own foreground colour.
- **Harmonise the land to the light.** The land should look lit by the new sky (Adobe: Color Adjustment "harmonizes
  the foreground with sky colors"; PhLearn: blend with Color Balance and Levels, grade the land to match). Use
  the colour of the light, which shows in the lit clouds, not the blue of the sky: a sunny scene is lit mostly
  by the sun, so tinting a brick house blue because the new sky is blue turns it grey.
- **Keep the sky brighter than the land.** Near the horizon the sky is normally well above the land; graduated ND
  filters, the in-camera fix for that, come in 1, 2 and 3 stops (LEE 0.3/0.6/0.9). A sky barely brighter than the
  land looks stuck on.
- **Haze and reflections.** Haze near the horizon blends a too-dark or too-saturated sky into the land (Skylum).
  Water and windows must reflect the new sky, in its direction and colours.
- **Light wrap.** Against a bright sky, light spills over the edges of roofs and trees; a land edge that stays
  exactly as dark as before, right up to a new bright sky, looks cut out. Compositors wrap it: the sky blurred until
  no cloud detail is left, in a lightening blend, along the land's edge (Planet Photoshop's light wrap; the old Inner
  Glow, one flat colour, fails under mixed light). Subtle: a soft lighter edge at 3x, nothing at 1x.
- **Grain and resolution.** A clean stock sky over a noisy photo, or an enlarged small sky over a sharp one, gives
  itself away. Match the grain; don't enlarge a sky more than about 1.5x.
- **Editable.** The sky on its own layer with its mask, the land's adjustment separate, the original untouched.
- **Real estate: believable, and disclosed.** A clean, natural blue on dull exteriors is standard (not saturated
  stock blue). Disclosure rules vary by MLS; California's AB 723 (in force since 1 January 2026) requires
  licensees to disclose digitally altered listing photos and give access to the originals, and sky replacement
  was the most common alteration in a study of listing photos (HousingWire). Tell the user.

## The layer stack you're building

    Sky replacement               group, Pass Through
      Horizon haze                Solid Color = the old sky's horizon colour, mask = haze.png (optional)
      Light wrap                  the new sky blurred, Screen, mask = wrap_mask.png: the land's edge (optional)
      Sky                         the fitted sky photo, mask = alpha.png
      Foreground harmonise        Curves (red, green, blue): the land takes part of the new light's colour
      Sky edges (decontaminated)  edge.png, mask = edge_mask.png: edge pixels with the old sky taken out
    Background                    original, untouched

The harmonise curves sit under the sky, so they change only the land and the edge colours. Enhancing instead
builds a `Sky enhance` group of two Curves layers in Luminosity mode.

## Step 1: the mask

Work in a folder under the home directory (`~/.photocraft-skill/work/<photo>/`): the app only opens files there.

    python3 sky_mask.py photo.jpg ~/.photocraft-skill/work/<photo>/sky [--area area.json] [--trees]

It runs `select.sky` with the CLI, crops the photo from the top to below the skyline (every layer covers that
crop) and refines the coarse region:

- Sky that `select.sky` missed is added back where it continues the known sky with no edge in between: above the
  coarse skyline any smooth pixel, below it smooth pixels of the sky's hue (brightness can't be the test: a clear
  sky pales toward the horizon, an overcast one darkens).
- Around the coarse edge (a band of `--band` 1.5 % of the width), in tree canopies near the sky, and around thin
  dark things inside the sky (aerials, wires, birds, which stay), every pixel is solved with a local colour model:
  the clean sky at that spot (a robust local plane fit that follows the gradient toward the horizon) and the
  foreground beside it. alpha = how far the pixel sits along the line from foreground to sky colour.
- Edge pixels get their foreground colour back (`edge.png`): I = alpha x S + (1 - alpha) x F, solved for F.
- Holes in canopies are solved against the brightness of the sky seen through neighbouring holes, so a
  vignetted corner still comes out fully sky. Sky islands inside solid foreground (pale tiles, a window) are
  dropped.
- If the sky runs on to the bottom of the crop, the crop is taken taller and the matte solved again.

`--trees` is for sky seen through branches all over the frame (looking up into trees, a forest skyline). The
canopy search covers the whole crop, and the sky colour comes from the open patches between the branches. On an
overcast day a white wall or a fence would pass for sky that way, so use it only for such photos. The script
suggests it when a lot of sky-like area stayed foreground.

Read `viz.png` (shrink it first): blue = sky, yellow = the alpha 0.5 contour, magenta = low confidence (the
foreground is the sky's colour there, so the coarse mask decided), green = thin dark objects kept in the sky.
Then zoom 2-3x on chimneys, aerials and trees with `alpha.png`. Fix with `area.json` (full-image coordinates,
`grid.py` draws them), then rerun with `--reuse` to skip the CLI steps:

    {"sky": [[[x, y], ...]], "keep": [[[x, y], ...]]}

`sky` adds a region it still missed; `keep` protects foreground the colour of the sky (a pale gable, snow, a white
van against white cloud). `--shift 1` lets the sky take 1 px of the foreground's edge (Photoshop's Shift Edge):
it removes a pale line of old sky along solid roofs, and with it every twig, tendril and aerial thinner than that. It takes about 25 s for a 3-megapixel photo; `mask.json` holds the crop, the stats, the
photo's colour profile and any warnings.

On a synthetic scene with known truth (anti-aliased house, 15 px chimney, 2 px aerial, 1 px wire, porous tree, a
vignetted corner the coarse mask missed) the mean alpha error was 0.0004 on the chimney, 0.0008 on the roofline,
0.005 on the aerial, 0.002 on the wire, 0.002 in the missed corner and 0.012 in the canopy (alpha 0..1); 0.05 %
of pixels were off by more than half. Decontaminated edge colours were 24 levels from the truth, the raw photo's
77.

## Step 2: enhance or replace

    python3 sky_check.py enhance ~/.photocraft-skill/work/<photo>/sky

It measures the sky (share blown white, fine detail, colour). The verdict is "replace" when over 30 % is blown or
the sky is flat and colourless; otherwise it has already planned the enhancement (see "Enhance instead of
replace").

For a replacement, ask the user for a sky photo unless they want the clean real-estate blue (`--clear-blue`).
Choose one that matches the scene: sun side, time of day, soft or hard light, and a horizon (its lower part should
be the pale part near the horizon, not mid-sky). It should be wider than the photo, so it isn't enlarged.

## Step 3: choose and fit the new sky

    python3 sky_check.py plan ~/.photocraft-skill/work/<photo>/sky sky.jpg [--sky-x 0.5] [--sky-y 1] [--zoom 1]
        [--sky-rect x y w h] [--flip] [--harmonize 0.5] [--ev 0] [--haze 0.3] [--wrap 0.3]

- **Fit.** The CLI crops the sky photo to the crop's shape (largest part; `--sky-x` left to right, `--sky-y` 1 =
  its bottom at the skyline), resizes it, converts it to the photo's colour profile (a Display P3 sky in an sRGB
  photo would otherwise shift; an embedded ProPhoto or Adobe RGB maps to PhotoCraft's `-compat` builtin), and
  mirrors it with `--flip`. `--sky-rect` leaves out ground, trees or poles at the sky photo's edges; `--zoom 1.3`
  takes a smaller part for bigger clouds.
- **Grain.** It measures the grain of the old sky away from any edge and adds the difference to the new sky (Add
  Noise, gaussian, monochromatic: 0.64 levels of sigma per unit of amount in 0.7.0). On the synthetic scene a
  clean sky went from 0.2 to 2.39 against the old sky's 2.47.
- **Harmonise.** The land is scaled per channel, in linear light, by (new light / old light) ^ `--harmonize`, with
  luminance kept. The light is the brightest sky pixels that aren't blue (lit clouds); a clear blue sky leaves the
  land's colour alone. `--ev` changes the land's exposure in stops (a sunny sky doesn't make an overcast land
  sunlit, so that's your call).
- **Haze.** `--haze 0.2..0.4` lays the old sky's horizon colour over the new sky, strongest at the horizon (a
  straight line fitted under the skyline, so it doesn't step at trees) and fading up over `--haze-height` (0.35)
  of the sky. Use it when the new sky is darker or more saturated near the horizon than the land can carry.
- **Light wrap.** `--wrap 0.3` (0.3-0.4) lays the new sky, blurred by `--wrap-blur` px (2 % of the width), over the
  land's edge in Screen: a band on the land side of the skyline, fading over `--wrap-width` px (0.6 % of the width,
  11.5 px on a 1920 px photo), times the land's share of each edge pixel. On two test photos it lifted that band by 14
  levels on average at 0.3 under a cloudy sky, 17 at 0.4, and 22 at 0.3 under the pale horizon of `--clear-blue`;
  roofs against bright cloud got a soft lighter edge at 4x. Thin branches lie wholly inside the band and turn lighter
  and a little hazier: for a tree-lined skyline use `--wrap 0.2` or a `--wrap-width` of 4-6 px.
- **Clear blue** (`--clear-blue`, no sky photo): a dithered gradient from `#5d8fd0` overhead to `#cfe0ef` at the
  horizon, blended in linear light; `--zenith` and `--horizon-color` change it.

Read the warnings in the output (`plan.json`): sky enlarged over 1.5x; something dark that isn't sky in the part
used (a lamp post at the sky photo's edge: `--sky-rect`); the new sky darker toward the horizon than above (shot
upward: take its lower part, or add haze); the sky under half a stop above the land near the horizon (pasted
look) or far brighter than before. Look at `compare.png` (before | after), then zoom 2x on `preview.png` along the
skyline. `preview.png` holds the document's numbers: for a P3 or ProPhoto photo it looks off when viewed raw.

## Step 4: build it

    python3 import_layers.py ~/.photocraft-skill/work/<photo>/sky/layers.json            # live document
    python3 import_layers.py …/layers.json --file photo.jpg --out photo-sky.psd           # headless

It brings each PNG in at the crop's centre with the photo's colour profile assigned, makes the masks and groups
the layers as "Sky replacement" on top of the stack. Then it renders the document, crops it and compares with
`preview.png`: on the test photos the mean difference was 0.000-0.002 levels (max 1), so the preview is exactly
what PhotoCraft renders. An embedded ProPhoto RGB, ROMM, Adobe RGB (1998) or Display P3 profile is matched to
PhotoCraft's builtin twin, so those photos verify exactly too. If it warns "no builtin twin" and reports a mismatch,
convert the document to the nearest builtin first (`edit.convertToProfile`), then import. Hide the group to compare
with the original.

## Step 5: check like a professional

    python3 sky_check.py check ~/.photocraft-skill/work/<photo>/sky --render export.png

`export.png` is a flat export of the document (`$PC export`, or the headless `--out x.png`); the script crops it. A
light wrap is a deliberate light rim on the land side, so it is taken back out first (Screen inverts exactly), at the
opacity the render shows: fitted over the wrap band against the preview, so a Light wrap layer lowered, raised or
hidden after the import is measured right (`lightWrap` gives the planned and fitted opacity and the mean lift; the fit
assumes the rest of the document is as planned). Tested: a 0.4 wrap as planned fitted 0.401, and taken out the median
rim read -0.71 with 21 % of tiles light, against -0.72 and 20 % for the same sky without a wrap (measured as rendered,
`--keep-wrap`: 1.02 and 38 %). A 0.3 plan whose layer was lowered to 0.15 fitted 0.15 and read exactly what a 0.15
plan reads (mean lift 8.35, 1 dark-rim tile), where taking out the planned 0.3 had read a lift of 17.8 and 25 dark-rim
tiles; with the layer hidden it fitted 0.0 and read like the plan without a wrap.
It takes the luminance across the sky edge in 24 px tiles: a rim right at the edge brighter than both the new sky
beside it and the land behind it is old sky left in the edge pixels, or a mask that stops short. `check.png`
outlines each tile: green clean, orange a light rim, red a strong or dark rim, blue a thin structure only (no
inside to compare with: judge it by eye).

- **Median rim near 0** (`medianRim`, levels). The decontaminated results scored -0.6 to 0.1 on three photos where
  the same alpha without decontamination scored 1.4 to 2.1.
- **Look at every orange and red tile at 3x.** Against a much darker new sky, light stonework, dried tendrils and
  white trim rightly look lighter than the sky and get flagged too (15-28 % of tiles on the test photos, against
  38-44 % without decontamination). A real halo is a pale line along a dark edge, the colour of the old sky. On
  the synthetic scene a mask that stops 2 px short flagged 31 % of tiles; the decontaminated result 0 %.
- **Edges hold.** Aerials, chimney pots, branch tips and railings all there; no new sky inside solid foreground;
  no old sky left in canopy holes (light grey blotches between branches).
- **Light agrees.** Sun side matches the shadows; no visible sun over an overcast-lit scene.
- **Sky above land.** `stopsAboveLand` in `plan.json`; `skyLuminance` in the check shows how the sky runs from top
  to horizon (a clear sky should pale toward it).
- **Grain matches.** `grain.newSky` within about 30 % of `grain.oldSky`.
- **Colour.** The land keeps its own colours (brick still brick), shifted only toward the new light.
- **Reflections** in water and windows updated, or deliberately left (a window still reflecting the old grey sky
  under a blue one is a common giveaway).

## Enhance instead of replace

    python3 sky_check.py enhance ~/.photocraft-skill/work/<photo>/sky [--contrast 1.35] [--grad 0.5]
    python3 import_layers.py …/sky/layers_enhance.json

Two Curves layers in Luminosity mode, masked to the sky only, so nothing that sticks up into it darkens (the
advantage over a glass graduated filter). "Sky contrast" spreads the sky's own tones (2nd-98th percentile) around
their median by `--contrast`. "Sky grad" darkens by `--grad` stops at the top of the frame, fading to nothing at
the horizon. `preview_enhance.png` is exact (imports matched it to 0.17 levels). Keep it subtle: clouds with
shape, not drama.

## Reflections, and moving the sky later

- **Reflection in water:** duplicate the Sky layer, `edit.transform.flipVertical`, move it below the waterline with
  `edit.transform {"matrix": [1, 0, 0, 1, 0, dy]}` (x' = a x + c y + e, y' = b x + d y + f; it moves the active
  layer), mask it to the water (`select.lasso` + `layer.layerMask.revealSelection`), and darken it with a Curves
  layer clipped to it until it is as much darker than the sky as the old reflection was (reflections are darker
  than what they reflect). Lower its opacity so the water's own ripples show through.
- **Moving or scaling the sky:** select the Sky layer and `edit.transform` with a matrix. Its mask is linked and
  moves with it (tested), which would break the skyline: unlink it first with
  `layer.layerMask.linked {"layer": <sky id>, "linked": false}`. Or rerun `sky_check.py plan` with other
  `--sky-x/--sky-y/--zoom` and import again.

## Save

- Layered: `app.save {"path": "…/photo-sky.psd"}` (new name, next to the original).
- JPEG: `$PC cli convert photo-sky.psd photo-sky.jpg --quality 95` (keeps the colour profile; `app.save` ignores
  quality).

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Old grey sky left as a patch | `select.sky` missed it and an edge or texture cuts it off from the rest | `area.json` `sky` polygon over it, `--reuse` |
| Light grey blotches between branches | Canopy not reached (sky through trees far from the coarse sky) | `--trees` if branches fill the frame, else a `sky` polygon or larger `--canopy` |
| Warning "looks like sky but stays foreground" | Same | Check viz.png; `--trees` if it's sky through branches |
| New sky inside a pale wall, a white van or snow | Same colour as the sky and no edge between | `keep` polygon over it |
| Magenta in viz.png along a skyline | Foreground the sky's colour; the coarse mask decided | Check that stretch at 3x; `keep` or `sky` polygon if wrong |
| An aerial or wire gone | Fainter than 6x the sky's noise | Accept (often wanted for real estate) or `keep` polygon |
| Speck of old sky in a 2-4 px slit (between chimney pots, balusters) | Mixed pixels taken for foreground | Usually invisible at 1x; a few px `sky` polygon |
| Orange/red tiles on stonework or tendrils | Light material against a darker new sky, not a halo | Confirm at 3x; nothing to fix |
| A real pale line along solid roofs | Old sky in the edge pixels | `--shift 1`: the sky takes 1 px of the edge. It also deletes thin twigs, tendrils and aerials (tested), so only for solid skylines |
| Brick or foliage turned bluish | `--harmonize` too high for an off-colour sky photo | `--harmonize 0.25`, or white-balance the sky photo first |
| Sky looks pasted, dark at the horizon | Sky shot upward, no horizon part | `--sky-y` on a taller sky, or `--haze 0.3` |
| Dark object in the new sky | A pole or tree in the part of the sky photo used | `--sky-rect` |
| Sky softer than the photo | Enlarged more than 1.5x | A larger sky photo, or less `--zoom` |
| Land edge glows, branches look hazy | Light wrap too strong or too wide for thin structure | `--wrap 0.2`, `--wrap-width 4`; or lower the Light wrap layer's opacity |
| Land edge stays dark and cut-out against a bright new sky | No light wrap | `--wrap 0.3` |
| Import "MISMATCH" with a bias of a few levels, "no builtin twin" warning | An embedded profile import_layers can't match to a builtin | `edit.convertToProfile` to the nearest builtin, import again |
