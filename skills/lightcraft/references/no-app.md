# Without the desktop app: Linux servers and Claude's sandbox

Read this when there is no LightCraft window to drive: a Linux server, a chat in the Claude apps (web,
desktop, iPhone, iPad), whose commands run in Claude's cloud sandbox, or a Managed Agents session.
Everything goes through `lightcraft-cli`, headless. The commands, controls and recipes are the same as in
the app; only the window is missing.

Commands below use `$LC` and `$LOOK` as SKILL.md sets them:
`${CLAUDE_SKILL_DIR}/scripts/lc.py` and `${CLAUDE_SKILL_DIR}/scripts/look.py`.

## Contents
- Check the setup
- Install lightcraft-cli
- Where files come from and go
- Working headless
- Looking at your work
- Delivering results
- What needs the app

## Check the setup

    $LC status

`platform` is `linux` and `app` is null (a Mac with only the CLI shows `darwin`; there, `headless.md` is
all you need). `cli` is the CLI's path once it's installed. In a Claude sandbox, `sandbox` names the
folder that holds the user's files (`uploads`) and the one whose files they get back (`outputs`).

## Install lightcraft-cli

    python3 ${CLAUDE_SKILL_DIR}/scripts/install_cli.py

It downloads LightCraft's own Linux release (the version pinned in the script, about 105 MB) from
LightCraft's GitHub release page, checks its SHA-256 against the one that release published, puts
`lightcraft-cli` in `~/.lightcraft-skill/bin/` and runs it once. A sandbox starts empty, so run it at the
start of each new one; when the CLI is already installed it says so and does nothing. It runs on Linux
only.

- **The download fails.** A chat sandbox may reach github.com but not the host GitHub serves release files
  from. Ask the user to turn on network access under Settings > Capabilities and try again.
  `install_cli.py --tarball FILE` installs the same release tarball from disk instead (in Managed Agents,
  mount `lightcraft-0.9.1-linux-x86_64.tar.gz` as a session file). Never use a `lightcraft-cli` that
  failed the checksum, and don't fetch one from anywhere else.
- **It installs but doesn't run** (`GLIBC_2.35 not found`): the machine is older than LightCraft's Linux
  build allows (Ubuntu 22.04, Debian 12 or newer). Tell the user instead of switching to another editor.

## Where files come from and go

| Setup | The user's photos | Results |
|---|---|---|
| Chat in the Claude apps | `/mnt/user-data/uploads` | `/mnt/user-data/outputs`: offered for download, 30 MB per file at most |
| Managed Agents | `/mnt/session/uploads/…` (read-only) | `/mnt/session/outputs/`, which the caller downloads |
| Linux server | wherever the caller says | wherever the caller says, or next to the input |

LightCraft reads photos where they are and never writes over them, so renders and exports can read
straight from the uploads. Two things write next to the photos, though: `merge` (the HDR or panorama DNG)
and `photo.editExternal`. Copy the photos into a work folder first for those, e.g. `~/work/<shoot>/`
(in a chat the home folder is `/root`); the Managed Agents uploads folder is read-only anyway.

## Working headless

The recipes in SKILL.md and the workflow guides work without the window. Their live steps translate like
this:

| With the app | Headless |
|---|---|
| `$LC exec <command> '<params>'` | `$LC cli run --import photo.jpg <command> key=value …`, or a settings file with `render` |
| `$LC script steps.json` | `$LC script steps.json --import photo.jpg` (one `lightcraft-cli run`) |
| `$LC exec photo.inspect`, `develop.get` | the same commands at the end of a `run` chain |
| `$LC render look.png` | `$LC cli render photo.jpg -o look.png --size 1200 --settings look.json` |
| `$LC screenshot` | nothing needed: look at renders (`snapshot` draws the UI if the user wants to see it) |
| the user's library | a work library, `--library ~/work/<shoot>/library`, when the job takes several steps |

A headless session starts from the original every time, so iterate on the settings file (or the command
list) and render again, rather than editing a previous export.

## Looking at your work

There is no window. Render a preview and look at it: with the Read tool in Claude Code, with the file
viewer in a chat or a Managed Agents session.

    $LC cli render photo.jpg -o ~/work/photo/look.png --size 1200 --settings ~/work/photo/look.json
    $LOOK measure ~/work/photo/look.png

For detail work (sharpening, noise, dust, mask edges), also look at 100 % crops: the same edit plus a
crop to the region, at full size, e.g. `$LC cli run --import photo.jpg <the edit…> crop.set
'rect=[0.4,0.3,0.6,0.5]' app.export path="$HOME/work/photo/crop.png" longEdge=0`. For a shoot, put
renders on numbered contact sheets (`$LOOK sheet`). Never report success from a JSON `ok` alone.

## Delivering results

- Always a JPEG: `app.export path=… quality=92 longEdge=0` (or the size the user wants), sRGB (the
  default) unless they ask for another space. Name it after the original (`<photo>-edited.jpg`) and put it in the outputs
  folder.
- When the user edits in LightCraft themselves and wants to keep working on your edit, give them the edit,
  not just pixels. Both of these were tested to bring the full edit, masks included, into another library:
  - **A preset** (a few KB): `preset.create '{"name": "<photo> edit"}'` then
    `preset.export '{"path": ".../<photo>-edit.lcpreset"}'`. They bring it in with Import Presets and
    apply it to their original.
  - **The original with its edit**: `app.export '{"dir": "…", "format": "original"}'` gives the photo plus
    an XMP sidecar; importing both into LightCraft restores the edit. Raws are often over 30 MB: check the
    size (`ls -l`) and fall back to the preset when it's too big for a chat download.
- For editing in another program, a 16-bit TIFF (`format: "tiff", bitDepth: 16`) keeps the most
  latitude, but it's large (6 bytes a pixel before compression), so a full-size photo rarely fits the
  30 MB limit. A full-size JPEG at quality 95 is often the practical choice.
- Raws can also go out as DNG with the edit embedded (`format: "dng"`), for LightCraft users.

## What needs the app

- The user's own library, the window, watching the edit, and pointer tools.
- Adding exports to Apple Photos (`addToPhotos`, macOS only).
- The models behind Object/Describe masks, faces and AI Denoise download into LightCraft's settings
  folder; in a sandbox they'd be downloaded again every session (SAM 3 is about 3.4 GB). Use the
  classical tools there (Sky, Subject, Background, range masks, Find Dust).
