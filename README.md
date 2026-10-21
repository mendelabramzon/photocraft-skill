# PhotoCraft and LightCraft for Claude Code (unofficial)

A Claude Code plugin that lets Claude operate two open-source photo apps:
[PhotoCraft](https://github.com/storytold/photocraft), the Photoshop-style editor, and
[LightCraft](https://github.com/storytold/lightcraft), the Lightroom-style photo library and raw developer.
In the apps on your Mac, or headless in a chat in the Claude apps (web, desktop, iPhone, iPad) and on Linux.
Ask for an edit in plain words; Claude runs the apps' own commands (the same ones their menus and tools
use), looks at the result, and keeps your originals untouched.

> Community project, not affiliated with or endorsed by the PhotoCraft or LightCraft authors.

## What it can do

### PhotoCraft

- **Drive the live app.** Open files, add layers and adjustment layers, masks, selections, filters,
  type, shapes, layer styles, brush strokes and dialogs, in a PhotoCraft window you can watch and
  keep working in. Saves layered PSDs.
- **Edit headless.** File-in, file-out with `photocraft-cli`: batch resize, sharpen, convert
  (PSD, PNG, JPEG, TIFF, WebP), scripted edit chains, in about 0.2 s per edit chain.
- **Retouch skin like a professional, and keep it natural.** Removes temporary blemishes (acne,
  whiteheads, scabs) with hundreds of tiny healing dabs sourced from clean skin nearby, then evens
  post-acne marks with micro dodge & burn and a colour layer that fade tone and colour together.
  Pores, stubble, light and the person's features stay. Everything lands on named, editable layers.
  Pick the tier (light, commercial, beauty): beauty work adds frequency separation, built in 16-bit and
  checked to give the photo back exactly, with texture healed on the texture layer only, and flyaway hair
  cleaned off plain backdrops while the hair's natural edge stays.

The other most-requested retouching jobs work the same way. Each has a guide with the rules
professionals follow and planning scripts that measure what a retoucher would eyeball. The result is
built as named, masked layers and checked against the plan's predicted pixels.

- **Eyes and teeth.** Teeth less yellow but never whiter than the eye whites. Cleaner eye whites,
  a little life in the iris, red-eye. Closed eyes opened with the eyes from another frame of the same
  shoot.
- **Colour by the numbers.** White balance from real neutrals (even when a strong cast clips the
  whites), black and white points for screen or print, skin checked by its Lab numbers and on the
  vectorscope, camera colour fitted from a ColorChecker in the shot, tested looks (split tone, matte
  blacks, a Margulis-style Lab boost), local contrast kept off skin, matching one shot to another, and
  black & white. All as editable layers.
- **Cutouts and marketplace-ready product shots.** Edges checked on white, black and colour; the
  channel route for hair, glass on any backdrop, and non-destructive edge-colour layers instead of baked
  decontamination. The product's real shadow kept (or a contact shadow, or a glossy reflection), and
  Amazon, Google, eBay, Shopify, Etsy and Zalando presets, or a client's own spec, drive the placement and a
  pass/fail deliverable check.
- **Dust, wires and distractions.** Sensor dust and power lines are removed along the whole wire,
  stopping at poles and branches. People and objects go with patch and clone, shadows and
  reflections included.
- **Straight horizons and verticals.** Measured from the photo's own lines and corrected with a camera
  model from its EXIF, so buildings keep their proportions. Cropped with no empty corners.
- **Skies.** A precise sky mask, a decision between enhancing and replacing, and a light-matched new
  sky with no halo, its light wrapped round the skyline.
- **Compositing.** A cut-out product or person placed into another photo the way compositors match it
  (black point, then white point, then the colour of the light, grain and focus), with the plate's light
  wrapped round its edge and a contact shadow, as editable layers checked against a predicted render.
- **Old-photo restoration.** Dust and scratches repaired through masks with the grain kept, dense flaking
  and crazing found and drawn, faded dyes and casts corrected, stains on black-and-white and sepia prints
  dropped through the cleanest colour channel with the print's own tone kept (an inset print or hand
  colouring left out), big scans worked in bands, faces left as they are.
- **A retoucher's QC.** Solar, luminance, negative and saturation check views (also as hidden check
  layers in the document), and the measurements a reviewer would make: changes outside the work area,
  seams around composites and patches, clone-stamp repeats, banding in skies and backdrops.
- **Deliverables in one step.** Web, Instagram, email, watermarked proofs, print TIFFs and an archive from
  one master, each cropped, sharpened for its output, in the right colour space, and checked. Screen files
  carry only your credit and copyright: no GPS and no hidden thumbnail of the unretouched original.

### LightCraft

- **Develop raws and JPEGs.** White balance from a real neutral, exposure and the tonal end points set by
  measurement, colour mixer and grading, sky, subject and gradient masks with their coverage checked, lens
  corrections, Upright and crops for every format. Edits stay settings; originals are never written.
- **Whole shoots.** Assisted culling (focus scores, burst groups) on numbered contact sheets, picks and
  ratings, one look synced across the photos taken in the same light, exposures matched.
