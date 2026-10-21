---
name: lightcraft
description: "Operate LightCraft, the open-source Lightroom-style photo library and raw developer (storytold/lightcraft): the live app on the user's Mac, or headless on Linux and in Claude's sandbox (Claude app chats, Managed Agents). Develops raw and JPEG photos without touching the originals (white balance, tone, colour, sky and subject masks, crop and Upright, lens corrections, dust removal, presets), culls shoots (sharpness scoring, ratings, flags), organizes libraries, merges HDR and panoramas, and exports JPEG, TIFF, PSD, WebP and DNG with lightcraft-cli, one photo or hundreds. Use this whenever the user mentions LightCraft, or asks to develop raw photos, cull or rate a shoot, put one look on many photos, or export photos for web, print or social media and LightCraft is their photo app, including photos attached to a chat, even if they just say 'my raws', 'the shoot' or 'my library'. Layer work (skin retouching, removing objects, compositing, text) is PhotoCraft's: the photocraft skill."
license: Apache-2.0
compatibility: Live app - macOS with the LightCraft desktop app and Claude Code on that Mac (driven over 127.0.0.1). Headless - also Linux, including Claude's cloud sandbox in the Claude apps and in Managed Agents. Headless work needs lightcraft-cli - installed by the user on a Mac, by scripts/install_cli.py on Linux (x86_64 or aarch64, glibc 2.35 or newer).
---

# LightCraft

LightCraft is a native Rust reimplementation of Lightroom: a photo library plus a raw developer.
Photos are imported into a library, and an edit is a set of **develop settings** (sliders, curves,
masks, crop) kept in the library and rendered on the fly. Originals are never written: LightCraft
refuses to export over one. Everything is a **command** with an id (`develop.set`) and JSON params,
from one registry of ~370, and every slider is a **control** with an id (`light.highlights`) and a
range, 122 in all. The window, the CLI and the control channel all run the same commands.

All access goes through `scripts/lc.py` in this skill's directory (Python 3, standard library only).
Set variables for it and its companion in your shell commands,
`LC=${CLAUDE_SKILL_DIR}/scripts/lc.py` and `LOOK=${CLAUDE_SKILL_DIR}/scripts/look.py`, and run
`$LC -h` or `$LC <subcommand> -h` for usage.

## Two ways to operate it

| | Live app (control channel) | Headless (`lightcraft-cli`) |
|---|---|---|
| Use when | The user wants it *in LightCraft*: in their library, in the window, to keep working on | File in, file out: "develop these raws to JPEG", batch exports, one look across a folder |
| State | The user's library; every edit is saved as it's made | Nothing kept, unless you open a library with `--library` |
| Speed | One round trip per request | About half a second to import, edit and export a photo |
| Start | `$LC launch [photos…]` | installed once (`$LC cli-info` says how), then `$LC cli …` |
| Details | `references/live-app.md` | `references/headless.md` |

If unclear, ask yourself whether the user expects to find the photo in their LightCraft library
afterwards. If yes, live; otherwise headless is faster and leaves their library alone.

**No desktop app** (a Linux server, a chat in the Claude apps, a Managed Agents session, or a Mac with
only the CLI): everything is headless, and `$LC launch`, `$LC screenshot` and `$LC render` don't work
(`$LC cli render` does). On Linux and in a Claude sandbox, read `references/no-app.md` first: it covers
installing the CLI, where the user's photos are and where results go, and how to look at your work. On
a Mac with only the CLI, `references/headless.md` covers how to run everything; the recipes and their
guides apply as they are.

## Step 1: check what's there

    $LC status

This reports the app path and version, whether `lightcraft-cli` is installed, every running LightCraft
process (and whether it has the control channel), whether the channel answers, and the library it has open.

- **CLI missing and you need headless:** `$LC cli-info` names the `lightcraft-cli` zip from the same
  release as the installed app and where the binary goes. Ask the user to install it: download that zip
  from the release page, check its SHA-256 against the release's `SHA256SUMS.txt`, unzip it, and put
  `lightcraft-cli` in `~/.lightcraft-skill/bin/` or on their PATH. The skill never downloads binaries on
  its own on a Mac; if the user asks you to do those steps for them, go ahead.
