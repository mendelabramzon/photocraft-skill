---
name: photocraft
description: Operate PhotoCraft, the open-source Photoshop-style image editor (storytold/photocraft), on the user's Mac. Drives the live desktop app (open files, add layers, adjustment layers, filters, type, shapes, selections, masks, layer styles, brush strokes, dialogs, screenshots) through its JSON control channel, and does headless file-in/file-out editing, batch processing and format conversion (PSD, PNG, JPEG, TIFF, WebP…) with photocraft-cli. Includes professional retouching workflows: skin, eyes and teeth, colour correction and grading, cutouts and product photos on white, removing objects, wires and dust, straightening horizons and verticals, sky replacement, old-photo restoration. Use this whenever the user mentions PhotoCraft, or asks to edit, retouch, color-grade, resize, crop, caption, composite, batch-process or convert images and PhotoCraft is how they edit images — even if they just say "the app", "my photo editor", or "do it in Photoshop-like steps".
license: Apache-2.0
compatibility: Needs macOS with the PhotoCraft desktop app, and Claude Code running on that Mac (it drives the app over 127.0.0.1). Headless editing and the retouching workflows' planning scripts also need photocraft-cli, installed by the user.
---

# PhotoCraft

PhotoCraft is a native Rust reimplementation of Photoshop: same menus, shortcuts, layers, masks,
adjustment layers, layer styles, type and PSD files. Every menu item, tool and dialog is a
**command** with an id (`filter.blur.gaussianBlur`) and JSON params, from one registry of ~850.
The UI, the CLI and the control channel all run the same commands, so anything a user can click,
you can run.

