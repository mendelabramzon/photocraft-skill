# LightCraft command quick reference

Parameter docs copied from the LightCraft 0.9.1 command registry (371 commands, 122 develop controls).
This is a starting point, not the full list. The registry on the user's machine is the source of truth,
since ids and params change between releases:

Commands below use `$LC` and `$LOOK` as SKILL.md sets them:
`${CLAUDE_SKILL_DIR}/scripts/lc.py` and `${CLAUDE_SKILL_DIR}/scripts/look.py`.

    $LC cli commands | grep -i <word>     # headless: id, label, shortcut, params
    $LC cli commands --json               # the same as JSON
    $LC cli controls                      # every develop control with its range
    $LC call engine.commands              # live app: also `enabled` and `disabled_reason`

Notation: `?` marks optional; `x, y` and rects are normalized 0..1 in the whole upright photo (see
SKILL.md); `ids` are photo ids from `catalog.query`; most commands without `ids` act on the active photo
or the selection. A command that doesn't list `ids` acts on the active photo and quietly ignores an `ids`
given to it. A `null` result is success.

## Contents
- Develop controls · Settings JSON · Global develop commands · Masks · Crop and geometry
- Spots and red eye · Presets and profiles · Library: import, select, query · Culling
- Metadata, keywords, albums, files · Copying settings · History and versions · Export · Merge
- Models (ask first)

## Develop controls

Set with `develop.set {"values": {"<id>": n}}`, nudge with `develop.adjust {"control", "delta"}`.
Ranges with the default in brackets.