- **App not found:** headless work needs only the CLI, so carry on headless unless the user wants the
  window. The app is at https://github.com/storytold/lightcraft/releases (macOS `.dmg`), and the ArtCraft
  Launcher installs it too.
- **Linux** (`platform` is `linux`): there is no app to find. If `cli` is null, run
  `python3 ${CLAUDE_SKILL_DIR}/scripts/install_cli.py`, which downloads LightCraft's own Linux release and
  checks its SHA-256. In a Claude sandbox, `sandbox` names the uploads and outputs folders. Then follow
  `references/no-app.md`.

## Step 2 (live): get a controllable window

A LightCraft started normally (Dock, Finder) has no control channel and cannot be driven. `$LC launch`
starts it with `--control` on 127.0.0.1 (port 7980), with the library LightCraft would open anyway, the
user's own. Photos given to it are imported **in place** (the files stay where they are; the library
points to them) and a single photo opens in the Detail view.

- If `status` shows `controlReachable: true`, reuse it. `$LC launch photo.jpg` imports into that one.
- **A LightCraft opened normally holds the library**, and `launch` refuses while it runs. Ask the user to
  quit it (LightCraft saves edits as they're made, so nothing is lost), then launch. Never quit or kill
  it yourself.
- `--memory` starts a throwaway session that saves nothing (demo photos, unless photos are given);
  `--library DIR` opens another library.
- **The channel has no token.** While this window is open, any program on this computer can drive it.
  When you finish, say so: leave it open if the user wants to keep working in it, otherwise `$LC quit`.
- `status` shows `libraryProblem` when the library couldn't be opened (another program has it, such as a
  LightCraft MCP server started with `--library`); the window asks what to do. Tell the user rather than
  clicking through it.

## Step 3: work in a loop: look, act, check

Live, commands go through `$LC exec`, `$LC call` and `$LC script`, as below. Headless, the same commands
go into a `$LC cli run` chain (`$LC cli run --library DIR photo.inspect catalog.query`, or `--import
photo.jpg` instead of `--library`), `$LC script steps.json --import photo.jpg`, or a settings file for
`$LC cli render`; `exec` and `call` need the window.

1. **Look.** `$LC exec photo.inspect --max-chars 0` gives the active photo: `id`, file, `width` and
   `height` (know the pixel size before you choose render and export sizes), camera data, `develop`
   settings, rating, flag, `history`. `$LC exec catalog.query` maps ids to file names (ids follow no
   order you can assume). `$LC exec develop.controls '{"section": "light"}'` gives current slider values.
2. **Find the command.** Start with `references/commands.md` (exact params by task). For anything else,
   `$LC cli commands | grep -i <word>` or, live, `$LC call engine.commands` (with `enabled` and
   `disabled_reason`). When a call fails with `invalid parameters`, the error names what it expects.
3. **Act.** `$LC exec develop.set '{"values": {"light.exposure": 0.3, "light.highlights": -40}}'`. For
   several steps, write them to a file and `$LC script steps.json` (one line of output per step, stops at
   the first error). Results longer than `--max-chars` (2000 for `script`) are cut to a string: pass
   `--max-chars 0` when you parse them.
