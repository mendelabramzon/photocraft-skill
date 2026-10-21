# Old photo restoration: repaired, not reinvented

Read this before restoring a scanned print or negative: dust, specks, hairs, scratches, cracks, flaking emulsion,
tears, missing corners, stains, fading and colour casts. It is the full version of the recipe in SKILL.md: how
professional restorers work, and how to do the same in PhotoCraft with `find_defects.py` and `restore_tone.py`.

## Contents
- What separates a professional restoration from a cheap one
- The layer stack you're building
- Step 1: set up and map the photo
- Step 2: stains on a black-and-white or toned print (the cleanest channel)
- Step 3: dust, specks, hairs and scratches (masked medians)
- Step 4: bigger damage: flakes, streaks, dense flaking and crazing, tears, missing pieces
- Step 5: faces, last and minimal
- Step 6: tone and colour (fading, dye casts)
- Step 7: finishing
- Step 8: check like a restorer
- Step 9: save
- Tuning and false hits

## What separates a professional restoration from a cheap one

The points restoration guides agree on (Eismann, Palmer & Dunbar's *Photoshop Restoration & Retouching*; Adobe's
Dust & Scratches help; archive digitisation guidelines; the Image Permanence Institute's Graphics Atlas):

- **The scan stays untouched.** Every repair goes on its own layer above it, so any of it can be undone, redone or
  toned down. Scan prints at 600 ppi or more (small prints 800+), 16-bit if the scanner allows, whole print with its
  border; the border shows how the paper aged.
- **Never blur or Dust & Scratches the whole photo.** Run globally, it removes the dust and also the grain, the
  eyelashes and the texture of hair and cloth, so the photo looks melted. Professionals apply it only where the defects
  are (a selection, the History Brush, or a mask), with the smallest radius that removes them and the highest
  threshold that still does. `find_defects.py` makes exactly that mask.
- **Repairs carry the grain.** A smooth patch in a grainy photo reads as a smudge at 100 %. Median repairs get grain
  matched to the photo's; healing and fills copy real grain.
- **The right tool for the size.** Specks and hairlines: a median through a mask. A defect thicker than a median can
  take: one Remove or Healing Brush dab a little bigger than the defect, with its edge on clean surroundings (healing
  blends in whatever colours lie under its edge), or one stroke along a scratch, never a row of small dabs. Dense
  flaking and crazing: Dust & Scratches and Clone Stamp in Darken through a mask of the flakes, so only they change.
  Bigger losses of background or clothing: a Remove loop; Content-Aware Fill for a piece too big for one. Faces: by
  hand, minimally.
- **Remove the damage, keep the photograph.** Grain, soft focus, paper texture, the vignetting and the print's tone
  are part of the original. Real detail that looks like dust (catchlights, a lit button, white lettering, lace) stays.
- **Never invent a face.** Content-Aware Fill and other synthesis fill a missing cheek or eye with features from
  elsewhere: another person's. Rebuild only from the same face (the other eye, mirrored) or leave the loss visible.
- **Fading is per channel.** The three dyes of a colour print fade at different rates: in the dark the cyan dye
  usually goes first, leaving the print red-magenta; on display magenta goes, leaving it blue-green (Graphics Atlas).
  Each channel needs its own black and white point, then neutral midtones. A sepia or toned black-and-white print
  keeps its tone unless the user wants it neutral.
- **Stains on a one-tone print: keep the channel they hide in.** Foxing, water and glue stains and yellowed patches are
  dyes in the paper that absorb blue far more than red. Restorers compare the red, green and blue channels and keep the
  one where the stain is weakest and the detail best (Adobe Community restorers; Lynda's damaged black-and-white
  course), before any spotting, then give a toned print its tone back.
- **Order: big to small, structure to detail.** Crop and straighten, the channel step for a stained black-and-white
  print, dust and scratches, larger damage, faces, then per-channel black and white points and casts, light noise
  reduction that keeps the grain, light sharpening. In layers the channel and tone adjustments sit on top of every
  repair, so the repairs get the same treatment, and the order you build them in doesn't matter as long as you judge
  the repairs with those layers visible.

## The layer stack you're building

    Print tone                 Gradient Map of the clean print's own colours, Color blend (restore_tone.py --retone)
    Tone (faded dyes)          Curves: per-channel black/white points, neutral midtones   (restore_tone.py)
    Channel (red: …)           Channel Mixer, monochrome: the least stained channel     (restore_tone.py --channel)
    Faces                      empty layer, a few hand-placed heals (sample: current and below)
    Heal                       empty layer with the Remove dabs, loops and strokes from heal.json
    Dust & scratches (…)       a group per region (find_defects.py + import_layers.py)
      Clone light, Darken      empty, masked to the dense damage: Clone Stamp from clean texture  (--dense)
      Dense light (…, Darken)  Stamp Visible + Dust & Scratches 4/8, mask = dense_light.png     (--dense)
      Coarse (median 5, …)     Stamp Visible + Median 5 + matched grain, mask = coarse*.png
      Fine (median 2, …)       Stamp Visible + Median 2 + matched grain, mask = fine*.png
    Background                 the scan, untouched

## Step 1: set up and map the photo

Work in a folder under the home directory (`~/.photocraft-skill/work/<photo>/`): the app only opens files under its
read root.

1. Open the scan. A **Grayscale** document (most black-and-white scans) works for every repair: `import_layers.py`
   makes its PNGs grey and loads masks from the gray channel. Convert it with `image.mode.rgb {}` only when the
   result will be toned or colourised, or when `restore_tone.py` should balance colour channels.
2. Crop to the picture and straighten it (`image.crop` with `angle`). A print is a rectangle: level it by its own
   edge, not the scene (the camera may have tilted the scene): `straighten.py scan.tif out --mode horizon --level
   X1,Y1,X2,Y2` with two points on the print's top or bottom edge (the mount's, if the print sits square on it), or
   `--mode rotate --plumb X1,Y1,X2,Y2` on a side (`references/straighten.md`). Keep the border on a copy if the user
   wants the object as it is.
