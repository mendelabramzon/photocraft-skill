# Colour correction and grading: by the numbers

Read this before correcting white balance, fixing a cast, setting black and white points, matching shots, applying a
look or adding local contrast. Correction is done by measurement: neutrals measured to grey, skin checked by its Lab
numbers and on the vectorscope, clipping counted per channel. `scripts/color_check.py` does the measuring and writes
the corrections as Curves layers whose result it predicts exactly; `scripts/import_layers.py` builds them and checks
the render. Grading (the look) comes after, on its own layers, tested for what it does to skin and clipping.

## Contents
- What separates a professional colour job from a cheap one
- The layer stack you're building
- Step 1: measure
- Step 2: white balance
- Step 3: black and white point, contrast
- Step 4: the look (local contrast at its end)
- Step 5: match a shot, or a series
- Step 6: black and white
- Check like a professional
- Save, and colour management
- Tuning and false hits

## What separates a professional colour job from a cheap one

- **Correct first, then grade.** White balance, black and white points and contrast make the photo true; the look
  comes after. A look on top of a cast compounds it. Dan Margulis's order: fix colour by the numbers, add contrast
  without changing colour, then add colour.
- **Numbers over eyes.** Eyes and screens adapt to a cast in seconds. Margulis's "colour by the numbers": things that
  are neutral in life must read R = G = B (Lab a* = b* = 0). Measure them; don't judge by eye.
- **White balance from a real neutral, at several levels.** Grey card, white or grey clothing in the main light,
  concrete, asphalt, a white wall you know is white, shaded cloud. Never a coloured surface: a golden dog's fur
  used as "neutral" turned the dog grey-green (tested). Casts change with brightness: a camera's tungsten preset
  read b* -18 at a light grey, -32 at a mid grey and -18 at black on one colour chart, so one neutral corrects its
  own level and left the others 12-17 b* off. Use a dark, a mid and a light neutral when the photo has them.
- **A chart when colour has to be right.** A ColorChecker in the first frame turns "looks right" into ΔE per patch
  against published values, the way product colour is judged against a physical swatch with a set tolerance, and it
  fixes what a white balance can't: the hues a camera's rendering turned at the wrong white balance.
- **Keep the light that's meant to be there.** Golden hour, candlelight, a cosy tungsten room: correct partially
  (amount 0.5-0.8) or not at all. Memory colours (golden fur, skin, a sunset) must stay warm.
- **Skin is the cross-check, not the reference.** Two checks, on a well-lit facial midtone, never a skin average
  (Dehancer's *Lifelike* measured 20a/17b on a cheek and -3a/-25b on a hand in one frame):
  - *Hue:* skin of every complexion lies near the vectorscope's I line, the "skin-tone line" (Kdenlive's scope docs),
    at about 123° (the YIQ I axis); Dolby's ICtCp data puts most people within ±10° of the average. Measured here: a
    studio portrait with a neutral chart 116°, golden-hour skin 115°, its skylit shadow side 110°. Forcing skin onto
    the line can look too yellow (pixls.us ART thread).
  - *Magnitude and balance (Lab):* Margulis: "The face, being red, needs to be positive in both A and B". Dehancer's
    chapter after him: midtone a* and b* typically 15-20, under 15 reads pale, over 30 oversaturated, and b* a little
    above a* reads healthy, a* above b* red or "burned" (normal for babies, the elderly and redheads). The angle alone
    misses a cast along the line: the same studio portrait shot with a camera's warm preset put skin at 128°, inside
    110-130°, while its b*/a* read 2.2 and the chart's greys b* +14 to +24.
  So correct from neutrals, then check that skin sits at roughly 110-130° with plausible Lab numbers, and that no
  grade moves it by more than about 5°. Every source calls these numbers starting points; per-ethnicity CMYK
  formulas are forum lore, and absolute targets per complexion risk stereotyping.
- **Black and white points by output, without clipping.** Count clipped pixels per channel: a warm push clips red
  first (2.9 % of one portrait). Specular highlights may clip; skin and white clothing may not. A print keeps its
  ends inside what paper holds (published targets around 7-10 and 243-245); a screen can use nearly all of 0-255.
- **Contrast without colour shifts.** A Curves S in Luminosity blend adds contrast without the saturation jump
  of a Normal-mode S (Chromasia). Vibrance before Saturation: Adobe documents that Vibrance protects skin tones.
  Local contrast ("clarity") goes on its own layer, masked off skin, which it would make gritty.
