# PhotoCraft command quick reference

Parameter docs copied from the PhotoCraft 0.7.0 command registry (858 commands). This is a
starting point, not the full list. The registry on the user's machine is the source of truth,
since ids and params change between releases:

    pc.py cli commands --filter <text>            # headless: id, label, menu
    pc.py cli commands --json | python3 -c ...    # full params docs
    pc.py exec command.list                       # live app: same, plus `enabled`/`disabledReason`

Notation: `0..100=50` is a range with default 50; `?` marks optional; `id` is a numeric layer id
from `document.inspect`. Colours are `"#rrggbb"`. Opacity is 0..1 in `layer.setProps` but 0..100
in fills, strokes and layer styles.

`+ mask*` on adjustment layers means they also take `"path"` (make a vector mask from a path);
otherwise an active selection becomes the layer mask, or the mask is white with no selection.
Every `layer.newAdjustmentLayer.X` has a destructive twin `image.adjustments.X` with the same
params, applied to the active pixel layer.

## Contents
- Document & canvas · Layers · Adjustments · Selections & masks · Channels and Apply Image · Filters
- Retouching tools · Type · Shapes & painting · Layer styles · Transform · Export

## Document & canvas

- `file.new` — New…
  `{"width":1..300000=1920,"height":1..300000=1080 (pixel counts are rounded),"mode":"rgb|gray|grayscale|cmyk|lab"="rgb","depth":8|16|32=8,"background":"white|black|backgroundColor|transparent|#rrggbb"="white","backgroundColor":[r,g,b]? (0..1; defaults to toolbox colour),"resolution":1..30000=72 (ppi),"name":str}`
- `image.duplicate` — Duplicate…
  `{"name":str,"mergedOnly":bool=false}`
- `history.newDocument` — New Document from State
  `{"state":index?,"name":str?} (History entry, 0 = oldest; default the current state) → {document,name}`
- `image.imageSize` — Image Size…
  `{"width":px,"height":px,"resolution":ppi,"resample":"bicubic|bilinear|nearest|lanczos|preserveDetails|none"="bicubic"} → {width,height} (the document's size after the command; "none" changes the resolution only)`
  Give only `width` (or only `height`) to scale proportionally.
- `image.canvasSize` — Canvas Size…
  `{"width":px,"height":px,"relative":bool=false,"anchor":"topLeft|top|topRight|left|center|right|bottomLeft|bottom|bottomRight"="center","extensionColor":"background|foreground|white|black|transparent|#rrggbb"="background"}`
- `image.crop` — Crop
  `{"x":px,"y":px,"width":px,"height":px,"angle":-3600..3600=0,"deleteCroppedPixels":bool=true,"targetWidth":px,"targetHeight":px,"resolution":ppi,"resample":"bicubic|bilinear|nearest|lanczos|preserveDetails"="bicubic"} → {x,y,width,height,documentWidth,documentHeight,resolution} (targetWidth/targetHeight, both or neither: the cropped area is resampled to exactly that size, as Image Size, in the same undo step; resolution: the document's new ppi)`
  With `angle` the box is centred on (x + w/2, y + h/2) and turned clockwise, so the content turns counter-clockwise: a horizon falling to the right needs that same positive angle. Corners outside the photo fill with the background colour; a rect beyond the canvas is allowed (Reveal All brings kept pixels back).
- `image.trim` — Trim…
  `{"basedOn":"transparent|topLeft|bottomRight"="transparent","top":bool=true,"bottom":bool=true,"left":bool=true,"right":bool=true}`
- `image.imageRotation.90cw` — 90° Clockwise
  `{}`
- `image.rotation.arbitrary` — Arbitrary…
  `{"angle":-359.99..359.99=0,"direction":"cw|ccw"="cw","interpolation":"bicubic|bilinear|nearest"="bicubic"}`
- `image.mode.grayscale` — Grayscale
  `{"profile":"<builtin id>|working|/path/to/profile.icc"=working,"intent":"perceptual|relative|saturation|absolute"="relative","bpc":bool=true}`
- `image.mode.bits16` — 16 Bits/Channel
  `{}`
  Also `image.mode.bits8` and `image.mode.bits32`. A 16-bit document saves a 16-bit PNG (the planners' PNG
  reader takes it); JPEG is always 8-bit.
- `image.mode.lab` — Lab Color
  `{"profile":"<builtin id>|working|/path/to/profile.icc"=working,"intent":"perceptual|relative|saturation|absolute"="relative","bpc":bool=true}`
  Curves and Levels then take `lightness`, `a` and `b` channel keys.
- `document.inspect` — Inspect Document
  `{"document":index?}`
- `document.pixel` — Read Composite Pixel
  `{"x":i32,"y":i32}`
- `document.sampleColor` — Sample Color
  `{"x":f64,"y":f64,"size":"point"|1|3|5|11|31|51|101=1,"sampleLayer":"current"|"currentAndBelow"|"all"|"allNoAdjustments"|"currentAndBelowNoAdjustments"="all"} → [r,g,b,a] (the Eyedropper's Sample Size and Sample: the composite pixel, or the average of the size×size square centred on it, clipped to the canvas; transparent off the canvas)`
  Values 0..1, not 0..255.
- `document.activate` — Activate Document
  `{"document":index}`
- `image.revealAll` — Reveal All
  `{}`
- `image.mode.rgb` — RGB Color
  `{"profile":"<builtin id>|working|/path/to/profile.icc"=working,"intent":"perceptual|relative|saturation|absolute"="relative","bpc":bool=true}`
- `edit.profileInfo` — Profile Info
  `{"profile":"<builtin id>|document|/path/to/profile.icc"=document}`
- `edit.assignProfile` — Assign Profile…
  `{"profile":"working|srgb|display-p3|adobe-rgb-compat|prophoto-compat|linear-srgb|rec2020|gray-gamma-2.2|sgray|lab-d50|coated-cmyk|none" (or a path to an .icc file)}`
- `edit.convertToProfile` — Convert to Profile…
  `{"profile":"srgb|display-p3|adobe-rgb-compat|prophoto-compat|linear-srgb|rec2020|gray-gamma-2.2|sgray|lab-d50|coated-cmyk|working" (or a path to an .icc file),"intent":"perceptual|relative|saturation|absolute"="relative","bpc":bool=true}`