3. Crop the region to work on at full resolution, at most about 2 MP per run. `find_defects.py` is pure Python: a
   2413 x 880 band (2.1 MP) took 150 s and 5 GB of memory, so on a 16 GB machine run regions one at a time. A
   whole small print goes in one run, a big scan in bands that overlap by about 30 px:

       $PC cli run scan.tif --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' --out crop.png

   Give each band `--own X0,Y0,X1,Y1`, its share of the photo with the overlaps split down the middle, so a defect in
   an overlap is planned once. Each band's group is named after the part it owns ("Dust & scratches
   (0,950-2413,1800)", or `--group NAME`), and its stamp layers are cleared outside its crop: one band's import added
   33 MB to the PSD, against 122 MB with full-canvas stamps (13 of those had made a 385 MB file).

4. Write `area.json` with `grid.py crop.png X Y grid.png --step 50`, full-image coordinates:

       {"exclude": [[x0, y0, x1, y1], …], "faces": [[[x, y], …], …], "area": [[x, y], …]}

   `exclude`: everything real that looks like a defect: **eyes** (catchlights), teeth, white lettering and captions,
   jewellery, lit buttons, lace, plaid and other patterned cloth, sky through leaves, stars in a night sky.
   `faces`: polygons round each face big enough to matter; inside them only clear specks, long scratches and crisp
   flakes far lighter than everything round them are touched. `area` (optional) limits the work to a region. Leave out
   the scan's border and mount.

## Step 2: stains on a black-and-white or toned print (the cleanest channel)

Only for a print that should be one tone (black and white, sepia, a tintype) and shows yellow, brown or other
coloured stains. Scan it in colour: a Grayscale scan has the stains baked into its one channel.

    python3 restore_tone.py scan.tif chan --area area_tone.json --channel auto --channel-only [--protect x0,y0,x1,y1]
    python3 import_layers.py chan/layers.json                      # on top of the stack; "verify": "ok"