- **Looks are subtle and checked.** Partial opacity, skin angle and clipping measured after each one. Black and
  white through a channel mix chosen for the subject, never plain desaturation (flat grey, no separation).
- **Consistency.** The same light gets the same correction: apply the same layers to every photo of that light.
- **Non-destructive and named.** Curves and adjustment layers in groups ("Colour correction", "Look") above the
  untouched original, so the user can switch each part off.

## The layer stack you're building

    Local contrast             Stamp Visible + High Pass (desaturated), Overlay 50 %, mask = everything but skin
    Look                       group (optional): Color Lookup at 30-50 %, Gradient Map split tone, Color Balance,
                               Vibrance, Curves (Lab colour boost: a/b curves)
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
- `skin` (with an area.json from `grid.py`, or a rectangle `x0,y0,x1,y1`): the median skin's angle, offset from the
  line, saturation and Lab, and `litMidtone`: the same on the lit midtone only (the area's 50th-90th luminance
  percentile, so the shadow side, hair and brows below it and the speculars above it drop out), with `chroma`, `bOverA`
  (null when a* or b* is 2 or less: no ratio to read) and a `labVerdict`: pale under 10 (not Dehancer's 15: a correctly
  balanced light-skinned studio portrait read a* 14.5), oversaturated over 30, red below b*/a* 0.8, yellow above 1.5, a
  cast when a* or b* is near zero or negative. Draw the area over cheeks, forehead and chin; a rough box over the whole
  face works too (one read b*/a* 1.41 as a median, 1.22 on its lit midtone, 1.09 on the cheeks alone).

What the lit midtone read on eight correctly balanced portraits, and on one of them shot with wrong camera presets:

| Portrait | a* | b* | b*/a* | Angle | labVerdict |
|---|---|---|---|---|---|
| Studio, medium skin | 20.5 | 21.2 | 1.03 | 116° | typical |
| Studio, light skin | 14.5 | 17.2 | 1.18 | 118° | typical |
| Studio, ruddy face | 18.8 | 11.7 | 0.62 | 109° | red (and the angle says pinker) |
| Daylight, dark skin | 19.0 | 16.3 | 0.86 | 113° | typical |
| Daylight, freckled | 20.6 | 16.3 | 0.79 | 112° | red, borderline |
| Golden hour | 27.7 | 28.1 | 1.01 | 116° | typical |
| Child in low sun | 27.5 | 37.6 | 1.37 | 121° | oversaturated: warm light |
| High-key studio, fair skin, chart neutral | 6.4 | 6.9 | 1.08 | 116° | pale: the light and complexion, not a cast |
| Same, camera set to tungsten | 1.8 | -14.1 | null | 333° | not red-yellow: a cast |
| Same, camera set to warm | 11.3 | 25.0 | 2.22 | 128° | yellow (the angle alone passes it) |
| Same, camera set to cloudy | 14.4 | 19.7 | 1.37 | 120° | typical: only the chart's greys (b* +6 to +18) show this cast |

So a verdict is a question, not a fix: a pale, red or oversaturated reading with neutral greys is the person or the
light; the same reading with greys off is the cast. And skin can pass while the greys fail (cloudy), which is why
neutrals correct and skin only checks. One more case: after a big correction the greys can be right and skin still
read yellow. That is the camera's colour rendering at the wrong white balance, which curves can't undo (Step 2,
"Camera colour from a chart").

Look at every candidate before trusting it. Then sample the real neutrals you found:
`measure now.png --neutral X,Y,R --neutral …` gives each patch's Lab and cast, and warns on clipped patches.
For a Display P3 document (`edit.profileInfo {"profile": "document"}` says so) pass `--space p3` for Lab numbers
(before or after the subcommand, as `--max-side` too).

## Step 2: white balance

    python3 color_check.py correct now.png ~/.photocraft-skill/work/<photo>/wb \
        --neutral X,Y,R --neutral X,Y,R [--white X,Y,R] [--black X,Y,R] [--amount 0.7] [--skin skin.json]
    python3 import_layers.py ~/.photocraft-skill/work/<photo>/wb/layers.json            # live
    python3 import_layers.py …/wb/layers.json --file photo.jpg --out photo-corrected.psd  # headless

