# Developing a photo: the professional way

Read this before developing a photo the user cares about: a raw from their camera, a portrait, a landscape,
a photo for print or a client. It is the order professionals work in, the numbers they check, and the
mistakes that make an edit look cheap. Every step works live (`$LC exec`) and headless (a settings file
and `$LC cli render`); `scripts/look.py` does the measuring.

Commands below use `$LC` and `$LOOK` as SKILL.md sets them:
`${CLAUDE_SKILL_DIR}/scripts/lc.py` and `${CLAUDE_SKILL_DIR}/scripts/look.py`.

## Contents
- What separates a professional develop from a cheap one
- The order
- Step 0: look and measure
- Step 1: lens and geometry
- Step 2: white balance
- Step 3: tone
- Step 4: presence and colour
- Step 5: local adjustments (masks)
- Step 6: detail
- Check like a professional
- Tuning and false hits

## What separates a professional develop from a cheap one

- **Correct, then shape, then style.** Lens, horizon, white balance and the tonal end points make the photo
  true; masks shape the light; a look comes last. A look on top of a cast compounds it.
- **Numbers over eyes.** Eyes adapt to a cast in seconds and screens differ. Things that are neutral in life
  (a grey card, white clothing in the light, concrete, shaded cloud) must read a* = b* = 0. Skin of every
  complexion sits near the vectorscope's skin line at about 123°; 110–130° is the usual range.
- **Keep the intent.** Golden-hour warmth, a low-key portrait, a high-key product shot, fog. Correct toward
  the intent, not toward an average grey. Ask when you can't tell what the photographer wanted.
- **Restraint.** The cheap look is every slider pushed: Shadows +100, Highlights −100, Clarity +60, Dehaze
  +50, Saturation +40. It reads flat, crunchy and haloed. Professional global moves are small; the big
  moves are local, in masks.
- **Whites stay white, blacks stay black.** Recovering highlights must not turn white things grey, and
  lifting shadows must not turn black things grey-blue.
- **A set looks like one light.** Photos taken in the same light get the same white balance and look
  (`shoot.md`).

## The order

| Step | What | Commands | Check |
|---|---|---|---|
| 0 | Look | render, `$LOOK measure` | what to fix, what to keep |
| 1 | Lens and geometry | `develop.merge` optics, `crop.autoStraighten`, `geometry.upright`, `crop.aspect` / `crop.set` | `$LOOK grid` on the result |
| 2 | White balance | `develop.wbPick`, `develop.wb` | neutral \|a*\|, \|b*\| ≤ 2; skin 110–130° |
| 3 | Tone | `develop.auto` (read it), `light.*`, `develop.curve` | clipping, L* end points |
| 4 | Presence and colour | `effects.*`, `color.*`, `mixer.*`, `grading.*`, presets | skin angle, saturation clipping |
| 5 | Local | `mask.add`, `mask.adjust` | coverage (overlay or `$LOOK diff`) |
| 6 | Detail | `detail.*` | 100 % crops |

Crop before tone: the post-crop vignette and your own judgment of brightness depend on what is in the
frame.

## Step 0: look and measure

Render the photo as it is, look at it, then measure:

    $LC cli render photo.dng -o ~/work/photo/before.png --size 1200
    $LOOK measure ~/work/photo/before.png

Know the photo's pixel size first: `width` and `height` in `photo.inspect` or `catalog.query`. With a
1200 px original, `--size 1200` is already full size, and 100 % crops of a small photo are small.

Read `clipping` (per channel: a warm scene clips red first), the L* percentiles (`0.5` near 0 = crushed
blacks, `99.5` near 100 = white clipping) and `cast`. The cast is the mean of the near-neutral pixels: a
hint, not the truth, since a sunset or a beige room has no true neutrals. Decide what the photo needs before
moving anything, and say it to the user in a sentence when the intent is unclear.

## Step 1: lens and geometry

- **Lens corrections.** Profile and chromatic-aberration correction are off by default:
  `develop.merge '{"settings": {"optics": {"lens_profile": true, "remove_ca": true}}}'` for camera files
  with lens data. Phone JPEGs come corrected already; leave them.
- **Horizon.** `crop.autoStraighten` returns the angle it applied (it found −3.0° on a 3° test tilt);
  check it on `$LOOK grid` over the result. A horizon should be level within about 0.2°; small
  tilts read as mistakes, big ones as intent.
- **Verticals.** `geometry.upright '{"mode": "vertical"}'` makes converging verticals parallel;
  `auto` balances level and perspective; `full` corrects both directions and can look stretched;
  `guided` takes up to 4 lines you give (`geometry.guides`). Steep upward shots look more natural with a
  little convergence left: if the building looks top-heavy, back `geometry.vertical` off a little.
- **Crop.** `crop.aspect` then `crop.set` (rect in the straightened frame). Keep the subject off-centre
  unless symmetry is the point, leave room in the direction a face or motion faces, and never cut at joints.

## Step 2: white balance