| Section | Controls |
|---|---|
| profile | `profile.amount` 0..200 (100) |
| color | `wb.temp` 2000..50000 (6500), `wb.tint` −150..150 (0), `color.vibrance`, `color.saturation` −100..100 |
| light | `light.exposure` −5..5 EV (0), `light.contrast`, `light.highlights`, `light.shadows`, `light.whites`, `light.blacks` −100..100 |
| hdr | `hdr.maxEv` 0..5 (3); `hdr.sdrBrightness`, `hdr.sdrContrast`, `hdr.sdrHighlights`, `hdr.sdrShadows`, `hdr.sdrWhites`, `hdr.sdrClarity` −100..100 (the SDR rendition of an HDR edit) |
| curve | `curve.highlights`, `curve.lights`, `curve.darks`, `curve.shadows` −100..100; splits `curve.splitShadows` 10..70 (25), `curve.splitMid` 20..80 (50), `curve.splitHighlights` 30..90 (75); `curve.refineSaturation` 0..100 (100) |
| mixer | `mixer.<band>.hue`, `.sat`, `.lum` −100..100, bands `red orange yellow green aqua blue purple magenta` |
| bwMix | `bw.<band>` −100..100, same bands (in B&W) |
| grading | `grading.<shadows/midtones/highlights/global>.hue` 0..360, `.sat` 0..100, `.lum` −100..100; `grading.blending` 0..100 (50), `grading.balance` −100..100 |
| effects | `effects.texture`, `effects.clarity`, `effects.dehaze` −100..100 |
| vignette | `vignette.amount` −100..100, `vignette.midpoint` 0..100 (50), `vignette.roundness` −100..100, `vignette.feather` 0..100 (50), `vignette.highlights` 0..100 |
| grain | `grain.amount` 0..100, `grain.size` 0..100 (25), `grain.roughness` 0..100 (50) |
| detail | `detail.sharpenAmount` 0..150, `detail.sharpenRadius` 0.5..3 (1), `detail.sharpenDetail` 0..100 (25), `detail.sharpenMasking` 0..100; `detail.nrLuminance` 0..100, `detail.nrDetail` (50), `detail.nrContrast`, `detail.nrColor`, `detail.nrColorDetail` (50), `detail.nrColorSmoothness` (50); `enhance.denoise` 0..100 (AI Denoise amount, needs a model) |
| optics | `optics.distortion`, `optics.vignetting` −100..100, `optics.vignettingMidpoint` (50); `optics.profileDistortion`, `optics.profileVignetting` 0..200 (100, the lens profile's strength); `optics.defringePurple`, `optics.defringeGreen` 0..20 with hue ranges; `optics.caRed`, `optics.caBlue` −100..100 |
| geometry | `geometry.vertical`, `geometry.horizontal`, `geometry.aspect`, `geometry.offsetX`, `geometry.offsetY` −100..100, `geometry.rotate` −10..10, `geometry.scale` 50..150 (100); `crop.angle` −45..45 |
| calibration | `calibration.shadowsTint`, `calibration.redHue/redSat/greenHue/greenSat/blueHue/blueSat` −100..100 |

`wb.temp` is Kelvin on raws with colour matrices and relative (6500 = as shot) on everything else.

## Settings JSON

`develop.get {id?}` returns a photo's whole develop JSON; `develop.merge {settings, label?}`,
`render --settings FILE` and presets take a partial one, deep-merged. Its keys are its own, nested and
snake_case, not control ids:

    {"light": {"exposure": 0.3, "highlights": -40}, "wb": {"mode": "custom", "temp": 5200, "tint": 4},
     "optics": {"lens_profile": true, "remove_ca": true}, "detail": {"sharpen_amount": 40},
     "masks": [{"name": "Sky", "components": [{"op": "add", "invert": false, "shape": {"kind": "sky"}}],
                "adjust": {"exposure": -0.5}, "invert": false, "visible": true}]}

Booleans that are no slider live only here: `optics.lens_profile` and `optics.remove_ca` (off by
default), `enhance.raw_details`, `treatment` (`"color"`/`"bw"`). Read the photo's `develop.get` before
writing one, and copy the shape; crops are easiest set with the crop commands.

## Global develop commands

- `develop.set` — Set Develop Values
  `{control?: controlId, value?: number, values?: {controlId: number}, ids?: [photo]}`
  `crop.angle` here turns the crop like `crop.straighten`.
- `develop.adjust` — Nudge Develop Value `{control, delta}`
- `develop.quickAdjust` — Quick Develop `{control, delta, ids?}`: adds `delta` to each photo's own value
- `develop.merge` — Apply Settings JSON `{settings: partial DevelopSettings JSON, label?}`
- `develop.auto` — Auto Settings `{}` → the values it chose (exposure, contrast, highlights, shadows,
  whites, blacks, vibrance, saturation)
- `develop.wb` — White Balance
  `{mode: asShot|auto|daylight|cloudy|shade|tungsten|fluorescent|flash|custom, temp?, tint?}`
- `develop.wbPick` — White Balance Selector `{x, y}` normalized coords of a neutral point → `{temp, tint}`
- `develop.treatment` — Black & White `{bw?: bool}` (toggles when omitted); `develop.autoBwMix {}`
  sets the B&W mix from the photo's colours
- `develop.profile` — Set Profile `{id: profile id (see profiles.list), amount?: 0..200}`
- `develop.curve` — Set Point Curve `{channel: master|red|green|blue, points: [[x,y],...] in 0..1}`
- `develop.targeted` — Targeted Adjustment
  `{target: curve|hue|sat|lum, x, y, delta, channel?: parametric|master|red|green|blue}`: adjusts the
  curve region or mixer bands under the point (the TAT tool) and returns the changed controls, e.g.
  `{"mixer.magenta.sat": -10, "mixer.purple.sat": -3.4}` on a purple sky: the way to tell which mixer
  bands a colour falls in
- `develop.hdr` — HDR `{enabled?: bool, maxEv?: 0..5}`
- `develop.reset` — Reset Edits `{ids?}`; `develop.resetSection`
  `{section: light|curve|color|mixer|grading|effects|vignette|grain|detail|optics|geometry}`
- `develop.controls` — `{section?}`: every slider with range, default and current value
- `develop.updateProcess` — `{ids?}`: moves photos on an older rendering process to the current one
  (their look can change)

## Masks

- `mask.add` — Create New Mask
  `{kind: brush|linear|radial|sky|subject|background|luminanceRange|colorRange|object|prompt, ...shape params, name?}` → `{activeMask}`
  - `radial`: `center: [x, y]`, `rx`, `ry` (radii as fractions of the photo's long edge, so 0.1 and 0.1
    is a circle), `angle?`, `feather?` (0..100, default 50), `invert?`
  - `linear`: `start: [x, y]` (full effect) to `end: [x, y]` (none)
  - `sky`, `subject`, `background`: no params; computed when rendered (heuristics, no model)
  - `luminanceRange`: `lo`, `hi` (luminance 0..1), `lo_feather?`, `hi_feather?` (0.1)
  - `colorRange`: then `mask.sampleColor {x, y, add?}` picks the colour (up to 5 samples)
  - `brush`: then `mask.brushStroke`
  - `object` (`points`/`exclude`) and `prompt` (`text`): need the SAM 3 model (ask first)
- `mask.adjust` — Set Mask Adjustments
  `{id?, values: {exposure, contrast, highlights, shadows, whites, blacks, temp, tint, texture, clarity, dehaze, hue, saturation, sharpness, noise, moire, defringe, color_hue, color_sat, amount}}`
  Exposure in EV, the rest −100..100; `amount` (default 100) scales them all.
- `mask.addComponent` — Add/Subtract/Intersect `{id?: maskId, op: add|subtract|intersect, kind, ...shape params}`
- `mask.brushStroke` — `{id?, points: [[x,y],…], size?: fraction of long edge (0.03), feather?, flow?, density?, erase?: bool, autoMask?: bool}`
- `mask.update` — `{id?, component?: index (0), shape: MaskShape JSON}` (move or resize a shape)
- `mask.refine` — Refine Mask Edges `{id?, value: 0..100}`: edges snap to the photo's
- `mask.invert {id?}`, `mask.select {id|null}`, `mask.rename {id?, name}`, `mask.visible {id?, visible?}`,
  `mask.duplicate {id?, invert?}`, `mask.delete {id?}`, `mask.deleteAll {}`
- `mask.component` — `{id?, component: index, action: invert|duplicate|delete|rename|op, name?, op?}`
- `mask.effects {}` / `mask.applyEffect {name, id?|ids?|all?}`: saved mask presets, when the user has some

## Crop and geometry

- `crop.set` — Set Crop `{rect?: [x0,y0,x1,y1] normalized in the straightened frame, angle?: degrees}`
- `crop.straighten` — `{angle: degrees -45..45}`: keeps the crop if it fits, else shrinks it about its centre
- `crop.autoStraighten` — `{}` → `{angle, changed}`: levels the horizon (or plumb lines)
- `crop.aspect` — `{aspect: "original"|"free"|"current"|"toggle"|"1x1"|"4x5"|"8.5x11"|"5x7"|"2x3"|"4x3"|"16x9"|"16x10"|[w,h]}`
  The ratio follows the photo's orientation, and a square photo counts as landscape; `crop.rotateAspect
  {}` turns it (a portrait 4:5 from a landscape or square photo). In `develop.get`, tell the orientation
  from the crop `rect`: its `aspect` field reads the other way round.
- `crop.drag` — `{handle: topLeft|…|move, from: [x,y], to: [x,y], keepRatio?}` (straightened frame)
- `crop.reset {}`
- `geometry.upright` — Upright `{mode: off|auto|guided|level|vertical|full}`: line segments → vanishing
  points; `level` rotation only, `vertical` verticals too, `full` both directions
- `geometry.guides` — `{guides: [[x0,y0,x1,y1], …] (≤ 4, lens-corrected image), add?}` → Guided Upright
- `photo.rotateLeft` / `photo.rotateRight` / `photo.flipHorizontal` / `photo.flipVertical` — `{ids?}`

## Spots and red eye

- `spot.findDust` — `{sensitivity?: 0..100 (50), add?: bool (true)}` → `{spots: [{x, y, size}], added}`
- `spot.add` — `{mode?: remove|heal|clone|fill (content-aware), points: [[x,y],…], size?: fraction of long edge, feather?, opacity?, source?: [dx,dy]}` → `{index}`
  More than one point makes a stroke (a wire, a scratch).
- `spot.select {index|null}`, `spot.update`, `spot.delete {index?}` (the selected spot)
- `spot.findBlemishes` — `{sensitivity?, add?, maxPerFace?: 1..20 (6)}`: needs the YuNet face model
- `redeye.add` — `{center: [x,y], rx, ry: radii as fractions of the long edge, pet?: bool, pupilSize?: 0..100, darken?: 0..100}` → `{index}`; `redeye.delete {index}`

## Presets and profiles

- `presets.list {}` → `[{id, name, group, builtin, favorite}]` (41 built in, ids `lc.*`)
- `preset.apply` — `{id: presetId, amount?: 0..200 (percent), ids?}`
- `preset.create` — `{name, group?, groups?: [settingsGroup]}` → `{id}` (from the active photo)
- `preset.update {id, groups?}`, `preset.export {path, ids?, group?}` (a `.lcpreset` file),
  `preset.import {paths, group?, dryRun?}` (`.lcpreset`, XMP and `.lrtemplate` presets…)
- `profiles.list {}`; `develop.profile {id, amount?}`. Built in: `lc.color` (default), `lc.neutral`,
  `lc.vivid`, `lc.landscape`, `lc.portrait`, `lc.mono`, film, cinematic and muted looks.

Settings groups (for presets, copy, paste, sync): `profile treatment whiteBalance light toneCurve color
colorMixer colorGrading effects vignette grain detail optics geometry crop masks spots redEye lensBlur
calibration`.

## Library: import, select, query

- `library.import` — `{paths: [file or folder (recursive)], mode?: add|copy|move, destination?, organize?: date|month|flat|template, rename?, album?}`
  `add` (default) references the files in place.
- `library.importPreview {paths}` → what an import would add, duplicates marked; adds nothing
- `library.select` — `{ids: [id], active?: id, mode?: replace|add|toggle|range}`;
  `library.selectAll {}`, `library.selectNone {}`, `library.next {}`, `library.previous {}`
- `library.state {}` → selection, filter, sort, source, undo/redo labels
- `library.info {}` → path, photos, persistent, unsaved changes
- `catalog.query` — `{filter?: Filter, sort?: Sort, offset?, limit?}` → `{photos: [{id, fileName, format, kind, width, height, captured, rating, flag, label, keywords, edited, previewOnly, …}], total}`
  Filter: `{text?, rating?, ratingOp?: atLeast|exactly|atMost, flag?: pick|reject|none, label?, kind?, edited?, date?, keyword?, person?, camera?, …}`.
  `text` takes the search box's fields: `rating:>3 flag:pick iso:>800 camera:x2 date:2026-04 keyword:mountains`.
- `library.filter` — the same partial Filter, applied to the view; `library.sort`
  `{key?: captureDate|importDate|editDate|fileName|rating|fileSize|random, ascending?}`
- `photo.inspect {id?}` → everything about one photo (develop, meta, history, versions)

## Culling

- `photo.analyze` — Assisted Culling `{ids?, rejectBelow?: sharpness 0..100, pickBest?: bool}` →
  `{photos: [{id, sharpness, clipped, group, best}], groups, rejected, picked}`
  Groups are look-alike shots taken within 10 s; `best` is each group's sharpest. `clipped` is the share
  (0–1) of pixels clipped at either end, so a black background counts. Without `rejectBelow` or
  `pickBest` it changes nothing.
- `photo.rate` — `{rating: 0..5, ids?, advance?}`; `photo.flag` — `{flag: pick|reject|none, ids?}`;
  `photo.label` — `{label: red|yellow|green|blue|purple|none, ids?}`
- `library.selectBy` — `{flag?, rating?, ratingOp?: gte|eq|lte, label?, add?}` (among the photos in view)
- `stack.auto` — `{gap?: seconds (60), ids?, preview?}` → `{stacks, photos}`
- `library.findSimilar` — `{id?, similarity?: 0..1 (0.8), filter?: bool (true)}` → `{photos: [{id, similarity}]}`
  (filters the view; `library.clearFilter {}` goes back)

## Metadata, keywords, albums, files

- `photo.setMeta` — `{ids?, title?, caption?, altText?, copyright?, creator?, location?, city?, state?, country?, gps?: "lat, lon"|[lat, lon]|null, keywords?, addKeywords?, removeKeywords?}`
- `keyword.list {}`, `keyword.create {name, parent?, addToSelected?, ids?}`, `keyword.rename {from, to}`
- `album.create` — `{name, parent?, folder?, addSelected?}` → `{id}`; `album.addPhotos {id, ids?}`;
  `album.removePhotos {id?, ids?}`; `album.createSmart {name, rules?: partial Filter}`; `albums.list {}`
- `photo.rename` — `{template: "{date}_{name}", start?, ids?}`: renames the files on disk (sidecars too)
- `photo.virtualCopy {ids?, name?}` → `{ids}`: a second set of settings for the same file
- `photo.delete {ids?}`: to Recently Deleted (`photo.restore {ids?}` brings it back); only when the user
  asks. `library.emptyRecentlyDeleted {}` removes those from the library; the files stay on disk.
- `photo.saveMetadataToFile {ids?}`: writes `<name>.xmp` next to each original (edits as `lc:settings`)
- `photo.editExternal` — `{ids?, colorSpace?: adobeRgb|proPhoto|displayP3|srgb, format?: tiff|psd, bitDepth?: 16|8, dir?}`:
  `<name>-Edit.tif/.psd` next to the original, added stacked on it; `photo.reload {ids?}` re-reads it after
  another editor saved it

## Copying settings

- `develop.copy {groups?}` (default: everything but crop, masks and spot removal), then
  `develop.paste {ids?, groups?}`
- `develop.sync {groups?}`: the active photo's settings to every selected photo
- `develop.pastePrevious {ids?, groups?}`: from the photo active before this one
- `develop.matchExposure {ids?}`: each selected photo's Exposure set so its total exposure (shutter, ISO,
  aperture and the slider) equals the active photo's → `{changed, skipped}`
- `develop.autoSync {on?}`: while on, edits to the active photo change the other selected photos too

## History and versions

- `edit.undo {}`, `edit.redo {}`; `history.list {id?}` → `{history, cursor, versions}`;
  `history.restore {index}`
- `version.create {name?}`, `version.restore {index}`: named snapshots of a photo's settings
- `beforeAfter.setBefore {source: import|current|history|version, index?, name?}`: what Before shows

## Export

- `app.export` — Export Now
  `{path?: file (.jpg/.png/.tif/.webp/.avif/.jxl/.psd/.dng) | dir?, ids?, preset?, format?: jpeg|png|tiff|webp|avif|jxl|psd|dng|original, longEdge?|shortEdge?|width?|height?|megapixels?|percent?, dontEnlarge?, ppi?, quality?: 1..100, limitKb?, colorSpace?: srgb|displayP3|adobeRgb|proPhoto|rec2020, bitDepth?: 8|10|16|32, hdr?, sharpen?: none|screen|matte|glossy, sharpenAmount?: low|standard|high, metadata?: all|allExceptCamera|copyright|none, removeLocation?, naming?, startNumber?, destinationMode?: specificFolder|sameAsOriginal, subfolder?, conflict?: unique|overwrite|skip, tiffCompression?: none|lzw|zip, watermark?: text | {text?, size?, opacity?, anchor?, inset?, color?, image?, …}, background?, addToPhotos?, photosAlbum?}`
  → `{files: [{path, width, height, bytes, sidecars}]}`
  - No size: 3000 px long edge. `longEdge: 0`: full size of the crop. `width` + `height` fit either
    orientation. `dontEnlarge` defaults to true. No `colorSpace`: sRGB.
  - `path` is for **one** photo (the active one, or `ids: [id]`) and replaces that file if it exists.
    With several `ids` it ignores the name and writes `<name>.<ext>` into the current folder, so for
    several photos use `dir` with a `naming` template (`{name}-web`; tokens as in `photo.rename`).
    `dir` exports the selection (or `ids`); a name already taken gets `-2` (`conflict: unique`).
  - An unknown parameter or a value of the wrong kind is an error, never a silent default.
  - Writing over an original or its sidecar is refused.
  - `format: "dng"` needs a raw; `format: "original"` copies the file plus an XMP sidecar.
  - `background: true` (live) returns at once; poll `activity.list` or `ui.inspect` → `export`.
- `export.presets {}`: built in `JPEG (Small)` (2048 px, q85, sRGB), `JPEG (Large)` (full size, q92),
  `Original + Settings`, `DNG`; use as `{preset: name, …overrides}`; `export.savePreset {name, params?}`
- `export.contactSheet` — `{path, ids?, paper?: a4|letter, landscape?, columns?: 1..8, rows?: 1..10, captions?}` → a PDF
- `export.addToPhotos {paths, album?, wait?}` (macOS): add files to Apple Photos; the first time macOS
  asks the user to allow it. Only when the user asks.

## Merge

- `merge.hdr` — `{ids?, align=true, deghost=none|low|medium|high, autoSettings=true, stack=false, preview=false}`
- `merge.panorama` — `{ids?, projection=auto|spherical|cylindrical|perspective, boundaryWarp=0..100, autoCrop=false, fillEdges=false, autoSettings=true, stack=false, maxMegapixels?}`
- `merge.hdrPanorama`, `merge.hdrBatch` (every bracket set among the photos)
- CLI: `lightcraft-cli merge hdr|panorama|hdr-panorama|hdr-batch [--deghost …] [--projection …] [--auto-crop] [--fill-edges] [--preview OUT.png] FILES…`
  writes `<first>-HDR.dng` / `-Pano.dng` next to the first file and prints JSON.

## Models (ask first)

These download model weights under their own licences, into LightCraft's settings folder. Ask the user,
show them the licence from the list command, and only then pass `acknowledged: true`.

| Feature | Status / list | Download |
|---|---|---|
| Object and Describe masks (SAM 3, about 3.4 GB, Meta's SAM License) | `segment.model.status {}` | `segment.model.download {acknowledged: true}` |
| Faces, Find Blemishes (YuNet detector and recognizers) | `faces.models.list {}` | `faces.models.download {id, acknowledged: true}` |
| AI Denoise | `denoise.models.list {}` | `denoise.models.download {id, acknowledged: true}` |

Without them, Sky, Subject and Background masks, Find Dust and classical noise reduction still work.