Each neutral goes to grey at its own luminance (so brightness doesn't change); `--black` is a dark neutral, and
`--black-level` / `--white-level` also move it to a level. Between the neutrals each channel's curve is piecewise power:
tested on a chart, two neutrals (light and dark) left the greys between within 6 b*, where a natural spline through the
same points swung the mid grey to b* +31. Curve points are whole levels, as a PSD stores them (fractional ones reopened
up to 1 level off): the references still land within 0.5 a*b* (0.7 on a near-black patch, where one level is a bigger
step), and a saved PSD renders exactly as previewed (tested: max difference 0). The import renders, crops and compares
with `preview.png`: "verify ok" means PhotoCraft matches the prediction (mean 0.0, at most 1 level in every test).

Read the output: each reference `before` / `after` (|a*|, |b*| ≤ 0.5 at amount 1), `skinBefore` / `skinAfter`, clipping
after, and the warnings: one reference only; references at the same level that disagree (one isn't neutral, or a second
light); a channel moving more than 40 levels (see 16-bit in the tuning table). Look at `before_after.png`. The tungsten
studio test: four chart greys plus the black and white patches took the greys from b* -18…-32 to within 0.5 and skin
from 341° (blue) to 127°, b*/a* 2.3. The same scene shot with the right white balance reads 116°, b*/a* 1.0: the greys
are right and the skin is still too yellow. A camera renders colour after its white balance, so a JPEG shot at the wrong
one has its hues turned as well (the chart's colour patches read 10° off on average after the correction, light skin
+15°, dark skin -7°), and per-channel curves only move each channel by its own value. The fix is below.

- **A white or black reference with one clipped channel** is kept. A strong cast clips one channel of the whites
  first (red under warm light, blue under a tungsten preset) and one of the blacks; that channel reads 255 (or 0)
  however bright the patch really is, so no point through it can move it to grey. The end of that channel's curve
  does, as the Curves white and black eyedroppers do: it is placed so the patch lands on its target, extrapolated
  from the next reference (a patch only partly clipped keeps its measured value). The output says which channel and
  that detail beyond the patch in that channel is gone. Only for `--white` / `--black`, and only with one channel
  clipped; a mid neutral with a clipped channel is still left out. Tested:
  - A balanced chart portrait given a strong warm cast (red clipped in 4 % of the photo, blue crushed in 12 %):
    the white and black patches used to be dropped and ended b* +9.7 and +21.2; now +0.0 and +0.7. Mean ΔE to the
    original went from 8.3 to 5.3, in the crushed shadows from 18.0 to 5.6, and no blue stays clipped (was 9 %).
  - The same scene shot with a camera's warm, cloudy and tungsten presets (red clipped in 94 % and 90 % of the white
    patch, blue in 10 %): white patch b* +3.4, +2.3 and -6.2 before, within 0.25 a*b* now; red clipping after the warm
    correction 2.5 % → 0.
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

### Camera colour from a chart

A camera renders colour after its white balance, so a JPEG shot at the wrong one keeps hues the curves can't reach.
When an X-Rite ColorChecker Classic is in the shot, or in a frame shot in the same light, measure it after the white
balance and let it fix the rest:

    python3 color_check.py chart now.png ~/.photocraft-skill/work/<photo>/chart --corners X,Y X,Y X,Y X,Y \
        [--skin face.json --area face.json] [--fit lab|hue|none]
    python3 import_layers.py …/chart/layers.json            # above the colour correction

- `--corners`: the centres of the dark skin, bluish green, black and white patches, clockwise from dark skin whichever
  way up the chart is; the other patches are placed between them. Each is sampled on a disk of 0.22 x the patch pitch
  (specks ignored) and compared with X-Rite's published values (the formulation made since November 2014) by CIEDE2000:
  `dE00`, `dE00colour` (at the measured lightness, so exposure and the camera's tone curve don't count) and, for the
  colour patches, the hue error. `chart.png` shows each patch as measured | after the mixer | X-Rite's value. It
  refuses a bottom row that doesn't step from white to black (corners in the wrong order), warns when the chart's
  greys are more than 2 a*b* off (run `correct` first) and leaves clipped patches out of the fit.
- The fix is a Channel Mixer layer whose rows add up to exactly 100 % in whole percents, so greys stay grey and a PSD
  keeps it as planned (a PSD stores the mixer in whole percents: 33.33 x 3 reopens as 99 %, the photo 1.3 levels
  darker). It is solved for X-Rite's colours at the camera's lightness (`--fit lab`; `hue` matches only the hues,
  `none` only measures). PhotoCraft's mixer is round(Σ weight x value / 100), so `preview.png` is exact (imports
  verified at mean 0.007 and 0.06, max 1 level).
