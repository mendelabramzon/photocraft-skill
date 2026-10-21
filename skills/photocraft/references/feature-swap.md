# Feature swap: open eyes, smiles and heads from another frame

Read this before borrowing anything from another photo: opening closed or blinking eyes with the eyes
from a frame where they're open, swapping a smile, replacing a head in a group shot. It is the full
version of the recipe in SKILL.md. The numbers and the user's reactions quoted below come from a real
eye swap (a squinting subject, eyes from a frame of the same shoot taken 8 minutes earlier) that took
five rounds of feedback before it read as natural.

## Contents
- What makes a swap invisible
- Find the donor
- The layer stack you're building
- Step 1: bring the donor in
- Step 2: align
- Step 3: match tone and colour
- Step 4: mask
- Step 5: check, then answer feedback
- Smiles, heads and other features
- What PhotoCraft can't do

## What makes a swap invisible

- **A real donor, not painting.** PhotoCraft has no generative fill and nothing that opens eyes by
  itself; eyes painted from scratch look fake at 100 %. Find another frame of the same person from the
  same shoot. Without one, tell the user what's possible instead of faking it (see the last section).
- **Close in light, angle and gaze.** The best donor is a burst neighbour seconds away. Otherwise pick
  the frame whose head angle, light direction, light colour and gaze are closest. The eyes must look
  where the face looks.
- **Align on landmarks that don't move.** The eye corners (canthi) are visible whether the eye is open
  or closed. Fit all four together with one rotation + scale + shift, so the eyes' spacing and tilt
  come from one real face. A few px of error is normal when the target squints, since squinting pulls
  the outer corners down.
- **Transplant the eye, not its surroundings.** The mask covers the opening with its lashes and lid
  margin and stops before the socket shading, the brow and the under-eye. A big soft blob brought the
  other frame's shading along, which read as dark rings. *User: "too much shades, looks unnatural".*
- **Cover what's underneath.** The target's closed lash line has to sit under the fully opaque part of
  the mask, out past both corners. A soft or faded edge there lets the old lash line show beside the
  new eye. *User: "right eye looks strange".*
- **Match exposure like exposure.** The donor is usually exposed and white-balanced differently, and
  may be in another colour profile (copying converts it). Scale the donor by the skin's ratio, as a
  change of exposure would, so lashes, iris and lid crease keep their contrast to the skin. A
  one-point curve lifts the darks more than the skin (2.1× vs 1.8×), and the eyes go pale and flat.
  *User: "still something unnatural".* A strong S-curve on top reads as fake too. *User: "lower the
  contrast, i dont like it".*
- **Fix the donor, not the mask.** Corners darker than the skin get lightened on the donor (a clipped
  Curves). Fading the mask there brings the closed eye back.
- **Non-destructive and named.** A donor layer with a mask, clipped Curves for tone, every layer
  named, the Background untouched. Then "lighter", "less contrast" or "the left one" is a one-command
  change, not a redo.
- **Show it only after checking it** at 1× and 3×, against the original (Step 5).

## Find the donor

Scripts are in this skill's `scripts/` (stdlib only; they crop through photocraft-cli).

    python3 feature_swap.py donors ~/Pictures/shoot/IMG_1234.JPG

lists the images next to the target from the same camera, nearest in capture time first, with size and
colour profile (Spotlight metadata). Edits of a file carry the original's capture time and are
labelled. In the real case the donor was 7.8 minutes earlier, in Display P3 where the target was sRGB,
and had first been missed by listing only file names close to the target's. `--dir` adds folders;
`--any-camera` drops the camera filter.

Look at each candidate (`sips -Z 1600 file --out small.jpg`, then Read), then at a crop of the eyes.
Brighten a dark crop to judge it:

    $PC cli run donor.jpg --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' \
      --cmd image.adjustments.curves --params '{"points":[[0,0],[90,190],[255,255]]}' --out eyes.png

Want: eyes naturally open (not mid-blink or wide), looking the same way the target's face looks, head
angle within ~15°, light from the same side. The target's expression stays: a squinting face keeps its
furrowed brow and raised cheeks around relaxed eyes. Tell the user that up front.

