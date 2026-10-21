# Compositing: an element into another photo

Read this before putting something cut out of one photo into another: a product into a room or onto a beach, a
person onto a new background, a subject from another frame of the same shoot. It is the full version of the recipe in
SKILL.md: what makes a composite believable, and how to do it in PhotoCraft with `scripts/composite.py`, which
measures the plate and the element and builds the matching as named, editable layers.

## Contents
- What separates a believable composite from a pasted one
- The layer stack you're building
- Step 1: the element
- Step 2: place it
- Step 3: plan the match
- Step 4: build it
- Step 5: what the numbers can't do
- Step 6: check like a compositor
- Save
- Tuning and false hits

## What separates a believable composite from a pasted one

Sources: Toronto Metropolitan University's *Photoshopped* (Pressbooks) and ProVideo Coalition on matching an element
to a plate; Adobe Learn on light; Planet Photoshop's light-wrap method; Clipping Expert Asia and Photoshop Essentials
on shadows; and what testing in PhotoCraft 0.7.0 added.

- **Tones in a fixed order: black point, white point, gamma, then colour.** A plate's darkest tone is rarely pure
  black (lens flare, haze, processing): often a muddy brown or a deep navy. An element whose blacks go deeper than
  anything in the plate looks stuck on. Match the black point first, then the white point, then the midtones, and only
  then the colour: a cast is easy to see once the brightness matches (TMU, ProVideo Coalition). The midtones are the
  one step no measurement settles (two different things share no midtone): `composite.py` measures the ends and the
  colour, and leaves gamma and exposure to you (`--gamma`, `--ev`).
- **The colour of the light.** Both photos show their light in the things that are neutral in life: a white shirt, a
  grey wall, paper. Take the element's neutrals to the plate's. Tested on a subject cut from one frame of a white
  balance series and composited into another frame of the same shot (the true result known): the colour error fell
  from dE 18.5 to 7.3 on average over seven pairs (warm, cold, tungsten and cloudy into neutral, and back); the b*
  left was 1.1 or less in four of them, and the strongest cast (a tungsten preset's blue, b* -24) kept -9.3.
- **Light direction and quality.** Adobe: match the light's direction and quality, and don't mix hard light with soft,
  or warm with cool. Shadows on the element must fall the way the plate's do; a studio-lit person on a sunlit meadow
  with long shadows still looks pasted however well the colours match. No measurement here can fix that: choose an
  element shot in matching light, mirror it if only the side is wrong (`edit.transform.flipHorizontal`, unless it
  carries text or a logo), or reshoot.
- **Perspective and scale.** The element must be seen from the plate's camera height and sized for its distance. In
  a photo taken from eye level, the eyes of every standing adult sit near the horizon, near or far; an object resting
  on the floor has its base on the floor's perspective. Size it against something nearby of known size (a door about
  2 m, a chair seat about 45 cm, a table about 75 cm high).
- **Sharpness matched to the focal plane.** A crisp studio element on a background at another distance gives itself
  away. Match its edge softness to the plate's around it (ProVideo Coalition: Lens Blur with depth, not one uniform
  blur over everything). Never blur a sharp plate to match a soft element: use a sharper element.
- **Grain.** A clean element in a noisy plate shows at 100 %. Add the missing grain; grain can't be taken away from an
  element that is noisier than the plate, so reduce its noise first.
- **Edges.** The old backdrop left in the cut's edge pixels shows as a light or dark rim on any plate darker or
  lighter than that backdrop. That is a cut problem: decontaminate the cut (`references/cutout.md`), nothing on top
  hides it.
- **Light wrap.** Light from a bright background spills over a subject's edge; a hard, untouched edge sits on the
  plate like a sticker. Planet Photoshop's method: a copy of the background blurred until no detail is left, in a
  blend mode that lightens, painted in at about 30 % along the subject's edge, more where the background is bright. It
  replaces the old Inner Glow, a single colour, which fails when the light is mixed warm and cool; a blurred plate
  carries each part of the background's own colour.
