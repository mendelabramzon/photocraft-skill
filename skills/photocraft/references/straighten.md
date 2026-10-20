# Straighten: level horizons, vertical verticals

Read this before straightening a photo: a tilted horizon, converging verticals on a building or in a room, a facade
that should face the camera square-on. It is the full version of the recipe in SKILL.md: what architectural and
real-estate photographers do, and how to do the same in PhotoCraft with `scripts/straighten.py`, which measures the
photo's own lines and plans exact steps instead of eyeballing them.

## Contents
- What separates a professional straightening from a cheap one
- The order of operations, and what stays editable
- Step 1: measure and plan
- Step 2: apply
- Step 3: check like a professional
- Step 4: save
- When detection needs help: manual lines
- Tuning and false hits

## What separates a professional straightening from a cheap one

Sources: Adobe's Lightroom Classic help on Upright perspective correction, The Photo Ephemeris ("Architectural
Photography, Part 3: Fixing Converging Verticals"), HDRsoft ("Why do straight lines turn out curved in my property
photos?"), Photography Life ("The importance of straightening the horizon and aligning lines"), Light Stalking ("The
truth about converging verticals"); numbers from tests with this script.

- **Measured, not eyeballed.** Crooked horizons are among the most common faults, and photographers miss them in
  their own pictures (Photography Life). straighten.py measures lines to a few hundredths of a degree: on test images
  with known tilt it recovers roll and pitch within 0.01°, and corrected real photos re-measure within 0.05°.
- **Lens distortion first, then perspective, then rotation, then the crop.** Adobe recommends lens profile
  corrections before Upright because the analysis works better on straight lines. Bowed lines bias the measurement:
  with moderate barrel distortion a test's pitch read 6.1° instead of 8°.
- **The right reference.** A sea horizon is exact. On land the true horizon is usually hidden, and rooflines, kerbs
  and table edges seen at an angle are perspective lines, not level references. In architecture and interiors the
  verticals are the reference: they're vertical in the world from any viewpoint.
- **Verticals vertical; horizontals follow perspective.** Architectural and real-estate photos are expected to show
  vertical lines vertical (HDRsoft; The Photo Ephemeris: they "should appear strictly parallel"). The horizontals of
  a building seen from a corner still converge, correctly. Only a facade or back wall seen square-on also gets level
  horizontals (Lightroom's Full and Guided Upright; here, two `--level` lines).
- **A camera model, not a keystone squeeze.** Dragging the corners apart until the verticals are parallel leaves the
  building squat: for facades shot 8°, 12° and 20° off level, an eyeballed keystone made them 7, 11 and 21 % too
  short. Turning a virtual camera level with the photo's own focal length (K R K⁻¹, what a shift lens does
  optically) keeps windows square: 0 % error with the EXIF focal length. At 12° of pitch, assuming 20 or 50 mm for a
  28 mm photo errs by -1 or +5 %, and never leaves the verticals converging.