## The layer stack you're building

    Match donor tone 2    Curves (red/green/blue), clipped, mask = soft box around one eye (--per-eye)
    Match donor tone 1    Curves (red/green/blue), clipped, mask = soft box around the other eye
    Eyes from <donor>     pixel layer: a face-sized patch of the donor, aligned, mask = two almonds
    Background            the target, untouched

## Step 1: bring the donor in

Work in a folder under the home directory (the app's roots), e.g. `~/.photocraft-skill/work/<photo>/`.

1. Open the target (if it isn't) and the donor: `$PC call app.open '{"path": "/abs/donor.jpg"}'`.
   Documents are addressed by index: `$PC call ui.inspect` → `session.documents[].index`,
   `session.active`.
2. In the donor (active after opening; else `$PC exec document.activate '{"document": N}'`):
   `select.rect` around the face, 3–4 eye widths around the eyes, then `layer.new.layerViaCopy`, and
   read the new layer's id from `document.inspect`. A patch keeps the PSD small; the mask works on it
   all the same.
3. Copy it into the target. It's a command, so it goes through `exec` (`call` answers "unknown
   method"):

       $PC exec layer.copyToDocument '{"source": <donor index>, "document": <target index>, "layers": [<id>]}'

   Leave out `offset`, `at` and `center`, so the patch keeps the donor file's coordinates and corners
   measured in the donor file stay valid. The result names the layer's id in the target, which is now
   the active document.
4. Close the donor if you opened it: `$PC exec file.close '{"document": <donor index>}'`. That discards
   only the patch layer you added; the file on disk is untouched. If it was already open in the app
   before, it may hold the user's unsaved work: undo your patch layer there instead (`edit.undo`).
   `file.close` never asks.
5. Name the layer: `layer.setProps {"layer": id, "name": "Eyes from <donor>"}`.

Copying converts colours when the profiles differ (Display P3 → sRGB in the real case). That's fine for
the pixels, but the donor file's numbers no longer describe them: measure tone in the target document
(Step 3).

## Step 2: align

1. Measure the four eye corners in both files: the inner corner (nose side) and outer corner of each
   eye. Use gridded crops (`grid.py crop.png X Y grid.png --step 10 --scale 4`, brightened as above if
   dark). On a closed eye, the corners are where the lash line meets the skin fold at each end.
2. Fit and apply, donor point = target point, in the same order:

       python3 feature_swap.py align --pair 862,1301=1124,1322 --pair 929,1303=1181,1319 \
         --pair 1003,1310=1246,1327 --pair 1072,1313=1302,1338 --layer <id>
       $PC exec edit.transform '<the "transform" it prints>'

   The matrix is in document coordinates: x' = a·x + c·y + e, y' = b·x + d·y + f (verified in
   0.7.0). Without `rect`, the layer's own bounds are used, which doesn't change the result.
3. Read the errors. 2–4 px at the corners is normal for a squinting or closed target (3.4 px in the
   real case).
   - Don't fit each eye to its own two corners. It copies the squint's tilt onto the open eye: one eye
     came out rotated +8.6° and drooping.
   - Don't use `--affine` with eye corners alone. They lie on one line, so the vertical scale is a
     guess (it stretched 135 %). An affine needs landmarks off that line.
   - Eyeballing the scale from the closed eyes' "centres" put it at 0.80 where the corners say 0.85:
     eyes 7 % too small. Measure the corners.
4. `edit.autoAlignLayers` only works for whole frames that are nearly identical (a burst). Copy the
   full donor frame in, select both layers and run
   `{"projection": "collage", "reference": <Background id>}`; it returns the matrix, matches and rms.
   It refuses face patches and frames from different setups ("couldn't find enough matching detail
   between the layers"). People move between burst frames, so check the corners afterwards.

## Step 3: match tone and colour

Before masking, so the donor's skin around the eye is visible.

1. Export the target document twice, with the donor visible and hidden:

       $PC export ~/.photocraft-skill/work/x/with.png
       $PC exec layer.setProps '{"layer": <id>, "visible": false}'
       $PC export ~/.photocraft-skill/work/x/without.png
       $PC exec layer.setProps '{"layer": <id>, "visible": true}'

2. Measure and build:

       python3 feature_swap.py tone without.png with.png --eye 1181,1319=1124,1322 \
         --eye 1246,1327=1302,1338 --per-eye --layer <id> --steps tone.json
       $PC script tone.json

   `--eye` is inner corner = outer corner in the target. It samples skin below each eye and beside the
   inner corner, and leaves out samples where the frames disagree (a nose side lit in one frame and
   shaded in the other). The curve per channel scales like exposure (`--shape gain`, the default).
   Read the report:
   - `deltaE` per sample after the curve: up to ~5 is invisible at the seam. Over 6 → the light
     differs across the face; `--per-eye` gives each eye its own curve, masked to a box around it (in
     the real case one side of the face was warmer and darker: 7.5 dE with one curve, 5.1 with two).
   - Warnings about eye highlights clipping (eye whites going paper-white) or keeping under 60 % of
     their contrast (flat whites): a donor exposed closer to the target is the real fix.
   - `--white X,Y` on a donor eye white (as placed) reports its colour after the curve. A white in
     warm light reads about a* 0–4, b* 4–12; orange or pink means the curve tints it.
3. If the eyes still look washed out, add a gentle composite curve to the Curves layer (each one, with
   `--per-eye`). It keeps the per-channel match:

       $PC exec layer.setAdjustment '{"layer": <curves id>, "points": [[0,0],[60,50],[130,126],[255,255]]}'

   That one was accepted. A stronger one (60→38) was rejected as too contrasty.

## Step 4: mask

    python3 feature_swap.py mask --eye 1181,1319=1124,1322 --eye 1246,1327=1302,1338 --layer <id> \
      --steps mask.json --viz with.png --viz without.png --out viz.png
    $PC script mask.json

Look at viz.png first. Yellow is the selection edge, dashed cyan the fully opaque core, and red marks
the corners. On the donor panel, the open eye with its lashes sits inside yellow. On the target panel,
the closed lash line sits inside cyan, out past both corners. The brow and the under-eye bags stay
outside.

The shape is an almond along the corner line, so it follows the head's tilt. Sizes are in eye widths:
`--up 0.34 --down 0.24 --inner 0.06 --outer 0.14 --feather 0.07`. The failed first attempt was
1.6 × 1.0 eye widths with an 8 px feather. Raise `--outer` if the closed lash line runs further out,
and `--up` only if the donor's lid crease must come along. `--replace` deletes an existing mask first.

## Step 5: check, then answer feedback

Export, crop the same rectangle from the original and the export, and compare at 3×:

    $PC cli run original.jpg --cmd image.crop --params '{…}' --out before.png
    $PC cli run export.png --cmd image.crop --params '{…}' --out after.png
    python3 compare.py before.png after.png sheet.png --scale 3

Before showing it:
- no dark ring or shading around the eyes (mask too big)
- no old lash line beside the new eye, especially at the outer corners
- corners no darker than the skin next to them
- irises and lash line as defined as the brows and mouth: not pale, not harder
- eye whites not glowing, pink, orange or blue
- both eyes looking at the same point, catchlights on the side the light comes from, in both eyes
- eye size plausible for the face, tilt following the head
- no seam: measured below, and looked at along the whole mask edge at 3x. A swap is exactly what close inspection
  catches: in March 2024 four news agencies withdrew a family photo over a misaligned sleeve and a hand that didn't
  line up, the seams of a multi-frame composite.

Measure the seam along the donor's mask: grain inside against outside (a smoother or noisier patch), the tone step
across it once the gradient is taken out (a lighter block), and edge sharpness on both sides. The mask comes out as
a document of its own, the same size as the photo (tested: identical to the layer's mask):

    $PC exec layer.select '{"layer": <donor id>}'
    $PC exec channel.duplicate '{"channel": "mask", "document": "new"}'
    $PC call app.save '{"path": "/abs/path/work/x/swap_mask.png"}'   # the new document is active
    $PC exec file.close '{"document": <its index>}'
    $PC exec document.activate '{"document": <the photo index>}'
    $PC export ~/.photocraft-skill/work/x/after.png
    python3 qc.py seams after.png swap_mask.png ~/.photocraft-skill/work/x/seams

For speed on a big photo, crop both to the face with the CLI (same rectangle) and add `--origin X Y`. Read
`seams.png` and the flagged tiles: a tone step means the tone curves (Step 3) or the mask, not the seam itself.

Then save a layered PSD and a JPEG with new names (SKILL.md, "Saving"). After reopening a PSD, layer
ids change, so read them again from `document.inspect`.

| The user said | Cause | Fix |
|---|---|---|
| "too much shades, looks unnatural" | the mask took the donor's socket shading | `mask --replace` at the default size |
| "still something unnatural" (pale, flat eyes) | a one-point curve lifted the darks | `tone` (gain shape) on a fresh export |
| "lower the contrast, i dont like it" | a strong contrast curve | `layer.setAdjustment` with a gentler `points`, or none |
| "around corners make it lighter" | the donor's corners are darker | a clipped Curves masked to the corners (below) |
| "right eye looks strange" | a faded mask shows the closed lash line | the mask opaque out past that corner |

Lighten the corners without touching the donor's mask (verified: corners +15 levels, rest unchanged).
Dabs about 0.4 eye widths across, one per corner:

    $PC exec layer.select '{"layer": <donor id>}'
    $PC exec layer.newAdjustmentLayer.curves '{"points": [[0,0],[128,150],[255,255]]}'
    $PC exec layer.setProps '{"clipped": true, "name": "Lighten eye corners"}'
    $PC exec edit.fill '{"contents": "black", "target": "mask"}'
    $PC exec paint.stroke '{"layer": <curves id>, "target": "mask", "points": [[X,Y],[X,Y]],
                            "size": 22, "hardness": 0, "opacity": 0.6, "color": "#ffffff"}'

## Smiles, heads and other features

Same steps with other landmarks and a hand-drawn mask:
- **Smile:** mouth corners, the base of the nose and the chin point. Mask with `select.lasso` along
  the lip line and nasolabial folds, feather 2–4 % of the mouth width, then
  `layer.layerMask.revealSelection`.
- **Head in a group shot:** eye corners and mouth corners. Mask the head and neck down to the collar,
  along the jaw shadow and the hairline. The background behind the hair has to match, or keep the
  target's hair edge.
- Tone: `tone without.png with.png --sample X,Y ...` with samples on the skin just outside the seam,
  all round.
- **A head from another setup** (another camera, ISO, light or day) also brings its own grain and black level, which
  the tone step doesn't touch; `qc.py seams` shows the grain ratio. Treat it as a composite (`references/composite.md`):
  with the aligned donor masked, hide every other layer and export the donor alone as a PNG with transparency, then
  `composite.py without.png donor.png <dir> --same-frame --wrap 0` plans its black and white points, colour of light
  and grain against the target, in place. Import that group and hide the original donor layer and its tone curves.
  On a subject cut from one frame of a white-balance series and put into another frame of the same shot, that took
  the colour error from dE 18.9 to 6.4.

## What PhotoCraft can't do

- **Eyes without a donor.** There's no generative fill or face-aware eye opening. Hand-painted eyes
  look fake up close. Say so, and offer to look for a donor frame, to export the image and a mask for
  a generative tool, or to paint on a separate layer with honest expectations.
- **Auto-Align on patches or different setups.** It only aligns whole near-identical frames (Step 2).
- **Changing the expression.** `filter.liquify` can soften a furrowed brow, but that changes the
  person's face: ask first, unless the user already asked for a livelier or "less sleepy" face.
  Then keep it to a few pixels, on a named stamp layer they can switch off:
  - **Lid lift** (`forwardWarp`, size 40, three strokes along each upper lash line, the middle one
    longest): at most 4–5 px on a ~1000 px photo. At 6–9 px the lashes fuse into a black mass and the
    pupil stretches into a vertical slit, which only shows at 5×; judge every eye at 5× against the
    original, not at fit-to-screen.
  - **Brows** up 4–5 px and **mouth corners** up about 4 px (size 28) read as awake and stay natural.
  - Stamp Visible first (`"stamp": [["filter.liquify", {"strokes": […]}]]` in `layers.json`), and put
    any later adjustment layers above it: layers below a stamp no longer show.
