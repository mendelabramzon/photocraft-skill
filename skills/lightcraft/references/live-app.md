# Driving the live LightCraft window

Read this when you work in the desktop app (not headless): reading UI state, showing the user something
in the window, screenshots, pointer input, background tasks.

Commands below use `$LC` and `$LOOK` as SKILL.md sets them:
`${CLAUDE_SKILL_DIR}/scripts/lc.py` and `${CLAUDE_SKILL_DIR}/scripts/look.py`.

Upstream reference: `docs/control-protocol.md` in https://github.com/storytold/lightcraft. It describes
the latest code, which may be ahead of the user's installed version. When the doc and the app disagree,
believe the app (`$LC call engine.commands`, error messages).

## Contents
- How the channel works
- Control methods
- Reading state
- Showing the user: views, panels, before and after, mask overlays
- Pointer and keys
- Background tasks
- The library: lock, problems, saving
- Things that go wrong

## How the channel works

`$LC launch` starts LightCraft with `--control <port>` (7980 unless taken): a JSON-lines server on
127.0.0.1 only. One request per line, one reply per line, in order: `{"id", "ok", "result" | "error"}`.
Requests run on the UI thread between frames, with a 60 s limit. A line that isn't a JSON request gets an
error and the connection is closed (so a web page can't smuggle commands in), and at most 16 connections
are served at once.

There is no token. While the window is open with the channel on, any program on this computer can drive
it, and through it read photos and write exports anywhere the user can. That's why `launch` is only for
live work: when it's done, tell the user, and `$LC quit` unless they want to keep working in it.

`lightcraft-cli run --connect` and `lightcraft-cli mcp --connect` talk to the same port (both default to
127.0.0.1:7980), with the same commands.

## Control methods

Send with `$LC call <method> '<json params>'`; `$LC exec <command> '<params>'` is
`engine.execute`.

| Method | What it does |
|---|---|
| `engine.execute {command, params?}` (alias `ui.menu.invoke`) | Run any command, including UI commands such as `view.detail` |
| `engine.commands` | Every command with `enabled` and `disabled_reason`. Big; filter it with python |
| `ui.inspect` | UI state (a few KB): see below |
| `ui.set {…}` | Change UI state, e.g. `{"view": "detail", "right": "edit"}`; replies with the whole UI state. An unknown value is an error that lists the valid ones |
| `ui.screenshot {path, headless?}` | PNG of the window once pending renders finish (`$LC screenshot out.png` shrinks it to 1600 px) |
| `ui.render {id?, size?, path}` | PNG of one photo with its edits, no UI (`$LC render out.png`) |
| `ui.widgets {filter?}` | On-screen widgets `{id, rect}`; ids like `button:upright-auto`, `slider:effects.clarity` |
| `ui.clickWidget {id, count?, button?}` / `ui.dragWidget` / `ui.hoverWidget` | Real input on a widget by id |
| `ui.pointer {events: [{kind: down|drag|up, x, y}], alt?, shift?, cmd?}` | A gesture in normalized image coordinates (Detail view): brush strokes, gradients, crop handles |
| `ui.move` / `ui.click` / `ui.drag` | Raw pointer input in screen points |
| `ui.key {key, cmd?, shift?, alt?, ctrl?}` / `ui.text {text}` | Keys (in-app shortcuts) and typing. macOS menu accelerators don't go through `ui.key`: run the command instead |
| `ui.dialog.confirm` / `ui.dialog.cancel` | Close the open dialog |
| `ui.menu.list` / `ui.menu.tree` | The menus, with command ids |
| `app.quit` | Quit. Use `$LC quit`, which checks for running exports and imports first |

## Reading state

`ui.inspect` keys worth knowing:
- `active`, `selection`: the active photo id and the selected ids.
- `ui`: the UI state, including `view`, `right` (the open panel), `beforeAfter`, `openSections`.
- `loupe`: what the Detail view shows: `source` (`render`, `cached`, or a lower-quality stand-in),
  `pending`, `failed`.
- `import` (`{done, total, imported, cancelled}` while an import runs), `export` (`{running, last}`),
  `activity` (every long task in flight), `tasks`.
- `notices` (warnings waiting to be shown), `quitPrompt`, `libraryProblem`, `unsaved` (changes the
  library couldn't write to disk yet).

The photo itself: `$LC exec photo.inspect`, `develop.get`, `develop.controls {section?}`,
`library.state` (selection, filter, sort, undo label), `catalog.query`.

## Showing the user: views, panels, before and after, mask overlays

`$LC call ui.set '<json>'` with:
- `view`: `photoGrid`, `squareGrid`, `detail`, `compare`, `survey`, `reference`, `people`.
- `right` (the panel on the right): `none`, `edit`, `crop`, `remove`, `masking`, `redEye`, `versions`,
  `activity`, `keywords`, `info`, `profiles`. `openSections: ["light", "color"]` opens Edit sections.
- `beforeAfter`: `off`, `original`, `sideBySide`, `split`, `topBottom`, `splitTopBottom`. Before is the
  import state unless `beforeAfter.setBefore` says otherwise.

To show what a mask covers: `$LC exec mask.select '{"id": 1}'`, then
`$LC call ui.set '{"right": "masking", "maskOverlay": true, "maskOverlayAll": true}'` and take a
screenshot. The mask shows as a red overlay.

These are the user's preferences and LightCraft remembers them. Put back what you changed for your own
checks (`maskOverlayAll: false`, `beforeAfter: "off"`), and leave the view on the photo you worked on.

## Pointer and keys

Prefer commands to gestures: `mask.add`, `mask.brushStroke`, `crop.set`, `spot.add` are exact and don't
depend on zoom or on which tool is active. Use the pointer when the user wants to watch a tool being used.
`ui.pointer` coordinates are normalized to the image in the Detail view. Mask brushing in the UI goes
through the UI command `tool.brush` (`{}` paints on the current mask, `{"new": true}` makes a brush mask).

## Background tasks

Imports, exports with `"background": true`, preview builds, merges and model downloads run on worker
threads. `$LC exec activity.list` shows them (`{tasks: [{id, kind, label, done, total, …}]}`) and
`activity.cancel '{"id": …}'` stops one at its next photo. `app.export` without `background` runs inside
the request: fine for a few photos, but a big batch can hit the 60 s limit, so batch with
`"background": true` and poll.

`$LC launch photo.jpg` waits for the import of the photos it was given. After `library.import` sent
through the channel, poll `ui.inspect` → `import` until `done == total` before editing.

## The library: lock, problems, saving

- Every change is written to the library's journal before the command replies. There is no "save". If the
  write fails (disk full, drive gone), the command replies `saved in memory but not written to disk: …;
  LightCraft will retry`; the change is applied and retried, but is lost if the app quits first. Tell the
  user.
- A library is open in one program at a time (`catalog.lock`). While the window has it, the CLI's
  `--library` on it fails; drive the window instead.
- If the app can't open its library at launch, the window asks what to do and `ui.inspect` →
  `libraryProblem` says why. Leave that choice to the user.
- `$LC launch --library DIR` opens another library for that session only: LightCraft doesn't remember
  it, and its next normal start opens the user's usual library again.

## Things that go wrong

- **`the app drew no frame for 5 s`.** The window is minimized or on another space, so it isn't drawn and
  requests aren't served. Ask the user to bring it up. `$LC screenshot --headless` draws the UI on the
  CPU and works meanwhile.
- **A command is disabled.** `engine.commands` gives `disabled_reason` ("nothing to redo", no selection).
- **`invalid parameters`.** The error names the expected params or variants. Read it and retry once.
- **Edited the wrong photo.** Check `selection.active` after imports and `library.select`; undo with
  `edit.undo`.
- **Quit is refused.** `$LC quit` refuses while an export or import runs, or when changes aren't on disk
  yet. Wait, or `--force` only when the user said so.