4. **Check visually.** Don't report success from `ok` alone; look at the pixels. Live: `$LC render
   look.png` (the photo with its edits, 1600 px) or `$LC screenshot shot.png` (the window, with the
   sliders). Headless: render the file (below). Read the PNG with the Read tool. For numbers,
   `$LOOK measure look.png` gives clipping, tone percentiles, a cast estimate and the colour at points.

Headless, the edit is a settings JSON: render it, look, change the file, render again. Each render starts
from the original, so every attempt is reproducible:

    $LC cli render photo.dng -o ~/work/look.png --size 1200 --settings look.json --set light.exposure=0.4

A settings JSON is the develop JSON (`develop.get`), partial: nested, with its own snake_case keys
(`{"light": {"highlights": -40}, "optics": {"lens_profile": true}}`), not control ids. Chains of commands
run with `$LC cli run --import photo.dng develop.set 'values={"light.exposure":0.3}' app.export
path=out.jpg longEdge=0`, or a steps file with `$LC script steps.json --import photo.dng`.

### The mistakes to avoid

- **Positions are 0..1 in the whole upright photo, before any crop or straightening.** Mask centres and
  gradients, `develop.wbPick`, spots and red eye all use that frame: a radial mask at `[0.75, 0.25]` on a
  photo cropped to its right half sits at the middle of the crop, and masks turn with the photo when it
  is straightened. Read positions off `$LOOK grid` drawn on a render with no crop (render the original
  file). Crop rects (`crop.set`, `crop.drag`) are the exception: they are in the straightened frame,
  which is the same frame while the angle is 0.
- **Know which photos a command changes.** `develop.set` changes the active photo; `preset.apply`,
  ratings, flags, labels, `develop.sync` / `paste` and exports to a `dir` act on the whole selection; all
  of these take `ids` instead. `develop.auto`, `develop.wb`, `develop.wbPick`, masks and crop act on the
  active photo only and quietly ignore an `ids` they don't take: `library.select '{"ids": [id]}'` first.
  After an import every imported photo is selected and the first is active. With Auto Sync on, develop
  commands also change the other selected photos.
- **`app.export` without a size writes 3000 px** on the long edge. Full size is `longEdge: 0`.
  `dontEnlarge` is on by default. `render` without `--size` is full size. `path` names the file for
  **one** photo; for several, give `dir` and a `naming` template (with several `ids`, `path` is ignored
  and the files land in the current folder).
- **White balance has two scales.** On raws with colour matrices `wb.temp` is Kelvin (5500 ≈ daylight);
  on JPEG, TIFF and other raws it is relative, and 6500 / 0 means "as shot". Use `develop.wbPick`
  on a neutral, or `develop.wb '{"mode": "daylight"}'`, rather than typing Kelvin into a JPEG.
- **Sky, Subject and Background masks are heuristics** (no model): `subject` caught an eagle's head but
  not its shoulders. Check what a mask covers before trusting it (`references/develop.md`, Step 5).
- **AI features need models with licence terms**: Object and Describe masks (SAM 3), Find Blemishes and
  faces, AI Denoise. Ask the user before any model download; those commands need
  `"acknowledged": true`, which means the user accepted the terms.
- **A library is open in one program at a time.** `lightcraft-cli --library` fails with "already open in
  LightCraft" while the app has it; work through the live channel instead.
- **`run` arguments:** a word without `=` starts the next command. Quote values with brackets, braces or
  spaces: `'values={"light.exposure":0.5}'`, `'ids=[3,4]'` (zsh treats `[…]` as a glob). Give paths
  there in full (`path="$HOME/out.jpg"`): zsh leaves `~` after `=` alone, and the CLI then makes a
  folder named `~`. The CLI prints one JSON line per command (imports print none) and a plain-text
  summary on stderr when one failed.
- **Many commands return `null`.** That means success with no data, not failure.
- **Some commands write beside the originals:** `merge hdr` writes `<first>-HDR.dng` in the photos'
  folder, `photo.editExternal` writes `<name>-Edit.psd` there, and `photo.saveMetadataToFile` writes
  XMP sidecars. Copy brackets to a work folder first, and write sidecars only when the user asks.

## Recipes

### Develop one photo (read `references/develop.md` first)

Work the way a careful Lightroom user does: correct, then shape, then style, checking each stage on a
render. The order matters: the crop changes what the eye and the post-crop vignette see, and the white
balance changes every colour decision after it.

1. **Look first.** Render the original, `$LOOK measure` it, and decide what the photo needs and what to
   keep (golden-hour warmth, a low-key mood, deliberate blown windows).
2. **Lens and geometry.** `develop.merge '{"settings": {"optics": {"lens_profile": true, "remove_ca":
   true}}}'` for photos with lens data; `crop.autoStraighten` for a tilted horizon, `geometry.upright
   '{"mode": "auto"}'` for leaning buildings; `crop.aspect` / `crop.set` for the frame.
3. **White balance** from something neutral in the main light: `develop.wbPick '{"x": …, "y": …}'`, then
   `$LOOK measure --point` the same spot: |a*| and |b*| ≤ 2, unless warmth is the point.
4. **Tone.** `develop.auto` measures only Exposure; the rest of what it sets is the same on every photo
   (Contrast +68, Highlights −66, Shadows +52, Vibrance +30 in 0.9.1), a strong generic look. Take its
   Exposure as a hint, then set Highlights / Shadows and Whites / Blacks to the end points yourself.
5. **Presence and colour.** Texture, Clarity and Dehaze in small amounts; Vibrance before Saturation;
   the Color Mixer for one colour at a time; grading or a preset for the look.
6. **Local.** Masks for what the global sliders can't do: a darker sky, a brighter face, light where the
   eye should go. Check each one's coverage.
7. **Detail and output.** Sharpening and noise reduction for the output size, then export, and look at
   the export, not only the preview: `$LOOK measure` reads the exported JPEG or TIFF directly.

### A shoot: cull, match, sync, export (read `references/shoot.md` first)

1. Import into a library: the user's (live) or a work library
   (`--library ~/.lightcraft-skill/work/<shoot>/library`, headless).
2. `photo.analyze` scores focus and clipping and groups bursts; look at numbered contact sheets
   (`$LOOK sheet`, `--mark` frames the picks), then rate and flag. Never delete or reject unless asked.
3. Develop one photo per lighting situation, then copy its settings to the rest (`develop.copy` +
   `develop.paste`, or `develop.sync` with the photos selected) without crop, masks or spots.
   `develop.matchExposure` evens out exposure differences.
4. Look at every photo on sheets again, then export with a naming template. Ratings and flags live in
   the library: headless, tell the user which photos you picked, and write XMP sidecars only if they ask.

### Quick looks: presets and profiles

`$LC exec presets.list` lists 41 built-in looks (`lc.teal-orange`, `lc.bw-selenium`, `lc.moody`…);
`preset.apply '{"id": "lc.golden-hour", "amount": 60}'` applies one at 60 % (0–200; 40–70 usually looks
the most natural); like other selection-wide commands it styles every selected photo, or `ids`.
Profiles (`profiles.list`, `develop.profile '{"id": "lc.vivid", "amount": 80}'`) set the base rendering
of the active photo; sync them to others with `develop.sync '{"groups": ["profile"]}'`.

### Straighten, Upright and crops for social media

`crop.autoStraighten` levels the horizon (it found −3.0° on a 3° test tilt);
`geometry.upright '{"mode": "auto"}'` (or `level`, `vertical`, `full`) fixes converging verticals.
Formats: `crop.aspect '{"aspect": "4x5"}'` then export `width=1080 height=1350` (Instagram portrait),
`"1x1"` at 1080, `[9,16]` at 1080 × 1920 (stories). The ratio follows the photo's orientation, and a
square photo counts as landscape: on both, `4x5` gives a 5:4 crop, so add `crop.rotateAspect` for a
portrait one. `width` + `height` fit either orientation, so a missed rotate still returns `ok` with a
landscape file: check the size in the export's result. The crop is centred; move it with
`crop.set '{"rect": [x0, y0, x1, y1]}'`. An export never comes out larger than the crop's own pixels
(`dontEnlarge`): for an exact size from a smaller photo, pass `dontEnlarge: false` and tell the user it's
upscaled. A crop that isn't exactly 4:5 in whole pixels lands one pixel short (1080 × 1349); when the
exact size matters, `crop.set` one that is (`references/shoot.md`, Export recipes). In `develop.get` the
crop's `aspect` reads the other way round: check the `rect`, or the export's size.

### Dust, red eye and small distractions

`spot.findDust '{"sensitivity": 50}'` puts a heal spot on each sensor-dust speck in smooth areas (6 of 6
found on a test sky, plus one false hit at the horizon); look at the spots it lists at 100 % and delete
false ones (`spot.delete`). `spot.add '{"mode": "heal", "points": [[x, y]], "size": 0.01}'` removes one
by hand; `redeye.add '{"center": [x, y], "rx": 0.01, "ry": 0.01}'` fixes a pupil. Larger removals,
people and skin work belong in PhotoCraft (below).

### HDR and panoramas

`$LC cli merge hdr a.dng b.dng c.dng` writes `a-HDR.dng` next to the first file and prints the alignment
and EV of each frame; `merge panorama` (`--projection`, `--auto-crop`) works the same way. Live:
`merge.hdr` / `merge.panorama` with `ids`. The result is a raw DNG: develop it like any photo.

### Edit in PhotoCraft: the retouching round trip

LightCraft's own "Edit in" path, like Lightroom's "Edit in Photoshop":

1. `photo.editExternal '{"format": "psd"}'` renders the active photo (or `ids`) with its edits as
   `<name>-Edit.psd` next to the original (16-bit, Adobe RGB) and adds it to the library, stacked on
   the original; the result gives the copy's `id`.
2. Retouch that PSD with the photocraft skill (skin, objects, composites, text) and save it in place:
   PhotoCraft keeps its layers in it.
3. `photo.reload '{"ids": [<copy id>]}'`: LightCraft shows the retouched picture, ready to develop further
   or export.

Use `psd`, not the default `tiff`: PhotoCraft saves back in place only to PSD. For a one-off file
instead, export a 16-bit TIFF (`app.export '{"path": "…", "format": "tiff", "bitDepth": 16, "longEdge":
0}'`); PhotoCraft opens it as a 16-bit document.