- `--skin`: the subject's skin is reported before and after, and the chart's skin patch nearer to it carries
  `--skin-weight` (3). Browns elsewhere (hair, wood, leather) are measured too; when the mixer turns them redder it
  says so: then mask it to the skin with `--area` (the whole face and other skin, feathered over `--feather` 30 px).
- A chart frame shot first in the same light: plan on it, then import the same layers.json into every frame of that light
  (`--no-verify` on the others), as with the white balance.

On the tungsten test, against the same scene shot at the right white balance (ΔE00 on the face, the hair and the whole
frame), after the curves of the white balance:

| Then | Face (lit midtone) | Face | Hair | Frame | Chart's colour patches |
|---|---|---|---|---|---|
| nothing | 127°, b*/a* 2.28 | 5.8 | 6.5 | 5.6 | ΔE00 6.2, hue error 10.3° |
| `chart`, whole photo | 123°, 1.65 | 4.7 | 6.7 | 5.5 | 4.1, 6.3° |
| `chart --skin face.json --area face.json` | 121°, 1.47 | 4.7 | 6.5 (untouched) | 5.6 | 4.0, 6.0° |
| `chart --skin face.json`, whole photo | 121°, 1.47 | 4.7 | 7.7 (browns 44° → 37°: warned) | 5.7 | 4.0, 6.0° |
| no chart: Hue/Saturation, yellows hue -10, on the face | 124°, 1.77 | 5.5 | 6.5 | - | - |

So for a portrait, fit with `--skin` and mask the mixer to the skin, as the brown warning says; for products and
scenes without people the whole-photo fit improved the frame overall. A chart recovers part of the error, not all of
it: at the right white balance the face reads 116°, b*/a* 1.0. The full fix is to develop the raw again with the right
white balance (LightCraft, the lightcraft skill in this plugin) when there is a raw.

Without a chart, move the skin on its own: a Hue/Saturation layer with a mask from `mask.py skin.json mask.png --size W
H --feather 30` (`"mask": "mask.png"` on the layer in a layers.json). Measured on the same face: yellows hue -10 →
123.7°, b*/a* 1.77, ΔE00 to the reference 5.8 → 5.5; a master hue of -5 → 122.0°, 1.58, ΔE00 5.8; -8 → 118.8°, 1.27, but
ΔE00 6.2, because a hue turn can't fix how the camera rendered lightness and chroma. Judge it by eye against the rest of
the photo.

## Step 3: black and white point, contrast

- `correct … --tone` adds "Black & white point": a straight composite curve taking the darkest and lightest
  `--clip` % (0.05) of every channel to the output's end points. It is measured per channel, because measuring
  luminance let the red of warm highlights clip 0.9 %. `--for` picks the end points:

  | `--for` | Black, white | Ends past the target | Why |
  |---|---|---|---|
  | `screen` (default) | 4, 251 | stay (only ever stretch) | rich black and white with texture; speculars can still reach 255 |
  | `print` | 8, 244 | pulled in too | paper and press hold detail only inside: Kelby (*Photoshop CC 2017 for Digital Photographers*) 7/245, his CS2 edition 20/244, Macworld 10/243, Curvemeister users 10-15/245 |

  The targets disagree by author and edition, so they are parameters: `--black-target` / `--white-target` override
  either preset. On the tungsten chart photo, `--for print` gave the curve `[[0, 8], [255, 249.7]]` (darkest 0 → 8,
  lightest 249 → 244, speculars now top out under 250) and nothing clipped. Make the print version a separate file
  from the screen one; at 8/244 a photo looks a little flat on a screen.
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
| Split tone (cool shadows, warm highlights) | `gradientMap {"stops": [[0.25, "#6480a0"], [0.5, "#808080"], [0.75, "#a08060"]], "dither": true}`, blend Soft Light, opacity 0.3 | greys within 1.1 a*b*, skin +0.7° (golden) and +3.1° (pale studio skin, b* +1.7), no new clipping; at 0.6 the pale skin moved 5.3° |
| Faded film | Curves `[[0,24],[60,64],[128,128],[200,206],[255,242]]` + `vibrance {"vibrance": -10}` + `colorBalance {"shadows": [0,0,6], "highlights": [2,0,-2], "preserveLuminosity": true}` | chroma -2…-25 %, pale skin +4.5° |
| Matte blacks | Solid Color `#4b4b4b`, blend Lighten, opacity 0.5 | black point (0.1 %) 16 → 46 on the portrait, 11 → 43 on the landscape; mean chroma 9-20 % lower (the shadows lose colour); skin and everything above 75 unchanged |
| Moody | `hueSaturation {"saturation": -20}` + Curves `[[0,6],[128,114],[255,248]]` + `colorBalance {"shadows": [-6,0,6]}` | skin ±0.8°, median -10 levels |
| Bleach bypass | `colorLookup {"lut": "bleachBypass"}`, opacity 0.4 | skin saturation -30 %, angle stable |
| Colour boost (Margulis, Lab) | Curves `{"a": [[12,0],[243,255]], "b": [[12,0],[243,255]]}` (a and b steepened 10 % through 128) | landscape chroma +10 %, 1.1 % of dark foliage newly blue-clipped; golden skin a*/b* 27.7/28.1 → 30.7/31.3 |
| Colour boost, portrait | Curves `{"a": [[6,0],[249,255]], "b": [[12,0],[243,255]]}` (a +5 %, b +10 %) | golden skin 28.9/31.2, +0.9°; pale studio skin +1.5° |