- **Contact and cast shadows.** An object resting on a surface needs a dark contact shadow where it touches, or it
  floats. A shadow is the ground darkened, in its own hue, not a black stamp. A cast shadow (light from one side)
  is drawn by hand: a copy of the silhouette, filled dark, distorted away from the light, Multiply at about 55-75 %,
  blurred more the further it reaches (Clipping Expert Asia); the Drop Shadow layer style alone "doesn't cut it"
  (Photoshop Essentials).
- **Seams at 100 %.** Detail inspection is what catches a composite: in March 2024 four news agencies withdrew a
  family photo after readers spotted a misaligned sleeve and a hand that didn't line up, the seams of a multi-frame
  composite. Check every edge at 100 % and 3x before showing anything.
- **Non-destructive.** The element on its own layer, every adjustment clipped to it and named, the plate untouched:
  "a bit warmer", "less glow" or "move it left" is then a one-layer change.

## The layer stack you're building

    Composite: <name>       group, Pass Through
      Light wrap            the plate blurred, Screen 35 %, clipped, mask = a band just inside the element's edge
      Grain                 grey 127.5 + noise/2, Linear Light, clipped (only when the plate is noisier)
      Match plate           Curves red/green/blue: black point, white point, colour (gamma, exposure if given); clipped
      <element>             the cut, scaled and placed, transparent outside it (--element-name, else --name or the file)
      Contact shadow        Multiply, along where it touches the ground (--shadow contact)
      Occlusion shadow      Multiply at --occlusion, the soft dark under it and its overhangs (--occlusion)
    Background              the plate, untouched

Clipped layers act on the element's own colour, then the result goes over the plate by the element's alpha (tested:
PhotoCraft composites a clipping group the way Photoshop does). A mask on the Element layer hides its clipped layers
with it.

## Step 1: the element

1. Cut it out with the cutout workflow (`references/cutout.md`) and export only the masked layer as a PNG with
   transparency (`cut.png`) that carries its colour profile: `composite.py` converts it to the plate's (an Apple RGB
   studio shot into an sRGB room), and an untagged PNG is read as sRGB. Check the cut first: `cutout_check.py` on
   black and on a colour close to the plate.
2. If the element's photo has a strong cast, white-balance it there first (`references/color-grade.md`, several
   neutrals at different levels): one neutral corrects its own brightness only. In testing, one picked light grey
   left b* +4.7 on a warm subject (its cast read b* +14 at L* 92 but +20-24 at L* 59-79), where the automatic estimate
   left 0.0.
3. The same frame from another shot (a tripod series, a burst): cut the subject in that frame and keep the frame's
   size; `--same-frame` then keeps it in place.

## Step 2: place it

Work in a folder under the home directory (`~/.photocraft-skill/work/<plate>/`). Read the plate's coordinates with
`grid.py plate.jpg 0 0 grid.png --step 100` and decide:
- `--at X,Y`: where it stands: the bottom centre of the visible element (`--anchor bottom`, the default) on the
  ground in the plate, or its centre (`--anchor center`).
- the size: `--height H` or `--width W` in plate pixels (the visible element), or `--scale S`. From the perspective
  rules above. Enlarging more than 1.05x is reported: it softens the element.
- what stands in front of it: a chair leg, a railing or a branch in the plate that should pass in front is masked out
  of the element after the build (Step 4).
- a cut cut off by its own frame (a half-length portrait) must leave the plate on that side too: the plan warns when
  a cut-off side lands inside the plate, where it would show as a straight edge.

**Camera height and view angle.** A packshot taken from above shows its top; a room photographed from eye height sees
a chest's top at a shallow angle. Estimate both angles before placing:
- The plate: the angle its camera looks down at the spot, theta = atan((y - cy) / f) - pitch, with the camera's pitch
  and 35 mm focal length from `straighten.py plate.jpg <dir>` (`verticals.pitch`, positive when the camera looks up:
  +37.6 on a tower shot from below; `focal35`; f in pixels = focal35 x the long side / 36), y the spot's row and cy
  the centre row.
- The element: a round feature on its top (a lid, a button, a logo ring) is an ellipse whose height over width is
  sin theta; a square top's visible depth over its width the same. Or `straighten.py` on the packshot.