## Saving and the user's files

- **Live:** edits are saved in the library as they're made; there is nothing to save. When the user
  wants a file, export it.
- **Headless:** nothing persists. The export is the result; keep the settings JSON so a later change
  starts from the same edit.
- **Never overwrite originals** (LightCraft refuses anyway). Export next to the original with a suffix
  (`photo-edited.jpg`) or into a folder the user names, and say where it went.
- **Formats:** JPEG at quality 90–95 for delivery; 16-bit TIFF or PSD for further editing; `format: "dng"`
  writes a raw as DNG with the edits embedded; `format: "original"` copies the file plus an XMP sidecar.
  LightCraft reads its edits back from that sidecar; other apps read the rating, keywords and captions but
  not the edits.

## Undo and recovery

`edit.undo` / `edit.redo` step through the history (`history.list`, `history.restore`). Before an
experiment, `version.create '{"name": "before grade"}'` keeps a snapshot, and `photo.virtualCopy` makes a
second set of settings for the same file. `develop.reset` clears a photo's edits;
`develop.resetSection '{"section": "grading"}'` one section.

## When things don't respond

- `cannot reach the LightCraft control channel`: no controlled instance is running. `$LC launch` when the
  user wants the window; for headless work, run the command through `$LC cli run` instead of `exec`.
