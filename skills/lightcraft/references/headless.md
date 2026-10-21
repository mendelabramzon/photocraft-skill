# Headless work with lightcraft-cli

Read this for file-in, file-out work that doesn't need the window: developing and exporting photos,
batches, one look across a folder, contact sheets, merges. Everything runs through `$LC cli …`, which
forwards to the `lightcraft-cli` binary (the user installs it once; `$LC cli-info` says which file and
where; on Linux, `install_cli.py` installs it, see `no-app.md`).

Commands below use `$LC` and `$LOOK` as SKILL.md sets them:
`${CLAUDE_SKILL_DIR}/scripts/lc.py` and `${CLAUDE_SKILL_DIR}/scripts/look.py`.

A headless session is its own library, in memory unless you give it one with `--library`: it never sees
the desktop app's library, and nothing it does reaches it. It reads photos anywhere and writes exports
anywhere, but never over an original.

## Contents
- `render`: one photo, one file
- The settings-file loop
- `run`: chains of commands
- Step files: `$LC script --import`
- Work libraries
- `merge`, `snapshot`, `commands`, `controls`
- MCP server (optional)

## `render`: one photo, one file

    $LC cli render in.dng -o out.jpg [--set CONTROL=VALUE]… [--settings FILE] [--preset ID] \
        [--size N] [--quality Q] [--opt KEY=VALUE]…

- The format comes from the extension: `.jpg .png .tif .webp .avif .jxl .psd .dng`.
- `--size N` is the long edge; without it the render is full size (cropped). `--quality` 1..100 (92).
  Output is sRGB unless `--opt colorSpace=…` says otherwise.
- `--set light.exposure=0.5` sets a control (repeatable); `--settings look.json` merges a partial develop
  JSON or applies a `.lcpreset`; `--preset lc.moody` applies a built-in or user preset.
- `--opt` takes any `app.export` option: `--opt colorSpace=displayP3 --opt bitDepth=16`,
  `--opt shortEdge=1080`, `--opt metadata=copyright --opt removeLocation=true`.
- It prints `lightcraft-cli: wrote <path> (W×H)` on stderr.

## The settings-file loop

For one photo, keep the edit in a JSON file and render it after each change. Every render starts from
the original, so attempts are reproducible and nothing accumulates by accident:

    $LC cli render photo.dng -o ~/work/photo/look.png --size 1200 --settings ~/work/photo/look.json
    $LOOK measure ~/work/photo/look.png --point 0.42,0.61,greycard

The file is a partial develop JSON with its own nested keys (see `commands.md`, "Settings JSON"). Start
it from what you know works: run the commands once with `run` and read `develop.get` back, then edit the
numbers:

    $LC cli run --import photo.dng develop.auto mask.add kind=sky mask.adjust 'values={"exposure":-0.5}' develop.get

Masks belong in the file too (`"masks": [...]`, copied from `develop.get`). When it's right, export at
full size with the same file: `--settings look.json --opt longEdge=0` (or no `--size`).

## `run`: chains of commands

    $LC cli run [--import PATH]… [--library DIR | --demo] [--connect [ADDR]] [--script FILE|-] [--keep-going] \
        COMMAND [key=value | '{json}']… [COMMAND …]…

- A word without `=` starts the next command. `key=value` values are JSON when they parse (`1`, `true`,
  `[1,2]`, `{…}`), else strings. A `'{…}'` argument merges a JSON object into the params.
- Quote anything with brackets, braces or spaces: `'ids=[3,4]'`, `'values={"light.exposure":0.4}'`.
- Give paths in `key=value` in full: zsh doesn't expand `~` after `=`, and `dir=~/out` makes a folder
  named `~` in the current directory. Write `dir="$HOME/out"`.
- `--import` (repeatable) imports files or folders (folders recursively) before the commands; the first
  new photo becomes active. Imports print nothing.
- Output: one JSON line per command, `{"command", "ok", "result" | "error", "ms"}`. It stops at the first
  failure (exit status 1, and `lightcraft-cli: 1 command(s) failed` on stderr) unless `--keep-going`.
- `--connect` runs the same commands in the running app instead (default 127.0.0.1:7980).

Examples:

    # one photo: develop and export a web JPEG
    $LC cli run --import a.dng develop.auto develop.set 'values={"light.highlights":-30}' \
        app.export path=a-web.jpg longEdge=2048 quality=85 sharpen=screen metadata=copyright

    # a folder: one preset on every photo, exported with names kept
    $LC cli run --import ~/Pictures/shoot preset.apply id=lc.golden-hour amount=60 \
        app.export dir="$HOME/Pictures/shoot-web" 'naming={name}-web' longEdge=2048

