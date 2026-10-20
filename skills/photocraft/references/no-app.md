# Without the desktop app: Linux servers and Claude's sandbox

Read this when there is no PhotoCraft window to drive: a Linux server, a chat in the Claude apps (web,
desktop, iPhone, iPad), whose commands run in Claude's cloud sandbox, or a Managed Agents session.
Everything goes through `photocraft-cli`, headless. The commands, layers and workflows are the same as in
the app; only the window is missing.

## Contents
- Check the setup
- Install photocraft-cli
- Where files come from and go
- Working headless
- Looking at your work
- Delivering results
- What needs the app

## Check the setup

    $PC status

`platform` is `linux` and `app` is null. `cli` is the CLI's path once it's installed. In a Claude
sandbox, `sandbox` names the folder that holds the user's files (`uploads`) and the one whose files they
get back (`outputs`).

## Install photocraft-cli

    python3 ${CLAUDE_SKILL_DIR}/scripts/install_cli.py

It downloads PhotoCraft's own Linux release (the version pinned in the script) from PhotoCraft's GitHub
release page, checks its SHA-256 against the one that release published, puts `photocraft-cli` in
`~/.photocraft-skill/bin/` and runs it once. A sandbox starts empty, so run it at the start of each new
one; when the CLI is already installed it says so and does nothing. It runs on Linux only.

- **The download fails.** A chat sandbox may reach github.com but not the host GitHub serves release files
  from. Ask the user to turn on network access under Settings > Capabilities and try again.
  `install_cli.py --tarball FILE` installs the same release tarball from disk instead (in Managed Agents,
  mount `photocraft-0.10.0-linux-x86_64.tar.gz` as a session file). Never use a `photocraft-cli` that
  failed the checksum, and don't fetch one from anywhere else.
- **It installs but doesn't run** (`GLIBC_2.35 not found`): the machine is older than PhotoCraft's Linux
  build allows (Ubuntu 22.04, Debian 12 or newer). Tell the user instead of switching to another editor.

## Where files come from and go

| Setup | The user's photo | Results |
|---|---|---|
| Chat in the Claude apps | `/mnt/user-data/uploads` | `/mnt/user-data/outputs`: offered for download, 30 MB per file at most |
| Managed Agents | `/mnt/session/uploads/…` (read-only) | `/mnt/session/outputs/`, which the caller downloads |
| Linux server | wherever the caller says | wherever the caller says, or next to the input |

The headless engine (`pc.py script --open`, `import_layers.py --file`) only opens files under the home
folder, and refuses others with "automation path rejected". Copy the photo into a work folder there first,
e.g. `~/work/<photo>/` (in a chat the home folder is `/root`), and point every planning script's output
folder inside it. The upload stays as it was.

## Working headless

The recipes in SKILL.md and the workflow guides work without the window. Their live steps translate like
this:

| With the app | Headless |
|---|---|
| `$PC exec <id> '<params>'`, `$PC script steps.json` | `$PC script steps.json --open photo.jpg --save work.psd`: the same steps on a file, in one `photocraft-cli serve` session |
| `$PC exec document.inspect` | `$PC cli info work.psd`, or `--cmd document.inspect` at the end of a `$PC cli run` |
| `import_layers.py layers.json` | `import_layers.py layers.json --file work.psd --out work.psd` |
| `$PC export now.png` | `$PC cli convert work.psd now.png` |
| `$PC screenshot` | nothing: render the image and look at it (below) |

- In `$PC script`, write every editing step as `{"command": "<id>", "params": {…}}`. A `[name, params]`
  pair is a session method (`doc.open`, `doc.inspect`, …), not a command, and fails with "unknown method".
- `--save` may name the file that `--open` opened; the new layers land on top of the old ones. To try
  again, start from the original photo rather than from a result, so every attempt is reproducible.
- Planners' `steps.json` files are already in the command form; run them with `--open`/`--save` on the
  full-size file, as SKILL.md says.

## Looking at your work

There is no screenshot. Render a preview and look at it: with the Read tool in Claude Code, with the file
viewer in a chat or a Managed Agents session.

    $PC cli run work.psd --cmd image.imageSize --params '{"width":1600}' --out ~/work/<photo>/look.png

`image.imageSize` with only a width keeps the aspect ratio. For retouching, also look at crops at 100–200 %
(`--cmd image.crop --params '{"x":…,"y":…,"width":…,"height":…}'`), not only at the whole frame. Never report
success from a JSON `ok` alone.

## Delivering results

- Always a JPEG: `$PC cli convert work.psd <photo>-edited.jpg --quality 95` (keeps the colour profile).
- Layers, when the user may keep editing. A chat download is capped at 30 MB, and a layered PSD passes that
  fast: a 6 MP test image with two adjustment layers came to 35 MB as PSD and 15 MB as PhotoCraft's own
  `.pcraft`, with the layers kept. Check the size (`ls -l`). When the PSD is too big, deliver
  `$PC cli convert work.psd <photo>-edited.pcraft` instead and tell the user why: it opens in PhotoCraft,
  not in Photoshop.
- Put the files in the outputs folder, named after the original.

## What needs the app

- Watching the edit, the Layers panel in a screenshot, dialogs, and pointer tools on the canvas.
- `feature_swap.py donors` finds the frames shot just before and after through macOS Spotlight. Elsewhere
  it falls back to file dates, which mean nothing for uploads: ask the user which frame to take the eyes
  from.