- `view.gamutWarning` — Gamut Warning
  `{"on":bool=toggle,"threshold":deltaE=4,"profile":"<proof profile override>"}`
  With a builtin id (`srgb`, `display-p3`, `adobe-rgb-compat`, `coated-cmyk`, …) it answers `{"fraction", "outOfGamut", "threshold", "profile"}`: the share of pixels more than ΔE 4 outside that profile (a saturated Display P3 photo: 0.289 against srgb), headless too. An .icc path, and `view.proofSetup` with a profile, are refused in automation ("uses ambient filesystem paths"); the preset `view.proofSetup.workingCmyPlate` and `view.proofColors {"on": true}` run.
- `edit.undo` — Undo
  `{}`
- `edit.redo` — Redo
  `{}`

## Layers

- `layer.new.layer` — Layer…
  `{"name":str?}`
- `layer.select` — Select Layer
  `{"layer":id,"mode":"replace|toggle|range|add"="replace"} (toggle = ⌘-click, range = ⇧-click)`
- `layer.setProps` — Layer Properties
  `{"layer":id?,"name":str?,"visible":bool?,"opacity":0..1?,"fill":0..1?,"blend":"Multiply|…"?,"clipped":bool?,"locked":bool?,"locks":{"transparency","pixels","position","artboard","all":bool}?,"channels":[bool,…]? (Advanced Blending: which colour channels blend, R G B / C M Y K / L a b)}`
  `blend` takes Photoshop's names: "Normal", "Multiply", "Screen", "Overlay", "Soft Light", "Hard Light",
  "Linear Light", "Vivid Light", "Pin Light", "Lighten", "Darken", "Color Dodge", "Color Burn",
  "Linear Dodge (Add)", "Linear Burn", "Subtract", "Divide", "Difference", "Exclusion", "Hue", "Saturation",
  "Color", "Luminosity". Each renders exactly as `imgops.blend` predicts (checked on every 8-bit pair; the
  colour modes use the luminosity weights 0.3/0.59/0.11). Soft Light is Photoshop's classic formula, not the
  W3C one. A clipped layer shows only where the layer below is visible: its pixels and its mask.
- `layer.duplicate` — Duplicate Layer…
  `{"layer":id?,"inPlace":bool=false (artboards: keep the copy on the original instead of beside it)} (no layer: every selected layer)`
  The copy lands directly above its source, not at the top. In `document.inspect`, `layers[0]` is the top layer.
- `layer.moveTo` — Move Layers
  `{"layer":id?| "layers":[id,…]?, "target":id,"position":"above|below|into"="above","copy":bool=false} (layers: one undoable move, document order preserved; copy: place duplicates there and leave the layers, as ⌥-dragging a Layers panel row)`
- `layer.layerStyle.blendingOptions` — Blending Options (Blend If)
  `{"layer":id?,"blend":"normal|multiply|…"?,"opacity":0..100?,"fillOpacity":0..100?,"blendIf":{"channel":"gray|red|green|blue|cyan|…"|index="gray","thisLayer":[black,white]|[blackLo,blackHi,whiteLo,whiteHi]?,"underlying":[…]?}|[{…},…]|null?,"channels":[bool,…]?,"knockout":"none|shallow|deep"?,"blendInteriorEffectsAsGroup":bool?,"blendClippedLayersAsGroup":bool?,"transparencyShapesLayer":bool?,"layerMaskHidesEffects":bool?,"vectorMaskHidesEffects":bool?} (Blend If values 0..255; split points fade; null resets)`
- `layer.delete` — Delete Layer
  `{"layer":id?} (no layer: every selected layer)`
- `layer.translate` — Move Layer
  `{"layer":id?,"dx":i32,"dy":i32} (no layer: every selected layer; linked layers follow)`
- `layer.groupLayers` — Group Layers
  `{"layer":id?,"name":str?} (no layer: every selected layer)`
- `layer.arrange.bringToFront` — Bring to Front
  `{"layer":id?}`
- `layer.mergeDown` — Merge Down
  `{"layer":id?}`
- `layer.mergeVisible` — Merge Visible
  `{}`
- `layer.flattenImage` — Flatten Image
  `{}`
- `layer.rasterize.layer` — Layer
  `{"layer":id?} (no layer: every selected layer it applies to)`
- `layer.smartObjects.convertToSmartObject` — Convert to Smart Object
  `{"layer":id?} (default: combine selected layers)`
- `layer.newFillLayer.solidColor` — Solid Color…
  `{"color":"#rrggbb"=foreground,"path":"work"|saved path name|{…path}? (the active path: becomes the vector mask, making a shape; else the selection is the layer mask)}`
- `layer.newFillLayer.gradient` — Gradient…
  `{"from":"#rrggbb","to":"#rrggbb","angle":deg=90,"style":"linear|radial|angle|reflected|diamond","reverse":bool,"path":"work"|saved path name|{…path}? (the active path: becomes the vector mask; else the selection is the layer mask)}`
- `layer.align.horizontalCenters` — Horizontal Centers
  `{"to":"auto|layers|selection|canvas"="auto"} (auto: the selection bounds with one layer and an active selection, else the selected layers' bounds)`