A stain multiplies each channel's light by its own transmission, so in linear light the ratios between channels
carry the stain and none of the picture. From them the script measures how strongly the stains absorb in each
channel (`stains.absorbance`: 0 for the cleanest channel, 1 for the most stained) and writes a monochrome Channel
Mixer layer with the cleanest channel, or an even mix of channels within 0.1 of it (less grain). On synthetic stains
with known absorbance on real scans the estimate came within 0.025 of the truth: yellow-brown stains (red 0, green
0.24, blue 1) and a magenta mould (0, 1, 0.07, so red and blue mixed). The stain left over in the kept channel, as a
share of the tonal range:

| Stain | Red | Green | Blue | Plain luminance | The script's pick |
|---|---|---|---|---|---|
| Yellow-brown on a black & white scan | 1.3 % | 4.3 % | 12.6 % | 4.3 % | red |
| Yellow-brown on a sepia print | 1.4 % | 4.4 % | 12.4 % | 4.4 % | red |
| Magenta mould | 2.9 % | 10.3 % | 3.5 % | 7.3 % | red + blue: 3.2 % |

Read `channels.png`: the photo, its red, green and blue channels, the mix, and the stains found (magenta). Anything
coloured that isn't a stain comes up magenta too and goes pale or dark in the kept channel: a pasted-in print, hand
colouring, a coloured mount. Keep the layers off it with `--protect x0,y0,x1,y1` (or an area.json of polygons): it is
left out of the measurements, and `protect.png`, black there with a 4 px feathered edge, becomes the mask of every
layer the script writes. On the test family print a pasted-in sepia portrait kept its colour while the rest went to
the kept channel, and the import verified (mean difference 0.0; 0.13 with the verify window across a protected
edge). On the bench a sepia family print had 9 % stained, a glass negative 1.3 % (both kept red), a tintype's tarnish
absorbed red and kept green. Under 0.3 % stained, it says so and mixes all three channels evenly.

**The Channel layer is for looking, not for working under.** A stamp layer copies everything visible and Remove's
`sampleAllLayers` samples it, so with the Channel layer showing, every repair of Steps 3–4 comes out grey: invisible
through it, but grey patches in the colour render that `--retone` later measures the print's tone from. So hide it
(`layer.setProps {"layer": <id>, "visible": false}`) before you export the crops `find_defects.py` reads (its
preview must match what the stamps see) and before every import and plan; show it again to judge the repairs.
At Step 6 either keep it and measure the tone on the grey render as usual, or give the print its tone back:
with it hidden, export, `restore_tone.py repaired.png tone --channel auto --retone [--protect …]`, import, and
delete the early Channel layer (the new one replaces it). `--retone` adds "Print tone", a Gradient Map in Color
blend whose stops are the clean print's own median colour at each grey level: the stains go and the sepia stays
(`--channel-only --retone` writes the Channel layer and Print tone, without a Tone curve). The end points are
measured on the kept channel itself. On a synthetic stained sepia print the stained areas came out within ΔE 1.0 on
average (2.4 at the 95th percentile) of the clean print taken through the same layers; the tone step alone
(`--keep-tone`) left them at ΔE 8.1 (21). The paper of a toned print is cream, so re-toned at the usual white level
its red reached 255 on 4.4 % of the picture; the script lowers the white level until the paper's own colour fits
(248 to 244 there, then no channel reached 255) and says so. In the deepest shadows a toned black sits at the edge
of the colour space (blue at 0 on 2.2 % of that print, luminosity kept, a dark brown-black as on the print):
tone.json's `clipped` gives each channel's share at 0 and at 255 (`"blue": [2.2, 0.0]` there; on the test family
print, re-toned, blue at 0 on 1.5 %), and `clippedPct` the share with any channel at either end.

## Step 3: dust, specks, hairs and scratches (masked medians)

    python3 find_defects.py crop.png X Y out --area area.json [--own X0,Y0,X1,Y1]
    python3 import_layers.py out/layers.json --above <Background id>   # just above the scan; "verify": "ok"
    $PC exec layer.new.layer '{"name": "Heal"}'                        # once, above the groups (Step 4 paints on it)