A top is foreshortened by sin theta and a front by cos theta: from 30 degrees a top shows at 0.50 of its depth and a
front at 0.87 of its height; at 14 degrees 0.24 and 0.97. No single scale fits both. Squashing the cut to 85 % (what an
end-to-end test tried: a console shot from about 30 degrees on a chest seen at about 14) still shows 1.8x the top the
room's camera could see, and makes the front 24 % too short. Put the element where the plate's camera sees a surface
at about its angle (lower in the frame is steeper), or reshoot it at the plate's. Never squash or stretch a product
a client sells: its proportions are part of what is sold.

## Step 3: plan the match

    python3 composite.py plate.jpg cut.png ~/.photocraft-skill/work/<plate>/comp --at X,Y --height H \
        [--shadow contact] [--occlusion 0.45] [--blur auto] [--ref-area AREA] [--name "N64 console"]

It scales the cut with photocraft-cli (premultiplied resampling: edges stay clean), converts it to the plate's colour
profile when they differ (an Apple RGB studio shot into an sRGB plate), and works in a frame: the element plus a
margin of 12 % of its size. It measures and plans:

- **Black and white points.** The darkest and lightest 0.5 % of the plate outside the element's alpha grown by 2 px
  (or inside `--ref-area`), and of the element. Its alpha, not its box: the box of a table hid the plate between its
  legs, which left only a strip of floor to measure (black 77, a false "no deep shadows" warning) where the room's dark
  furniture (10) and window (251) showed between them. Blacks move only if both have real blacks (element darkest
  under 60, plate under 45: a white product has no black to match, and a plate without deep shadows has no black
  level). Each channel moves by the plate's black
  less the element's black level, so a neutral black takes the plate's tint and a navy one stays navy. Whites move in
  level only, and only if both have whites (element over 220, plate over 230): on a grey backdrop scene the plate's
  brightest was a table at 185, and matching it pulled a white shirt down 58 levels. `--tones contain` moves only blacks
  deeper and whites brighter than the plate's; `--tones none` leaves both.
- **Colour.** What a neutral looks like in each: the dominant colour of smooth, low-chroma surfaces (the estimate
  `color_check.py measure` uses). The element's goes to the plate's, per channel in linear light, luminance kept
  (`--harmonize`, default 1). `--plate-neutral X,Y` and `--element-neutral X,Y` (the latter in the CUT's pixels)
  replace the estimates. Gamma and exposure aren't measured: `--gamma` and `--ev` are your call, by eye.
- **Grain.** The noise floor of both: imgops.grain's statistic in every 8x8 block, the quietest fifth of the blocks,
  so knitwear, foliage and leather don't count as grain. On a textured element it recovered added noise of sigma 1, 2
  and 4 as 1.03, 2.00 and 3.89; a grassy meadow read 1.4 where the whole-image statistic read 3.3. The missing grain
  (sigma sqrt(plate^2 - element^2) / 0.943) goes on the Grain layer; on the test shoe the element read 1.66 against the
  plate's 1.44 afterwards (0.58 before).
- **Sharpness.** Edge softness on both, as the sigma of a Gaussian edge (contrast over the steepest slope across
  contrasty edges with flat sides). The suggestion is the blur that makes the element's edges measure like the
  plate's, found by blurring the element and measuring it again (the same measure on both sides, so its own bias
  cancels), to a tenth of a pixel: with "plates" made by blurring a sharp shoe by 0.5, 0.8, 1, 1.5, 2 and 3 px it found
  exactly those, where the quadrature of the two readings, sqrt(plate^2 - element^2), said 0.78, 1.08, 1.33, 2.06,
  2.80 and 3.78. `--blur auto` bakes it into the element layer with an exact Gaussian (sigma within 1 % from 0.2 to 2
  px; an earlier three-box blur did nothing under 0.6 px, so a 0.5 px "applied" blur left the layer identical). On a
  console put on a room's chest the seams' sharpness ratio (`qc.py seams`) read 1.38 unblurred, 0.95 at the suggested
  0.9 px and 1.05 at 0.7. The warning stays whenever the applied blur is under three quarters of the suggestion or
  changed nothing. Only a clear difference counts (the plate's edges 1.3x the element's or more): they are different
  things, and in a same-frame test a backdrop and a table measured 0.70 against eyes and hair at 0.55 with the focus
  identical. In the app, the same as a smart filter on the element layer: `filter.convertForSmartFilters`, then
  `filter.blur.gaussianBlur {"radius": R}` (PhotoCraft's radius is about the sigma: radius 5 measured 4.7, 10
  measured 9.7). Too few contrasty edges near the element: no suggestion, judge by eye.
