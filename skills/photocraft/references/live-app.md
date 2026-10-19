# Driving the live PhotoCraft window

Read this when you are working in the desktop app (not headless): driving tools with the pointer,
working with dialogs, reading UI state, or anything the user wants to watch happen on screen.

Upstream reference: `docs/control-protocol.md` in https://github.com/storytold/photocraft. It
describes the latest code, which may be ahead of the user's installed version. When the doc and
the app disagree, believe the app (`pc.py exec command.list`, error messages).

## Contents
- Control methods
- Reading state
- Pointer, keys and tools
- Dialogs
- Files and the automation roots
- Long-running jobs
- Things that go wrong

## Control methods

Send any of these with `pc.py call <method> '<json params>'`:

| Method | What it does |
|---|---|
| `engine.execute {command, params, wait?}` | Run an engine command (`pc.py exec` is the shortcut). Never opens a dialog. |
| `engine.commands` | Every command with `enabled`, `disabledReason`, `needsDocument`. Big; filter it with python. |
| `ui.inspect` | Whole UI state. Big (tens of KB); pipe through python and pick keys. |
| `ui.set {tool?, zoom?, fit?, brushSize?, theme?, panels?, selectionMode?, …}` | Change UI state. Unknown fields are an error and nothing changes. |
| `ui.menu.invoke {id, params?}` | Click a menu item. With no params it opens that command's dialog, like a user would. |
| `ui.menu.list` | The menu tree. |
| `ui.dialog.set {dialog, field, value}` / `ui.dialog.confirm {dialog}` / `ui.dialog.cancel {dialog}` | Drive an open dialog; `dialog` is the id from `ui.inspect.dialogs`. |
| `ui.pointer {events, tool?, modifiers?, button?}` | Drive the active tool in **document pixel** coordinates. |
| `ui.click {x, y, button?, count?}` / `ui.move {x, y}` | Synthetic mouse input in **screen points** (not document pixels). |
| `ui.key {key, command?, shift?, alt?, ctrl?}` | Press a key, e.g. `{"key":"Enter"}`, `{"key":"z","command":true}`. |
| `ui.type {text}` | Type text into the focused widget or the type layer being edited. |
| `ui.screenshot` | PNG of the main window (`pc.py screenshot out.png` saves it anywhere). |
| `ui.focus` | Bring the window to the front. |
| `ui.resize {width, height}` | Resize the main window. |
| `app.open {path}` / `app.save {path?}` | File I/O, restricted to the automation roots (see below). |
| `app.quit` | Closes immediately and **discards unsaved work without asking**. Use `pc.py quit`. |

## Reading state

`ui.inspect` keys worth knowing:
- `session.documents[]`: `{index, name, path, dirty, width, height, revision}`, plus `session.active`
  and the toolbox `foreground` / `background` colours (0..1 floats).
- `document`: the active document, same shape as `document.inspect` (layers, history, selection).
- `tool`, `toolOptions`, `brush`: the current tool and its settings.
- `dialogs[]`: open dialogs `{id, kind, title, fields}`. Check this when something seems stuck.
- `status`, `statusError`, `notices`: the status bar text and pop-up notices (errors land here).
- `jobs`: running background jobs.
- `views[]`: zoom, centre, rotation of each document view.

Example, print just the layer stack:

    pc.py exec document.inspect --max-chars 0 | python3 -c "import json,sys; d=json.load(sys.stdin); [print(l['id'], l['kind'], l['name'], 'visible' if l['visible'] else 'hidden') for l in d['layers']]"

## Pointer, keys and tools

- Pick a tool with `ui.set {"tool": "<name>"}` or pass `tool` inside `ui.pointer`. Names are
  case-insensitive (spaces, `-`, `_` ignored): `move`, `rect` (rectangular marquee), `ellipse`
  (elliptical marquee), `lasso`, `polygonLasso`, `magneticLasso`, `magicWand`, `quickSelection`,
  `objectSelection`, `crop`, `eyedropper`, `brush`, `pencil`, `mixerBrush`, `eraser`, `gradient`,
  `paintBucket`, `type`, `verticalType`, `hand`, `zoom`, `spotHealing`, `healing`, `patch`,
  `cloneStamp`, `blur`, `sharpen`, `smudge`, `dodge`, `burn`, `sponge`, `pen`, `pathSelection`,
  `directSelection`, `rectangle`, `ellipseShape`, `triangle`, `polygon`, `line`, `customShape`.
  An unknown name is the error ``unknown tool `x` ``.