(Layer kinds are `layer.newAdjustmentLayer.<kind>` (`layer.newFillLayer.solidColor` for the matte); opacity and
blend with `layer.setProps` on the new layer.)
The same teal & orange from Color Balance (`shadows [-5,0,8]`, `highlights [5,0,-6]`) crushed a navy shirt (1.5 %
of pixels to red 0) and clipped cloud highlights 2 %: the lookup at 40 % is safer. `image.adjustments.colorLookup.list`
names the other built-in looks (warm, cool, fadedFilm, dayForNight, monoContrast, crossProcess). Pale,
low-saturation skin (vectorscope saturation under ~25) turns several degrees for a small change: judge it by eye too.

- **Split tone** (Matt Summerfield's Gradient Map method): Soft Light ignores 50 % grey, so the `#808080` stop leaves
  the midtones alone and the end stops tint only shadows and highlights. In PhotoCraft a Gradient Map maps by Rec.601
  luma (0.299/0.587/0.114, not the 0.3/0.59/0.11 of its blend modes), interpolates linearly in 8-bit sRGB values, and
  holds the first and last stop's colour beyond them. The stop colours above have a luma near 128, so they change hue
  more than brightness. `"dither": true` keeps smooth skies and backdrops from banding. Summerfield calls the full
  strength "often too strong": 0.2-0.3. To keep the warm highlights but spare the skin, give the layer a mask that
  is weaker there: `mask.py face.json mask.png --size W H --feather 30 --inside 0.3 --outside 1` prints the
  `"center"` for a layers.json whose gradient map layer takes `"mask": "mask.png"`. On a portrait the split tone moved
  the face +2.0° (b*/a* 2.32 → 2.66), with the face at 30 % +0.9° (2.48). Draw the area as the whole face, eyes and
  mouth inside: holes excluded from it count as outside, and their feather leaked full strength into the cheeks
  (+1.4°). Blend If (`layer.layerStyle.blendingOptions {"layer": <id>, "blendIf": {"channel": "gray", "underlying":
  [0, 0, 150, 210]}}`) is the other route, by tone instead of by place: it fades the layer out over light tones, which
  kept a pale face exactly as it was, but takes the warm highlights away everywhere, which is most of the look.
- **Matte blacks** (PetaPixel's #4B4B4B method): a Lighten fill raises only what is darker than 75 (per channel, so
  shadows also lose saturation) and leaves everything else exactly as it was. At opacity 1 every tone under 75 goes
  flat at 75: use 0.3-0.5. A Curves black lift does the same job but bends the curve above it: `[[0,32],[64,68],
  [255,255]]` also darkened the portrait's median 3 levels and the golden-hour skin 2.6 L* (a* +2.4); pin the
  midtones with more points (the Faded film curve) if you use one.
- **Colour boost** (Margulis, *Photoshop LAB Color*): steepen a* and b* symmetrically through neutral, so greys stay
  grey and every colour moves away from them. In PhotoCraft a Curves layer given `a` and `b` keys in an RGB document is
  a live Lab-space curve (`"space": "Lab"` in `document.inspect`; an identity curve renders the photo exactly), so no
  mode change is needed. Don't convert the document instead: an 8-bit RGB → Lab → RGB round trip moved pixels up to 16
  levels (16-bit: none). A straight line through (128, 128) with slope s is `[[128 - 128/s, 0], [128 + 127/s, 255]]`, in
  whole levels: `[[12,0],[243,255]]`, `[[17,0],[238,255]]`, `[[21,0],[234,255]]` for 1.1, 1.15, 1.2. Measured: landscape
  chroma +10 / +15 / +20 %, with 1.1 / 2.4 / 4.0 % of the pixels (dark foliage) newly clipped in blue; golden-hour skin
  a*/b* 27.7/28.1 → 30.7/31.3 / 32.6/32.8 / 34.0/34.0 (over 30 reads oversaturated). Vibrance +15 for comparison:
  landscape chroma +3 %, skin unchanged. So: +10 % for landscapes and products, less on a* for portraits (Margulis's
  caution: more a* reddens noses and blemishes), or mask skin out; neutralise first, because the boost amplifies any
  cast left (the chart's greys, b* -1.4, moved 0.1-0.2 further at +20 %); check `clippedLow%`. **Save it as `.pcraft`**
  (`app.save {"path": "….pcraft"}`), or stamp it into a pixel layer before saving a PSD: a PSD has no Lab curve in an
  RGB file, and PhotoCraft writes the a and b curves as green and blue curves (reopened, the photo was up to 36 levels
  off; the .pcraft reopened exact).

### Local contrast ("clarity")

The last layer of the look: a Stamp Visible with High Pass at a large radius, desaturated, in Overlay at 50 %, masked
off skin (KelbyOne's two layer recipes are a large-radius Unsharp Mask, amount 5-30 %, radius 30-100 px, threshold 0,
and a High Pass around 180 px on a 6000 px photo in Overlay or Soft Light).

    python3 color_check.py clarity now.png ~/.photocraft-skill/work/<photo>/clarity --skin skin.json \
        [--method highpass|usm] [--radius PX] [--blend "Soft Light"] [--opacity 0.5] [--colour] [--at X,Y]
    python3 import_layers.py …/clarity/layers.json        # live; headless: --file photo.jpg --out x.psd

`--skin` is an area.json around all visible skin (face, neck, hands); the mask fades over `--feather` (40) px.
Defaults: High Pass at 3 % of the long side, desaturated (`--colour` keeps its colour), Overlay at 0.5 (`--blend` also
takes Soft Light, Hard Light or Linear Light); `--method usm` uses amount 20 at 1.5 %, in Normal or Luminosity (which
keeps the colours as they were). The output reports local contrast (mean |luminance - its blur at 1 % of the long
side|) off skin before and after, on skin, and clipping, measured on the 1200 px copy. `preview.png` is exact for the
verify window, which goes where the layer changes most and across the skin mask's edge (`verifyWindow`: its crop, the
mean predicted change, the share of skin; `--at X,Y` picks another): a window inside the skin, where the mask turns
the layer off, would pass whatever the import did. The filter runs through the CLI on that window plus 3 radii.
Imports verified at mean difference 0.0, max 1 level, in 8-bit documents for every blend (Linear Light 0.03), and at
0.06 in a 16-bit document. About 8 s on a 1200 px photo, under 2 minutes on an 18 MP original.

| Setting (no mask), local contrast and clipping (highlights/shadows %) | Landscape | Golden-hour portrait | Studio portrait |
|---|---|---|---|
| High Pass 3 %, desaturated, Overlay 0.5 (the default) | +26 %, no new clipping | +25 %, no new clipping | +22 %, no new clipping |
| High Pass 3 %, desaturated, Soft Light 1.0 | +30 %, shadows 0.14 → 0.20 | +30 %, shadows 0.01 → 0.06 | +28 %, no new clipping |
| Unsharp Mask 20 %, radius 1.5 % (`--method usm`) | +19 %, 0.8/0.1 → 1.7/1.8 | +18 %, 0.2/0.0 → 0.7/0.4 | +17 %, highlights 0.0 → 0.9 |
| Unsharp Mask 30 %, radius 2 % | +29 %, → 2.3/3.2 | +28 %, → 1.2/1.4 | +27 %, → 1.6/1.0 |

How strong that is: at the default 0.5 the layer changed 43 % of a studio portrait's pixels by more than 2 levels
(95th percentile 16 levels) and moved the colour chart in it by up to 5.4 L* (its mid grey lighter, its black darker:
local contrast at the patch edges); at 0.3, 36 %, 10 levels and 3.2 L*. For "a bit of" local contrast use 0.25-0.3,
and add a chart or any other measurement target to the `--skin` area (another polygon) so it stays as shot.

Unsharp Mask pushes each channel past its ends in saturated areas; Overlay and Soft Light can't, so High Pass gives
more local contrast for less clipping. Without desaturation the High Pass in Overlay also raised the landscape's 95th
percentile chroma 8 % (desaturated: 2 %). The skin mask matters: on a studio headshot with the face masked out, the
face's local contrast and Lab stayed exactly as they were (the background +21 %); without it the face gained 29 %
local contrast and went 2.5 L* lighter and 1.6 a* less red.

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
- `image.adjustments.matchColor` exists, but it is destructive; run it on a duplicate layer if the user wants it, and
  control the strength with that layer's opacity rather than its Fade (John Paul Caponigro).

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

- True neutrals |a*|, |b*| ≤ 2 after correction (≤ 0.5 at amount 1); any warmth left is a deliberate amount. Read
  them on a render of the correction alone (the look switched off): a look tints greys by design (the split tone
  above took a chart's dark grey to b* -2.8) and local contrast moves their lightness.
- Skin 110-130°, and moved by a look ≤ 5° (`skin` before/after); lit and shadow sides each plausible. Its
  `litMidtone` Lab positive in a* and b*, in roughly 10-30, b* near or a little above a*, unless the `labVerdict`
  has a reason you can name (fair skin in soft light, low sun, a ruddy or freckled face, a baby).
- Clipping per channel no higher than before beyond speculars (+0.1 % budget), at both ends.
- Memory colours: sky blue (not cyan or purple), foliage yellow-green, skin neither orange nor magenta.
- No banding in skies and backdrops at 100 %; the scope's neutral cloud at the centre.
- Before/after at fit and at 100 %; each group switched off once.

## Save, and colour management

- Layered: `app.save {"path": "…/photo-graded.psd"}` (new name next to the original).
- JPEG: `$PC cli convert photo-graded.psd photo-graded.jpg --quality 95` (`app.save` ignores quality; the profile is kept).
- For the web, convert a wide-gamut document to sRGB on a copy first: `image.duplicate`, then
  `edit.convertToProfile {"profile": "srgb"}`, then export. Assigning a profile changes the colours; converting keeps them.
- **File size.** A Stamp Visible (the clarity layer) is a second full-size pixel layer: a 3840 x 2560 16-bit PSD with
  one and the background was 168 MB. Save the working file as `.pcraft` (smaller), and deliver flat files.
- **16-bit for strong moves and wide gamut** (`image.mode.bits16`): stacked strong curves round between layers in
  8-bit, and a wide space spreads 8-bit code values further apart (Photography Life). Measured here: an 8-bit RGB → Lab
  → RGB round trip moved pixels by up to 16 levels, a 16-bit one by none. ProPhoto RGB is an editing space only:
  convert to sRGB (8-bit, profile embedded) for the web, and to the lab's profile or Adobe RGB for print.
- **How much falls out of gamut** (live or headless): `view.gamutWarning {"on": true, "profile": "srgb"}` answers
  `fraction` and `outOfGamut` (pixels more than ΔE 4 outside that profile). A saturated Display P3 photo read 0.289
  against `srgb` and 0 against `display-p3`: converting it for the web would visibly flatten those colours, so
  compare before and after converting, or pull the most saturated colours in first. `coated-cmyk` (PhotoCraft's
  synthetic press profile) is only a rough indicator for print.
- **Soft proofing for print** is the user's step in the app (View › Proof Setup › Custom with the lab's .icc): in an
  automation session `view.proofSetup` with a profile is refused ("uses ambient filesystem paths and is disabled",
  tested with photocraft-cli serve), and so is an .icc path in `view.gamutWarning`. The sources disagree on the intent:
  WhiteWall says Relative Colorimetric with Black Point Compensation, theprintspace Perceptual with it, CreativePro
  Relative or Absolute without it. Use what the lab asks for; with Simulate Paper Color the proof looks duller but shows
  the paper's white. Print versions take `--tone --for print`.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Candidates on fur, a wall, wood, sand | The dominant low-chroma surface is coloured | Pick real neutrals by eye; the grey-edge warning flags most of these |
| Subject turns grey-green or grey-blue | A coloured surface was used as `--neutral` (glass, fur) | Check each sample's `cast` against what it is in life; resample |
| "one reference" warning, other levels off | Casts vary with brightness | Add a darker and a lighter neutral |
| "same level but … apart" | One sample isn't neutral, or two lights (within 20 L* of white or black "the same level" is 5 L*, elsewhere 10: casts change fastest near the ends) | Drop the odd one; second light → `--area` layer |
| Points dropped to keep curves monotone | References contradict (brighter input → darker target) | Same as above |
| A white or black reference "left out" | Two or more channels clipped, or a mid neutral with a clipped channel | A less bright white (or less dark black) with detail; one clipped channel is fine as `--white` / `--black` |
| Highlights a little dimmer in one channel after the correction | A clipped white's channel end was pulled to grey, by design | Expected; that channel's detail above the white was already gone |
| Corrected photo looks darker than expected | Correction keeps each neutral's luminance | `--tone`, or a midtone curve |
| `--tone --for print` looks flat on screen | Ends pulled in to 8/244 for paper | Expected; keep a separate screen version |
| Saturated colours a bit too red after a big correction | Curves on a rendered JPEG are not raw white balance (the camera's colour matrix) | `hueSaturation` reds -5…-10, or Vibrance -5; check skin |
| Skin too yellow after a big correction while the greys are neutral (labVerdict yellow) | The camera's colour rendering at the wrong white balance, not the light: it turned the hues before the curves saw them | `chart` with a ColorChecker (`--skin`, masked with `--area`), or a skin-masked Hue/Saturation; the full fix is the raw, developed again at the right white balance |
| Chart fit warns that browns turn redder | One mixer for all colours: what helps the face moves hair and wood too | `--area` over the skin; the brown warning disappears |
| Shadows still tinted | No dark neutral; the black end is pinned | `--black` on a dark neutral |
| "a channel moves 40+ levels" | Very strong cast | One curve showed no banding in 8-bit; stacks of strong layers round between each other in 8-bit (a Curves pair halving then doubling lost 49 % of the levels; in 16-bit it moved the mean 0.08 at most), so `image.mode.bits16` first and `qc.py banding` after |
| `labVerdict` pale on a correctly balanced portrait | Fair skin in bright, soft light (measured a* 6, b* 7) | Fine if the greys are neutral; Vibrance or a gentle warm-up only if the user wants more colour |
| `labVerdict` oversaturated in golden light | Low sun raises skin chroma (b* 28-38 measured) | Keep the light; tone it down only if it reads orange |
| `labVerdict` red on one face, typical on others | Ruddy, freckled or flushed skin | Leave it, or a masked Hue/Saturation on reds (hue toward yellow) on that face only |
| Match turns skin pink, greys blue | Different content in the two shots | `--area` / `--ref-area` on shared content; `--anchor-skin` |
| Highlights greyer after a match | The target's clipped channel compresses the top of the curve | `--amount 0.8`, or accept; speculars can't be recovered |
| Teal shadows crush dark clothing | Color Balance shadows pull red to 0 | Color Lookup tealOrange at 40 %, or a smaller shift; watch `clippedLow%` |
| Split tone warms the skin too much | Light skin sits in the highlight stop's range | A mask from `mask.py … --inside 0.3 --outside 1` on the layer (the whole face as the area); Blend If drops the warm highlights everywhere |
| Matte fill flattens the shadows | Lighten fill at full opacity: everything under 75 becomes 75 | Opacity 0.3-0.5 |
| Colour boost clips dark greens and blues | a*/b* pushed past the gamut in dark saturated areas | Slope 1.1 or less, lower on b*; check `clippedLow%` |
| Colour boost makes noses and blemishes red | a* steepened on skin | The portrait variant (a +5 %), or mask skin out |
| Colour boost gone or wrong after reopening a PSD | A Lab curve saved to PSD comes back as green and blue curves | Save as `.pcraft`; for a PSD, stamp the boost into pixels first |
| Clarity makes skin gritty or blotchy | No skin mask | `clarity --skin` with an area over all visible skin |
| Clarity warns about clipping | Unsharp Mask, or Overlay at a high opacity | High Pass (the default), lower `--opacity` |
| Clarity warns the verify window "changes only" a little | Little for the layer to act on there (a flat or masked area) | `--at X,Y` on detail outside the skin, so the import check means something |
| Black & white clips or skin glows | Channel weights over 100 | The softer weights above; check clipping |
| Skin angle jumps on a pale face | Low saturation: small chroma change, big angle change | Judge by eye; compare `lab` before/after |
