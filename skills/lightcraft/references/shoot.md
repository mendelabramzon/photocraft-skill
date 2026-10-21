# A whole shoot: cull, match, sync, export

Read this when the job is many photos: a wedding, an event, a trip, a product line, a folder of raws to
turn into something deliverable. It covers culling, giving photos of the same light the same edit, and
exporting for each use. Single-photo development is in `develop.md`.

Commands below use `$LC` and `$LOOK` as SKILL.md sets them:
`${CLAUDE_SKILL_DIR}/scripts/lc.py` and `${CLAUDE_SKILL_DIR}/scripts/look.py`.

## Contents
- What a professional delivers
- Step 1: a library for the shoot
- Step 2: cull
- Step 3: develop one photo per light
- Step 4: match and sync
- Step 5: check the set
- Step 6: export
- Export recipes
- Tuning and false hits

## What a professional delivers

- **A selection, not everything.** Technical failures out (missed focus, motion blur, closed eyes, badly
  missed exposure), the best of each burst kept, near-duplicates thinned. Event photographers often deliver
  10–20 % of what they shot; the user decides the ratio.
- **Nothing deleted.** Culling is ratings and flags. Rejected photos stay in the library and on disk.
  Delete only when the user asks, and even then `photo.delete` only moves them to Recently Deleted.
- **One look per light.** Photos taken in the same light get the same white balance and the same look, so
  the set reads as one story. Exposure differences are evened out.
- **Files fit for their use.** Web, social, print and archive exports differ in size, colour space,
  sharpening and metadata (see Export recipes).

## Step 1: a library for the shoot

- **Live:** the user's own library. `$LC launch ~/Pictures/shoot` imports the folder in place.
- **Headless:** a work library, so ratings and edits survive between steps:

      W=~/.lightcraft-skill/work/<shoot>
      $LC cli run --library $W/library --import ~/Pictures/shoot library.info catalog.query

`catalog.query` lists ids and file names; keep that map at hand. Bursts can be grouped first:
`stack.auto '{"gap": 2}'` stacks photos taken within 2 s of each other.

## Step 2: cull

1. **Score.** `photo.analyze` (on the selection, or `ids`) gives each photo a focus score (0–100) and
   `clipped`, the share (0–1) of its pixels clipped at either end (a black background counts). It groups
   look-alike shots taken within 10 s and marks each group's sharpest as `best`.
   It changes nothing unless you pass `rejectBelow` or `pickBest`.
2. **Read the scores within a group, not across the shoot.** Sharpness is measured over the frame: a
   shallow-depth portrait with sharp eyes scores below a sharp landscape (on eight different test photos
   it ranged from 24 to 100). The useful question is which frame of a burst is sharpest.