- `layer.copyToDocument` — Copy Layers to Document
  `{"document":index (destination),"layers":[id,…]?=the source's selected layers,"source":index?=active,"center":bool=false (centre on the destination's canvas),"at":[x,y]? (centre the copies on this point),"offset":[dx,dy]?=[0,0] (from their place in the source)}`
  A command (`$PC exec`); without at, offset or center the copy keeps its pixel position. `at` centres the layer's visible (non-transparent) content, not its canvas: a PNG with transparent margins lands off by its content's offset from the centre (`import_layers.py` corrects for it from the layer's `bounds`).
- `layer.stampVisible` — Stamp Visible
  `{} → {layer} (every visible layer merged into a new layer above the active one; the originals stay)`
  Merges everything visible into the new layer, wherever it sits in the stack.
- `layer.createClippingMask` — Create Clipping Mask
  `{"layer":id?} (no layer: every selected layer but the lowest clips to the layer below it)`
- `select.findLayers` — Find Layers
  `{"name":str (case-insensitive substring)}`
  Selects layers by name, so a steps file can target them without knowing their ids.
- `layer.smartFilter.setParams` — Edit Smart Filter
  `{"layer":id?,"index":u32?,"params":{…} (merged)}`
  Re-edits a smart filter (e.g. Camera Raw) without rebuilding it.
- `edit.autoAlignLayers` — Auto-Align Layers…
  `{"projection":"auto|perspective|cylindrical|spherical|collage|reposition","reference":layer id?=bottom selected layer,"geometricCorrection":bool=false,"interpolation":"bicubic|bilinear|nearest"}`
  Aligns whole, nearly identical frames only (a tripod sequence); on patches it fails.
- `layer.smartObjects.stackMode.median` — Median
  `{"layer":id?}`
  After auto-align + convert to one smart object: whatever moved between frames disappears.

## Adjustments (non-destructive layer vs. direct)

- `layer.newAdjustmentLayer.levels` — Levels…
  `{"inBlack":0..253=0,"gamma":0.01..9.99=1,"inWhite":2..255=255,"outBlack":0..255=0,"outWhite":0..255=255,"red":json,"green":json,"blue":json} (top level = composite; per channel {"inBlack","gamma","inWhite","outBlack","outWhite"} under red/green/blue, gray, cyan/magenta/yellow/black or lightness/a/b) + mask*`
  Gamma has a slope-limited toe near black, not t^(1/gamma): predict with Curves when a result must be exact.
- `layer.newAdjustmentLayer.curves` — Curves…
  `{"points":json,"red":json,"green":json,"blue":json,"eyedropper":json} (curves as [[in,out],…] in 0..255, 2..19 points: points = composite; red/green/blue, gray, cyan/magenta/yellow/black or lightness/a/b per channel; eyedropper = the dialog's Set Black/Neutral Gray/White Point picker {"point":"black|gray|white","at":[x,y]} or {"point",…,"color":[r,g,b] 0..1}, RGB and Grayscale (no gray) only, applied over the given curves) + mask*`
  A natural cubic spline per curve, the end values held beyond the first and last point (`imgops.spline_lut`); within one layer the channel curves apply first, then the composite.
  A PSD stores curve points as whole levels and Channel Mixer values as whole percent: fractional ones come back
  rounded (a render moved up to 1 level for Curves, 2 for a mixer; 33.33 % x 3 reopened as 99 %, 1.3 levels darker).
  `.pcraft` keeps them exactly; the planners write mixers in whole percent adding up to 100.
  `lightness`/`a`/`b` keys in an RGB document make a live Lab-space Curves layer (an identity curve renders exactly). Saved as PSD and reopened, its a and b curves come back as green and blue RGB curves (up to 36 levels off): keep such a file as `.pcraft`.
- `layer.newAdjustmentLayer.brightnessContrast` — Brightness/Contrast…
  `{"brightness":-150..150=0,"contrast":-50..100=0,"legacy":bool=false} + mask*`
- `layer.newAdjustmentLayer.exposure` — Exposure…
  `{"exposure":-20..20=0,"offset":-0.5..0.5=0,"gamma":0.01..9.99=1} + mask*`
- `layer.newAdjustmentLayer.vibrance` — Vibrance…
  `{"vibrance":-100..100=0,"saturation":-100..100=0} + mask*`
- `layer.newAdjustmentLayer.hueSaturation` — Hue/Saturation…
  `{"hue":-180..180=0,"saturation":-100..100=0,"lightness":-100..100=0,"colorize":bool=false,"reds":json,"yellows":json,"greens":json,"cyans":json,"blues":json,"magentas":json} (per range {"hue","saturation","lightness","range":[4 hue degrees]}; colorize: hue 0..360, saturation 0..100) + mask*`
- `layer.newAdjustmentLayer.colorBalance` — Color Balance…
  `{"shadows":json,"midtones":json,"highlights":json,"preserveLuminosity":bool=true} (each tone [cyan-red, magenta-green, yellow-blue] in -100..100) + mask*`
- `layer.newAdjustmentLayer.blackWhite` — Black & White…
  `{"reds":-200..300=40,"yellows":-200..300=60,"greens":-200..300=40,"cyans":-200..300=60,"blues":-200..300=20,"magentas":-200..300=80,"tint":bool=false,"tintColor":"#rrggbb"} + mask*`
- `layer.newAdjustmentLayer.photoFilter` — Photo Filter…
  `{"filter":"warming85|warmingLBA|warming81|cooling80|coolingLBB|cooling82|red|orange|yellow|green|cyan|blue|violet|magenta|sepia|deepRed|deepBlue|deepEmerald|deepYellow|underwater","color":"#rrggbb","density":0..100=25,"preserveLuminosity":bool=true} + mask*`
- `layer.newAdjustmentLayer.gradientMap` — Gradient Map…
  `{"stops":json,"reverse":bool=false,"dither":bool=false} (stops [[location 0..1, "#rrggbb"], …], 2..64) + mask*`
  Maps by Rec.601 luma (0.299/0.587/0.114, not the blend modes' 0.3/0.59/0.11), interpolates linearly in 8-bit sRGB values between stops and holds the end colours beyond the first and last. A #808080 middle stop in Soft Light leaves the midtones alone (split toning).
- `layer.newAdjustmentLayer.colorLookup` — Color Lookup…
  `{"lut":"none|warm|cool|tealOrange|bleachBypass|fadedFilm|dayForNight|monoContrast|crossProcess"="none","file":text,"interpolation":"trilinear|tetrahedral"="trilinear","dither":bool=false,"data":json} (file: .cube/.3dl/.look path; data: file text + "fileName") + mask*`
- `image.adjustments.colorLookup.list` — List Color Lookup Looks
  `{}`
  → [{id, label}]: warm, cool, tealOrange, bleachBypass, fadedFilm, dayForNight, monoContrast, crossProcess.
- `layer.newAdjustmentLayer.selectiveColor` — Selective Color…
  `{"method":"relative|absolute"="relative","colors":"reds|yellows|greens|cyans|blues|magentas|whites|neutrals|blacks"="reds","cyan":-100..100=0,"magenta":-100..100=0,"yellow":-100..100=0,"black":-100..100=0,"reds":json} (per-range [c,m,y,k] arrays: reds yellows greens cyans blues magentas whites neutrals blacks) + {"path":"work"|saved path name|{…path}? (the active path: becomes the vector mask; else the selection is the layer mask, or white with no selection)}`
- `layer.newAdjustmentLayer.channelMixer` — Channel Mixer…
  `{"red":json,"green":json,"blue":json,"gray":json,"monochrome":bool=false} (per output channel [red %, green %, blue %, constant %] in -200..200; gray = the monochrome mix) + {"path":"work"|saved path name|{…path}? (the active path: becomes the vector mask; else the selection is the layer mask, or white with no selection)}`
- `image.adjustments.matchColor` — Match Color…
  `{"source":doc,"sourceLayer":json,"luminance":1..200=100,"intensity":1..200=100,"fade":0..100=0,"neutralize":bool=false,"useSelectionInSource":bool=false,"useSelectionInTarget":bool=false} (source: document index; sourceLayer: layer id, default the merged image)`
  Destructive; `color_check.py match` gives the same as an editable Curves layer.
- `layer.setAdjustment` — Adjustment Properties
  `{"layer":id?, …params of that adjustment kind}`
- `image.adjustments.desaturate` — Desaturate
  `{}`
- `image.adjustments.shadowsHighlights` — Shadows/Highlights…
  `{"shadowAmount":0..100=35,"shadowTone":0..100=50,"shadowRadius":0..2500=30,"highlightAmount":0..100=0,"highlightTone":0..100=50,"highlightRadius":0..2500=30,"color":-100..100=20,"midtone":-100..100=0,"blackClip":0..50=0.01,"whiteClip":0..50=0.01}`
- `image.autoTone` — Auto Tone
  `{}`
- `image.autoContrast` — Auto Contrast
  `{}`
- `image.autoColor` — Auto Color
  `{}`

## Selections & masks

- `select.all` — All
  `{}`
- `select.deselect` — Deselect
  `{}`
- `select.inverse` — Inverse
  `{}`
- `select.rect` — Rectangular Selection
  `{"x":i32,"y":i32,"width":u32,"height":u32,"mode":"replace|add|subtract|intersect"="replace","ellipse":bool=false,"antiAlias":bool=true,"feather":px=0}`
- `select.lasso` — Lasso
  `{"points":[[x,y],…],"mode":"replace|add|subtract|intersect"="replace","antiAlias":bool=true,"feather":px=0}`
- `select.magicWand` — Magic Wand
  `{"x":px,"y":px,"tolerance":0..255=32,"contiguous":bool=true,"antiAlias":bool=true,"sampleAllLayers":bool=false,"mode":"replace|add|subtract|intersect"="replace"}`
- `select.colorRange` — Color Range…
  `{"select":"sampledColors|reds|yellows|greens|cyans|blues|magentas|highlights|midtones|shadows|outOfGamut"="sampledColors","color":"#rrggbb"=foreground,"colors":["#rrggbb",…]?,"points":[[x,y],…]? (eyedropper samples),"subtractPoints":[[x,y],…]? (minus eyedropper),"order":["+"|"-",…]? (click order of points and subtractPoints; default all points first),"fuzziness":0..200=40 (tones: 0..100 %=20),"localized":bool=false,"range":0..100=100 (% of the longer side),"tonalRange":level|[lo,hi] (shadows 65, highlights 190, midtones [105,150]),"invert":bool=false,"sampleAllLayers":bool=true,"mode":"replace|add|subtract|intersect"="replace"}`
- `select.subject` — Subject
  `{"sampleAllLayers":bool=true,"mode":"replace|add|subtract|intersect"="replace"}`
- `select.sky` — Sky
  `{"mode":"replace|add|subtract|intersect"="replace","sampleAllLayers":bool=true,"threshold":0..100=50 (higher = stricter),"softness":0..100=50 (edge softness)} → {selected, changed, coverage (0–1 of the canvas), bounds [x,y,w,h]}`
  In 0.7.0 a smooth blob 10–20 px off the real skyline: refine it with `sky_mask.py`, don't use it as the mask.
- `select.object` — Object Selection
  `{"rect":[x,y,w,h],"mode":"replace|add|subtract|intersect"="replace","sampleAllLayers":bool=false}`
- `select.quick` — Quick Selection
  `{"points":[[x,y],…],"size":px=30,"mode":"add|subtract|replace"="add","sampleAllLayers":bool=false,"enhanceEdge":bool=false}`
  Floods into a white backdrop around white products; trace with select.lasso there.
- `select.refineEdge` — Refine Edge
  `{"radius":px=0,"smartRadius":bool=false,"smooth":0..100=0,"feather":px=0,"contrast":0..100=0,"shiftEdge":-100..100=0,"decontaminate":bool=false,"amount":0..100=100,"output":"selection|layerMask|newLayer|newLayerWithMask"="selection","sampleAllLayers":bool=false}`
  Product edge: radius 1, contrast 25; hair and fur: radius 8, smartRadius, decontaminate. shiftEdge moves whole pixels at radius 1 (-15..-25 = one pixel in).
- `select.modify.feather` — Feather…
  `{"radius":0.1..1000=1,"applyAtCanvasBounds":bool=false}`
- `select.modify.expand` — Expand…
  `{"radius":1..500=1,"applyAtCanvasBounds":bool=false}`
- `select.modify.contract` — Contract…
  `{"radius":1..500=1,"applyAtCanvasBounds":bool=false}`
  Leaves a binary (jagged) edge: run refineEdge after it.
- `layer.layerMask.revealSelection` — Reveal Selection
  `{"layer":id?} (no layer: every selected layer that can take a mask)`
- `layer.layerMask.revealAll` — Reveal All
  `{"layer":id?} (no layer: every selected layer that can take a mask)`
- `layer.layerMask.apply` — Apply
  `{"layer":id?}`
- `select.loadSelection` — Load Selection…
  `{"channel":index|name|"composite"|"red|green|blue|…"|"transparency"|"mask"|"vectorMask"|"quickMask"|"selection","layer":id?,"document":index?,"invert":bool=false,"operation":"new|add|subtract|intersect"="new"}`
  A grey layer's red channel ("gray" in a Grayscale document) becomes a soft selection; the next adjustment layer takes it as its mask.
- `layer.matting.colorDecontaminate` — Color Decontaminate…
  `{"amount":0..100=100,"radius":1..100=4}`
  The matting commands act on transparency only: on a masked layer they change nothing, so apply the mask on a copy first.
- `layer.matting.defringe` — Defringe…
  `{"width":1..200=1}`
- `layer.matting.removeWhiteMatte` — Remove White Matte
  `{}`
- `layer.matting.removeBlackMatte` — Remove Black Matte
  `{}`
- `layer.layerMask.linked` — Unlink Layer Mask
  `{"layer":id?,"linked":bool? (default: toggle)}`
  Masks are linked by default, so `edit.transform` moves the mask with its layer: unlink first to move a layer
  under a fixed mask (a sky photo under a skyline mask).
- `edit.fill` — Fill…
  `{"contents":"foreground|background|color|contentAware|pattern|history|black|gray|white"="color","color":"#rrggbb|[r,g,b,a]"=foreground (contents=color),"pattern":id|name (contents=pattern),"scale":%=100,"angle":deg,"state":index? (contents=history; default the oldest state),"colorAdaptation":bool=true (contents=contentAware),"mode":"normal|multiply|…"="normal","opacity":0..100=100,"preserveTransparency":bool=false,"target":"pixels"|"mask"|"quickMask"|{"channel":i}?}`
- `edit.stroke` — Stroke…
  `{"width":1..250=1,"color":"#rrggbb|[r,g,b,a]"=foreground,"location":"inside|center|outside"="center","mode":"any layer blend mode"="normal","opacity":0..100=100,"preserveTransparency":bool=false}`
- `edit.contentAwareFill` — Content-Aware Fill…
  `{"sampling":"auto|rectangular|custom","margin":px?,"area":[x,y,w,h]?,"channel":index|name?,"colorAdaptation":"default|none|high|veryHigh","rotationAdaptation":"none|low|medium|high|full","scale":bool=false,"mirror":bool=false,"output":"current|new|duplicate","seed":u64=1}`

## Channels and Apply Image

- `image.applyImage` — Apply Image…
  `{"source":{"document":index?,"layer":id|"merged"="merged","channel":"composite"|"red|…"|index|"selection"|"transparency"|"mask"="composite","invert":bool=false},"blending":"normal|multiply|screen|overlay|softLight|hardLight|colorDodge|colorBurn|darken|lighten|difference|exclusion|linearBurn|linearDodge|add|subtract|…"="multiply","opacity":0..100=100,"scale":1..2=1,"offset":-255..255=0,"preserveTransparency":bool=false,"mask":{"document","layer","channel","invert"}?}`
  Applies to the active layer. Frequency separation's texture layer, set to Linear Light over the blurred one:
  16-bit (`image.mode.bits16` first) `{"source": {"layer": <Low>, "invert": true}, "blending": "add", "scale": 2,
  "offset": 0}` reproduces the photo exactly (max 1 level, the final 8-bit rounding). 8-bit `"blending":
  "subtract", "scale": 2` needs `"offset": 127` here: the textbook 128 lightens every pixel by 1-2 levels, and
  127 leaves half the pixels exact and the rest 1 level darker (8 bits lose one bit).
- `image.calculations` — Calculations…
  `{"source1":{"document","layer","channel","invert"},"source2":{…},"blending":"multiply|…"="multiply","opacity":0..100=100,"scale":1..2=1,"offset":-255..255=0,"mask":{…}?,"result":"newChannel|newDocument|selection"="newChannel","name":str?}`
- `channel.duplicate` — Duplicate Channel…
  `{"channel":index|name|"red|…"|"composite"|"quickMask","name":str?,"document":index|"new"?=active,"invert":bool=false}`
  The start of a channel mask (hair, glass): copy the channel with the most contrast (`"invert": true` when the
  subject is darker than the backdrop), `channel.target` the copy, crush it with `image.adjustments.levels`
  (which then edits only that channel), `channel.target {"channel": "composite"}`, and
  `select.loadSelection {"channel": "<its name>"}` (verified).
- `channel.target` — Target Channel
  `{"channel":"composite"|"red|green|blue|…"|index|name="composite"}`
- `channel.list` — List Channels
  `{}`

## Filters

- `filter.blur.gaussianBlur` — Gaussian Blur…
  `{"radius":0.1..1000=1}`
- `filter.blur.motionBlur` — Motion Blur…
  `{"angle":-360..360=0,"distance":1..2000=10}`
- `filter.blurGallery.tiltShift` — Tilt-Shift…
  `{"blur":0..500=15,"centerX":0..1=0.5,"centerY":0..1=0.5,"angle":-90..90=0,"focus":0..1=0.1,"transition":0.01..1=0.15}`
- `filter.blur.lensBlur` — Lens Blur…
  `{"radius":0..100=15,"shape":"hexagon|triangle|square|pentagon|heptagon|octagon","bladeCurvature":0..100=0,"rotation":0..360=0,"depthMap":"none|transparency|layerMask","focalDistance":0..255=0,"invert":bool,"brightness":0..100=0,"threshold":0..255=255,"noise":0..100=0,"distribution":"uniform|gaussian","monochromatic":bool,"seed":u32=0}`
- `filter.sharpen.unsharpMask` — Unsharp Mask…
  `{"amount":1..500=50,"radius":0.1..1000=1,"threshold":0..255=0}`
- `filter.sharpen.smartSharpen` — Smart Sharpen…
  `{"amount":1..500=100,"radius":0.1..64=1,"reduceNoise":0..100=10}`
- `filter.noise.reduceNoise` — Reduce Noise…
  `{"strength":0..10=6,"preserveDetails":0..100=60,"reduceColorNoise":0..100=45,"sharpenDetails":0..100=25,"removeJpegArtifact":bool}`
- `filter.noise.addNoise` — Add Noise…
  `{"amount":0.1..400=12.5,"distribution":"uniform|gaussian","monochromatic":bool,"seed":u32=0}`
- `filter.noise.median` — Median…
  `{"radius":1..500=1}`
  Radius r removes specks up to about 1.4r across and lines up to about 0.8r wide.
- `filter.noise.dustAndScratches` — Dust & Scratches…
  `{"radius":1..500=1,"threshold":0..255=0}`
  The median wherever |pixel - median| > threshold; never over a whole photo, only through a mask.
- `filter.other.highPass` — High Pass…
  `{"radius":0.1..1000=10}`
- `filter.other.minimum` — Minimum… (and `filter.other.maximum`)
  `{"radius":0.2..500=1,"preserve":"squareness|roundness"}`
  On a mask (target it), Minimum chokes a cutout's edge in and Maximum spreads it.
- `filter.blurGallery.fieldBlur` — Field Blur…
  `{"blur":0..500=15,"centerX":0..1=0.5,"centerY":0..1=0.5,"pins":json}`
- `filter.stylize.oilPaint` — Oil Paint…
  `{"stylization":0.1..10=4,"cleanliness":0..10=5,"scale":0.1..10=1,"bristleDetail":0..10=5,"lighting":bool=true,"angle":-180..180=-60,"shine":0..10=1}`
- `filter.pixelate.mosaic` — Mosaic…
  `{"cellSize":2..200=10}`
- `filter.render.clouds` — Clouds
  `{"seed":u32=0}`
- `filter.convertForSmartFilters` — Convert for Smart Filters
  `{"layer":id?} (default: combine selected layers)`
- `filter.cameraRaw` — Camera Raw Filter…
  `{"temperature":-100..100=0,"tint":-100..100=0,"exposure":-5..5=0,"contrast":-100..100=0,"highlights":-100..100=0,"shadows":-100..100=0,"whites":-100..100=0,"blacks":-100..100=0,"texture":-100..100=0,"clarity":-100..100=0,"dehaze":-100..100=0,"vibrance":-100..100=0,"saturation":-100..100=0,"curveHighlights":-100..100=0,"curveLights":-100..100=0,"curveDarks":-100..100=0,"curveShadows":-100..100=0,"curveSplits":[25,50,75],"pointCurve":[[in,out]],"pointCurveRed":[[in,out]],"pointCurveGreen":[[in,out]],"pointCurveBlue":[[in,out]],"hslHue":[8],"hslSat":[8], …`
  Works as a smart filter (filter.convertForSmartFilters first), re-editable with layer.smartFilter.setParams.
- `filter.lensCorrection` — Lens Correction…
  `{"profile":"none|auto|generic","focalLength":mm=0,"correctDistortion":bool=true,"correctVignette":bool=true,"correctCA":bool=true,"autoScale":bool=false,"distortion":-100..100=0,"redCyan":-100..100=0,"blueYellow":-100..100=0,"vignetteAmount":-100..100=0,"vignetteMidpoint":0..100=50,"vertical":-100..100=0,"horizontal":-100..100=0,"angle":-180..180=0,"scale":50..150=100,"edge":"transparency|edgeExtension|black|white","straighten":[[x,y],[x,y]]?}`
  Distortion +N pushes the edges out (fixes barrel), vertical -N widens the top (fixes a looking-up shot), angle +N turns clockwise; a smart filter on a smart object.

## Retouching tools

Work on an empty layer above the photo (or a duplicate). Steps planned by the scripts carry an explicit
`"layer"` and `"target": "pixels"`.

- `paint.spotHealing` — Spot Healing Brush
  `{"points":[[x,y,pressure?],…],"size":1..5000 px=tool size,"hardness":0..100=tool hardness,"opacity":1..100=100,"flow":1..100=100,"spacing":1..1000 (% of size)=Brush Settings spacing,"layer":id?=active,"target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target,"type":"contentAware|createTexture|proximityMatch"="contentAware","sampleAllLayers":bool=false}`
  Small specks on even ground; content-aware.
- `paint.healingBrush` — Healing Brush
  `{"points":[[x,y,pressure?],…],"size":1..5000 px=tool size,"hardness":0..100=tool hardness,"opacity":1..100=100,"flow":1..100=100,"spacing":1..1000 (% of size)=Brush Settings spacing,"layer":id?=active,"target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target,"source":[sx,sy] | "offset":[dx,dy],"aligned":bool=true,"sampleLayer":"current|currentAndBelow|all"="current","mode":"normal|…"="normal" → {"damage","offset","aligned","nextSource"}}`
  Copies texture from source/offset and takes its tone from the dab's rim. On an empty layer pass "sampleLayer": "currentAndBelow" (with "current" it does nothing and still returns ok). A multi-point stroke heals dab by dab, with one offset: a parallel strip, the wire stroke.
  "all" also samples visible adjustment layers above the target: with a solar check layer showing, a heal came out 71 levels darker. Hide check layers before healing, or use "currentAndBelow". On frequency separation's High layer use "current": anything below reads the photo into a Linear Light layer (a spot 57-66 levels too light).
- `paint.cloneStamp` — Clone Stamp
  `{"points":[[x,y,pressure?],…],"size":1..5000 px=tool size,"hardness":0..100=tool hardness,"opacity":1..100=100,"flow":1..100=100,"spacing":1..1000 (% of size)=Brush Settings spacing,"layer":id?=active,"target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target,"source":[sx,sy] (sampled under the first point) | "offset":[dx,dy],"aligned":bool=true,"sampleLayer":"current|currentAndBelow|all"="current","mode":"normal|multiply|…"="normal" → {"damage","offset","aligned","nextSource"}}`
  For edges and structure, where healing smears: hardness 60-90, offset along the edge. Offsets are whole pixels
  (`[10.5, 3.25]` runs, and comes back, as `[11, 3]`).
- `paint.patch` — Patch
  `{"offset":[dx,dy] (how far the selection was dragged),"mode":"source|destination"="source","contentAware":bool=false (fill the selection content-aware from the dragged-to place; a background job),"structure":1..7=4 (content-aware: 3..7 copy the middle exactly, 1..2 re-synthesise more of it),"color":0..10=0 (content-aware: how far the copy's level adapts to the selection's surroundings),"sampleAllLayers":bool=false (content-aware),"layer":id?=active,"target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target} → {"damage","offset"}`
  From a selection: offset points at a donor on the same plane and light; content-aware patch and fill smeared high-key areas in 0.7.0.
- `paint.remove` — Remove
  `{"points":[[x,y,pressure?],…],"size":1..5000 px=tool size,"hardness":0..100=tool hardness,"opacity":1..100=100,"flow":1..100=100,"spacing":1..1000 (% of size)=Brush Settings spacing,"layer":id?=active,"target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target,"closeLoops":bool=true (a stroke around an object removes what it encloses),"sampleAllLayers":bool=false → {"damage"} (a background job)}`
  A background job; content-aware; clean on wires, specks and flakes, smears person-sized areas; closeLoops fills what a loop encloses.
- `paint.redEye` — Red Eye
  `{"x":px, "y":px} | {"points":[[x,y],…] (at most 64)},"pupilSize":1..100=50,"darken":0..100=50,"layer":id?=active,"target":"pixels"|"mask"|"quickMask"|{"channel":i} → {"damage":[x,y,w,h], "pixels":n}`
  The defaults leave a pink pupil on strong red-eye; pupilSize 100, darken 80-100 gave a dark one.

## Type

- `type.create` — New Type Layer
  `{"x":px,"y":px (baseline anchor of point text),"text":str,"box":[x,y,w,h]? (paragraph text),"name":str?,"align":"left|center|right|justify…"?,"orientation":"horizontal|vertical"="horizontal", …character keys: "font","size":pt=12,"color",…}`
  The "character keys" are the ones listed under `type.setStyle` below (`font`, `fontStyle`,
  `weight`, `tracking`, `leading`, …); they work in `type.create` too. `size` is in points; on a
  72 ppi document 1 pt = 1 px. To centre text, use `align: "center"` with a `box`, then check the
  bounds: tracking adds space after the last letter, so nudge with `type.edit {"move": [dx, 0]}`.
- `type.edit` — Edit Type
  `{"layer":id?,"text":str? (replace all, styles kept),"replace":{"start":char,"end":char,"text":str}?,"runs":[{"start":char,"end":char,…character keys}]?,"box":[x,y,w,h]? (to paragraph text),"point":[x,y]? (to point text),"move":[dx,dy]?,"transform":[a,b,c,d,e,f]?,"antialias":"none|sharp|crisp|strong|smooth"?,"name":str?,"kerning":1/1000em|"metrics"|"optical"|"off"? (with "range":[startChar,endChar]?, default all),"kernPair":{"at":caretChar,"by":1/1000em}? (Alt+←/→: the pair before the caret becomes manual, its current kerning + by)}`
- `type.setStyle` — Set Type Style
  `{"layer":id? or "layers":[id,…]? (default selected Type layers),"range":[startChar,endChar]? (single layer; default all),"metricsAsShown":bool=false (size/leading include each layer's transform scale), "font":str,"fontStyle":str,"weight":100..900,"italic":bool,"size":0.1..=1296 pt,"color":"#rrggbb"|[r,g,b,a],"tracking":-1000..=10000 (1/1000 em),"leading":pt|"auto","baselineShift":pt,"horizontalScale":%,"verticalScale":%,"underline":bool,"strikethrough":bool,"fauxBold":bool,"fauxItalic":bool,"kerning":1/1000em (manual, after each character)|"metrics"|"optical"|"off","caps":"normal|small|all","ligatures":bool,"discretionaryLigatures":bool,"features":{"ss01":1},"variations":{"wght":650},"langua …`
- `type.info` — Type Layer Info
  `{"layer":id?} → text, runs/paragraphs (char offsets + styles), shape, transform, laid-out lines (text space px), bounds`
- `type.fonts` — List Fonts
  `{"family":str? (faces of one family)}`
  The reply is large (100 KB+ even for one family); pipe it through python and print only names.

## Shapes & painting

- `shape.create` — New Shape Layer
  `{"kind":"rect|roundedRect|ellipse|polygon|star|line|path"="rect","rect":[x,y,w,h] (rect/roundedRect/ellipse/polygon/star),"radii":[tl,tr,br,bl]|r (roundedRect=10),"sides":3..100=5,"starRatio":0..1 (star=0.5),"from":[x,y],"to":[x,y],"weight":px=1 (line),"path":{…} (kind path),"fill":"#rrggbb"|[r,g,b,a]|{"gradient":{"stops":[[t,"#hex"]],"angle":deg,"scale":%,"style":"linear|radial|angle|reflected|diamond","reverse":bool}}|{"pattern":name}|null (no fill)=foreground,"stroke":{"width":px,"color":"#rrggbb"|fill,"opacity":0..100,"align":"inside|center|outside","cap":"butt|round|square","join":"miter|round|bevel","miterLimit":n,"dashes":[multiples of width],"dashOffset":n}|null=none,"name":str?,"add …`
- `paint.stroke` — Brush Stroke
  `{"points":[[x,y,pressure?,tiltX?,tiltY?,rotation?,timeMs?,wheel?],…],"brush":{…BrushSettings}?,"preset":name?,"size":0.5..5000 px?,"hardness":0..1?,"opacity":0..1?,"flow":0..1?,"spacing":0..10?,"color":"#rrggbb"?=foreground,"mode":"normal|multiply|screen|…"="normal","erase":bool?,"smoothing":0..1?,"zoom":number=1,"seed":u64?,"target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target}`
- `tools.setColors` — Set Colors
  `{"foreground":"#rrggbb"?,"background":"#rrggbb"?}`
- `tools.setBrush` — Set Brush
  `{"preset":name?,"reset":bool?,…BrushSettings fields (camelCase, deep-merged)}`

## Layer styles

- `layer.layerStyle.dropShadow` — Drop Shadow…
  `{"color":"#rrggbb","opacity":0..100=75,"blend":str="multiply","angle":deg=120,"useGlobalLight":bool,"distance":px=5,"spread":0..100,"size":px=5,"contour":"Linear|Cone|Cone (Inverted)|Domed|Domed (Inverted)|Diagonal (Descending)"="Linear","noise":0..100,"knocksOut":bool,"add":bool,"layer":id}`
- `layer.layerStyle.stroke` — Stroke…
  `{"size":px=3,"position":"outside|inside|center","color":"#rrggbb","from":"#rrggbb","to":"#rrggbb","style":str,"angle":deg,"opacity":0..100,"blend":str,"add":bool}`
- `layer.layerStyle.outerGlow` — Outer Glow…
  `{"color":"#rrggbb","opacity":0..100=75,"blend":str="screen","technique":"softer|precise","spread":0..100,"size":px,"range":0..100,"contour":name,"noise":0..100,"add":bool}`
- `layer.layerStyle.colorOverlay` — Color Overlay…
  `{"color":"#rrggbb","opacity":0..100=100,"blend":str,"add":bool}`
- `layer.layerStyle.gradientOverlay` — Gradient Overlay…
  `{"from":"#rrggbb","to":"#rrggbb","style":"linear|radial|angle|reflected|diamond","angle":deg=90,"scale":10..150=100,"reverse":bool,"opacity":0..100,"blend":str,"add":bool}`
- `layer.layerStyle.bevelEmboss` — Bevel & Emboss…
  `{"style":"inner|outer|emboss|pillow|stroke","technique":"smooth|chiselHard|chiselSoft","contour":bool,"contourRange":1..100=50,"texture":pattern id|name?,"textureScale":1..1000=100,"textureDepth":-1000..1000=100,"textureInvert":bool,"textureLink":bool=true,"depth":1..1000=100,"direction":"up|down","size":px=5,"soften":px,"angle":deg,"altitude":deg,"add":bool}`
- `layer.layerStyle.replace` — Edit Layer Style
  `{"layer":id,"effects":[{"kind":"dropShadow|innerShadow|outerGlow|innerGlow|stroke|colorOverlay|gradientOverlay|patternOverlay|satin|bevelEmboss","params":{…layer.layerStyle.<kind> params…},"fx":<effect snapshot carried through the Layer Style dialog, optional>}]} (replaces the layer's whole effect list; an entry with `fx` edits that effect with the params present, one without builds from params)`
- `layer.layerStyle.clear` — Clear Layer Style
  `{"layer":id? (no layer: every selected layer that has a style)}`

## Transform

- `edit.transform` — Free Transform
  `{"layer":id?,"rect":[x0,y0,x1,y1]? (source frame; default = layer content ∩ selection),"quad":[[x,y]×4]? (where the frame's corners go, clockwise from top-left),"matrix":[a,b,c,d,e,f]? (affine alternative),"interpolation":"bicubic|bilinear|nearest"="bicubic","target":"pixels"|"mask"|"quickMask"|{"channel":i}=Channels panel target (an unlinked mask, an alpha channel or the Quick Mask transforms alone; a linked mask moves with its layer)}`
  The quad is a true projective homography. It moves only the active layer (a Background becomes "Layer 0"), and pixels pushed off the canvas are kept. `matrix` [a,b,c,d,e,f]: x' = a·x + c·y + e, y' = b·x + d·y + f, in document coordinates.
- `edit.transform.flipHorizontal` — Flip Horizontal
  `{}`
- `edit.transform.warp` — Warp
  `{"layer":id?,"rect":[x0,y0,x1,y1]? (warp box; default = layer content ∩ selection),"style":"custom|none|arc|arcLower|arcUpper|arch|bulge|shellLower|shellUpper|flag|wave|fish|rise|fisheye|inflate|squeeze|twist","bend":%=50,"hDistort":%,"vDistort":%,"vertical":bool,"mesh":{"us":[0,…,1],"vs":[0,…,1],"points":[[x,y]…]} ((3c+1)×(3r+1) control points, row-major, document px),"grid":[cols,rows]?,"warp":{full warp object}?,"interpolation":"bicubic|bilinear|nearest"}`
- `edit.perspectiveWarp` — Perspective Warp
  `{"planes":[{"src":[[x,y]×4],"dst":[[x,y]×4]}…] (corners clockwise from top-left; corners that coincide in src are linked),"straighten":"horizontal|vertical|auto"?,"interpolation":"bicubic|bilinear|nearest","layer":id?}`
  Not yet exercised by these workflows; straighten.py uses edit.transform's quad.
- `image.analysis.rulerTool` — Ruler Tool
  `{"start":[x,y],"end":[x,y],"protractor":[x,y]|null?,"clear":bool=false} (no params: read) → X/Y/W/H/angle/L1/L2`
  Angle is y-up: a line falling to the right reads negative.
- `image.analysis.straightenLayer` — Straighten Layer
  `{"crop":bool=(active layer is the Background)} (rotates so the ruler line is level; crop = rotate the canvas and crop to the image)`
  Levels the ruler line and crops to the largest rectangle with the photo's aspect.

## Export

- `file.export.quickExport` — Quick Export
  `{"path":str? (required unless Export Preferences › Location is "sameFolder" and the document is saved)} → {path, format, bytes}`
- `file.export.saveForWebLegacy` — Save for Web (Legacy)…
  `{"preset":"GIF 128 Dithered|JPEG High|PNG-24|…"?,"format":"gif|png8|png24|jpeg|wbmp"="png24","palette":"perceptual|selective|adaptive|restrictive|exact|systemMac|systemWindows|uniform"="selective","colors":2..256=256,"dither":"none|diffusion|pattern|noise"="diffusion","ditherAmount":0..100=88,"transparency":bool=true,"matte":"#rrggbb|none"="#ffffff","interlaced":bool=false,"webSnap":0..100=0,"quality":0..100=60,"progressive":bool=false,"optimized":bool=true,"embedIcc":bool=false,"metadata":"none|copyright|copyrightAndContact|all"="copyright","convertToSrgb":bool=true,"width"|"height"|"percent"? (image size),"resample":"bicubic|bilinear|nearest"?,"path":file? (whole image),"dir":folder? (one  …`
- `file.export.layersToFiles` — Layers to Files…
  `{"dir":folder,"format":"png|jpg|psd|tiff|…"="png","prefix":str=document name,"visibleOnly":bool=true,"quality":0..12?,"tiffLayers":bool=false} → {files}`