All access goes through one helper script, `scripts/pc.py` in this skill's directory (Python 3,
standard library only). Set a variable for it in your shell commands,
`PC=${CLAUDE_SKILL_DIR}/scripts/pc.py` (this skill's directory), and run `$PC -h` or
`$PC <subcommand> -h` for usage. The other scripts mentioned below live next to it.

## Two ways to operate it

| | Live app (control channel) | Headless (`photocraft-cli`) |
|---|---|---|
| Use when | The user wants it done *in PhotoCraft*: to watch, keep working on the result, see dialogs, use tools on the canvas | File in → file out: "make these 40 photos web-sized", convert formats, generate an image, scripted edits |
| Speed | One round trip per request | ~0.2 s for a whole edit chain |
| Start | `$PC launch [files…]` | the user installs it once (`$PC cli-info`), then `$PC cli …` |
| Details | `references/live-app.md` | `references/headless.md` |

If unclear, ask yourself whether the user expects to see the result open in the app afterwards.
If yes, live; otherwise headless is faster and can't disturb their open work.

## Step 1: check what's there

    $PC status

This reports the app path and version, whether `photocraft-cli` is installed, every running
PhotoCraft process (and whether it has the control channel), and whether the channel answers.

- **CLI missing and you need headless** (batch work, conversions, and the crops and renders the
  workflow planners read): `$PC cli-info` names the `photocraft-cli` zip that matches the installed app and
  where the binary goes. It's on that version's release page,
  `https://github.com/storytold/photocraft/releases/tag/v<appVersion>`. Ask the user to install it:
  download that zip, check its SHA-256 against the release's `SHA256SUMS.txt`, unzip it, and put
  `photocraft-cli` in `~/.photocraft-skill/bin/` or on their PATH. Then `$PC status` shows it. The
  skill never downloads binaries on its own; if the user asks you to do those steps for them, go ahead.
- **App not found:** it's at https://github.com/storytold/photocraft/releases (macOS `.dmg`).

## Step 2 (live): get a controllable window

A PhotoCraft started normally (Dock, Finder) has no control channel and cannot be driven. The
channel only exists when the app is launched with `--control`, which `$PC launch` does: it starts
**a separate PhotoCraft window** with a fresh token in `~/.photocraft-skill/token` (mode 0600),
listening on loopback only, with file access limited to the automation roots (default: the
user's home folder; override with `--read-root` / `--write-root`).

- If `status` shows `controlReachable: true`, reuse it; don't launch another.
- If the user already has PhotoCraft open normally, never kill or quit that process; it may hold
  unsaved work. Launching the controlled instance alongside it is fine; mention that the new
  window is the one you're driving, and that their documents in the other window aren't visible
  to you. If they'd rather have one window, they can save and quit theirs first.
- Open their file in it: `$PC launch ~/Pictures/photo.jpg`, or later
  `$PC call app.open '{"path": "/abs/path/photo.jpg"}'`.
- Right after opening, run `$PC status`: if `dialogs` isn't empty, a dialog is blocking the window.
  The common one is the colour-profile mismatch (e.g. a Display P3 photo in an sRGB working space).
  Get its id from `$PC call ui.inspect` → `dialogs`, then confirm it with
  `$PC call ui.dialog.confirm '{"dialog": <id>}'`. Its default is `preserve`, which keeps the
  photo's own profile and is the safe choice. Mention it to the user.

## Step 3: work in a loop: look, act, check

1. **Look.** `$PC exec document.inspect --max-chars 0` gives the layer tree (`id`, `name`, `kind`,
   `visible`, `bounds`), `activeLayer`, `history`, selection. Layer ids are what commands take.
   Watch the bounds format: `document.inspect` gives `[x, y, w, h]`, while some command results
   (e.g. `type.create`) give `[x0, y0, x1, y1]`.
2. **Find the command.** Start with `references/commands.md` (common commands with exact param
   docs). For anything else, search the live registry:
   `$PC cli commands --filter <word>` (headless) or
   `$PC exec command.list --max-chars 0 | python3 -c "…filter by id…"` (live; includes `enabled`
   and `disabledReason`). Param shapes differ between versions, so when a call fails with
   `invalid parameters`, read that command's params doc instead of guessing again.
3. **Act.** `$PC exec <command-id> '<json params>'`. For several steps at once, write them to a file
   and `$PC script steps.json` (one connection, one line of output per step, stops at the first error).
4. **Check visually.** Don't report success from a JSON `ok` alone; look at the pixels.
   Live: `$PC screenshot <any path>.png` (whole window, shows the Layers panel too; written by
   the script, so any folder works) or `$PC export <path>.png` (just the image, flattened; written
   by the app, so the path must be inside the write root — the home folder by default, not `/tmp`).
   Headless: the `--out` file.
   Then read the PNG with the Read tool. Shrink large ones first (`sips -Z 1600 in.png --out small.png`)
   so they fit in context.

### The mistake to avoid: wrong active layer

Creating a layer, adjustment layer, fill layer or type layer makes **it** the active layer, and an
adjustment layer additionally targets its **mask**. A filter, fill or paint stroke right after that
silently goes onto the mask or the new layer, not the photo, and still returns `ok`. Before any
pixel operation (filters, `edit.fill`, `paint.stroke`, `image.adjustments.*`), run
`layer.select {"layer": <pixel layer id>}` and check `activeLayer`. Do the pixel work first and
add adjustment layers last when you can.

### Other traps

- **Ids change.** `filter.convertForSmartFilters` and `layer.smartObjects.convertToSmartObject`
  replace the layer with a new one that has a new id. Re-read `document.inspect` after them.
- **Smart selection is approximate.** `select.subject` can return `ok` while catching only
  part of the subject (e.g. a bird's white head but not its dark shoulders). Look at it in a
  screenshot (the marching ants show), then patch it with `select.object {"rect": […], "mode": "add"}`
  or `select.rect`/`select.lasso` in `add`/`subtract` mode.
- **Many commands return `null`.** That means success with no data, not failure; verify by
  inspecting or looking.
- **Subtle edits on dark images** are hard to judge in a screenshot. Temporarily add a Levels
  layer that brightens everything, compare with the effect on and off, then remove it
  (`layer.delete`) so it doesn't end up in their file.

- **Paint tools follow the targeted channel.** After adding a mask, `paint.*` commands may write
  into the mask (or fail with "layer has no mask" on another layer). Always pass
  `"target": "pixels"` and an explicit `"layer"` to `paint.spotHealing`, `paint.stroke`, etc., and
  `layer.select` that layer first: with a group active they fail ("not available right now").
- **`file.close` discards unsaved changes without asking.** Only close documents you opened as scratch.
- **Bringing an image in:** `file.placeEmbedded` is refused over the control channel. `app.open` the
  file, then `$PC exec layer.copyToDocument` (a command, so `exec`; `call` answers "unknown method")
  with `{"document": <target>, "source": <it>, "layers": [id], "at": [cx, cy]}`, and
  `file.close {"document": <it>}`. Documents are indices (`$PC call ui.inspect` → `session.documents`;
  `document.activate {"document": i}` switches). Without `at`, `offset` or `center` the copy keeps its
  pixel position from the source. A grayscale image becomes a soft selection with
  `select.loadSelection {"channel": "red", "layer": id}`, and the next adjustment layer takes it as its mask.
- **Copying between documents converts colours** when their profiles differ. An untagged PNG opens as
  sRGB, so copied into a Display P3 phone photo, skin comes out less red and bluer. When pixel values
  must arrive unchanged, `edit.assignProfile` the source to the target's profile first
  (`edit.profileInfo {"profile": "document"}` names it). Grey masks are unaffected.
  `scripts/import_layers.py` does this for every planner's PNGs, Grayscale documents included.
- **Healing on an empty layer** needs `"sampleLayer": "currentAndBelow"` (or `"all"`): with
  `"current"` it does nothing and still returns `ok`. The planners' steps carry it.
- **Planners' steps are in full-image coordinates,** even when planned on a crop: run them on the
  whole photo. On the crop every dab lands in the wrong place, and still returns `ok`.
- **`edit.transform` moves only the active layer** (not every selected one) and keeps pixels pushed
  off the canvas; a linked mask moves with its layer (`layer.layerMask.linked {"linked": false}`
  keeps it in place). `image.crop` with an `angle` rotates every layer.
- **A fill layer covers only the canvas it was made on:** grow the canvas (`image.canvasSize`)
  before creating fills, or the new area stays transparent.
- **Content-aware fill and Remove synthesise:** never use them on faces (a torn cheek got a second
  eye and mouth); on smooth high-key areas they smear, so prefer `paint.patch` from a donor on the
  same plane and light. `select.sky` is a smooth blob 10–20 px off the real skyline; refine it.
- **The import check renders a flat copy,** so the app shows "Saved _verify_full.png … flattened".
  The document itself is unchanged.

### Recipe: skin retouch, clean but natural (read `references/skin-retouch.md` first)

Users judge retouching harshly: blur, smoothing layers, big dabs and content-aware fills read as
cheap and "plastic", and one user explicitly asked for a 10 px brush at most. Work the way
professional retouchers do: texture first, then tone, then colour, removing only what's temporary
(acne, scabs, flakes) and keeping what's the person (moles, freckles, stubble, pores, shape, light).

1. **Map the skin.** Duplicate the photo → "Healing". Crop the work region plus median-10 and
   median-3 references with the CLI. Write `area.json` (skin polygon, exclusions) using
   `scripts/grid.py` to read coordinates. Never include eyes, lips, ears, hairline or other people.
2. **Heal (texture).** `scripts/plan_heals.py` plans hundreds of ≤10 px Healing Brush dabs, each
   sourced from clean skin nearby (pass `--ref-small` so no source carries a speck). Check its
   overlay, run it with `$PC script`, then export and re-plan: 2–3 passes. Then do a **whitehead
   pass**: leftover light bumps between healed pimples read as white scars. Add `--bright-weight` on
   rim-lit skin and `--add X,Y` for blemishes it misses.
3. **Dodge & burn + colour (tone).** `scripts/skin_masks.py` computes exact masks for a Dodge and a
   Burn Curves layer (Luminosity) and a "Skin colour" layer. These correct a mark's tone and colour
   by the **same fraction**: taking the red out of a mark that stays darker leaves a grey-blue
   "bruise". It touches only blotch-scale tone, never pores or light, and only inside an area drawn
   around the marks. Check `viz.png`, `preview.png` and `compare.py --marks`, then
   `scripts/import_masks.py` builds the group in the live document and verifies nothing shifted.
4. **Check** before/after at 1× and 2–3× plus `compare.py --check`. Pores continuous, light and
   identity intact, nothing outside the skin changed. Save a layered PSD and a JPEG with new names
   (JPEG via `$PC cli convert x.psd x.jpg --quality 95`, since `app.save` ignores quality).

### Recipe: blur the background behind a subject ("portrait mode")

1. Select the subject (`select.subject`, fix it as above), then `layer.duplicate` the photo twice.
2. Top copy: `layer.layerMask.revealSelection` → the sharp subject. Name it.
3. Lower copy: `select.modify.expand {"radius": 8}`, `edit.contentAwareFill` (removes the subject,
   so the blur doesn't smear a halo around it), `select.deselect`, then
   `filter.convertForSmartFilters` + `filter.blur.lensBlur {"radius": 20..40}` (or Gaussian).
4. Keep the original Background untouched below; export, then look at the result.

### Recipe: open closed eyes from another frame (read `references/feature-swap.md` first)

PhotoCraft has no generative fill, so eyes are never painted: they come from another frame of the
same shoot. The same steps swap a smile or a head. `scripts/feature_swap.py` measures what
retouchers eyeball.

1. **Donor.** `feature_swap.py donors photo.jpg` lists the camera's frames nearest in capture time.
   Pick eyes open, head angle, light and gaze close to the target's. If there's none, say so; don't
   fake it.
2. **Align.** Copy a face-sized patch in with `layer.copyToDocument` (no offset), measure the four
   eye corners in both photos (`grid.py`), then `feature_swap.py align` → `edit.transform`. One fit
   for both eyes; 2–4 px of error is normal on a squint.
3. **Tone, before the mask.** Export with the donor shown and hidden. `feature_swap.py tone` builds
   Curves clipped to the donor that scale it like exposure, per eye with `--per-eye`.
4. **Mask.** `feature_swap.py mask` draws an almond per eye: the eye with its lashes and lid margin,
   opaque over the old lash line out past the corners, never the donor's socket shading. Look at
   `--viz` first.
5. **Check** at 1× and 3× against the original: no dark rings, no old lash line, no dark corners,
   eyes neither pale nor harsh. Feedback goes into the clipped layers, never into fading the donor's
   mask.

### The other expert workflows

Each has a reference doc with the professional rules, exact steps, measurable checks and a table of
false hits, and planning scripts that measure what a retoucher would eyeball. A planner writes
`steps.json` (run with `$PC script`) and/or `layers.json`. `scripts/import_layers.py layers.json`
builds the named, masked layers in the live document (`--file in --out out.psd` headless), then renders
the result and compares it with the plan's `preview.png`. It must say `"verify": "ok"`. Planners work
in a folder under the home directory, because the app only opens files under its read root.

### Recipe: eyes and teeth, fresh but natural (read `references/eyes-teeth.md` first)

Colour first, brightness second: take part of the yellow out of teeth (never neutral, never whiter
than the eye whites), clean the eye whites (veins, redness) and lift them only beside the iris
(bright corners flatten the eyeball), lift the iris across from the catchlight, sharpen iris and
lashes only.
1. After any skin retouch: export, crop the face (even size), write `regions.json` with `grid.py`
   (lid openings, rough iris circles, teeth polygons inside the lips).
2. `scripts/eyes_teeth.py crop.png X Y regions.json <out> [--light warm]`: masks plus curves solved
   against Lab targets, the teeth measured against the eye whites so warm light stays warm. Check
   `regions.png`, `viz.png`, `preview.png`; `import_layers.py <out>/layers.json`.
3. Red-eye first, if any: `paint.redEye` on a copy, with an explicit `layer`.

### Recipe: colour correction and grading (read `references/color-grade.md` first)

Correct by the numbers, then grade: things that are neutral in life must read R = G = B, and eyes
adapt to a cast within seconds.
1. **Measure.** `scripts/color_check.py measure now.png --viz viz.png --scope scope.png`. Read the
   per-channel clipping and the cast candidates, and look at each candidate: fur, painted walls and
   wood come up too. Sample real neutrals (grey card, white clothing in light, concrete) at a dark,
   a mid and a light level.
2. **White balance.** `color_check.py correct now.png <dir> --neutral X,Y,R … [--black X,Y,R]
   [--amount 0.7] [--tone]`, then `import_layers.py <dir>/layers.json`. Keep intended warmth with
   amount < 1; a second light gets its own `--area` layer.
3. **Look.** Use the tested looks in the doc (Color Lookup tealOrange at 40 %, a Luminosity S-curve,
   Vibrance not Saturation). Black & white through a Black & White layer with subject weights, never
   desaturate.
4. **Check.** `color_check.py compare before.png after.png --neutral … --skin …`: neutrals |a*|,
   |b*| ≤ 2, skin at 110–130° on the vectorscope and moved ≤ 5° by the look, no new clipping. The
   same light gets the same layers.json on every photo.

### Recipe: cutouts and product photos on white (read `references/cutout.md` first)

1. **Select by edge type.** `select.subject`; for a white product or a blown backdrop,
   `select.magicWand` on the backdrop + `select.inverse`. Add what it dropped (`select.object
   {"rect": …, "mode": "add"}` or a traced `select.lasso`): it drops low-contrast parts and parts
   touching the frame.
2. **Refine into a masked copy.** Product: `select.refineEdge {"radius": 1, "contrast": 25,
   "output": "newLayerWithMask"}`; hair and fur: `{"radius": 8, "smartRadius": true,
   "decontaminate": true, "amount": 100, "output": "newLayerWithMask"}`. Name it "Product".
3. **Check the cut.** Export it with the Background hidden (RGBA) plus the original;
   `scripts/cutout_check.py cut.png orig.png <dir> --kind product|soft`. Read `sheet.png`: fringe
   p95 ≤ 6 on the target background, `backdropInside` ≤ 0.03, `cutInto` ≤ 0.08.
4. **White, shadow, canvas.** `scripts/product_shot.py orig.png cut.png <ps> --size 2000 --fill 0.85`
   keeps the real contact shadow (`--shadow contact` paints one). Fix any `missingParts`, then
   `$PC script <ps>/prep.json` → `import_layers.py <ps>/layers.json --above <Background id>` →
   `$PC script <ps>/steps.json`.
5. **Deliverable.** JPEG via `$PC cli convert … --quality 95`, then
   `cutout_check.py --deliverable x.jpg <dir>`: border pure white, nothing off-white touching it, no
   specks, fill ≥ 0.85, sRGB.

### Recipe: remove dust, wires and distractions (read `references/object-removal.md` first)

The bar is an invisible removal: grain, light and structure continue, poles and branches stay, and a
removed object's shadow and reflection go with it. Dust first, then wires, then objects, each on its
own named layer.
1. **Map.** Crop + median refs with the CLI (radius 45 for dust, 12 for wires). Write `area.json`
   with `grid.py`: the sky or plain background, excluding every pole, crossarm, insulator, lamp, tree
   and roof with ~10 px to spare. It is the only reliable protection for thin hardware.
2. **Dust.** `scripts/plan_spots.py crop.png ref45.png X Y --area area.json --layer <empty layer>
   --sample currentAndBelow --steps dust.json --overlay ov.png --check check.png`: one Healing Brush
   dab per soft, round, neutral spot, past its halo. Drop birds and stars, then `$PC script dust.json`.
   24 MP and up: plan at half size with `--zoom 2`.
3. **Wires.** `scripts/plan_lines.py crop.png ref12.png X Y --area area.json --layer <empty layer>
   --sample currentAndBelow --steps wires.json --overlay ov.png`: healing strokes along each wire
   from a clean strip beside it, crossings last, stopping before structure. Finish the orange clone
   spots with `paint.cloneStamp`.
4. **Objects.** Lasso with shadow and reflection, rebuild lines behind it with the clone stamp,
   `paint.patch` from a donor on the same row and light, heal the seams.
5. **Check** at 1× and 2× (`compare.py --check` on skies), then re-plan the export: no rings,
   smudges or repeats; structure identical.

### Recipe: straighten a horizon or converging verticals (read `references/straighten.md` first)

1. `scripts/straighten.py photo.jpg <dir>` measures the photo's own lines: the horizon (a hazy sea
   horizon too) or where the verticals converge, with the focal length from EXIF. Read `mode` and
   `reason`, check `lines.png` (green must be real verticals) and `preview.png`. It leaves deliberate
   steep shots and straight photos alone.
2. Rotation only: one `image.crop` with an angle (rotate and crop, same aspect, no empty corners).
   Perspective: `edit.transform` with the quad of turning the camera level (a real camera model, so
   proportions stay right, unlike a keystone squeeze), then `image.crop` centred on the old centre.
   Steep upward shots keep about 15 % of their convergence.
3. Do it first, on the photo layer: `layer.select` it, then `$PC script <dir>/steps.json`
   (headless: `--open photo --save out.psd`). `--smart` keeps it editable.
4. Re-measure the export with `--verify`: roll and horizon within 0.1°, `edgeLean` within 0.2°.

### Recipe: replace or enhance a sky (read `references/sky.md` first)

`select.sky` alone gives a blobby edge 10–20 px off, and laying a new sky over it leaves a pale halo
of old sky.
1. **Mask.** `scripts/sky_mask.py photo.jpg <work>/sky` refines it (chimneys, aerials, canopies,
   missed patches) and recovers the edge pixels' own colours. Read `viz.png`; fix with `area.json`
   sky/keep polygons; `--trees` when branches fill the frame.
2. `scripts/sky_check.py enhance <work>/sky` says enhance or replace. If enhance, import
   `layers_enhance.json`.
3. **Replace.** Ask for a sky that matches the sun side, time of day and soft or hard light:
   `sky_check.py plan <work>/sky sky.jpg [--flip] [--haze 0.3]`, or `--clear-blue` for real estate.
   Read the warnings and `compare.png`, then `import_layers.py <work>/sky/layers.json`.
4. **Check.** `sky_check.py check <work>/sky --render export.png`: median rim near 0, every orange or
   red tile looked at 3×. Tell real-estate users that altered listing photos may need disclosure
   (California AB 723).

### Recipe: restore an old photo (read `references/restore.md` first)

Repair damage, never reinvent: the scan stays untouched, every fix is a masked or empty layer, grain
is kept, and no face is invented.
1. Crop and straighten. `area.json` via `grid.py`: `exclude` eyes, teeth, lettering, buttons; `faces`
   polygons.
2. Empty "Heal" layer, then `scripts/find_defects.py crop.png X Y <out> --area area.json --layer <Heal id>`.
   Read `overlay.png`, then `import_layers.py <out>/layers.json --above <Background id>`: median layers
   masked to the defects, with grain matched to the photo's.
3. `layer.select` Heal, `$PC script <out>/heal.json` (Remove dabs and strokes; Healing Brush inside
   faces). Missing background: lasso + expand + `edit.contentAwareFill {"output": "new"}`, never on
   faces.
4. Faces last, by hand, minimal. Tone: export, `scripts/restore_tone.py repaired.png <tone>
   [--keep-tone | --white-ref X,Y]`, import on top. Check at 100 and 200 %, re-run `find_defects.py`
   on a render, save a PSD and a JPEG under new names.

### Prefer non-destructive edits

Like a careful Photoshop user: adjustment layers (`layer.newAdjustmentLayer.*`) over direct
`image.adjustments.*`, new layers for painting and text, smart filters
(`filter.convertForSmartFilters` then the filter) when the user may want to tweak later. Name
layers (`layer.setProps {"layer": id, "name": "…"}`) so the user can find your work.

## Saving and the user's files

- Never overwrite the user's original image unless they asked to. Export to a new name next to it
  (`photo-edited.jpg`), and say where it went.
- Flat formats (JPEG, PNG) flatten layers on export; that's expected for a deliverable. If the
  user may keep editing, also save a layered `.psd` (or `.pcraft`).
- Live: `app.save {"path": …}` saves; `$PC export` writes a flat copy and leaves the document as is.
  `file.save` / `file.saveAs` are refused over the control channel by design; don't fight it.
- `app.save` to `.jpg` ignores `quality` (writes about q90). When quality matters, save the PSD, then
  `$PC cli convert photo-edited.psd photo-edited.jpg --quality 95` (keeps the colour profile).
- An export taken right after a save can come back stale. If a check doesn't match what you did,
  export again before concluding anything.
- `$PC quit` closes the controlled instance but refuses while documents are unsaved
  (the raw `app.quit` discards unsaved work without asking). Only use `--force` on documents you
  created as scratch, or when the user said to discard. Leaving the window open at the end is
  usually what the user wants anyway.

## Undo and recovery

`$PC exec edit.undo` steps back one history entry; `document.inspect` lists `history`. For risky
experiments, duplicate first: `image.duplicate {"name": "trial"}` or `history.newDocument {}`
make a new document and leave the original untouched.

## When things don't respond

- `cannot reach the PhotoCraft control channel`: the controlled instance isn't running; `$PC launch`.
- Requests time out: the window may be minimized or fully hidden (macOS stops drawing it, and the
  channel is served from the draw loop). `$PC call ui.focus`, or ask the user to bring it up.
- A dialog is open and blocking: `$PC call ui.inspect` → `dialogs`; cancel with
  `$PC call ui.dialog.cancel '{"dialog": <id>}'`.
- Long filters: `--no-wait`, then poll `$PC call jobs.list` (see `references/live-app.md`).

## Reference files

- `references/commands.md`: common commands with exact parameter docs, by task.
- `references/live-app.md`: every control-channel method, pointer/keys/tools, dialogs,
  automation roots, jobs, troubleshooting. Read before using pointer input or dialogs.
- `references/headless.md`: `run`, `batch`, `serve`, `convert`, `info`, and the optional MCP server.
- `references/skin-retouch.md`: the professional skin-retouch workflow, parameters, false hits.
- `references/feature-swap.md`: opening closed eyes (or swapping a smile or head) from another frame:
  donor, alignment, tone, mask, checks, and the feedback each mistake drew. Script: `feature_swap.py`
  (`donors`, `align`, `mask`, `tone`).
- `references/eyes-teeth.md`: teeth whitening, eye whites, iris, catchlights, red-eye. Script:
  `eyes_teeth.py`.
- `references/color-grade.md`: white balance from neutrals, black and white points, contrast, tested
  looks, matching shots, black & white. Script: `color_check.py` (`measure`, `correct`, `match`,
  `compare`).
- `references/cutout.md`: selection by edge type, edge checks, real shadows, marketplace specs.
  Scripts: `cutout_check.py` (the cut, and `--deliverable`), `product_shot.py`.
- `references/object-removal.md`: dust, wires, people and objects; tool choice, donors, checks.
  Scripts: `plan_spots.py`, `plan_lines.py`.
- `references/straighten.md`: horizons, converging verticals, frontal facades, crops. Script:
  `straighten.py`.
- `references/sky.md`: sky masks, enhance or replace, light and horizon matching, halos. Scripts:
  `sky_mask.py`, `sky_check.py` (`plan`, `enhance`, `check`).
- `references/restore.md`: dust, scratches, tears, fading and dye casts on scans. Scripts:
  `find_defects.py`, `restore_tone.py`.
- Skin-retouch scripts: `plan_heals.py` (healing dabs), `skin_masks.py` (dodge & burn and colour
  masks), `import_masks.py` (builds those layers in the live document).
- Shared scripts (Python 3 standard library only): `import_layers.py` (builds any planner's
  `layers.json`, live or headless, and verifies the render), `grid.py` (coordinate grid for
  `area.json`), `compare.py` (before/after and check view), `imgops.py` and `pngio.py` (the pixel
  maths and PNG I/O the planners share).
