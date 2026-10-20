# PhotoCraft for Claude Code (unofficial)

A Claude Code plugin that lets Claude operate [PhotoCraft](https://github.com/storytold/photocraft),
the open-source, Photoshop-style photo editor: in the app on your Mac, or headless in a chat in the Claude
apps (web, desktop, iPhone, iPad) and on Linux. Ask for an edit in plain words; Claude runs PhotoCraft's
own commands (the same ones its menus and tools use), looks at the result, and keeps your originals
untouched.

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

The other most-requested retouching jobs work the same way. Each has a guide with the rules
professionals follow and planning scripts that measure what a retoucher would eyeball. The result is
built as named, masked layers and checked against the plan's predicted pixels.

- **Eyes and teeth.** Teeth less yellow but never whiter than the eye whites. Cleaner eye whites,
  a little life in the iris, red-eye. Closed eyes opened with the eyes from another frame of the same
  shoot.
- **Colour by the numbers.** White balance from real neutrals, black and white points, tested looks,
  matching one shot to another, and black & white. All as editable Curves layers.
- **Cutouts and product photos on white.** Edges checked on white, black and colour, the product's
  real shadow kept. Marketplace images (pure white, 85 % fill, sRGB) are checked automatically.
- **Dust, wires and distractions.** Sensor dust and power lines are removed along the whole wire,
  stopping at poles and branches. People and objects go with patch and clone, shadows and
  reflections included.
- **Straight horizons and verticals.** Measured from the photo's own lines and corrected with a camera
  model from its EXIF, so buildings keep their proportions. Cropped with no empty corners.
- **Skies.** A precise sky mask, a decision between enhancing and replacing, and a light-matched new
  sky with no halo.
- **Old-photo restoration.** Dust and scratches repaired through masks with the grain kept, faded
  dyes and casts corrected, faces left as they are.

Example requests:

- "Open ~/Pictures/beach.jpg in PhotoCraft, make it warmer and punchier, keep it editable."
- "Retouch his skin: clean, but very natural."
- "Whiten her teeth a little and brighten the eyes. Nobody should notice."
- "Put these product photos on pure white for Amazon, with a soft shadow."
- "Remove the power lines from the sky."
- "The building leans backwards. Straighten the verticals."
- "Restore this scan of my grandparents' wedding photo."
- "Make 256 px web thumbnails of every JPEG in this folder, as PNGs in thumbs/."

## Requirements

On a Mac, to watch the edits in the app:

- macOS with PhotoCraft installed ([releases](https://github.com/storytold/photocraft/releases))
- Python 3 (the scripts use only the standard library)
- [Claude Code](https://code.claude.com)
- For headless editing and the retouching workflows: `photocraft-cli`, from the same PhotoCraft release as your
  app. On that release's page, download `photocraft-cli-<version>-macos-universal.zip`, compare its
  SHA-256 with `SHA256SUMS.txt` there, unzip it, and put `photocraft-cli` in `~/.photocraft-skill/bin/`
  or anywhere on your PATH. Ask Claude "which PhotoCraft CLI do I need?" and it will name the exact
  file. It's signed by PhotoCraft's developer.

In the Claude apps (web, desktop, iPhone, iPad): a paid Claude plan with code execution on (Settings >
Capabilities). Nothing to install on your device; Claude sets up `photocraft-cli` in its sandbox.

On a Linux server: Python 3, Claude Code, and x86_64 or aarch64 with glibc 2.35 or newer (Ubuntu 22.04+,
Debian 12+). Claude installs `photocraft-cli` with `install_cli.py`.

## Install

In Claude Code:

```
claude plugin marketplace add mendelabramzon/photocraft-skill
claude plugin install photocraft@photocraft-skills
```

Inside a Claude Code session, the same commands start with `/plugin`. The skill loads by itself when
you ask for a photo edit; you can also call it as `/photocraft:photocraft`.

To update later: `claude plugin marketplace update photocraft-skills`, then
`claude plugin update photocraft@photocraft-skills`.

In the Claude apps, once, in claude.ai or the desktop app: **Customize > Plugins > Add > Add
marketplace**, enter `mendelabramzon/photocraft-skill`, then **Add** on PhotoCraft. It's then in your
chats on every device, and in Claude Code too. Attach a photo, ask for the edit, and download the
result. Downloads from a chat are capped at 30 MB per file, so large layered files come as PhotoCraft's
own `.pcraft`, which is smaller than a PSD.

## How it works, and what it touches

- `pc.py launch` starts a **separate** PhotoCraft window with its control channel on: localhost only,
  a fresh token in `~/.photocraft-skill/token` (mode 0600), and file access limited to your home
  folder by default. A PhotoCraft window you opened yourself is never driven, closed or quit.
- On a Mac the plugin never downloads anything. Headless editing (and the retouching workflows'
  planners) need `photocraft-cli`, which you install yourself once; see Requirements.
- On Linux, including Claude's sandbox in the Claude apps, there is no app and nothing for you to
  install: `install_cli.py` downloads PhotoCraft's official Linux release (a pinned version) from its
  GitHub release page, checks its SHA-256, and installs `photocraft-cli` from it.
- Edits are saved under new names (`photo-edited.jpg`, a layered `.psd`); originals are not overwritten.
- Claude Code asks before running each script unless you allow it.

Everything the plugin runs or contacts, in full:

- **Runs locally:** Python 3 scripts in `skills/photocraft/scripts/`, the PhotoCraft app and
  `photocraft-cli` as local processes, macOS `pgrep` / `mdfind` to find them, and `mdls` to read
  photos' capture times when looking for a donor frame (feature swap).
- **Network:** on a Mac, `127.0.0.1` only, for the PhotoCraft control channel. Nothing else, no
  downloads and no telemetry: your photos never leave your Mac. On Linux, one download besides:
  `install_cli.py` fetches `photocraft-<version>-linux-<arch>.tar.gz` from
  `github.com/storytold/photocraft/releases`. In the Claude apps your photo is edited in Claude's
  sandbox, where Claude runs anyway.
- **Writes:** `~/.photocraft-skill/` (control token, launch state, working files; on Linux also
  `bin/photocraft-cli`) and the edited images you ask for.

## Notes for reviewers

- **The control token is not a user credential.** PhotoCraft creates a fresh random token each time
  `pc.py launch` starts it (`--control-token-file ~/.photocraft-skill/token`, folder mode 0700). `pc.py`
  reads that file only to authenticate its own connection to the app's control channel on
  `127.0.0.1`, and sends it nowhere else. There is no secret for the user to provide, so a `userConfig`
  option doesn't apply.
- **Executables.** The plugin runs only two programs: the PhotoCraft app the user installed in
  `/Applications`, and `photocraft-cli`, which the user installs themselves from PhotoCraft's official
  GitHub release. Both are signed with the PhotoCraft developer's Developer ID. The plugin contains no
  binaries. On a Mac it downloads nothing, installs nothing, and needs no network access beyond
  `127.0.0.1`.
- **Linux.** There, `scripts/install_cli.py` is the only code that uses the network. It refuses to run on
  macOS, downloads one file (PhotoCraft's official Linux release tarball for the pinned version and the
  machine's architecture), refuses it unless its SHA-256 matches the value pinned in the script (copied
  from that release's `SHA256SUMS.txt`), and extracts only `bin/photocraft-cli` into
  `~/.photocraft-skill/bin/`. `pc.py` itself still talks to `127.0.0.1` only.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   this repo is also its own marketplace
skills/photocraft/SKILL.md        the skill
skills/photocraft/references/     command reference, live-app, headless and no-app guides, one guide per retouching workflow
skills/photocraft/scripts/        pc.py (control channel + CLI helper), install_cli.py (Linux), the workflow planners, import_layers.py
```

## License

Apache-2.0, see [LICENSE](LICENSE). PhotoCraft itself is Apache-2.0 and belongs to its authors.