- **Exports for every use.** Web, Instagram and story crops, print TIFFs, size-limited uploads,
  watermarked client proofs and archives, one photo or hundreds, named by template.
- **HDR and panorama merges,** presets and profiles, keywords, albums and captions.
- **Hand-off between the two apps.** LightCraft renders a developed photo for PhotoCraft (skin, objects,
  composites, text), and shows the retouched version in your library afterwards.

Example requests:

- "Open ~/Pictures/beach.jpg in PhotoCraft, make it warmer and punchier, keep it editable."
- "Retouch his skin: clean, but very natural."
- "Beauty retouch for the cover: frequency separation, and tidy the flyaways."
- "Whiten her teeth a little and brighten the eyes. Nobody should notice."
- "Put these product photos on pure white for Amazon, with a soft shadow."
- "Make Zalando and Shopify versions of this packshot and check they pass."
- "Put this bottle on the kitchen counter photo so it looks like it was shot there."
- "Remove the power lines from the sky."
- "Check my retouch for seams, clone repeats and banding before I send it."
- "Export this PSD for the web, Instagram and an 8 × 10 print."
- "The building leans backwards. Straighten the verticals."
- "Restore this scan of my grandparents' wedding photo."
- "Make 256 px web thumbnails of every JPEG in this folder, as PNGs in thumbs/."
- "Develop these raws from the beach in LightCraft: natural colour, then web JPEGs."
- "Cull the wedding folder: the sharpest of each burst, flagged as picks."
- "Give every photo from the dinner the same warm look as this one."
- "Instagram portrait crops of the picks, 1080 × 1350."

## Requirements

On a Mac, to watch the edits in the app:

