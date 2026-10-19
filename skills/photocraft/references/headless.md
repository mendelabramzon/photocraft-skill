# Headless editing with photocraft-cli

Read this for file-in, file-out work that doesn't need the window: batch jobs, conversions,
scripted edits, generating images. Everything runs through `pc.py cli …`, which forwards to
the `photocraft-cli` binary (install it with `pc.py install-cli`).

Paths given to the CLI are ordinary paths; there are no automation roots in `run`, `batch`,
`convert` or `info`.

## Contents
- Subcommands
- `run`: one document, many commands
- `batch`: same action list over a folder
- `serve`: a stateful session over JSON lines
- MCP server (optional)

## Subcommands

    pc.py cli convert in.psd out.png [--format ext] [--quality 1-100] [--tiff-layers]
    pc.py cli info file [--compact]           # JSON: size, mode, depth, layer tree
    pc.py cli run (file | --new '<json>') --cmd <id> [--params '<json>'] [--cmd …] [--out file] [--quality N]
    pc.py cli batch --actions actions.json --in dir --out dir [--format ext] [--quality N]
    pc.py cli commands [--json] [--filter text]
    pc.py cli serve [--automation-read-root dir] [--automation-write-root dir]
    pc.py cli mcp   [--bridge 127.0.0.1:PORT --control-token-file FILE] [roots…]

A flag the subcommand doesn't take is an error (exit 2), not silently ignored.

## `run`: one document, many commands

Each `--params` belongs to the `--cmd` before it. One JSON line is printed per command result.
Export format comes from the `--out` extension; a flat format flattens and prints a warning
(`4 layer(s) flattened…`), which is expected. Use `.psd` or `.pcraft` to keep layers.

    pc.py cli run ~/Pictures/beach.jpg \
      --cmd layer.newAdjustmentLayer.curves --params '{"points":[[0,0],[60,45],[190,215],[255,255]]}' \
      --cmd layer.newAdjustmentLayer.vibrance --params '{"vibrance":25}' \
      --out ~/Pictures/beach-graded.jpg --quality 92

Start from nothing with `--new '{"width":1080,"height":1080,"background":"#101820"}'`.

Since each `run` starts fresh from the input file, iterate by changing the command list and
re-running from the original, rather than editing the output again. That keeps the original
untouched and each attempt reproducible. Add `--cmd document.inspect` at the end when you need
layer ids or bounds in the output.

When a later command needs an id that an earlier one returns (e.g. `layer.select` on the layer
that `type.create` made), ids are predictable within one run but not obvious: either do a first
run with `document.inspect` to learn them, or use `serve` below.

## `batch`: same action list over a folder

`actions.json` is a list of steps: `[["<id>", {params}], …]` or `[{"command": id, "params": {}}, …]`.

    [["image.autoTone", {}],
     ["image.imageSize", {"width": 2048, "resample": "bicubic"}],
     ["filter.sharpen.unsharpMask", {"amount": 60, "radius": 1.0}]]

    pc.py cli batch --actions actions.json --in ~/Pictures/raw --out ~/Pictures/web --format jpg --quality 85

`batch` creates `--out` if needed and keeps each file's base name with the new extension
(`Leaf.jpg` → `Leaf.png`). Try the action list on one file with `run` first, look at it, then batch.
For "a little sharpening" on small web images, Unsharp Mask around amount 50, radius 0.5 is a
gentle start; radius 1+ starts to look crunchy at thumbnail size.

`--out` must differ from `--in` unless `--in-place` is passed. Don't pass `--in-place` unless the
user asked for the originals to be replaced.

## `serve`: a stateful session over JSON lines

One process, one session, many requests; use it when later steps depend on earlier results.
File access needs explicit roots. Pipe the requests in:

    printf '%s\n' \
      '{"id":1,"method":"doc.open","params":{"path":"in.jpg"}}' \
      '{"id":2,"method":"batch","params":{"steps":[{"command":"image.adjustments.invert"},{"command":"filter.blur.gaussianBlur","params":{"radius":3}}]}}' \
      '{"id":3,"method":"doc.save","params":{"path":"out.png"}}' |
      pc.py cli serve --automation-read-root "$PWD" --automation-write-root "$PWD"

Methods: `engine.execute {command, params}`, `engine.commands {filter?}`, `doc.open {path}`,
`doc.new {file.new params}`, `doc.save {path?, quality?}`, `doc.inspect`, `doc.render {maxSide?, path?}`
(PNG preview), `doc.select {index}`, `doc.close`, `session.list`, `batch {steps, stopOnError?}`,
`jobs.list`, `jobs.cancel`. The session ends when stdin closes, so put the whole sequence in one pipe.

## MCP server (optional)

`photocraft-cli mcp` exposes the same engine as MCP tools (`command_list`, `command_run`,
`command_batch`, `doc_open`, `doc_save`, `doc_inspect`, `doc_render_preview`, and in bridge mode
`ui_*`). If the user wants PhotoCraft as a permanent MCP server in Claude Code, it can be added with:

    claude mcp add photocraft -- ~/.photocraft-skill/bin/photocraft-cli mcp \
      --automation-read-root <dir> --automation-write-root <dir>

That's a config change to their Claude setup: suggest it, don't do it unasked. This skill's
`pc.py` covers the same ground without it.
