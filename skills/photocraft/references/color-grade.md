# Colour correction and grading: by the numbers

Read this before correcting white balance, fixing a cast, setting black and white points, matching shots or
applying a look. Correction is done by measurement: neutrals measured to grey, skin checked against the
vectorscope, clipping counted per channel. `scripts/color_check.py` does the measuring and writes the corrections
as Curves layers whose result it predicts exactly; `scripts/import_layers.py` builds them and checks the render.
Grading (the look) comes after, on its own layers, tested for what it does to skin and clipping.

## Contents
- What separates a professional colour job from a cheap one
- The layer stack you're building
- Step 1: measure
- Step 2: white balance
- Step 3: black and white point, contrast
- Step 4: the look
- Step 5: match a shot, or a series
- Step 6: black and white
- Check like a professional
- Save
- Tuning and false hits

## What separates a professional colour job from a cheap one

- **Correct first, then grade.** White balance, black and white points and contrast make the photo true; the look
  comes after. A look on top of a cast compounds it.
- **Numbers over eyes.** Eyes and screens adapt to a cast in seconds. Dan Margulis's "colour by the numbers":
  things that are neutral in life must read R = G = B (Lab a* = b* = 0). Measure them; don't judge by eye.
- **White balance from a real neutral, at several levels.** Grey card, white or grey clothing in the main light,
  concrete, asphalt, a white wall you know is white, shaded cloud. Never a coloured surface: a golden dog's fur
  used as "neutral" turned the dog grey-green (tested). Casts change with brightness: a camera's tungsten preset
  read b* -18 at a light grey, -32 at a mid grey and -18 at black on one colour chart, so one neutral corrects its
  own level and left the others 12-17 b* off. Use a dark, a mid and a light neutral when the photo has them.
- **Keep the light that's meant to be there.** Golden hour, candlelight, a cosy tungsten room: correct partially
  (amount 0.5-0.8) or not at all. Memory colours (golden fur, skin, a sunset) must stay warm.