- **Light wrap.** `--wrap 0.35` (Screen), over `--wrap-width` px (1.5 % of the element's size) with the plate blurred
  by `--wrap-blur` (4 %). Measured on a studio portrait put on a bright sky: Screen at 35 % lifted the outer 1-3 px by
  21 levels where the plate behind was bright and by 1.8 where it was dark, the band 5-17 px in by 2, nothing deeper;
  at 3x the hard cut edge of the hair became a soft, light transition. Soft Light at 35 % moved them by 5.3, -0.9 and
  0.3 (barely visible); Screen at 60 % by 36.5, 3 and 3.4, which washed the hair out.
- **Contact shadow** (`--shadow contact`, `--shadow-strength 0.6`): a tight line along the lower convex hull of the
  silhouette (the chain at its bottom, which bridges the gap between legs) plus a soft spread, Multiply, in the
  ground's own colour (its median right under the base, taken down to a dark tone: a dark object nearby doesn't tint
  it), blurred as much as the element. On a table all of it lies at the two feet and none under the top; on a ball it
  sits under the contact, not across the ball's width. Not for a cut cut off at the bottom: it stands on nothing.
- **Occlusion shadow** (`--occlusion 0.45`): in soft light the ground darkens under everything near it, also where the
  element overhangs it, which a contact line at the feet leaves lit: a console's front between its feet, a sofa's
  underside, a shoe's arch. The silhouette squashed to a quarter of its height about the base line, blurred by 1.2 %
  of its width, Multiply in the same ground tone (a retoucher's hand-built occlusion shadow). On the test console the
  ground under its overhanging front (910 px, 6 px or more above the base line) went from 135 to 99 at 0.45, and the
  console sat on the chest instead of perching at 3x. For soft light (overcast, interiors lit by windows) and objects
  with an overhang or a gap under them; in hard sun, the cast shadow by hand instead.
- **The edge.** The share of edge pixels lighter (on a light old backdrop) or darker (on a dark one) than both the
  element just inside and the plate just outside: the old backdrop left in the cut's edge. Only the backdrop's polarity
  counts, read off the partly transparent edge pixels (how far they lean away from the colour just inside: +21 to +48
  on cuts from white sweeps) or given with `--old-backdrop light|dark`; light when the edge says nothing. A console cut
  from white had read a 20 % "dark rim", which was its own shadowed underside and black vents; now 0, its light rim
  1.4 %. A shoe cut from white reads 16.5 % light rim (white under the sole, gloss reflecting the sweep), a studio
  portrait's hoodie and hair 8.6 %. Over 8 % is reported; `edge_rim.png` marks the pixels (red light, blue dark).

Read the warnings, then look at `compare.png` (plate | pasted as is | composited) and `zoom.png` (3x tiles at the
element's top, sides and bottom, pasted | composited). `plan.json` has every number.

## Step 4: build it

    python3 import_layers.py ~/.photocraft-skill/work/<plate>/comp/layers.json        # live: the plate document active
    python3 import_layers.py …/comp/layers.json --file plate.jpg --out plate-comp.psd     # headless

The group goes on top of the stack; the import renders the frame and compares it with `preview.png`: expect
`"verify": "ok"` (the test composites matched to 0.011-0.013 levels on average, at most 1). PhotoCraft centres a
placed layer on its visible content, not on the PNG's canvas, so `element.png` carries two invisible corner pixels
(alpha 1/255, the plate's own colour) that pin it to the frame.

Something in the plate in front of the element: select it and hide it on the Element layer; its clipped layers follow
(tested: exactly the plate shows there). Mask the Contact shadow too where the object covers it.

    $PC exec select.lasso '{"points": [[x, y], …]}'
    $PC exec layer.layerMask.hideSelection '{"layer": <Element id>}'

## Step 5: what the numbers can't do

Say it to the user rather than hoping: the light's direction and hardness, perspective and scale. Look at the
element's shadows against the plate's (a soft studio face on a meadow with long, hard shadows stays pasted), at its
size against nearby things, and at the horizon. A cast shadow (sun from one side) is drawn by hand, as above.

## Step 6: check like a compositor

    $PC export ~/.photocraft-skill/work/<plate>/now.png         # headless: render the PSD with pc.py cli convert
    $PC cli run now.png --cmd image.crop --params '{"x":FX,"y":FY,"width":FW,"height":FH}' --out frame.png
    python3 qc.py seams frame.png comp/element_mask.png comp/seams --composite --origin FX FY

`FX FY FW FH` is `frame` in plan.json. Then:
- At 1x: same light direction, same sharpness, same colour of light; it stands on the ground.
- At 3x along every edge: no light or dark rim, no straight cut, no gap between element and contact shadow; hair
  tips softened by the wrap, not glowing.
- At 100 % inside: grain like the plate's beside it.
- The group switched off and on once.

## Save

- Layered: `app.save {"path": "…/photo-composite.psd"}`, a new name next to the plate.
- Deliverables: `deliver.py photo-composite.psd <out> --preset web` (`references/deliver.md`). A plain JPEG keeps the
  plate's camera EXIF (make, model, date: the end-to-end test's said a 2015 bridge camera), so the composite would
  present itself as that camera's original; deliver.py's screen presets keep only the creator and the copyright.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| "a light rim on N % of the element's edge pixels" | The cut's old backdrop is still in its edge | Decontaminate the cut (`references/cutout.md`), recheck with `cutout_check.py`, plan again |
| Rim pixels marked on the object's own dark underside, vents or outline (`edge_rim.png`) | The old backdrop was read, or given, as dark | `--old-backdrop light` when it was a light sweep; a good cut needs no change |
| "cut off at its bottom but that side lands inside the plate" | A cut that ends at its own frame | Place that side at the plate's edge, or behind something in the plate |
| Blacks lifted more than 25 levels (warning) | The plate has no dark things, so its darkest tone isn't a black level | `--tones contain` or `none`; judge the shadows by eye |
| "the plate's blacks are clipped" | Its darkest tones are 0 | Right for that camera; the element's deepest shadows clip with them. `--tones none` keeps their detail |
| Element turns blue, green or orange | Its "neutral", or the plate's, was a coloured surface (a beige coat, golden fur, a warm wall); `light` in plan.json shows both | `--element-neutral` / `--plate-neutral` on a real white or grey, or `--harmonize 0.5` |
| "error: N % of the element lands outside the plate" | `--at` or the size put it off the plate (only its box overlaps) | Check `--at` against the plate's size, and the size |
| "error: the cut has no fully opaque pixel" | The layer was exported at partial opacity, or the cut is all soft edge | Export the masked layer at 100 % opacity |
| "the element measures noisier than the plate" | Real noise, or skin pores and fabric the noise floor still counts (a studio face read 2.8 against a sky's 1.3) | Compare at 100 %; noise: `filter.noise.reduceNoise` on the source, then cut again; texture: leave it |
| "crisper than the plate" (also after `--blur`) | Different focus or distance, or a blur under three quarters of the suggestion | `--blur auto`, or Gaussian Blur radius about sigma as a smart filter; Lens Blur for depth |
| Hair or fur glows | Wrap too strong for a very bright plate | `--wrap 0.2`, or `--wrap-blend softlight` |
| It floats | No contact with the ground | `--shadow contact`; for sunlight, a cast shadow by hand |
| It perches: the ground under its front or between its feet stays lit | Soft light reaches under an overhang in the photo, not in the composite | `--occlusion 0.45` |
| Its top shows more (or less) of itself than the plate's camera could see | Different camera heights | Camera height section (Step 2): another spot, or reshoot; never squash the product |
| Looks pasted though the numbers agree | Light direction or hardness, perspective, scale | Step 5: another element, a mirrored one, or tell the user |
| A plate object should pass in front | Placement | `layer.layerMask.hideSelection` on the Element layer (Step 4) |
| Import "MISMATCH" | The document changed between planning and import, or a profile with no builtin twin | Plan on a fresh render; `edit.convertToProfile` to a builtin first |
