# Old photo restoration: repaired, not reinvented

Read this before restoring a scanned print or negative: dust, specks, hairs, scratches, cracks, flaking emulsion,
tears, missing corners, fading and colour casts. It is the full version of the recipe in SKILL.md: how professional
restorers work, and how to do the same in PhotoCraft with `find_defects.py` and `restore_tone.py`.

## Contents
- What separates a professional restoration from a cheap one
- The layer stack you're building
- Step 1: set up and map the photo
- Step 2: dust, specks, hairs and scratches (masked medians)
- Step 3: bigger damage: flakes, streaks, tears, missing pieces
- Step 4: faces, last and minimal
- Step 5: tone and colour (fading, dye casts)
- Step 6: finishing
- Step 7: check like a restorer
- Step 8: save
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
  blends in whatever colours lie under its edge), or one stroke along a scratch, never a row of small dabs. Missing
  pieces of background or clothing: Content-Aware Fill. Faces: by hand, minimally.
- **Remove the damage, keep the photograph.** Grain, soft focus, paper texture, the vignetting and the print's tone
  are part of the original. Real detail that looks like dust (catchlights, a lit button, white lettering, lace) stays.
- **Never invent a face.** Content-Aware Fill and other synthesis fill a missing cheek or eye with features from
  elsewhere: another person's. Rebuild only from the same face (the other eye, mirrored) or leave the loss visible.
- **Fading is per channel.** The three dyes of a colour print fade at different rates: in the dark the cyan dye
  usually goes first, leaving the print red-magenta; on display magenta goes, leaving it blue-green (Graphics Atlas).
  Each channel needs its own black and white point, then neutral midtones. A sepia or toned black-and-white print
  keeps its tone unless the user wants it neutral.
- **Order: big to small, structure to detail.** Crop and straighten, tone, colour, dust and scratches, larger damage,
  faces, finishing. In layers the tone and colour adjustments sit on top of every repair, so the repairs get the same
  tone, and the order you build them in doesn't matter as long as you judge the repairs with the tone visible.

## The layer stack you're building

    Tone (faded dyes)          Curves: per-channel black/white points, neutral midtones   (restore_tone.py)
    Faces                      empty layer, a few hand-placed heals (sample: current and below)
    Fill <n>                   Content-Aware Fill of a missing piece (output: new layer)
    Heal                       empty layer with the Remove dabs, loops and strokes from heal.json
    Dust & scratches           group (find_defects.py + import_layers.py)
      Coarse (median 5, …)     Stamp Visible + Median 5 + matched grain, mask = coarse*.png
      Fine (median 2, …)       Stamp Visible + Median 2 + matched grain, mask = fine*.png
    Background                 the scan, untouched

## Step 1: set up and map the photo

Work in a folder under the home directory (`~/.photocraft-skill/work/<photo>/`): the app only opens files under its
read root.

1. Open the scan. A **Grayscale** document (most black-and-white scans) works for every repair: `import_layers.py`
   makes its PNGs grey and loads masks from the gray channel. Convert it with `image.mode.rgb {}` only when the
   result will be toned or colourised, or when `restore_tone.py` should balance colour channels.
2. Crop to the picture and straighten it (`image.crop` with `angle`; `references/straighten.md` measures the angle).
   Keep the border on a copy if the user wants the object as it is.
3. Crop the region to work on at full resolution, at most ~2.5 MP per run (`find_defects.py` is pure Python: about
   3 min for 2.5 MP on a busy machine); a whole small print in one go, a big scan in a few regions:

       $PC cli run scan.tif --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' --out crop.png

4. Write `area.json` with `grid.py crop.png X Y grid.png --step 50`, full-image coordinates:

       {"exclude": [[x0, y0, x1, y1], …], "faces": [[[x, y], …], …], "area": [[x, y], …]}

   `exclude`: everything real that looks like a defect: **eyes** (catchlights), teeth, white lettering and captions,
   jewellery, lit buttons, lace, stars in a night sky. `faces`: polygons round each face big enough to matter; inside
   them only clear specks and long scratches are touched. `area` (optional) limits the work to a region. Leave out
   the scan's border and mount.