Headless, `import_layers.py out/layers.json --file work.psd --out work.psd`. With the Channel or Tone layer in the
document, hide it first (Step 2): a stamp merges everything visible.

The script compares the scan with Median 2, 5, 12 and 24 copies made by the CLI. A defect has to stand out from the
texture around it (`--texture` x the local median of the residual, so pores, hair and fabric stay, and a cluster of
specks can't hide one another) and from `--min-contrast` levels. Matched filters catch what is faint in heavy grain:
3x3 and 7x7 means of the residual (a speck or blob survives them, grain doesn't) and its mean along 11 and 25 px
lines at 12 angles (a hairline or a long transport scratch adds up along its length; Motion Blur computes those
means). Each defect then goes where its repair works, measured on its own pixels: the fine layer if Median 2 takes it
away, the coarse layer if Median 5 does, otherwise the heal plan (Step 4).

- **Context gate.** A defect is foreign to its surroundings; real detail belongs to them. Each candidate's contrast
  against the clean ring 2..6 px around it, over that ring's spread, must reach `--context` (default 6) for the
  coarse layer or healing, half that for the fine layer; below it the candidate is kept. Without it, on a sharp glass
  negative with no area file, the coarse median and Remove erased a cap's stripes and smeared a nose and mouth;
  with it they stayed. On a grainy scan real specks score 3–6: if the overlay shows clear specks kept in smooth
  areas, run again with `--context 4` (or 3). Never lower it on a sharp scan with patterned clothing or faces.
- **Read `overlay.png` (2x) first.** Green = fine layer, yellow = coarse, red rings = healing, magenta boxes = large
  damage left for you, blue = candidates kept as real detail (failed the context gate, on an edge, or a short line in a
  face), orange = dense damage (boxes: its zones; tint: its mask, Step 4). Rings or outlines on catchlights, teeth,
  lettering or lace: add an exclusion box and run again.
- On a face, a crisp light flake next to an eyebrow, the hairline or a beard has both in its ring, which spreads the
  ring and failed the gate (context 2.7–4.9 for four flakes on the test print's man); one on or within 24 px of a
  face that stands 4x `--min-contrast` beyond 90 % of its ring is planned anyway (all four healed cleanly). Away
  from faces that rule would take sky through leaves, so it stays off there.
- Each layer is Stamp Visible + Median + Add Noise (Gaussian, monochromatic), masked to its defects. The noise
  replaces exactly what the median took away: the residual's spread in the clean pixels around those defects (Add
  Noise amount 1 = 0.643 levels of standard deviation). When the grain around the defects differs more than 1.8x
  (a negative's highlights against its shadows), a scale gets two layers, each with its own grain; the names say it.
- `import_layers.py` renders the result and compares a 640 px window with `preview.png`, which has no grain.
  layers.json carries a `tolerance` for the grain the layers add (0.5 plus the noise expected under the masks in
  that window), so a heavily damaged print verifies too; `--no-grain` shows the exact match.
- Faint hairlines left in heavy grain: `--texture 4 --line-threshold 4` (check the overlay doesn't start marking grain
  or texture), or `--add X,Y,D` for single ones.

## Step 4: bigger damage: flakes, streaks, dense flaking and crazing, tears, missing pieces

1. **Heal plan.** `heal.json` uses PhotoCraft's Remove tool (`paint.remove`, content-aware, `sampleAllLayers`): one
   dab a little bigger than each compact defect and its halo, a closed loop round each blob bigger than `--heal-max`
   (Remove fills what a loop encloses), and one stroke along each thick scratch. Fragments of one defect are planned
   together, since a dab whose edge lands on the next fragment blends it back in:

       $PC script out/heal.json --layer-name Heal        # headless: --open work.psd --save work.psd too

   `--layer-name` puts the Heal layer's id into every step (ids change whenever a file is reopened), and heal.json
   starts by selecting that layer: PhotoCraft paints only on an active pixel layer, and refuses while a group or
   the Channel layer is active.

   Remove writes only to the empty Heal layer. In testing it beat the alternatives on flakes, blobs and a double
   scratch across a dark hat: a Healing Brush stroke smeared the scratch grey (PhotoCraft heals a stroke dab by dab,
   each blending in the scratch at its edge), a Clone Stamp copied a neighbouring line, Spot Healing left one line.
   Inside `faces` the plan always uses Healing Brush dabs copied from the same face's clean skin nearby (Remove could
   bring texture from elsewhere). `--heal-tool healing` does that everywhere, for a texture whose own pattern must
   continue (woven cloth, brickwork); look at the result, it smears where a defect is wide.
2. **Large damage** (magenta boxes, a flake or streak too big for a dab): a Remove loop round it on the Heal layer,
   a few px outside the damage, the first point repeated at the end:

       paint.remove {"points": [[x, y], …, [x0, y0]], "size": 10, "hardness": 80, "closeLoops": true,
                     "sampleAllLayers": true, "target": "pixels", "layer": <Heal id>}

   On the test print a 100 x 35 px flake on dark, crazed cloth filled with the cloth's texture (spread 24.6 levels
   inside, 36.6 around). Content-Aware Fill of the same selection gave a flat, grainless dark patch (spread 9.2), on
   the scan as on a Stamp Visible; and it samples only the active layer, so on the empty Heal layer it reports
   `"filled"` and changes nothing. Keep it for a missing piece too big for a loop (a corner torn off): select it a
   few px larger (`select.lasso`, `select.modify.expand {"radius": 4}`), make the scan or a Stamp Visible the active
   layer, `edit.contentAwareFill {"sampling": "auto", "output": "new"}`, then give the new layer the photo's grain
   (`filter.noise.addNoise`, Gaussian, monochromatic, amount = grain / 0.643) and look at it at 100 %. On a face it
   invents one: in testing it filled a torn corner across a girl's cheek with a second eye and mouth. Never use it
   on faces.
3. **Tears and cracks** across detail: a Remove stroke along them (`paint.remove` with the points of the tear,
   `"closeLoops": false`), or Clone Stamp (`paint.cloneStamp`, hardness 60–80, `offset` along the edge) where the tear
   crosses an edge, since content-aware tools blur edges. Rebuild the edge line first, then the texture beside it.
4. **Dense flaking and crazing** (orange in the overlay, `dense` in its JSON). Where flakes or cracks cover much of an
   area, the medians fail (a median of a patch that is mostly flakes is a flake), the context gate can't judge (the
   "clean ring" is more flakes), and Remove loops leave grey smears. `find_defects.py` finds them with a top-hat (the
   photo minus its opening: light structures narrower than 11 px, at any density) and lists the zones with their
   damaged share; without `--dense` that is all, and their defects are planned as usual. First check every zone: real
   light texture is in its mask too (the orange tint). On the test print a plaid shawl's light threads were; on a
   school photo sky through leaves and a patterned tie made 13 zones. Exclude those in area.json and run again with
   `--dense`. The zones' defects then leave the median layers and heal.json, and the group gets two layers through
   `dense_light.png`:
   - "Dense light (Dust & Scratches 4/8, Darken)": Dust & Scratches, radius 4, threshold 8 (`--dense-ds R,T`; 0 for
     none), in Darken, so it only darkens what is lighter than the median around it. On a 2.1 MP band of the test
     print it took 57 % of the small flake pixels inside the mask (34 % over the whole band, with the medians); where
     flakes fill more than half of a 9 px window the median is a flake and soft grey blotches stay. On the plaid it
     beaded the stripes (9.4 % of the shawl's pixels moved more than 4 levels): that is what excluding is for.
   - "Clone light, Darken (…)": empty, the same mask and mode. Clone into it from clean texture of the same material:
     only flake pixels lighter than the source change, and nothing outside the mask. Each zone outside faces lists
     `cloneFrom`, an offset to clean ground of its tone and grain (`sourceDamaged`, `sourceToneDiff` say how clean and
     how close), and `--clone-plan` writes a serpentine Clone Stamp stroke over each zone (size 36, hardness 60, rows
     22 px apart, `sampleLayer` currentAndBelow) as dense_light.json:

         $PC script out/dense_light.json --layer-name "Clone light, Darken (0,950-2413,1800)"

     On the band it took the flake pixels in the mask from 55,160 to 8,158 (85 % gone) and cleared the dark dresses,
     but with the plaid and a light sleeve fold left in, it pasted dark cloth over their light threads. A restorer
     testing this by hand found the same: in Darken without the mask, cloning darkened clean cloth and doubled a fold.

   Faces in a zone (`"face": true`) get no clone source: Dust & Scratches through the mask (radius 4, threshold 8
   cleared face crazing in that test), then small heals for what's left (Step 5). Dense dark damage (mould spots,
   dirt) needs `--dense-polarity dark`, since hair and beards read as dense dark specks; its layers are the Lighten
   twins, through `dense_dark.png`.