- **Skin is the cross-check, not the reference.** Skin of every complexion lies near the vectorscope's I line,
  the "skin-tone line" (Kdenlive's scope docs), at about 123° (the YIQ I axis, 33° past R-Y). Measured here: a
  studio portrait with a neutral chart 116°, golden-hour skin 115°, its skylit shadow side 110°. Practitioners
  note skin varies around the line, and forcing it onto the line can look too yellow (pixls.us ART thread). And a
  warm cast put pale skin at 125°, right on the line, while the chart's greys read b* +14 to +24. So use neutrals
  to correct; then check that skin sits in roughly 110-130° and that no grade moves it by more than about 5°.
- **Black and white points without clipping.** Count clipped pixels per channel: a warm push clips red first
  (2.9 % of one portrait). Specular highlights may clip; skin and white clothing may not.
- **Contrast without colour shifts.** A Curves S in Luminosity blend adds contrast without the saturation jump
  of a Normal-mode S. Vibrance before Saturation: Adobe documents that Vibrance protects skin tones.
- **Looks are subtle and checked.** Partial opacity, skin angle and clipping measured after each one. Black and
  white through a channel mix chosen for the subject, never plain desaturation (flat grey, no separation).
- **Consistency.** The same light gets the same correction: apply the same layers to every photo of that light.
- **Non-destructive and named.** Curves and adjustment layers in groups ("Colour correction", "Look") above the
  untouched original, so the user can switch each part off.

## The layer stack you're building

    Look                       group (optional): Color Lookup at 30-50 %, Color Balance, Vibrance, Curves
    Second light               group (mixed light only): White balance masked to that light's area
    Colour correction          group
      Black & white point      Curves composite, straight line (color_check.py correct --tone)
      White balance            Curves red/green/blue through the neutrals (color_check.py correct)
    Background                 original, untouched

## Step 1: measure

Work in a folder under the home directory (the app only opens files under its read root). Render the current state
(live: `$PC export ~/.photocraft-skill/work/<photo>/now.png`; headless: the original file works as it is).

    python3 color_check.py measure now.png --viz viz.png --scope scope.png [--skin skin.json]

Big images are measured on a 1200 px copy; every coordinate in and out is in full-image pixels. Read:
- `clippedHigh%` / `clippedLow%` per channel, `luminance%` (0.1, 1, 50, 99, 99.9 percentiles).
- `castEstimate`: the dominant smooth low-chroma colour (what a neutral looks like under this light, if the photo
  has neutrals) with its `candidates` (centre and radius, ready for `--neutral`), and a grey-edge estimate
  (van de Weijer et al.), which is usually 2-3x too weak but points the same way. The two disagreeing (a warning)
  means the dominant "neutral" is a coloured surface (fur, beige stone, a painted wall) or the light is mixed. It
  fired on those three test photos and stayed quiet on five studio shots where the estimate matched the chart.
- `viz.png`: clipped highlights red, clipped shadows blue, candidates cyan, neutral samples green, skin yellow.
  `scope.png`: a vectorscope; anything that should be neutral belongs at the centre, skin along the line.
- `skin` (with an area.json from `grid.py`, or a rectangle `x0,y0,x1,y1`): angle, offset from the line,
  saturation, Lab. Measure lit and shadow sides separately when the light differs.

Look at every candidate before trusting it. Then sample the real neutrals you found:
`measure now.png --neutral X,Y,R --neutral …` gives each patch's Lab and cast, and warns on clipped patches.
For a Display P3 document (`edit.profileInfo {"profile": "document"}` says so) pass `--space p3` for Lab numbers.

## Step 2: white balance

    python3 color_check.py correct now.png ~/.photocraft-skill/work/<photo>/wb \
        --neutral X,Y,R --neutral X,Y,R [--black X,Y,R] [--amount 0.7] [--skin skin.json]
    python3 import_layers.py ~/.photocraft-skill/work/<photo>/wb/layers.json            # live
    python3 import_layers.py …/wb/layers.json --file photo.jpg --out photo-corrected.psd  # headless

Each neutral goes to grey at its own luminance (so brightness doesn't change); `--black` is a dark neutral, and
`--black-level` / `--white-level` also move it to a level. Between the neutrals each channel's curve is piecewise
power: tested on a chart, two neutrals (light and dark) left the greys between within 6 b*, where a natural
spline through the same points swung the mid grey to b* +31. The import renders, crops and compares with
`preview.png`: "verify ok" means PhotoCraft matches the prediction (mean 0.0, at most 1 level in every test).

Read the output: each reference `before` / `after` (|a*|, |b*| ≤ 0.5 at amount 1), `skinBefore` / `skinAfter`,
clipping after, and the warnings: one reference only; references at the same level that disagree (one isn't
neutral, or a second light); a channel moving more than 40 levels (see 16-bit in the tuning table). Look at
`before_after.png`. The tungsten studio test: four chart greys plus the black patch took the greys from b* -18…-32
to ≤ 0.4, the white patch (not used) from -9.3 to -3.6, skin from 341° (blue) to 126°.

- **No usable neutral** (everything bright clipped, only coloured surfaces): correct by eye on memory colours,
  partially. Photo Filter `{"filter": "cooling82", "density": 25, "preserveLuminosity": true}` took a tungsten room's
  carpet from b* 31 to 26 and kept the dog golden; `warming85` the other way. Or Camera Raw as a smart filter
  (`filter.convertForSmartFilters`, then `filter.cameraRaw {"temperature": -20, "tint": 0}`; about 2 b* per 10
  units on mid greys), which stays re-editable: `layer.smartFilter.setParams {"index": 0, "params": {…}}`.
- **Two lights** (window daylight and tungsten, flash and ambient): correct the main light first, import, export
  again, then a second layer for the other light, masked to where it falls:

      color_check.py correct now2.png …/wb2 --neutral X,Y,R --area window.json --feather 60 \
          --name "White balance (window)" --group "Second light"

  `--area` is an area.json or a rectangle; the mask is feathered by `--feather` px. Tested on a composite of a
  fluorescent and an incandescent half: both backdrops from b* +3 / +24 to within 0.5, no seam.

## Step 3: black and white point, contrast

- `correct … --tone` adds "Black & white point": a straight composite curve taking the darkest and lightest
  `--clip` % (0.05) of every channel to 4 and 251. It is measured per channel, because measuring luminance let the
  red of warm highlights clip 0.9 %. An end that already reaches 0 or 255 stays put, and speculars can still reach 255.
- Exposure: a composite midpoint, e.g. `layer.newAdjustmentLayer.curves {"points": [[0,0],[110,128],[255,255]]}`
  lifts the midtones (check `luminance%` 50 before and after).
- Contrast: `{"points": [[0,0],[64,60],[128,128],[192,197],[235,238],[255,255]]}` then `layer.setProps
  {"blend": "Luminosity"}`. On a real landscape it added 0.2 % highlight and 0.3 % shadow clipping. Luminosity
  mode brightens saturated colours until a channel hits 255: a saturated synthetic sky went from 2.3 % to 8.5 %
  clipped. Check `clippedHigh%` after any contrast curve; mask it off saturated areas, or lower the 192 point.

## Step 4: the look

Grade after correction, on its own layers. Each recipe below was rendered on a balanced studio portrait, a
golden-hour portrait and a landscape and measured with `color_check.py compare`:

| Look | Layers (exact params) | Measured |
|---|---|---|
| Clean & punchy | Curves contrast as in Step 3 (Luminosity) + `vibrance {"vibrance": 15}` | skin ±0.3°, clipping +0.2 % / +0.3 % |
| Warm & soft | `photoFilter {"filter": "warming85", "density": 12, "preserveLuminosity": true}` + Curves `[[0,10],[128,130],[255,250]]` | skin +0.6°, greys b* +1, whites end at 250 |
| Teal & orange | `colorLookup {"lut": "tealOrange"}`, opacity 0.4 | skin +1.3…+3.8°, highlights b* +3, no new clipping |
| Faded film | Curves `[[0,24],[60,64],[128,128],[200,206],[255,242]]` + `vibrance {"vibrance": -10}` + `colorBalance {"shadows": [0,0,6], "highlights": [2,0,-2], "preserveLuminosity": true}` | chroma -2…-25 %, pale skin +4.5° |
| Moody | `hueSaturation {"saturation": -20}` + Curves `[[0,6],[128,114],[255,248]]` + `colorBalance {"shadows": [-6,0,6]}` | skin ±0.8°, median -10 levels |
| Bleach bypass | `colorLookup {"lut": "bleachBypass"}`, opacity 0.4 | skin saturation -30 %, angle stable |

(Layer kinds are `layer.newAdjustmentLayer.<kind>`; opacity and blend with `layer.setProps` on the new layer.)
The same teal & orange from Color Balance (`shadows [-5,0,8]`, `highlights [5,0,-6]`) crushed a navy shirt (1.5 %
of pixels to red 0) and clipped cloud highlights 2 %: the lookup at 40 % is safer. `image.adjustments.colorLookup.list`
names the other built-in looks (warm, cool, fadedFilm, dayForNight, monoContrast, crossProcess). Pale,
low-saturation skin (vectorscope saturation under ~25) turns several degrees for a small change: judge it by eye too.

## Step 5: match a shot, or a series

- **Same light:** reuse the correction. `import_layers.py …/wb/layers.json --file next.jpg --out next-corrected.psd
  --no-verify` for each photo (the verify crop belongs to the first). Identical layers give a consistent set.
- **Different shot, same look wanted:**

      color_check.py match target.png reference.png …/match --area A --ref-area A \
          [--skin S --ref-skin S --anchor-skin] [--amount 0.8]

  Per-channel quantile matching, fitted to a few points per channel. It recovered a known film grade to 0.4-0.8
  levels on average, and matched a "cloudy" white balance to the neutral one with the greys within 2.6 of neutral.
  Content that differs gets "corrected" too: a lamp in one shot pushed the greys to b* -17 and skin to 94°.
  Restrict both statistics to shared content (`--area`, `--ref-area`: greys within 3, the black patch 4.7), and for
  portraits pin skin (`--anchor-skin`: skin 115.5° against the reference's 115.9°). `match.png` shows
  before | after | reference.
- `image.adjustments.matchColor` exists, but it is destructive; run it on a duplicate layer if the user wants it.

## Step 6: black and white

Convert with a Black & White adjustment layer whose weights suit the subject, then a contrast curve:

| Subject | `layer.newAdjustmentLayer.blackWhite` | Then | Measured |
|---|---|---|---|
| Portrait | `{"reds": 70, "yellows": 80, "greens": 40, "cyans": 60, "blues": 20, "magentas": 80}` | Curves `[[0,0],[64,56],[192,200],[255,255]]` | skin light, no clipping |
| Landscape, dark sky (red filter) | `{"reds": 100, "yellows": 100, "greens": 0, "cyans": -30, "blues": -30, "magentas": 100}` | Curves `[[0,0],[64,58],[192,198],[235,238],[255,255]]` | image median 121 → 102 (the sky darkens), no new clipping |
| Landscape, milder (yellow filter) | `{"reds": 70, "yellows": 90, "greens": 50, "cyans": 20, "blues": 0, "magentas": 70}` | same | median 121 → 112 |

Weights above 100 on the dominant colour clip: a stronger red filter (120/110/-10/-50/-50/120) clipped 1-2 % of a
portrait at each end and blew its skin. `image.adjustments.desaturate` gives flat grey; don't. A tint: `"tint": true,
"tintColor": "#rrggbb"` on the same layer, or a Gradient Map.

## Check like a professional

    python3 color_check.py compare before.png after.png --neutral X,Y,R … --skin skin.json

- True neutrals |a*|, |b*| ≤ 2 after correction (≤ 0.5 at amount 1); any warmth left is a deliberate amount.
- Skin 110-130°, and moved by a look ≤ 5° (`skin` before/after); lit and shadow sides each plausible.
- Clipping per channel no higher than before beyond speculars (+0.1 % budget), at both ends.
- Memory colours: sky blue (not cyan or purple), foliage yellow-green, skin neither orange nor magenta.
- No banding in skies and backdrops at 100 %; the scope's neutral cloud at the centre.
- Before/after at fit and at 100 %; each group switched off once.

## Save

- Layered: `app.save {"path": "…/photo-graded.psd"}` (new name next to the original).
- JPEG: `$PC cli convert photo-graded.psd photo-graded.jpg --quality 95` (`app.save` ignores quality; the profile is kept).
- For the web, convert a wide-gamut document to sRGB on a copy first: `image.duplicate`, then
  `edit.convertToProfile {"profile": "srgb"}`, then export. Assigning a profile changes the colours; converting keeps them.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Candidates on fur, a wall, wood, sand | The dominant low-chroma surface is coloured | Pick real neutrals by eye; the grey-edge warning flags most of these |
| Subject turns grey-green or grey-blue | A coloured surface was used as `--neutral` (glass, fur) | Check each sample's `cast` against what it is in life; resample |
| "one reference" warning, other levels off | Casts vary with brightness | Add a darker and a lighter neutral |
| "same level but … apart" | One sample isn't neutral, or two lights | Drop the odd one; second light → `--area` layer |
| Points dropped to keep curves monotone | References contradict (brighter input → darker target) | Same as above |
| Corrected photo looks darker than expected | Correction keeps each neutral's luminance | `--tone`, or a midtone curve |
| Saturated colours a bit too red after a big correction | Curves on a rendered JPEG are not raw white balance (the camera's colour matrix) | `hueSaturation` reds -5…-10, or Vibrance -5; check skin |
| Shadows still tinted | No dark neutral; the black end is pinned | `--black` on a dark neutral |
| "a channel moves 40+ levels" | Very strong cast | One curve showed no banding in 8-bit; stacks of strong layers round between each other in 8-bit, so `image.mode.bits16` first |
| Match turns skin pink, greys blue | Different content in the two shots | `--area` / `--ref-area` on shared content; `--anchor-skin` |
| Highlights greyer after a match | The target's clipped channel compresses the top of the curve | `--amount 0.8`, or accept; speculars can't be recovered |
| Teal shadows crush dark clothing | Color Balance shadows pull red to 0 | Color Lookup tealOrange at 40 %, or a smaller shift; watch `clippedLow%` |
| Black & white clips or skin glows | Channel weights over 100 | The softer weights above; check clipping |
| Skin angle jumps on a pale face | Low saturation: small chroma change, big angle change | Judge by eye; compare `lab` before/after |