- `ui.pointer` events: `{"kind":"down"|"move"|"up", "x", "y", "pressure"?: 0..1}`. A stroke is one
  `down`, several `move`s, one `up`, all in one call. Coordinates are document pixels.
- Brush colour is the toolbox foreground: set it first with
  `pc.py exec tools.setColors '{"foreground":"#ff0000"}'`.
- Brush size: `ui.set {"brushSize": 24}`; other brush settings: `tools.setBrush`.
- Prefer engine commands over pointer gestures whenever one exists (`paint.stroke`,
  `select.rect`, `shape.create`, `type.create`, `edit.transform`). They are exact and don't depend
  on zoom or on which tool happens to be active. Use the pointer when the user wants to see the
  tool being used, or for tools with no command equivalent.
- A pixel tool used on a type, shape or smart object layer opens a "Rasterize?" dialog instead of
  painting. Add a new pixel layer (`layer.new.layer`) for painting instead of rasterizing their work.

## Dialogs

`pc.py menu <id>` with no params opens the dialog the user would see. Then:

    pc.py call ui.inspect --max-chars 0 | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['dialogs'], indent=1))"
    pc.py call ui.dialog.set '{"dialog": 3, "field": "gamma", "value": 1.4}'
    pc.py call ui.dialog.confirm '{"dialog": 3}'      # or ui.dialog.cancel

Opening a dialog is good when the user wants to watch or fine-tune it themselves; leave it open and
tell them. If you only need the result, run the engine command with params instead: one step, no UI.

## Files and the automation roots

The app was launched with `--automation-read-root` and `--automation-write-root` (default: the
user's home folder; see `pc.py status`). `app.open` and `app.save` refuse paths outside them, and
`file.open` / `file.save` / `file.saveAs` and other commands that take a file path are refused over
the control channel altogether. So:

- Open: `pc.py call app.open '{"path":"/Users/me/Pictures/photo.jpg"}'`, or pass files to
  `pc.py launch photo.jpg`.
- Save layered work: `app.save {"path": ".../name.psd"}` (or `.pcraft`). `app.save {}` with no path
  writes back only to a PSD/PSB/.pcraft the document came from; for a JPEG/PNG it errors.
- Export a flat copy: `pc.py export out.png`. It's a copy: the document keeps its own name and
  file, and stays marked unsaved.
- A file outside the roots (e.g. `/Volumes/...`): quit the controlled instance and relaunch with
  `--read-root` / `--write-root` pointing there.

## Long-running jobs

Filters, content-aware fill and similar run as background jobs. `engine.execute` waits for them
(up to 60 s). For something slower, use `pc.py exec <id> '<params>' --no-wait`, then poll
`pc.py call jobs.list` and cancel with `pc.py call jobs.cancel '{"job": N}'`.

A reply `timeout: not run` means it never started (safe to re-send). `timeout: no reply in 60s`
means it may still be running and may still apply: inspect the document before re-sending.
macOS stops rendering a fully hidden window, and the control channel is drained once per frame, so
if every request times out, `pc.py call ui.focus` (or ask the user to un-minimize the window).

## Things that go wrong

- **Edit landed on the wrong layer.** New layers, adjustment layers and type become the active
  layer; an adjustment layer also targets its mask. A filter or fill right after that hits the
  mask, not the photo. Always `layer.select {"layer": <pixel layer id>}` before pixel operations.
- **`invalid parameters … missing X`.** The installed version's params differ from what you assumed.
  Read that command's params doc from `command.list` and retry.
- **Command disabled.** `command.list` shows `disabledReason` (e.g. "no selection",
  "no document open").
- **Dialog left open blocks things.** Check `ui.inspect.dialogs` and cancel stray ones.
- **Undo.** `pc.py exec edit.undo` once per history entry; check `document.history` to see what's there.