5. Re-run `find_defects.py` on a fresh render of the area: it should find almost nothing but the blue ones.

## Step 5: faces, last and minimal

Faces were excluded or treated strictly above. Now look at each one at 200 %. Heal only what is clearly damage
(a speck on a cheek, a scratch over the nose) with small dabs on an empty "Faces" layer, the size of the speck plus a
few px. Keep pores, moles, wrinkles, the softness of the lens. A missing eye or mouth can only come from the same
face: copy the other eye (`select.lasso` → `layer.new.layerViaCopy`), flip it (`edit.transform.flipHorizontal`),
move it into place (`layer.translate`), mask its edge. Tell the user what was rebuilt; if they'd rather keep the
loss, keep it. Never change an expression (no smile added, no eyes opened, no frown softened): a restoration
repairs the photograph, not the person in it.

## Step 6: tone and colour (fading, dye casts)

Export the repaired state and measure it, so the import can check itself exactly:

    $PC export ~/.photocraft-skill/work/<photo>/repaired.png
    python3 restore_tone.py repaired.png tone --area area_tone.json [--keep-tone] [--lift 15]
    python3 import_layers.py tone/layers.json            # on top of everything; prints "verify": "ok"

- `area_tone.json` holds the picture without the border, mount, writing and big damage (`"area"`, `"exclude"`),
  and optionally `"skin"` polygons: their vectorscope angle is reported (skin of every complexion sits at 115–130°).