After `--import`, every imported photo is selected and the first is active. `develop.set` changes the
**active** photo; `preset.apply`, `photo.rate` / `flag` / `label`, `develop.sync` / `paste` and
`app.export` with `dir` act on the whole **selection**; all of these take `ids` (from `catalog.query`)
instead. `develop.auto`, `develop.wb`, `develop.wbPick`, masks and crop act on the active photo only and
quietly ignore an `ids` they don't take: `library.select 'ids=[4]'` first, in the same `run`. To put the
same slider values on many photos, `develop.set` with `ids`, or `develop.quickAdjust` for relative
changes.

## Step files: `$LC script --import`

The step files that drive the live app run headless too, in one `lightcraft-cli run`:

    $LC script steps.json --import photo.dng [--import more.dng] [--library DIR] [--keep-going]

Steps are a JSON array or JSON lines: `{"command": id, "params": {…}}` for commands,
`{"method": "ui.inspect"}` or `["method", {…}]` for control methods. Output is one line per step, as live; results longer than `--max-chars` (2000) are cut to a string, and
`--max-chars 0` keeps them JSON.
Put `app.export` at the end; a headless session keeps nothing after it ends.

## Work libraries

`--library DIR` opens (or creates) a persistent library: imports, edits, ratings and albums survive
between invocations, and ids stay the same. Use one for a shoot you'll work on in several steps:

    W=~/.lightcraft-skill/work/<shoot>
    $LC cli run --library $W/library --import ~/Pictures/shoot library.info
    $LC cli run --library $W/library photo.analyze
    $LC cli run --library $W/library library.select 'ids=[4]' develop.get

- Imports add the photos in place (the files stay where they are); the library holds thumbnails and the
  catalog, not copies.
- It writes no XMP sidecars next to the photos unless you ask (`photo.saveMetadataToFile`).
- A library is open in one program at a time: `--library` on the folder the desktop app has open fails
  with "already open in LightCraft". Never point it at the user's own library while their app might
  open it; if they want the work in their library, do it live.
- Ratings, flags and edits live in the work library. Before deleting it, give the user what they need:
  the picks by id and file name and, if they want them on the files, XMP sidecars next to the originals
  (`photo.saveMetadataToFile`: rating and colour label as standard XMP that other apps read, the pick
  flag as LightCraft's own). Keep the library until the user is done with the job, tell them where it
  is, and delete it when they say so.

## `merge`, `snapshot`, `commands`, `controls`

    $LC cli merge hdr a.dng b.dng c.dng [--deghost none|low|medium|high] [--no-align] [--preview p.png]
    $LC cli merge panorama *.dng [--projection auto|spherical|cylindrical|perspective] [--auto-crop] [--fill-edges]
    $LC cli merge hdr-batch ~/Pictures/brackets/*.dng       # every bracket set among the files

Merges write `<first>-HDR.dng` / `-Pano.dng` next to the first file and print JSON: each frame's
alignment, the EV spread and the result's path. `--preview p.png` writes only a small preview and nothing
next to the files. Work on copies in a work folder unless the user wants the DNG beside their photos.

    $LC cli snapshot --library DIR --script tour.jsonl -o shot.png [--size 1600x1000]

`snapshot` runs the whole app UI with no window (CPU-drawn) and writes screenshots: a way to show the
Edit panel or the grid without a desktop. `tour.jsonl` holds control requests, one per line
(`{"method": "ui.set", "params": {"view": "detail", "right": "edit"}}`, then `{"method": "ui.screenshot"}`);
`ui.settle {}` waits for renders.

    $LC cli commands [--json]      # the command registry with params docs
    $LC cli controls [--json]      # every develop control with range and default

## MCP server (optional)

`lightcraft-cli mcp` exposes the same engine as MCP tools (`set_develop`, `render_photo` returning the
image, `export`, `query_photos`, `run_command`, and in `--connect` mode the window's screenshot, clicks
and keys). If the user wants LightCraft as a permanent MCP server in Claude Code:

    claude mcp add lightcraft -- ~/.lightcraft-skill/bin/lightcraft-cli mcp --library <dir>
    claude mcp add lightcraft-app -- ~/.lightcraft-skill/bin/lightcraft-cli mcp --connect 127.0.0.1:7980

That's a config change to their Claude setup: suggest it, don't do it unasked. A server started with
`--library` holds that library's lock while it runs. This skill's `lc.py` covers the same ground without it.