1. Find something neutral in the main light: a grey card, white or grey clothing, concrete, asphalt,
   a white wall you know is white, shaded cloud. Read its position off `$LOOK grid` (on a render without a
   crop) and check it first: `$LOOK measure render.png --point X,Y,card` must show no `warning` (one
   appears when any pixel around the point is at 255 or 0 in a channel).
2. `develop.wbPick '{"x": X, "y": Y}'`. A warm grey card measured a* 4.6, b* 19.7 before and −0.2, 0.2
   after one pick.
3. Measure the same point on a new render: |a*| and |b*| ≤ 2. Then check skin, if there is any:
   `--point` on the lit cheek; `vectorscope` 110–130°.

- **Never pick a coloured surface.** Wood, beige stone, skin, a golden dog's fur: the photo goes cold or
  green. When nothing is neutral, use a mode (`develop.wb '{"mode": "daylight"}'`, `cloudy`, `shade`,
  `tungsten`, `flash`) or leave it as shot, and judge by skin and memory colours (sky, grass).
- **Keep warmth that's meant to be there.** At golden hour or by candlelight, correct only part of the way:
  pick, read the `temp` it set, and set `wb.temp` between the as-shot value and that one (on JPEGs the
  as-shot value is 6500 on the relative scale).
- **Two lights** (window and tungsten): balance for the main one, then fix the other with a mask
  (`mask.adjust` `temp` / `tint`) over its area.

## Step 3: tone

- **Auto measures Exposure only.** In 0.9.1 `develop.auto` sets Exposure from the photo and the same
  Contrast +68, Highlights −66, Shadows +52 and Vibrance +30 on every photo (ten different test photos,
  raw and JPEG, and a crop changes nothing). That's a strong generic look: on a white-headed eagle on
  black, the white feathers fell from L* 97 to 85, grey. Take its Exposure as a hint and set the rest
  yourself.
- **Exposure for the subject**, not the frame's average: a face, the product, the building. On a normal
  scene the subject's midtones land around L* 45–65; skin lighter or darker with complexion.
- **Highlights and Shadows** recover detail at the ends. Past roughly Highlights −60 or Shadows +50 a photo
  goes flat; when a sky or a dark corner needs more, use a mask instead.
- **Whites and Blacks** set the end points. A normal scene: `L*` `99.5` around 95–98 (specular highlights
  may clip; white clothing, skin and clouds may not) and `0.5` around 2–8. Low-key photos sit darker on
  purpose, high-key lighter. Check `clipping.highlightsAnyChannelPct` and the per-channel numbers: more than
  about 0.5 % of one channel clipped on a coloured area (a red dress, a blue sky) loses its detail; pull
  Exposure, Highlights or that colour's saturation. Watch the low end too: `byChannelPct.low` climbs when
  a white-balance correction, Vibrance or Saturation drives a saturated colour's weakest channel to 0
  (on a test photo, a warm-to-neutral correction put red at 0 on 0.6 % of the greens and Vibrance +20
  took it to 3.4 %). Pull that colour's saturation in the mixer, or lift Blacks.
- **Contrast** with the slider, or a gentle S on the point curve:
  `develop.curve '{"channel": "master", "points": [[0,0],[0.25,0.22],[0.75,0.79],[1,1]]}'`.
  The parametric curve (`curve.highlights` … `curve.shadows`) shapes regions without moving the end points.

## Step 4: presence and colour

- **Texture** (fine detail): +10 to +30 on landscapes and architecture; negative on skin, through a mask,
  never globally on a portrait.
- **Clarity** (midtone contrast): +10 to +25 on landscapes and textures; 0 or slightly negative globally on
  portraits. **Dehaze**: +5 to +25 through real haze; more darkens and halos; negative adds atmosphere.
- **Vibrance before Saturation.** Vibrance +10 to +30 lifts muted colours and protects skin; Saturation
  moves everything, skin included. A global Saturation beyond ±15 is rarely right.
- **The Color Mixer, one colour at a time.** To learn which bands a colour falls in,
  `develop.targeted '{"target": "sat", "x": …, "y": …, "delta": -5}'` adjusts the bands under the
  point and returns them (a purple sky: magenta and some purple). A deeper sky: `mixer.blue.lum` −10 to −30 (and `.sat` +10).
  Red, blotchy skin: `mixer.orange.sat` −5 to −15, `mixer.red.sat` −5 to −10, `mixer.orange.lum` +5 to +10.
  Fresher foliage: `mixer.green.hue` toward yellow (+10 to +20) or teal, `mixer.yellow.sat` down for less
  "lime".
- **Looks.** A preset or profile at 40–70 % (`preset.apply`, `develop.profile` with `amount`), or grading:
  `grading.shadows.hue` 200–220 (teal) and `grading.highlights.hue` 35–50 (warm), saturation 5–15 each,
  `grading.balance` to bias. After any look, measure skin again: it should move no more than about 5°.