- Colour prints: each channel's black and white point goes on the picture's own darkest and lightest 0.1 % (to 6
  and 248: rich black, paper white with texture), then a middle point per channel makes the most neutral midtones
  neutral. This restored a synthetically faded wedding photo from 27.8 to 6–9 levels from the original (ΔE 19.6 → 3–4).
- The end points assume the picture's lightest and darkest things were white and black. A scene whose lightest
  thing is coloured (a yellow scarf) turns it white: give `--white-ref X,Y` / `--black-ref X,Y` on something that
  was white or black, or `--neutral X,Y` on a known grey (a white shirt in shade, a stone wall).
- Family photos with no neutral: `--skin-line` brings the mean skin back into the 115–130° band if it's outside, and
  leaves plausible skin alone.
- Toned black-and-white prints (sepia, selenium): `--keep-tone` stretches all channels together, so the tone stays.
  Without it the print turns neutral grey; that's the user's choice, not a fix. `kind` in tone.json says what the
  script sees (monochrome, toned monochrome, colour).
- A print that is dark rather than faded: `--lift 10..25` raises the midtones (faces open up) with a composite middle
  point.
- `ends` near 0 and 255 in every channel: the scan was already auto-levelled, so there's no range to restore and the
  remaining cast is a colour balance problem (neutral points, skin, or the colour-correction workflow).