- **Not always 100 %.** On tall buildings shot from the ground many photographers keep a little convergence so the
  building soars instead of looming (practitioners in Light Stalking's discussion), and full automatic modes can
  over-correct (The Photo Ephemeris). The script corrects pitch fully up to 10° and eases to 85 % at 20°; roll is
  always fixed fully.
- **Deliberate tilt is not a mistake** (Photography Life). A steep upward shot, a Dutch angle or an abstract view of
  a tower stays as it is, or gets only its roll fixed.
- **Keep the composition and the aspect ratio.** The correction costs pixels at the edges. Crop to the largest
  rectangle with no empty corners, centred where the photo's centre lands, in the original aspect ratio.
  Photographers shoot wider to allow for it (HDRsoft; The Photo Ephemeris).
- **Editable when the user may tweak:** a smart object keeps the original inside and the lens fix as a smart
  filter; a crop that keeps its cropped pixels can be undone with Reveal All.

## The order of operations, and what stays editable

    1.  filter.lensCorrection {distortion}        only if lines bow (a wide lens without a profile)
    2a. edit.transform {rect, quad}               perspective: roll + pitch (+ yaw) as one exact homography
    2b. image.crop {x, y, width, height, angle}   rotation only: rotates and crops in one step
    3.  image.crop {x, y, width, height}          after 2a: the largest clean rectangle

`--smart` puts `layer.smartObjects.convertToSmartObject` first: the original stays embedded, the lens fix becomes an
editable smart filter, and the transform and angled crop apply to the smart object. `--keep-pixels` crops with
`deleteCroppedPixels: false`, so `image.revealAll` brings the edges back.

Do geometry first, on the photo, before retouching or adjustment layers. `edit.transform` moves only the active layer
(not every selected one) and turns the Background into "Layer 0" with transparent empty areas; `image.crop` with an
angle rotates every layer. In a layered document, convert the layers to one smart object first.

## Step 1: measure and plan

Work in a folder under the home directory (`~/.photocraft-skill/work/<photo>/`):

    python3 straighten.py photo.jpg ~/.photocraft-skill/work/<photo>/straighten

It renders a reduced copy (1600 px on the long side) with photocraft-cli, finds the straight segments (5–15 s), and
picks a mode:

| Mode | When (auto) | Steps |
|---|---|---|
| verticals | vertical segments totalling ≥ 2.5 × the image height (≥ 1.5 with no long horizon) | edit.transform + image.crop |
| horizon | a straight line across ≥ 60 % of the width (≥ 30 % if no perspective lines contradict it), including a hazy sea horizon (found where smooth sky meets textured water) | image.crop with angle |
| rotate | verticals that don't converge (pitch < 0.3°) | image.crop with angle |
| none | already straight (< 0.05°), no reliable lines, or a shot > 25° up or down (deliberate) | nothing |

The JSON line: `mode` and `reason`; `focal35` and `focalSource` (exif35, exif+sensor, given, assumed = 28 mm);
`horizon` {angle, span, soft}; `verticals` {roll, pitch, edgeLean: the lean a viewer sees at the left and right frame
edges, fitRms: how well the verticals agree (0.4–0.8° is normal on real photos), segments, length}; then `rotate` or
`roll`/`pitch`/`amount`/`yaw`, `crop`, `kept` (fraction of the area kept).

Read `lines.png` and `preview.png` before applying anything:
- `lines.png`: green = the verticals used, blue = the horizon, yellow = other near-level lines. Green must sit on
  things that are vertical in the world: wall corners, window and door frames, lamp posts. Not a leaning or curved
  tower, people, trees or furniture legs.
- `preview.png`: the predicted result with a grid every eighth. Magenta means an empty area inside the crop: it
  should never appear.

Options worth knowing:
- `--mode horizon|rotate|verticals` overrides auto; `rotate` fixes only the roll and keeps the convergence.
- `--amount 0.85`: fraction of the pitch to correct (roll is always full).
- `--focal 24`: the 35 mm-equivalent focal length when EXIF has none or the photo was cropped since capture.
- `--aspect keep|free|4:5`, `--crop centre|max`: centre (default) keeps the composition; max takes the largest clean
  rectangle anywhere, which can push the subject out on a steep correction.
- `--distortion 15`: run filter.lensCorrection first (positive = barrel); see Tuning.

## Step 2: apply

Live: select the photo layer, then run the steps:

    $PC exec layer.select '{"layer": <photo layer id>}'
    $PC script ~/.photocraft-skill/work/<photo>/straighten/steps.json

Headless, file in and file out:

    $PC script steps.json --open photo.jpg --save photo-straightened.psd

## Step 3: check like a professional

- Re-measure the export: `straighten.py photo-straightened.jpg <dir>/verify --verify --focal <same>`. Roll and the
  horizon angle should be within ±0.1°, `edgeLean` within ±0.2° (or the convergence you meant to keep when
  amount < 1). On the test photos: roll 0.004–0.05°, edgeLean ≤ 0.1° after, from up to 7.1° before.
- At fit-to-screen: verticals vertical, the horizon level, nothing looks as if it's falling backwards. At 100 %: no
  empty slivers along the edges, no lines bowing near the edges.
- Proportions: windows, tiles and doors plausible, circles round. Squat or stretched means a wrong focal length.
- Composition: the subject is still in frame; `kept` is usually 0.75–0.95. Much less: lower `--amount`, try
  `--aspect free`, or tell the user what the correction costs.
- The lines the script trusted were real verticals and a real horizon (lines.png).

## Step 4: save

- Layered: `app.save {"path": "…/photo-straightened.psd"}` (new name, next to the original).
- JPEG: render the PSD with the CLI at the original's quality: `$PC cli convert photo-straightened.psd
  photo-straightened.jpg --quality 95`.

## When detection needs help: manual lines

Read coordinates off `grid.py` on the photo (or a crop of it), in full-image pixels:

- `--level X1,Y1,X2,Y2`: a line that should be level (a horizon half hidden by trees, a long shelf in a frontal
  view). One line gives the rotation.
- `--plumb X1,Y1,X2,Y2` (repeatable): a line that should be vertical. One gives the rotation; two or more give the
  vanishing point too, like Lightroom's Guided Upright.
- Two or more `--level` lines on a facade or back wall seen square-on, in verticals mode: the camera is also turned
  to face it (yaw), so those horizontals come out level and the verticals stay vertical.

In the live app the user can also draw it: `image.analysis.rulerTool {"start": [x, y], "end": [x, y]}` along the
horizon, then `image.analysis.straightenLayer {"crop": true}`. It levels the ruler line and crops to the largest
same-aspect rectangle (rotation only).

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| `none`: "no reliable straight lines" on a seascape or plain | No straight boundary found (fog, waves breaking the line) | `--level` along the horizon |
| `none`: "steep NN deg shot" | Deliberate looking-up/down convergence | Leave it; `--mode rotate` for the roll only; `--mode verticals --amount 0.7` to force |
| A roofline, kerb or floor line taken for the horizon | Perspective lines in a street or room | Verticals win in architecture; `--mode verticals`, or `--level` on a true level line |
| Green lines on a leaning or curved building | Non-vertical architecture | `--plumb` on true verticals (an older building, a lamp post) |
| Verticals near the edges still lean or bend; pitch looks off | Barrel distortion from a wide lens without a profile | `--distortion 10..30`, keep the value with the lowest `fitRms`; camera JPEGs and phone photos are usually corrected already, leave 0 |
| Building looks squat or stretched after correction | Wrong focal length (no EXIF, or the photo was cropped) | `--focal` with the 35 mm-equivalent value |
| Top of the building cut off | `--crop max` on a steep correction | Default `--crop centre`, or `--aspect free` |
| `kept` below ~0.7 | Strong pitch on a wide lens | `--amount 0.8`, `--aspect free`; for the next shoot, step back or shoot wider |
| Back wall or facade horizontals still slope in a frontal shot | The camera wasn't square to the wall (yaw) | Two `--level` lines on that wall |
| Only one layer moved; the rest stayed tilted | `edit.transform` moves the active layer only | Straighten the flat photo first, or convert all layers to one smart object |
| White wedges in the corners after a rotation | A crop box reaching outside the photo (image.crop fills it with the background colour) | Use the script's crop, which always stays inside |
| `error: … too strong for this field of view` | A forced correction would wrap part of the frame behind the camera | Lower `--amount`, or `--mode rotate` |