## Step 2: dust, specks, hairs and scratches (masked medians)

    $PC exec layer.new.layer '{"name": "Heal"}'                    # empty, above the scan; note its id
    python3 find_defects.py crop.png X Y out --area area.json --layer <Heal id>
    python3 import_layers.py out/layers.json --above <Background id>   # lands between the scan and Heal; "verify": "ok"

The script compares the scan with Median 2, 5, 12 and 24 copies made by the CLI. A defect has to stand out from the
texture around it (`--texture` x the local median of the residual, so pores, hair and fabric stay, and a cluster of
specks can't hide one another) and from `--min-contrast` levels. Matched filters catch what is faint in heavy grain:
3x3 and 7x7 means of the residual (a speck or blob survives them, grain doesn't) and its mean along 11 and 25 px
lines at 12 angles (a hairline or a long transport scratch adds up along its length; Motion Blur computes those
means). Each defect then goes where its repair works, measured on its own pixels: the fine layer if Median 2 takes it
away, the coarse layer if Median 5 does, otherwise the heal plan (Step 3).

- **Context gate.** A defect is foreign to its surroundings; real detail belongs to them. Each candidate's contrast
  against the clean ring 2..6 px around it, over that ring's spread, must reach `--context` (default 6) for the
  coarse layer or healing, half that for the fine layer; below it the candidate is kept. Without it, on a sharp glass
  negative with no area file, the coarse median and Remove erased a cap's stripes and smeared a nose and mouth;
  with it they stayed. On a grainy scan real specks score 3–6: if the overlay shows clear specks kept in smooth
  areas, run again with `--context 4` (or 3). Never lower it on a sharp scan with patterned clothing or faces.
- **Read `overlay.png` (2x) first.** Green = fine layer, yellow = coarse, red rings = healing, magenta boxes = large
  damage left for you, blue = candidates kept as real detail (failed the context gate, on an edge, or a short line in a
  face). Rings or outlines on catchlights, teeth, lettering or lace: add an exclusion box and run again.
- Each layer is Stamp Visible + Median + Add Noise (Gaussian, monochromatic), masked to its defects. The noise
  replaces exactly what the median took away: the residual's spread in the clean pixels around those defects (Add
  Noise amount 1 = 0.643 levels of standard deviation). When the grain around the defects differs more than 1.8x
  (a negative's highlights against its shadows), a scale gets two layers, each with its own grain; the names say it.
- Build them while only the scan is visible (before the tone layer, or with it hidden): a stamp merges everything.
- `import_layers.py` renders the result and compares a 640 px window with `preview.png`, which has no grain.
  layers.json carries a `tolerance` for the grain the layers add (0.5 plus the noise expected under the masks in
  that window), so a heavily damaged print verifies too; `--no-grain` shows the exact match.
- Faint hairlines left in heavy grain: `--texture 4 --line-threshold 4` (check the overlay doesn't start marking grain
  or texture), or `--add X,Y,D` for single ones.

## Step 3: bigger damage: flakes, streaks, tears, missing pieces

1. **Heal plan.** `heal.json` uses PhotoCraft's Remove tool (`paint.remove`, content-aware, `sampleAllLayers`): one
   dab a little bigger than each compact defect and its halo, a closed loop round each blob bigger than `--heal-max`
   (Remove fills what a loop encloses), and one stroke along each thick scratch. Fragments of one defect are planned
   together, since a dab whose edge lands on the next fragment blends it back in:

       $PC exec layer.select '{"layer": <Heal id>}'
       $PC script out/heal.json

   Remove writes only to the empty Heal layer. In testing it beat the alternatives on flakes, blobs and a double
   scratch across a dark hat: a Healing Brush stroke smeared the scratch grey (PhotoCraft heals a stroke dab by dab,
   each blending in the scratch at its edge), a Clone Stamp copied a neighbouring line, Spot Healing left one line.
   Inside `faces` the plan always uses Healing Brush dabs copied from the same face's clean skin nearby (Remove could
   bring texture from elsewhere). `--heal-tool healing` does that everywhere, for a texture whose own pattern must
   continue (woven cloth, brickwork); look at the result, it smears where a defect is wide.
2. **Large damage** (magenta boxes, emulsion lost in patches, a corner torn off): on a background or clothing,
   select it a few px larger and fill it on its own layer:

       select.lasso {"points": [[x, y], …]}   then   select.modify.expand {"radius": 4}
       edit.contentAwareFill {"sampling": "auto", "output": "new"}   then   select.deselect, layer.setProps (name it)

   Content-Aware Fill continues texture and structure well, and on a face it invents one: in testing it filled a
   torn corner across a girl's cheek with a second eye and mouth. Never use it on faces.
3. **Tears and cracks** across detail: a Remove stroke along them (`paint.remove` with the points of the tear,
   `"closeLoops": false`), or Clone Stamp (`paint.cloneStamp`, hardness 60–80, `offset` along the edge) where the tear
   crosses an edge, since content-aware tools blur edges. Rebuild the edge line first, then the texture beside it.
4. Re-run `find_defects.py` on a fresh render of the area: it should find almost nothing but the blue ones.

## Step 4: faces, last and minimal

Faces were excluded or treated strictly above. Now look at each one at 200 %. Heal only what is clearly damage
(a speck on a cheek, a scratch over the nose) with small dabs on an empty "Faces" layer, the size of the speck plus a
few px. Keep pores, moles, wrinkles, the softness of the lens. A missing eye or mouth can only come from the same
face: copy the other eye (`select.lasso` → `layer.new.layerViaCopy`), flip it (`edit.transform.flipHorizontal`),
move it into place (`layer.translate`), mask its edge. Tell the user what was rebuilt; if they'd rather keep the
loss, keep it.

## Step 5: tone and colour (fading, dye casts)

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

## Step 6: finishing

- **Grain:** look at the repairs at 100 % beside untouched grain. Each median layer carries one grain value (its name
  says which); a repair that looks smoother or noisier than the grain beside it sits where the grain differs from the
  layer's average: raise or lower that layer's `addNoise` amount in layers.json, delete the group, import again.
- **Sharpening:** old photos are soft, and sharpening them sharpens grain and leftover damage. If at all, a Stamp
  Visible at the top with `filter.sharpen.smartSharpen {"amount": 40..60, "radius": 0.8..1.2, "reduceNoise": 20}`.
- **Colourisation** (only on request): Color-blend layers (`layer.new.layer` + `layer.setProps {"blend": "Color"}`),
  one per material, painted or masked from selections, in muted, era-plausible colours; skin first, checked on the
  vectorscope. Say it is a colourisation, not the original colours.

## Step 7: check like a restorer

- Before/after of the whole photo at fit-to-screen and the worked areas at 100 % and 200 %.
- Re-run `find_defects.py` on a render: what's left should be blue (kept detail) or tiny.
- Nothing outside the defects changed: diff the render against the scan; outside the masks, heals and fills it must
  be identical (on a dusty negative the median layers cover about 3 % of the pixels, defects plus a 1 px margin).
- Grain continuous over every repair; no smooth patches, no repeated texture from one healing source.
- Faces: same person, same expression, nothing invented; catchlights still there.
- Tone (tone.json `after`): no new clipping (`clippedPct` near 0), p1 and p99 inside 5..250, skin at 115–130°.

## Step 8: save

- Layered: `app.save {"path": "…/photo-restored.psd"}` next to the scan, never over it.
- Deliverable: `$PC cli convert photo-restored.psd photo-restored.jpg --quality 95` (or `.tif` for an archive).
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
| A blob left with a ring round it | Only its rim was found (a median sees a blob up to ~1.4x its radius) | Fixed by the Median 12/24 passes and hole filling; else `--add X,Y,D` |
| Smooth or noisy streak where a scratch was | The layer's grain value doesn't fit that area | Change that layer's `addNoise` amount in layers.json and re-import, or heal the streak |
| A missing piece filled with a face | Content-Aware Fill copies faces from elsewhere | Never on faces; rebuild from the same face or leave it |
| restore_tone turns a coloured highlight white | No neutral at the light end | `--white-ref` on a real white, `--neutral X,Y`, or `--keep-tone` |
| restore_tone changes almost nothing | The scan already spans 0–255 (`ends`) | Colour balance instead: neutral point, `--skin-line`, colour workflow |
| Sepia print turned grey | Per-channel end points neutralise a tone | `--keep-tone` |
| "verify" ~0.3 with `--lift` | Two curves (per channel, then composite) round twice | Expected; below 0.5 is a match |