- Faded colour prints are also desaturated: add a Vibrance layer (+10..+30) on top by eye, after the verified import.
- Stained black-and-white or toned prints: `--channel auto` (Step 2) adds the Channel layer under the tone, and
  `--retone` the print's own tone on top. Export with the early Channel layer hidden, import, then delete it.
  `--protect` keeps all three layers off an inset or hand colouring.
- **The Divide trick** (sample a known neutral, a white collar, into a Solid Color layer in Divide mode) is a pure
  per-channel gain: it fixes a cast that multiplies every tone, such as yellowed paper or varnish, and nothing else.
  Make the fill the sampled colour scaled so its brightest channel is 255 (`{"fill": "#fffbe9", "blend": "Divide"}`
  in layers.json; PhotoCraft renders it exactly as predicted): on a synthetically yellowed print it took ΔE 4.3 to
  1.05, as good as the curves here (1.12); the sample itself as the fill turns it pure white and brightens the whole
  print (ΔE 2.6). Faded dyes lift and tint the shadows, which a gain can't reach: ΔE 21.4 went only to 18.9, where the
  per-channel curves reached 4.8 (4.6 with `--white-ref`).

## Step 7: finishing

- **Grain:** look at the repairs at 100 % beside untouched grain. Each median layer carries one grain value (its name
  says which); a repair that looks smoother or noisier than the grain beside it sits where the grain differs from the
  layer's average: raise or lower that layer's `addNoise` amount in layers.json, delete the group, import again.
- **Specks done by hand** (left blue by `find_defects.py`, or a patch of lint): Dust & Scratches on a stamp, tuned the
  way Damien Symonds teaches (radius up from 1 until the specks go, threshold up from 0 until they come back, then a
  step down), in Lighten for dark specks or Darken for light ones, masked to the specks, with grain added:
  `object-removal.md`, "Many small specks", has the exact layer and the numbers.
- **Sharpening:** old photos are soft, and sharpening them sharpens grain and leftover damage. If at all, a Stamp
  Visible at the top with `filter.sharpen.smartSharpen {"amount": 40..60, "radius": 0.8..1.2, "reduceNoise": 20}`.
- **Colourisation** (only on request): Color-blend layers (`layer.new.layer` + `layer.setProps {"blend": "Color"}`),
  one per material, painted or masked from selections, in muted, era-plausible colours; skin first, checked on the
  vectorscope. Say it is a colourisation, not the original colours.

## Step 8: check like a restorer

- Before/after of the whole photo at fit-to-screen and the worked areas at 100 % and 200 %.
- Re-run `find_defects.py` on a render: what's left should be blue (kept detail) or tiny.
- Nothing outside the defects changed: diff the render against the scan; outside the masks, heals and fills it must
  be identical (on a dusty negative the median layers cover about 3 % of the pixels, defects plus a 1 px margin).
- Grain continuous over every repair; no smooth patches, no repeated texture from one healing source
  (`qc.py repeats render.png out --before scan.png` lists texture that appears twice).
