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
- Document & canvas · Layers · Adjustments · Selections & masks · Filters · Type
- Shapes & painting · Layer styles · Transform · Export

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
- `document.inspect` — Inspect Document
  `{"document":index?}`
- `document.pixel` — Read Composite Pixel
  `{"x":i32,"y":i32}`
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
- `layer.duplicate` — Duplicate Layer…
  `{"layer":id?,"inPlace":bool=false (artboards: keep the copy on the original instead of beside it)} (no layer: every selected layer)`
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

## Adjustments (non-destructive layer vs. direct)

- `layer.newAdjustmentLayer.levels` — Levels…
  `{"inBlack":0..253=0,"gamma":0.01..9.99=1,"inWhite":2..255=255,"outBlack":0..255=0,"outWhite":0..255=255,"red":json,"green":json,"blue":json} (top level = composite; per channel {"inBlack","gamma","inWhite","outBlack","outWhite"} under red/green/blue, gray, cyan/magenta/yellow/black or lightness/a/b) + mask*`
- `layer.newAdjustmentLayer.curves` — Curves…
  `{"points":json,"red":json,"green":json,"blue":json,"eyedropper":json} (curves as [[in,out],…] in 0..255, 2..19 points: points = composite; red/green/blue, gray, cyan/magenta/yellow/black or lightness/a/b per channel; eyedropper = the dialog's Set Black/Neutral Gray/White Point picker {"point":"black|gray|white","at":[x,y]} or {"point",…,"color":[r,g,b] 0..1}, RGB and Grayscale (no gray) only, applied over the given curves) + mask*`
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
- `layer.newAdjustmentLayer.colorLookup` — Color Lookup…
  `{"lut":"none|warm|cool|tealOrange|bleachBypass|fadedFilm|dayForNight|monoContrast|crossProcess"="none","file":text,"interpolation":"trilinear|tetrahedral"="trilinear","dither":bool=false,"data":json} (file: .cube/.3dl/.look path; data: file text + "fileName") + mask*`
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
- `select.object` — Object Selection
  `{"rect":[x,y,w,h],"mode":"replace|add|subtract|intersect"="replace","sampleAllLayers":bool=false}`
- `select.modify.feather` — Feather…
  `{"radius":0.1..1000=1,"applyAtCanvasBounds":bool=false}`
- `select.modify.expand` — Expand…
  `{"radius":1..500=1,"applyAtCanvasBounds":bool=false}`
- `layer.layerMask.revealSelection` — Reveal Selection
  `{"layer":id?} (no layer: every selected layer that can take a mask)`
- `layer.layerMask.revealAll` — Reveal All
  `{"layer":id?} (no layer: every selected layer that can take a mask)`
- `layer.layerMask.apply` — Apply
  `{"layer":id?}`
- `edit.fill` — Fill…
  `{"contents":"foreground|background|color|contentAware|pattern|history|black|gray|white"="color","color":"#rrggbb|[r,g,b,a]"=foreground (contents=color),"pattern":id|name (contents=pattern),"scale":%=100,"angle":deg,"state":index? (contents=history; default the oldest state),"colorAdaptation":bool=true (contents=contentAware),"mode":"normal|multiply|…"="normal","opacity":0..100=100,"preserveTransparency":bool=false,"target":"pixels"|"mask"|"quickMask"|{"channel":i}?}`
- `edit.stroke` — Stroke…
  `{"width":1..250=1,"color":"#rrggbb|[r,g,b,a]"=foreground,"location":"inside|center|outside"="center","mode":"any layer blend mode"="normal","opacity":0..100=100,"preserveTransparency":bool=false}`
- `edit.contentAwareFill` — Content-Aware Fill…
  `{"sampling":"auto|rectangular|custom","margin":px?,"area":[x,y,w,h]?,"channel":index|name?,"colorAdaptation":"default|none|high|veryHigh","rotationAdaptation":"none|low|medium|high|full","scale":bool=false,"mirror":bool=false,"output":"current|new|duplicate","seed":u64=1}`

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
- `filter.other.highPass` — High Pass…
  `{"radius":0.1..1000=10}`
- `filter.stylize.oilPaint` — Oil Paint…
  `{"stylization":0.1..10=4,"cleanliness":0..10=5,"scale":0.1..10=1,"bristleDetail":0..10=5,"lighting":bool=true,"angle":-180..180=-60,"shine":0..10=1}`
- `filter.pixelate.mosaic` — Mosaic…
  `{"cellSize":2..200=10}`
- `filter.render.clouds` — Clouds
  `{"seed":u32=0}`
- `filter.convertForSmartFilters` — Convert for Smart Filters
  `{"layer":id?} (default: combine selected layers)`

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
- `edit.transform.flipHorizontal` — Flip Horizontal
  `{}`
- `edit.transform.warp` — Warp
  `{"layer":id?,"rect":[x0,y0,x1,y1]? (warp box; default = layer content ∩ selection),"style":"custom|none|arc|arcLower|arcUpper|arch|bulge|shellLower|shellUpper|flag|wave|fish|rise|fisheye|inflate|squeeze|twist","bend":%=50,"hDistort":%,"vDistort":%,"vertical":bool,"mesh":{"us":[0,…,1],"vs":[0,…,1],"points":[[x,y]…]} ((3c+1)×(3r+1) control points, row-major, document px),"grid":[cols,rows]?,"warp":{full warp object}?,"interpolation":"bicubic|bilinear|nearest"}`

## Export

- `file.export.quickExport` — Quick Export
  `{"path":str? (required unless Export Preferences › Location is "sameFolder" and the document is saved)} → {path, format, bytes}`
- `file.export.saveForWebLegacy` — Save for Web (Legacy)…
  `{"preset":"GIF 128 Dithered|JPEG High|PNG-24|…"?,"format":"gif|png8|png24|jpeg|wbmp"="png24","palette":"perceptual|selective|adaptive|restrictive|exact|systemMac|systemWindows|uniform"="selective","colors":2..256=256,"dither":"none|diffusion|pattern|noise"="diffusion","ditherAmount":0..100=88,"transparency":bool=true,"matte":"#rrggbb|none"="#ffffff","interlaced":bool=false,"webSnap":0..100=0,"quality":0..100=60,"progressive":bool=false,"optimized":bool=true,"embedIcc":bool=false,"metadata":"none|copyright|copyrightAndContact|all"="copyright","convertToSrgb":bool=true,"width"|"height"|"percent"? (image size),"resample":"bicubic|bilinear|nearest"?,"path":file? (whole image),"dir":folder? (one  …`
- `file.export.layersToFiles` — Layers to Files…
  `{"dir":folder,"format":"png|jpg|psd|tiff|…"="png","prefix":str=document name,"visibleOnly":bool=true,"quality":0..12?,"tiffLayers":bool=false} → {files}`