- **Black and white:** `develop.treatment '{"bw": true}'`, `develop.autoBwMix {}` as a start, then the
  `bw.*` bands: `bw.blue` −20 to −40 darkens a sky, `bw.orange` / `bw.red` + brighten skin. Never
  desaturate instead: it loses the separation between colours of the same brightness.

## Step 5: local adjustments (masks)

| Task | Mask | Typical adjustment |
|---|---|---|
| Heavy or bright sky | `sky`, or `linear` from the top (`start`) to just below the horizon (`end`) | exposure −0.3 to −0.8, highlights −20 to −40, dehaze +5 to +15 |
| Subject a little brighter | `subject`, or `radial` over it | exposure +0.2 to +0.5, clarity +5 to +10 (not on faces) |
| Skin a little smoother | `radial` or `brush` over the face | texture −10 to −25, clarity −5 to −10 |
| Draw the eye in | `radial` with `invert: true` around the subject | exposure −0.2 to −0.5 |
| Foreground lift | `linear` from the bottom | shadows +10 to +30, exposure +0.1 to +0.3 |
| Second light's colour | `radial` / `brush` over it | temp / tint |

Positions and radii are in the whole photo's frame (0..1; radii are fractions of the long edge), and the
`feather` (0–100) is what makes a mask invisible: hard edges show. Name masks after what they do.

**Check every mask's coverage**, because the classical Sky, Subject and Background masks are heuristics:
- Live: `mask.select '{"id": N}'`, `ui.set '{"right": "masking", "maskOverlay": true, "maskOverlayAll":
  true}'`, screenshot: the mask is red. Put `maskOverlayAll` back to false afterwards.
- Headless: render twice, once as is and once with the mask's `exposure` raised to 2, then
  `$LOOK diff a.png b.png diff.png`: red is what the mask covers, and `bbox` its extent.

Fix coverage with components: `mask.addComponent '{"id": N, "op": "subtract", "kind": "radial", …}'`
(take a building out of a sky), `"op": "intersect", "kind": "luminanceRange", "lo": 0.5, "hi": 1` (only the
bright part of a gradient), `"op": "add"` (the part a subject mask missed). `mask.refine '{"value": 50}'`
snaps edges to the photo.

## Step 6: detail

- **Sharpening** for the output: `detail.sharpenAmount` 30–60, `sharpenRadius` 0.8–1.2, `sharpenDetail`
  15–35, `sharpenMasking` 30–70 (higher keeps sharpening off smooth skin and sky). Exports add output
  sharpening on top (`sharpen: screen`, `matte`, `glossy`), so keep capture sharpening modest.
- **Noise:** `detail.nrLuminance` 10–30 for high ISO (more smears fine detail), `detail.nrColor` around
  25 for raws with colour speckle. Lifted shadows show noise first: look there.
- Judge both at 100 % on a crop of the subject and of the darkest area, not on the whole frame.

## Check like a professional

1. **Before and after,** side by side: `$LOOK sheet before.png after.png --out ba.png --cols 2`, or live
   `ui.set '{"beforeAfter": "sideBySide"}'` (then back to `off`).
2. **Neutrals** |a*|, |b*| ≤ 2 (unless warmth is the intent); **skin** 110–130° and moved ≤ 5° by the look.
3. **End points:** no new clipping on non-specular areas; `0.5` and `99.5` percentiles where the intent puts
   them.
4. **100 % crops:** halos along high-contrast edges (Dehaze, Clarity, Shadows, mask edges), noise in lifted
   shadows, sharpening halos, banding in skies.
5. **The export, not only the preview:** export, then look at the file and `$LOOK measure` it (it reads
   JPEG and TIFF exports directly).

## Tuning and false hits

| Symptom | Likely cause | Fix |
|---|---|---|
| Whites look grey | Highlights pulled too far (Auto does this on bright subjects) | Whites up, Highlights less negative |
| Photo went cold or green after the eyedropper | A surface that is warm in life was picked (wood, beige, skin, fur) | Pick a true neutral, or use a white-balance mode |
| Dark band across buildings or mountains | A linear sky gradient crosses them | Use the `sky` mask, or subtract them, or intersect with a luminance range |
| Halo along the horizon or around the subject | Dehaze, Clarity or Shadows too high, or a hard mask edge | Reduce, raise `feather`, or `mask.refine` |
| Sky mask stops partway down, or leaves bright things out | The Sky heuristic expects sky at the top: on a frame that was all sky it left the lower third and the lightning bolt out | Add a `linear` or `brush` component |
| Subject mask covers part of the subject | The heuristic found the brightest, most distinct part (an eagle's head, not its shoulders) | Add `radial` / `brush` components |
| Skin orange or blotchy | Warm white balance or too much saturation | Correct the white balance; `mixer.orange.sat` down |
| `wb.temp` of 4200 on a JPEG looks wrong | Relative scale on non-raw files: 6500 means as shot | Judge by measurement, not by the number |
| Grey-blue shadows | Shadows lifted far on a dark area | Less Shadows, or a mask; colour noise reduction |
