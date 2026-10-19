---
name: photocraft
description: Operate PhotoCraft, the open-source Photoshop-style image editor (storytold/photocraft), on the user's Mac. Drives the live desktop app (open files, add layers, adjustment layers, filters, type, shapes, selections, masks, layer styles, brush strokes, dialogs, screenshots) through its JSON control channel, and does headless file-in/file-out editing, batch processing and format conversion (PSD, PNG, JPEG, TIFF, WebP…) with photocraft-cli. Use this whenever the user mentions PhotoCraft, or asks to edit, retouch, color-grade, resize, crop, caption, composite, batch-process or convert images and PhotoCraft is how they edit images — even if they just say "the app", "my photo editor", or "do it in Photoshop-like steps".
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
| Start | `$PC launch [files…]` | `$PC install-cli` once, then `$PC cli …` |
| Details | `references/live-app.md` | `references/headless.md` |

If unclear, ask yourself whether the user expects to see the result open in the app afterwards.
If yes, live; otherwise headless is faster and can't disturb their open work.

## Step 1: check what's there

    $PC status

This reports the app path and version, whether `photocraft-cli` is installed, every running
PhotoCraft process (and whether it has the control channel), and whether the channel answers.

- **CLI missing and you need headless:** `$PC install-cli` downloads the `photocraft-cli` release
  that matches the installed app's version from GitHub, verifies its SHA-256 against the release's
  `SHA256SUMS.txt`, and puts it in `~/.photocraft-skill/bin/`. Tell the user you're doing it.
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
  file, then `layer.copyToDocument {"document": <target>, "source": <it>, "layers": [id], "at": [cx, cy]}`
  and `file.close` it. A grayscale image becomes a soft selection with
  `select.loadSelection {"channel": "red", "layer": id}`, and the next adjustment layer takes it as its mask.
- **Copying between documents converts colours** when their profiles differ. An untagged PNG opens as
  sRGB, so copied into a Display P3 phone photo, skin comes out less red and bluer. When pixel values
  must arrive unchanged, `edit.assignProfile` the source to the target's profile first
  (`edit.profileInfo {"profile": "document"}` names it). Grey masks are unaffected.

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
- Skin-retouch scripts (stdlib only, + `scripts/pngio.py`): `grid.py` (coordinate grid for
  `area.json`), `plan_heals.py` (healing dabs), `skin_masks.py` (dodge & burn and colour masks),
  `import_masks.py` (builds those layers in the live document), `compare.py` (before/after and
  check view).
