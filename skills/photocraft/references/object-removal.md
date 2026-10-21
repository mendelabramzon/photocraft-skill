# Object and distraction removal: gone without a trace

Read this before removing sensor dust, power lines and wires, people, signs or litter. It covers how professional
retouchers do it, and how to do the same in PhotoCraft with the two planners: `plan_spots.py` (dust and specks) and
`plan_lines.py` (wires). Large objects are removed by hand with Patch and the clone stamp. The planners find what to
remove, choose clean sources, and stop at anything that must stay (poles, branches, roofs).

## Contents
- What separates a professional removal from a cheap one
- The layer stack you're building
- Step 1: set up and map the area
- Step 2: sensor dust and specks (plan_spots.py)
- Step 3: power lines and wires (plan_lines.py)
- Step 4: people, signs, litter (Patch, clone, heal)
- Step 5: check like a professional
- Step 6: save
- Tuning and false hits

## What separates a professional removal from a cheap one

The retouching literature agrees on these points (Adobe's Remove tool and Spot Healing help, PHLearn and Lightroom
Killer Tips on healing vs cloning, Lightroom's Visualize Spots tutorials):

- **Non-destructive.** Retouch on an empty layer that samples the layers below (Adobe's own advice for the Remove
  tool: a new layer plus Sample All Layers), or on a duplicate. The original stays untouched underneath.
- **The right tool for each spot.** Spot Healing for small specks on even ground. Healing Brush with a source *you*
  choose, of the same light, texture and scale, for anything textured. Near an edge, healing blends from the edge and
  smears it ("messy, smudged edges"). There, use the clone stamp, or contain the healing with a selection. Patch
  suits a medium area with a clean donor beside it, and Remove suits thin or small things. Crowds shot from a tripod
  come out cleanly with a stack median. The routing professionals teach (table in Step 4):
  - Healing tools fail on anything that touches the frame edge or dead-ends into another object (Ben Willmore,
    CreativeLive): there is nothing clean on that side to blend from.
  - Content-aware fill and Remove only on simple ground: sky, water, grass, sand, plain walls, a studio backdrop.
  - The clone stamp is the tool "when all other tools fail" (Matt Kloskowski): split a hard removal into small pieces
    and rebuild each one, structure first.
  - **Never an automatic fill on faces, hands or text.** Synthesis invents features there; they get clone and
    healing from the same face, hand or letterform, or stay.
- **Structure first, then texture.** Rebuild the horizon, wall edges and wave lines with the clone stamp, then heal
  the texture between them.
- **Donors from the same plane and light.** Take texture from the same distance (the same row in a landscape), so
  its scale matches, and from the same light: a donor nearer the sun is brighter.
- **Take everything that belongs to the object.** Its shadow, its reflection in water or wet sand, and where it
  touched the ground.
- **No traces.** No repeated clone patterns, smudges or patches smoother than the grain around them. A wire has to
  vanish where it crosses a cloud edge too, not only in open sky.
- **Dust needs a dust check.** Sensor dust is a soft, round shadow, most visible at small apertures (f/16 to f/22)
  on plain areas, and it sits in the same place in every frame of a session. Retouchers find it with a temporary
  extreme curve, inverted (Adobe's tutorial) or a steep zig-zag of about eight points (Shutterbug), or Lightroom's
  Visualize Spots, then fix each spot with a heal a little larger than the spot and delete the curve. Here:
  `compare.py before.png after.png cmp.png --check solar` (or `negative`) renders that view.
- **Many specks: Dust & Scratches through a mask, never over the photo.** For lint on dark cloth or a dusty scan,
  the filter on a copy, tuned the way Damien Symonds teaches (radius up from 1 until the specks go, threshold up
  from 0 until they come back, then a step back), painted in only over the specks in Lighten mode for dark specks and
  Darken for light ones (Have Camera Will Travel), with 2–3 % monochromatic noise so the repairs aren't smoother
  than the grain (a scanning guide from afk.fi). Measured numbers in "Many small specks" below.
- **Automatic tools still need hand cleanup.** Adobe says this of its own "Find distractions › Wires and cables": the
  result is good but not perfect, so compare with the original and finish by hand.

## The layer stack you're building

    Objects                     duplicate of the photo: Patch / clone / heal for people, signs, litter (Step 4)
    Retouch: wires              empty layer, healing strokes along the wires (plan_lines.py)
    Specks (dark), (light)      Stamp Visible + Dust & Scratches + noise, Lighten / Darken, masked (many small specks)
    Retouch: dust               empty layer, healing dabs (plan_spots.py)
    Background                  original, untouched

Do the dust first, so no later patch or clone copies a dust spot somewhere else.

## Step 1: set up and map the area

Work in a folder under home, e.g. `~/.photocraft-skill/work/<photo>/`. The planners read a crop of the current
composite plus a median reference from the CLI, at full resolution:

    $PC cli run photo.jpg --cmd image.crop --params '{"x":X,"y":Y,"width":W,"height":H}' --out crop.png
    … same + --cmd filter.noise.median --params '{"radius":45}' --out ref45.png     # dust
    … same + --cmd filter.noise.median --params '{"radius":12}' --out ref12.png     # wires

Then map the area with `grid.py crop.png X Y grid.png --step 100 --scale 1` and write `area.json`
(`{"skin": [[x, y], …], "exclude": [box or polygon, …]}`; "skin" is the area to work in). **For wires this is the
step everything depends on.** Draw the sky as the area. Exclude every pole, crossarm, insulator, lamp arm, sign,
tree and roof, with ~10 px to spare. The wire detector cannot tell a lamp arm or a smooth twig from a wire, and
every stroke is cut where its brush would touch an excluded area. For dust, exclude anything that isn't plain
background (a hazy rock face counts as smooth too).

Make the retouch layers: `layer.new.layer {"name": "Retouch: dust"}` (and one for wires), and note their ids.

## Step 2: sensor dust and specks (plan_spots.py)

    python3 plan_spots.py crop.png ref45.png X Y --area area.json --layer <dust layer id> --sample currentAndBelow \
        --steps dust.json --overlay dust_overlay.png --check dust_check.png
    $PC exec layer.select '{"layer": <dust layer id>}'
    $PC script dust.json

How it finds spots: the darkening against the median, measured at several scales, each in units of its own local
noise (a soft spot shows best at its own size). It then keeps only what looks like dust:
- round and compact;
- radially symmetric (`--max-asym`): darker sky between cloud wisps is lopsided;
- neutral (`--max-tint`): a shadow keeps the colour's chromaticity; birds and cloud gaps don't;
- visible (`--min-depth`): small spots need more contrast than big ones.
Each spot gets one Healing Brush dab that reaches past its whole halo (healing takes its tone from the dab's rim, so
a rim inside the halo leaves a ring). The source is the nearest clean, tone-matched patch, left or right first, since
sky gradients run vertically. Spot Healing is the fallback.

- Read `dust_check.png` (local contrast ×8, spots circled) and `dust_overlay.png` (red dab, cyan source) before
  running. Birds, stars, planes and antennas are not dust; drop their steps.
- **Big images:** real dust on a 24 MP sensor is 50–130 px across, larger than the median radius. Plan at half
  size: crop + `image.imageSize {"width": W/2}`, median 45 on that, `--zoom 2 --max-size 88`. The steps come out in
  full-size coordinates.
- Out-of-focus dust is a ring or a hexagon with a lighter centre; the planner centres on it before measuring.
- `--polarity light` finds light specks, and `--any-colour` also takes coloured specks (pollen, small litter on a
  backdrop).
- `--debug X,Y` says why the spot at that point was or wasn't planned.
- The same dust sits in every frame of a session: plan one frame, check it, and run the same steps on the others
  only after confirming the spots line up.

### Many small specks: Dust & Scratches through a mask

When there are too many tiny specks to heal one by one (lint on a dark suit, dust on a scanned slide, a speckled
backdrop), use one masked layer per polarity, in a layers.json for `import_layers.py`:

    {"name": "Specks (dark)", "stamp": [["filter.noise.dustAndScratches", {"radius": 4, "threshold": 8}],
       ["filter.noise.addNoise", {"amount": 5, "distribution": "gaussian", "monochromatic": true, "seed": 1}]],
     "blend": "Lighten", "mask": "dark_specks.png"}

Light specks get their own layer with `"blend": "Darken"`. The mask is the specks a couple of pixels wider (from
`plan_spots.py --polarity dark|light`, `find_defects.py`'s fine layer, or a lasso round a patch where the threshold
alone can tell specks from texture). By hand: `layer.stampVisible`, the two filters, `layer.setProps {"blend":
"Lighten"}`, `edit.fill {"contents": "black", "target": "mask"}` on a new mask, then white over the specks.

Tune it on a crop with the CLI, the way Damien Symonds teaches: radius up from 1 until the specks are gone, threshold
up from 0 until they start to come back, then a step down (`$PC cli run crop.png --cmd filter.noise.dustAndScratches
--params '{"radius": R, "threshold": T}' --out t.png`). Measured on a grainy black-and-white scan (grain 3.95 levels)
with 300 dark and 150 light synthetic specks 1–5 px across and 25 hairlines:

- The rule landed on radius 4, threshold 8 for the dark specks and radius 3, threshold 8 for the light ones. Bigger
  specks need a bigger radius.
- Masked to the specks plus 2 px: dark specks from −25.4 levels on average to −3.6, light ones from +28.3 to +2.9,
  nothing outside the mask changed. The layer above built and verified (0.05 level from the prediction without noise).
- The same filter over the whole frame changed clean texture by 3.2 (Lighten) and 4.7 (Darken) levels RMS, as much
  as the grain itself: that's why it goes through a mask. A Lighten and a Darken layer of the same filter over the same
  area add up to the plain filter, so it's one polarity per masked layer.
- Repairs held 70 % of the grain around them without noise, 74 % with Add Noise amount 2.5 (the 2–3 % of the scanning
  guides) and 83 % with amount 5 (about the grain in levels): set the amount near the photo's grain.

## Step 3: power lines and wires (plan_lines.py)

    python3 plan_lines.py crop.png ref12.png X Y --area area.json --layer <wires layer id> --sample currentAndBelow \
        --steps wires.json --overlay wires_overlay.png
    $PC exec layer.select '{"layer": <wires layer id>}'
    $PC script wires.json

What it does: thin dark lines (`--polarity light` for lit wires on storm cloud) against the median, on smooth
background, are thinned to centrelines. Paths cut by skeleton spurs are linked back up, and only long, thin,
straight lines as dark or as crisp as the strong wires count (dark gaps between cloud wisps are fainter and soft).
Each wire gets Healing Brush strokes in segments of up to 160 px. Each segment copies a clean strip beside the wire:
no other wire, smooth, same tone and grain; a segment with no clean side is split, then falls back to Remove. Where
wires cross or run together, one brush covers all of them, done last: a stroke along one wire with its neighbour
under the rim would take the neighbour's tone and smudge. Bits that no brush covers well get touch-up strokes.

- Read `wires_overlay.png` first. Red is a healing stroke and cyan the strip it copies. Yellow is a Remove stroke.
  Magenta is a line it rejected (wide, crooked, or hardware). Orange circles are where strokes stop at structure:
  finish those with the clone stamp along the pole.
- A thin piece of hardware attached to a pole (crossarm, lamp arm, insulator wire) is detected as a wire. Exclude
  it in area.json; that's the only reliable protection.
- Run it again on the export (new crop and ref): what remains are stubs at the poles and short bits. `--debug X,Y`
  explains any wire it skipped.
- Where a wire runs off the canvas edge, its last few pixels stay (healing has nothing beyond the edge to blend
  from): one clone dab.
- It takes ~20–30 s for a 2.8 MP crop; 300–600 strokes run in a few seconds.

## Step 4: people, signs, litter (Patch, clone, heal)

Choose the tool by where the object sits, not by its size alone:

| The object | Tool | Why |
|---|---|---|
| Small and isolated on even ground (a speck, a bird in clear sky) | Spot Healing or a `plan_spots.py` dab | blends from its own clean ring |
| Thin (a wire, a cable, a stray line) | `plan_lines.py` strokes, or Remove | Remove is at its best on thin things |
| Medium, with clean ground of the same plane and light beside it | Patch from that donor, then heal the seams | |
| Touching the frame edge, or running into another object | Clone stamp from a donor, or Patch; not healing | healing blends from the edge and the other object: nothing clean on that side (Ben Willmore) |
| Across structure (horizon, kerb, brick courses, a window frame) | Rebuild the line with the clone stamp first, then patch and heal between | structure before texture |
| A large area of simple ground (sky, water, grass, sand, a plain wall, a backdrop) | Content-aware fill on its own layer, checked at 100 %; else Patch | it smeared a bright beach in 0.7.0 |
| Faces, hands, lettering | By hand only: clone and heal from the same face, hand or letters | synthesis invents features; never content-aware or Remove |
| Anything the other tools fail on | Clone stamp, in small pieces (Matt Kloskowski) | you choose every source |
| People moving through a tripod sequence | Stack median (below) | |

Work on a duplicate named "Objects". Select the object **with its shadow and reflection**, a few px wide:

    select.lasso {"points": [[x, y], …], "feather": 2}

1. **Rebuild lines first.** If a horizon, wave line, kerb or wall edge runs behind the object, clone it across:
   `paint.cloneStamp {"points": [[x0, y], [x1, y]], "size": 20, "hardness": 70, "offset": [dx, 0],
   "aligned": true, "target": "pixels", "layer": <id>}`, with the offset along the line.
2. **Patch the area** from a donor on the same plane and in the same light, usually the same row:
   `paint.patch {"offset": [dx, dy], "mode": "source"}`, the offset pointing at the donor. On the test beach, a donor
   on the darker side blended invisibly. A donor nearer the sun left a lighter block, and content-aware Patch
   (`"contentAware": true`) left a darker block with hard edges.
3. **Heal the seams** with short Healing Brush strokes along the patch edge, sourced from clean neighbours, then
   `select.deselect`.

- `edit.contentAwareFill {"sampling": "auto" | "rectangular" | "custom", "area": [x, y, w, h], "output": "new"}`
  exists. On a bright, low-texture beach in 0.7.0 it produced a smeared, discoloured patch, so check its result
  closely and prefer Patch on smooth or ordered texture. With "custom" sampling, keep the subject and other objects
  out of the area.
- `paint.remove` (Remove) is excellent on thin things (wires, cables). On a person-sized area it smears texture
  into a soft column.
- **Crowds from a tripod sequence:** copy the frames into one document as layers (`layer.copyToDocument`), select
  them, then `edit.autoAlignLayers {"projection": "auto"}`, `layer.smartObjects.convertToSmartObject` and
  `layer.smartObjects.stackMode.median`. Whatever moved between frames disappears.

## Step 5: check like a professional

- **Before/after** at fit-to-screen and at 100–200 % of every worked area (`compare.py before.png after.png out.png
  --rect … --scale 2`). Add `--check --gain 8` for skies: no dark discs, no rings where dust was. `--check solar` (or
  `negative`) is the retoucher's extreme-curve view: leftover dust, smudges and seams stand out in it.
- **Re-plan the result.** `plan_spots.py` on the export finds 0–2 spots where it found many, and `plan_lines.py`
  finds no wire in open sky, only stubs at excluded structure.
- **Measured on ground truth** (synthetic wires and dust on real skies): healed wires came within the sky's grain
  (band RMS 2.2–2.6 levels against a grain floor of 3.5–4.4), with a low-frequency bias of ±0.3 levels where the
  wire left −7. Healed dust: RMS 2.6 against a 2.5 floor. Aim for that: no streak, no ring, grain continuous.
- **Structure intact:** poles, insulators, lamp arms, branches, horizon and roof lines are identical to the original
  (2× crops along every excluded area).
- **No repeats or smudges:** no cloned shapes twice, no patch smoother or brighter than its surroundings. Shadows
  and reflections are gone too. After clone or patch work, `qc.py repeats after.png out --before before.png` lists
  texture that now appears twice, and `qc.py seams after.png mask.png out` grain and tone steps along a patch's edge.
- **Nothing else changed:** outside the planned brushes the export matches the original.

## Step 6: save

- Layered: `app.save {"path": "…/photo-cleaned.psd"}`, a new name next to the original.
- JPEG: `$PC cli convert photo-cleaned.psd photo-cleaned.jpg --quality 95` (`app.save` writes about q90).
- Headless, for a batch or a test: `$PC script wires.json --open photo.jpg --save photo-cleaned.psd`. The steps are
  in full-image coordinates, so apply them to the whole photo, not to the crop.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| A big soft (or ring-shaped) dust spot isn't planned | Bigger than the median radius or `--max-size`; the median absorbs it | Plan at half size: `--zoom 2`, median 45, `--max-size 88` |
| A faint ring where a very dark dust spot was | The dab's rim sits inside the halo | `--margin 8`, or plan again on the export |
| Dark blotches between cloud wisps on a dark, noisy blue sky | Natural sky structure at dust scale | Usually rejected (tint, symmetry); check the overlay, raise `--threshold` to 4.5 |
| Dust "found" on a hazy rock or a hillside | Smooth, but not sky | Exclude it in area.json |
| Spots right at the crop's edge are skipped | The median and blurs are unreliable at the edge | Crop wider |
| **A lamp arm, crossarm or insulator wire was healed away** | Thin hardware looks like a wire | Exclude poles and their hardware in area.json, always |
| Twigs and branches planned as wires | Thin, dark, smooth lines too | Exclude trees in area.json; `--max-wiggle 0.6` |
| Dark gaps between cloud wisps planned as wires | Low-contrast lines | `--relative-contrast` (0.4) rejects them; raise to 0.5 |
| A faint thin wire is left | Under the contrast and crispness floors | `--debug X,Y`; `--relative-contrast 0.25` |
| A bundle of wires left in dashes | Its brush would exceed `--max-bundle` | Raise to 100 over open sky; at a pole, clone |
| Stubs left next to poles | Strokes stop before structure, by design | Clone stamp along the pole (`cloneSpots` in the stats) |
| The last pixels of a wire at the canvas edge | Healing has nothing beyond the edge to blend from | One clone dab |
| A soft smudge where two wires overlapped | A stroke whose rim lay on the other wire | Crossings are done last with one brush; second pass for leftovers |
| Content-aware fill: smeared, discoloured patch | 0.7.0 on smooth, high-key texture | Patch from a same-plane donor, then heal the seams |
| Patch leaves a lighter (darker) block | Donor in different light | Donor on the same row, away from the light source; heal the seam |
| Remove turns a person into a soft column | Content-aware synthesis averages texture | Remove only thin or small things; Patch and clone the rest |
| A smear where a heal met the frame edge or another object | Healing blends from what's under its edge | Clone stamp from a donor there |
| Dust & Scratches flattened fabric or grain | Run over a broad area, or the threshold too low | Mask it to the specks; raise the threshold until specks just start to return, then one step down |
| Specks gone but the spots look smoother than the grain | Median repairs carry no grain | Add Noise in the stamp near the grain (amount 5 held 83 % of a 4-level grain) |
| Texture as changed as by the plain filter, despite Lighten and Darken | A Lighten and a Darken layer of the same filter over the same area add up to the plain filter | One polarity per layer, each masked to its own specks |