- `the app drew no frame for 5 s`: the window is minimized or on a hidden space. Ask the user to bring it
  up; `$LC screenshot --headless` still works.
- Requests wait while a long command runs in the app; a big `app.export` blocks up to 60 s. For a batch,
  pass `"background": true` and poll `$LC exec activity.list` (`activity.cancel` stops it).
- Notices or a dialog in the way: `$LC call ui.inspect` → `notices`, `quitPrompt`, `libraryProblem`.

## Reference files

- `references/commands.md`: the commands by task with exact params, and every develop control with its
  range.
- `references/live-app.md`: control-channel methods, UI state, screenshots, widgets and pointer input,
  background tasks, troubleshooting.
- `references/headless.md`: `run`, `render`, settings files, work libraries, `merge`, `snapshot`, and the
  optional MCP server.
- `references/no-app.md`: working without the desktop app (Linux servers, Claude app chats, Managed
  Agents): `install_cli.py`, where files come from and go, looking at your work, delivering.
- `references/develop.md`: developing a photo the way professionals do: order, numbers to aim for,
  masks and how to check them, and the looks and mistakes clients notice.
- `references/shoot.md`: a whole shoot: assisted culling, contact sheets, matching and syncing settings,
  export recipes for web, social, print and clients.
- Scripts (Python 3 standard library only): `lc.py` (control channel and CLI helper), `look.py`
  (`measure`, `grid`, `diff`, `sheet`), `install_cli.py` (Linux), `pngio.py` (PNG I/O).