- Leftover dust: `compare.py scan.png render.png cmp.png --check solar` (or `negative`) shows what eyes miss.
- Stains (after Step 2): none left in `channels.png`'s kept channel; the toned result's paper the print's own colour.
- Faces: same person, same expression, nothing invented; catchlights still there.
- Tone (tone.json `after`): no new clipping (`clippedPct` near 0; `clipped` says which channel at which end, and a
  re-toned print's blue at 0 in the deepest shadows is its toned black), p1 and p99 inside 5..250, skin at 115–130°.

## Step 9: save

- Layered: `app.save {"path": "…/photo-restored.psd"}` next to the scan, never over it.
- Deliverables: `deliver.py photo-restored.psd out --preset archive --preset web` writes a full-size 16-bit TIFF, a
  copy of the layered file and a web JPEG (`references/deliver.md`); or `$PC cli convert photo-restored.psd
  photo-restored.jpg --quality 95`.
- Exports right after a save can come back stale; export again before judging a check.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Rings on catchlights, teeth, lettering, buttons, lace | Real detail as small and bright as dust | `exclude` boxes in area.json |
| Many green dots in wrinkles, pores or fabric | Texture as strong as the defects (a sharp modern-looking face) | `faces` polygons; `--texture 6` |
| Stripes, nostrils or a mouth line marked for repair on a sharp scan | Real dark detail as crisp as dirt | Keep `--context` at 6 or higher; `exclude` patterned areas; `faces` polygons |
| Clear specks left blue (kept) in a smooth grainy area | Grain lowers their context score to 3–6 | `--context 4` (or 3), after checking nothing real turns green |
| Faint hairlines left in heavy grain | They stand out less than 5x the local grain | `--texture 4 --line-threshold 4`, or `--add X,Y,D` |
| A hair or scratch along an edge left alone (blue) | On a strong edge a median would eat the edge | Heal or clone it by hand along the edge |
| Grey ghost, smear or a row of dark discs where a flake or scratch was | Healing dabs smaller than the defect, or a Healing Brush stroke (healed dab by dab) | The Remove plan (default); a dab bigger than the defect, one stroke along a scratch |
| Grey smears where Remove loops met a dense cluster of flakes | Most of the surroundings are flakes too | Step 4.4: check the orange zones, exclude real texture, `--dense` |
| Clear flakes or crazing kept (blue) or not found where they cover most of an area | The ring round each is more flakes; a median of them is a flake | The dense route, Step 4.4 |
| Orange zones on sky through leaves, lace, a plaid or a patterned tie | Light structures as small and dense as flaking | `exclude` them in area.json before `--dense` |
| Beaded stripes or dark blotches on a light pattern after `--dense` | A real pattern inside the dense mask | Exclude it and import again; erase that part of the Clone layer |
| Content-Aware Fill "filled" but nothing changed, or a flat dark patch | It samples only the active layer (the empty Heal layer); it lays no grain | A Remove loop (Step 4.2); else fill from the scan and add grain |
| A blob left with a ring round it | Only its rim was found (a median sees a blob up to ~1.4x its radius) | Fixed by the Median 12/24 passes and hole filling; else `--add X,Y,D` |
| Smooth or noisy streak where a scratch was | The layer's grain value doesn't fit that area | Change that layer's `addNoise` amount in layers.json and re-import, or heal the streak |
| A missing piece filled with a face | Content-Aware Fill copies faces from elsewhere | Never on faces; rebuild from the same face or leave it |
| restore_tone turns a coloured highlight white | No neutral at the light end | `--white-ref` on a real white, `--neutral X,Y`, or `--keep-tone` |
| restore_tone changes almost nothing | The scan already spans 0–255 (`ends`) | Colour balance instead: neutral point, `--skin-line`, colour workflow |
| Sepia print turned grey | Per-channel end points neutralise a tone, or the Channel layer is monochrome | `--keep-tone`; after the channel step, `--retone` |
| "verify" ~0.3 with `--lift` | Two curves (per channel, then composite) round twice | Expected; below 0.5 is a match |
| An inset print, hand colouring or a coloured mount goes pale or dark after the channel step | It's colour, not a stain (it shows magenta in `channels.png` too) | `restore_tone.py … --protect x0,y0,x1,y1` |
| Grey patches in the colour render, a re-toned print's tone a little off | Repairs made while the Channel layer showed | Hide it before every import and plan (Step 2); redo those layers |
| find_defects.py runs out of memory or takes many minutes | About 2.4 GB and 70 s per MP | Bands of about 2 MP, one at a time, `--own` for the overlaps |
| Stains still show in the kept channel | They absorb every channel alike (dark mould spots, some foxing) | They're damage, not colour: heal them in Steps 3–4 |
| The kept channel looks flat or grainy | A sepia print's red channel holds less contrast | Compare a mix in `channels.png` (`--channel 70,30,0`); the tone step stretches it |
| "this looks like a colour print" | Median colour of 10+ with the hues spread | The channel step makes it black and white; on a colour print use Step 6 alone |