3. **Look.** Render every photo small, named by its id, and put them on contact sheets, one group or 12–16
   photos per sheet. `$LOOK sheet` labels each cell with its file's number, so the labels are the ids:

       for id in 3 4 5 8 9 12; do
         $LC cli run --library $W/library app.export "path=$W/sheet/$id.png" "ids=[$id]" longEdge=400
       done
       $LOOK sheet $W/sheet/*.png --out $W/sheet-1.png --cols 4

   Check what scores can't: closed eyes, expressions, a hand in front of a face, a tilted horizon. For
   focus on a face, export a crop of it at full size (`develop.md`, Step 0 and the 100 % checks).
4. **Mark.** `photo.flag '{"flag": "pick", "ids": […]}'` for the keepers, `photo.rate` 1–5 for the
   user's ranking, `photo.flag reject` only for clear failures. Tell the user what you picked and why,
   with a sheet that frames the picks: the same `$LOOK sheet` command plus `--mark 3,5,6`. Ids mean
   nothing to the user, so name the cells too: `--labels 3-LEAF,5-NEST,…`, in the cells' order (id-named
   files are sorted by number); `--mark` still matches the ids, as file names.
5. **Hand the culling over.** Headless, ratings and flags live only in the work library: list the picks
   (ids and file names) in your reply, and write XMP sidecars next to the originals only if the user asks
   (`photo.saveMetadataToFile`; rating and colour label are standard XMP, the pick flag is LightCraft's
   own). Live, they are already in the user's library.

## Step 3: develop one photo per light

Group the picks by light: indoor tungsten, window light, outdoor shade, golden hour, flash. Develop the
best photo of each group fully (`develop.md`): white balance from a neutral, tone, colour, look. Masks,
crops and spot removal are per photo; everything else will travel.

## Step 4: match and sync

1. Select the group with its hero active: `library.select '{"ids": [hero, …the rest], "active": hero}'`.
2. `develop.sync '{"groups": ["profile", "whiteBalance", "light", "toneCurve", "color", "colorMixer",
   "colorGrading", "effects", "detail", "optics", "calibration"]}'` copies those groups to every selected
   photo. Leave `crop`, `masks`, `spots` and `redEye` out: they belong to one frame. (`develop.copy` then
   `develop.paste` does the same, and its default groups already leave those out.)
3. **Exposure varies** across a set shot in changing light or with auto exposure:
   `develop.matchExposure` sets each selected photo's Exposure so its total exposure (shutter, ISO,
   aperture and the slider) equals the hero's. It needs exposure data in the files; it reports the photos
   it skipped.
4. A preset made from the hero carries the look to later shoots in the same light:
   `preset.create '{"name": "…", "groups": [...]}'`.

## Step 5: check the set

- Render every photo of the group and put them on one sheet: the set should look like one light. Outliers
  stand out on a sheet much more than one by one.
- Measure the same kind of thing across photos (a white shirt, a grey wall, skin):
  `$LOOK measure` with `--point` on each render. Neutral |a*|, |b*| ≤ 2 and skin within a few degrees
  of each other across the group.
- Fix outliers on their own (`develop.set` with `ids`, `develop.quickAdjust` for relative nudges), not by
  re-syncing everything.

## Step 6: export

Export the picks (or the selection the user names) into a folder with a naming template:

    $LC cli run --library $W/library library.selectBy flag=pick app.export dir="$HOME/Pictures/<shoot>-web" \
        'naming={date}_{seq:3}' longEdge=2048 quality=85 sharpen=screen metadata=copyright removeLocation=true

`library.selectBy` selects among the photos in view: `flag`, `rating` with `ratingOp` (`gte` by default),
`label`. Copyright and creator go in once with `photo.setMeta '{"ids": […], "copyright": "© …", "creator":
"…"}'` before exporting. A PDF contact sheet for a client: `export.contactSheet '{"path": "…pdf", "columns":
4, "rows": 5, "captions": true}'`.

## Export recipes

All are `app.export` params; add `dir` and `naming` for many photos, `path` for one.

| Use | Params |
|---|---|
| Web, blog, portfolio | `longEdge: 2048, quality: 85, colorSpace: "srgb", sharpen: "screen", metadata: "copyright", removeLocation: true` |
| Instagram feed (portrait) | crop `4x5`, plus `crop.rotateAspect` on a landscape or square photo; `width: 1080, height: 1350, quality: 90, colorSpace: "srgb", sharpen: "screen"`. Check the size in the result; add `dontEnlarge: false` (and say it's upscaled) when the crop has fewer pixels |
| Stories and reels covers | crop `[9,16]` (rotated as above), `width: 1080, height: 1920` |
| Size-limited upload or email | `longEdge: 1800, limitKb: 500` (JPEG: quality is lowered until it fits) |
| Client proofs | `longEdge: 1600, quality: 80, watermark: {"text": "© Name", "opacity": 0.4, "anchor": "bottomRight"}` |
| Print at a lab | `format: "tiff", bitDepth: 16, colorSpace: "adobeRgb", ppi: 300, sharpen: "matte"` or `"glossy"`, and `longEdge` = print inches × 300 (or `longEdge: 0`). Use `srgb` JPEG at quality 95 when the lab asks for it |
| Archive master | `longEdge: 0`, 16-bit TIFF; raws as `format: "dng"` (edits embedded) or `format: "original"` (file + XMP) |

For a tight crop around a subject, export the crop and look at its edges at 100 %, then nudge `crop.set`:
positions read off a grid are good to about 1 % of the frame.

On macOS, `addToPhotos: true, photosAlbum: "…"` also adds the files to Apple Photos; only when the user
asks (macOS asks them to allow it the first time).

## Tuning and false hits

| Symptom | Cause | Fix |
|---|---|---|
| A sharp portrait was scored low | Sharpness is over the whole frame; a soft background lowers it | Compare within a burst; check the eyes at 100 % |
| `photo.analyze` made no groups | Groups need look-alike shots within 10 s | Use `stack.auto` with a gap, or compare by eye on sheets |
| Synced photos are too warm or cold | They were shot in a different light from the hero | Develop a hero for that light and sync the group separately |
| `matchExposure` skipped photos | No shutter, ISO or aperture in the file (scans, edited JPEGs) | Even them out by eye with `develop.quickAdjust` |
| Exported files have odd names or land in the wrong folder | `path` with several photos ignores the name | `dir` and `naming` for many photos |
| A repeated export made `-2` copies | `conflict: unique` (the default) | `conflict: "overwrite"` when replacing your own earlier export |
| An Instagram post came out landscape (1350 × 1080) | `4x5` on a landscape or square photo without `crop.rotateAspect` | Add it; check the size in the export's result |
| An Instagram post came out 1080 × 1349 | The crop isn't exactly 4:5 in whole pixels | `crop.set` one that is: for a photo `W` × `H` px, height `h` = `H` rounded down to a multiple of 5, width `w = 4h/5`, centred: `rect` = [(W−w)/2W, (H−h)/2H, (W+w)/2W, (H+h)/2H] (408 × 510 on a 512 px square). On a portrait photo narrower than 4:5, start from the width: `w` = `W` rounded down to a multiple of 4, `h = 5w/4` |
| The export is smaller than the size asked for | `dontEnlarge` (on by default) and a crop with fewer pixels | `dontEnlarge: false`, and tell the user it's upscaled |
