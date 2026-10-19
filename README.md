# PhotoCraft for Claude Code (unofficial)

A Claude Code plugin that lets Claude operate [PhotoCraft](https://github.com/storytold/photocraft),
the open-source, Photoshop-style photo editor, on your Mac. Ask for an edit in plain words; Claude runs
PhotoCraft's own commands (the same ones its menus and tools use), looks at the result, and keeps your
originals untouched.

> Community project, not affiliated with or endorsed by the PhotoCraft authors.

## What it can do

- **Drive the live app.** Open files, add layers and adjustment layers, masks, selections, filters,
  type, shapes, layer styles, brush strokes and dialogs, in a PhotoCraft window you can watch and
  keep working in. Saves layered PSDs.
- **Edit headless.** File-in, file-out with `photocraft-cli`: batch resize, sharpen, convert
  (PSD, PNG, JPEG, TIFF, WebP), scripted edit chains, in about 0.2 s per edit chain.
- **Retouch skin like a professional, and keep it natural.** Removes temporary blemishes (acne,
  whiteheads, scabs) with hundreds of tiny healing dabs sourced from clean skin nearby, then evens
  post-acne marks with micro dodge & burn and a colour layer that fade tone and colour together.
  Pores, stubble, light and the person's features stay. Everything lands on named, editable layers.

Example requests:

- "Open ~/Pictures/beach.jpg in PhotoCraft, make it warmer and punchier, keep it editable."
- "Retouch his skin: clean, but very natural."
- "Make 256 px web thumbnails of every JPEG in this folder, as PNGs in thumbs/."

## Requirements

- macOS with PhotoCraft installed ([releases](https://github.com/storytold/photocraft/releases))
- Python 3 (the scripts use only the standard library)
- [Claude Code](https://code.claude.com)

## Install

```
claude plugin marketplace add mendelabramzon/photocraft-skill
claude plugin install photocraft@photocraft-skills
```

Inside a Claude Code session, the same commands start with `/plugin`. The skill loads by itself when
you ask for a photo edit; you can also call it as `/photocraft:photocraft`.

To update later: `claude plugin marketplace update photocraft-skills`, then
`claude plugin update photocraft@photocraft-skills`.

## How it works, and what it touches

- `pc.py launch` starts a **separate** PhotoCraft window with its control channel on: localhost only,
  a fresh token in `~/.photocraft-skill/token` (mode 0600), and file access limited to your home
  folder by default. A PhotoCraft window you opened yourself is never driven, closed or quit.
- `pc.py install-cli` downloads the `photocraft-cli` that matches your installed app from PhotoCraft's
  GitHub releases and checks it against the release's SHA-256 sums.
- Edits are saved under new names (`photo-edited.jpg`, a layered `.psd`); originals are not overwritten.
- Claude Code asks before running each script unless you allow it.

Everything the plugin runs or contacts, in full:

- **Runs locally:** Python 3 scripts in `skills/photocraft/scripts/`, the PhotoCraft app and
  `photocraft-cli` as local processes, and macOS `pgrep` / `mdfind` to find them.
- **Network:** `127.0.0.1` only, for the PhotoCraft control channel. The one exception is
  `pc.py install-cli`, which, when you need the CLI, reads `api.github.com` and downloads that
  release's files from GitHub for `storytold/photocraft`. Nothing else, and no telemetry: your photos
  never leave your Mac.
- **Writes:** `~/.photocraft-skill/` (control token, launch state, the CLI, working files) and the
  edited images you ask for.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   this repo is also its own marketplace
skills/photocraft/SKILL.md        the skill
skills/photocraft/references/     command reference, live-app and headless guides, skin-retouch workflow
skills/photocraft/scripts/        pc.py (control channel + CLI helper) and the retouch planners
```

## License

Apache-2.0, see [LICENSE](LICENSE). PhotoCraft itself is Apache-2.0 and belongs to its authors.