- macOS with PhotoCraft ([releases](https://github.com/storytold/photocraft/releases)) and/or LightCraft
  ([releases](https://github.com/storytold/lightcraft/releases)) installed
- Python 3 (the scripts use only the standard library)
- [Claude Code](https://code.claude.com)
- For headless editing and the retouching workflows: `photocraft-cli`, from the same PhotoCraft release as your
  app. On that release's page, download `photocraft-cli-<version>-macos-universal.zip`, compare its
  SHA-256 with `SHA256SUMS.txt` there, unzip it, and put `photocraft-cli` in `~/.photocraft-skill/bin/`
  or anywhere on your PATH. Ask Claude "which PhotoCraft CLI do I need?" and it will name the exact
  file. It's signed by PhotoCraft's developer.
- For headless LightCraft work: `lightcraft-cli`, the same way, from the same LightCraft release as your app:
  `lightcraft-cli-<version>-macos-universal.zip`, checked against that release's `SHA256SUMS.txt`, into
  `~/.lightcraft-skill/bin/` or your PATH. Ask Claude "which LightCraft CLI do I need?". It's signed by the
  same developer.

In the Claude apps (web, desktop, iPhone, iPad): a paid Claude plan with code execution on (Settings >
Capabilities). Nothing to install on your device; Claude sets up `photocraft-cli` or `lightcraft-cli` in
its sandbox.

On a Linux server: Python 3, Claude Code, and x86_64 or aarch64 with glibc 2.35 or newer (Ubuntu 22.04+,
Debian 12+). Claude installs each CLI with its skill's `install_cli.py`.

## Install

In Claude Code:

```
claude plugin marketplace add mendelabramzon/photocraft-skill
claude plugin install photocraft@photocraft-skills
```

Inside a Claude Code session, the same commands start with `/plugin`. The skills load by themselves when
you ask for a photo edit; you can also call them as `/photocraft:photocraft` and `/photocraft:lightcraft`.

To update later: `claude plugin marketplace update photocraft-skills`, then
`claude plugin update photocraft@photocraft-skills`.

In the Claude apps, once, in claude.ai or the desktop app: **Customize > Plugins > Add > Add
marketplace**, enter `mendelabramzon/photocraft-skill`, then **Add** on the plugin. It's then in your
chats on every device, and in Claude Code too. Attach a photo, ask for the edit, and download the
result. Downloads from a chat are capped at 30 MB per file, so large layered files come as PhotoCraft's
own `.pcraft`, which is smaller than a PSD, and a LightCraft edit can come as a small preset to apply to
your original in your own library.

## How it works, and what it touches

- `pc.py launch` starts a **separate** PhotoCraft window with its control channel on: localhost only,
  a fresh token in `~/.photocraft-skill/token` (mode 0600), and file access limited to your home
  folder by default. A PhotoCraft window you opened yourself is never driven, closed or quit.
- `lc.py launch` starts LightCraft with its control channel on `127.0.0.1` (port 7980), with the library
  LightCraft opens anyway, and imports the photos you name in place (nothing is copied). LightCraft keeps one
  library open at a time, so if it's already open normally Claude asks you to quit it first; it never quits
  it for you. **LightCraft's control channel has no token:** while that window is open, other programs on
  your Mac could drive it too. Claude uses it only for work you want to see in LightCraft, says when it's
  done, and quits it unless you keep working in it.
- Headless LightCraft work runs in memory, or in a work library under `~/.lightcraft-skill/work/`, not in
  your own library, and writes only the exports you ask for.
- On a Mac the plugin never downloads anything. Headless editing (and the retouching workflows'
  planners) need `photocraft-cli` or `lightcraft-cli`, which you install yourself once; see Requirements.
- On Linux, including Claude's sandbox in the Claude apps, there is no app and nothing for you to
  install: each skill's `install_cli.py` downloads its app's official Linux release (a pinned version) from
  its GitHub release page, checks its SHA-256, and installs the CLI from it.
- Edits are saved under new names (`photo-edited.jpg`, a layered `.psd`); originals are not overwritten
  (LightCraft refuses to write over one).
- Claude Code asks before running each script unless you allow it.

Everything the plugin runs or contacts, in full:

- **Runs locally:** Python 3 scripts in `skills/photocraft/scripts/` and `skills/lightcraft/scripts/`, the
  PhotoCraft and LightCraft apps and their CLIs as local processes, macOS `pgrep` / `mdfind` to find them,
  `mdls` to read photos' capture times when looking for a donor frame (feature swap), and `sips` to shrink
  LightCraft screenshots.
- **Network:** on a Mac, `127.0.0.1` only, for the PhotoCraft and LightCraft control channels. Nothing else,
  no downloads and no telemetry: your photos never leave your Mac. On Linux, one download per app besides:
  `install_cli.py` fetches `photocraft-<version>-linux-<arch>.tar.gz` from
  `github.com/storytold/photocraft/releases`, or `lightcraft-<version>-linux-<arch>.tar.gz` from
  `github.com/storytold/lightcraft/releases`. In the Claude apps your photo is edited in Claude's
  sandbox, where Claude runs anyway.
- **Writes:** `~/.photocraft-skill/` (control token, launch state, working files; on Linux also
  `bin/photocraft-cli`), `~/.lightcraft-skill/` (launch state, app log, work libraries; on Linux also
  `bin/lightcraft-cli`), the edited images you ask for, and, in live LightCraft work, the photos and edits
  Claude adds to your library.

## Notes for reviewers

- **The control token is not a user credential.** PhotoCraft creates a fresh random token each time
  `pc.py launch` starts it (`--control-token-file ~/.photocraft-skill/token`, folder mode 0700). `pc.py`
  reads that file only to authenticate its own connection to the app's control channel on
  `127.0.0.1`, and sends it nowhere else. There is no secret for the user to provide, so a `userConfig`
  option doesn't apply.
- **LightCraft's control channel has no token.** That is LightCraft's own design: its protocol docs say the
  port has no authentication and should be turned on only when needed. It listens on `127.0.0.1` only,
  closes any connection whose first line isn't a JSON request (so a web page's request can't drive it), and
  serves at most 16 connections. The plugin turns it on only for live work the user asks for: `lc.py
  launch` starts it, the skill tells Claude to say so and to `lc.py quit` when the user is done, and
  headless work, the default for file-in, file-out jobs, opens no port. `lc.py` sends only control
  requests, to `127.0.0.1`.
- **Executables.** The plugin runs only four programs: the PhotoCraft and LightCraft apps the user
  installed in `/Applications`, and `photocraft-cli` and `lightcraft-cli`, which the user installs
  themselves from each app's official GitHub release. All four are signed with the same developer's
  Developer ID, and both apps are notarized. The plugin contains no binaries. On a Mac it downloads
  nothing, installs nothing, and needs no network access beyond `127.0.0.1`.
- **Linux.** There, each skill's `scripts/install_cli.py` is the only code that uses the network. Each
  refuses to run on macOS, downloads one file (its app's official Linux release tarball for the pinned
  version and the machine's architecture), refuses it unless its SHA-256 matches the value pinned in the
  script (copied from that release's `SHA256SUMS.txt`), and extracts only `bin/photocraft-cli` or
  `bin/lightcraft-cli` into `~/.photocraft-skill/bin/` or `~/.lightcraft-skill/bin/`. `pc.py` and `lc.py`
  themselves still talk to `127.0.0.1` only.

## Layout

```
.claude-plugin/plugin.json        plugin manifest
.claude-plugin/marketplace.json   this repo is also its own marketplace
skills/photocraft/SKILL.md        the PhotoCraft skill
skills/photocraft/references/     command reference, live-app, headless and no-app guides, one guide per retouching workflow
skills/photocraft/scripts/        pc.py (control channel + CLI helper), install_cli.py (Linux), the workflow planners, import_layers.py
skills/lightcraft/SKILL.md        the LightCraft skill
skills/lightcraft/references/     command reference, live-app, headless and no-app guides, developing a photo, a whole shoot
skills/lightcraft/scripts/        lc.py (control channel + CLI helper), install_cli.py (Linux), look.py (measure, grid, diff, contact sheets)
```

## License

Apache-2.0, see [LICENSE](LICENSE). PhotoCraft (Apache-2.0) and LightCraft (MIT or Apache-2.0) belong to
their authors.
