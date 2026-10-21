# Delivery: the files a client, a website and a print lab get

Read this before exporting a finished photo: web and portfolio JPEGs, Instagram and story crops, size-limited email
or upload copies, watermarked proofs, print TIFFs and an archive. It is how professionals prepare deliverables and
how `scripts/deliver.py` does it from a PhotoCraft master in one call, then checks every file it wrote.

## Contents
- What separates a professional delivery from a cheap one
- The files and where their numbers come from
- Step 1: the master
- Step 2: export
- Step 3: check every file
- Output sharpening, measured
- JPEG quality and file size, measured
- Metadata: what each file carries
- PhotoCraft specifics
- Tuning and false hits

## What separates a professional delivery from a cheap one

- **The master stays layered and archived; deliverables are flattened copies.** A layered PSD (named groups,
  adjustment layers) is kept for revisions, and flat JPEG, PNG or TIFF files go out (Skylum's PSD guide; Lisa Carney
  teaches file types as part of the business of retouching). Never export over the master.
- **Output sharpening is its own last step.** Capture sharpening makes the master look right at 100 %; output
  sharpening compensates for the resampling and the medium, at the output size (Adobe Community: reducing a 24–54 MP
  file to about 1024 px blurs the develop sharpening away). Screen takes less than print, and matte paper more than
  glossy (Lightroom's Screen, Matte and Glossy settings). Judge it at 100 % of the output, never on the master.
- **Size in pixels for screens, in inches and ppi for print.** The ppi value means nothing on a screen; for print,
  pixels = inches × ppi, 300 ppi as the usual lab target.
- **Convert, don't assign.** Screen files go to sRGB with the profile embedded: browsers and phones assume sRGB, and
  Shopify strips profiles on display. Converting keeps the colours; assigning keeps the numbers and changes the
  colours. Print files stay 16-bit, in Adobe RGB unless the lab asks for sRGB; ProPhoto is an editing space only
  (Photography Life).
- **Know what won't survive the conversion.** A wide-gamut master can hold colours sRGB can't: measure the share
  before converting.
- **Metadata on purpose.** Files that get published carry the creator and the copyright and nothing else
  (LightCraft's web recipe exports copyright-only metadata and removes the location). Above all, never a camera
  thumbnail: a retouched photo that travels with the camera's picture of the original undoes the retouch.
- **Consistent, versioned names**, so a revision never overwrites what the client already has.
- **Every file checked as delivered**: pixel size, ppi, bit depth, embedded profile, file size, a look at 100 %.

## The files and where their numbers come from

`deliver.py` presets; LightCraft's export recipes use the same names and numbers where both have one.

| Preset | Size | Format | Colour | Sharpening | Source of the numbers |
|---|---|---|---|---|---|
| `web` | long edge 2048 | JPEG q85 | sRGB | screen | LightCraft's "JPEG (Small)" export; Shopify: 2048 px squares "usually display best" |
| `instagram` | 1080 × 1350, a 4:5 crop | JPEG q90 | sRGB | screen | the feed size most guides cite (not an official Meta spec); the grid shows a centred 3:4 of it |
| `square` | 1080 × 1080 | JPEG q90 | sRGB | screen | the classic square post |
| `story` | 1080 × 1920, 9:16 | JPEG q90 | sRGB | screen | stories and reel covers |
| `email` | long edge 1800, under 500 KB | JPEG, quality searched | sRGB | screen | LightCraft's size-limited upload recipe |
| `proof` | long edge 1600 | JPEG q80 | sRGB | screen | LightCraft's client-proof recipe (with `--watermark`) |
| `print` | inches × 300 ppi (`--print-size 8x10in`), else full size | TIFF 16-bit | Adobe RGB | glossy (or `--sharpen matte`) | the usual lab request; sRGB JPEG q95 when the lab asks |
| `archive` | full size | TIFF 16-bit | the master's own, tagged | none | plus a copy of the layered master |

Instagram uploads outside 4:5 to 1.91:1 get cropped by the app; a landscape post is 1080 × 566. Marketplace product
images have their own presets in `product_shot.py` and `cutout_check.py` (`references/cutout.md`).

## Step 1: the master

Save the finished document under a new name next to the original (`app.save {"path": "…/photo-final.psd"}`). Hidden
layers (check layers, alternatives) don't matter: the export flattens what is visible. A 16-bit master keeps more for
the print file; screen files become 8-bit at the end, whatever the format.

## Step 2: export

    python3 deliver.py photo-final.psd ~/Pictures/client-delivery --preset web --preset instagram --preset print \
        --print-size 8x10in --copyright "© Name" [--focus X,Y]
    python3 deliver.py photo-final.psd ~/Pictures/client-delivery --preset proof --watermark "© Name"   # proofs

One run makes one file per preset. For each it flattens a copy, crops to the aspect (centred on `--focus X,Y`, in the
master's pixels, when the subject isn't central) and resizes with bicubic, converts to the output profile, sharpens,
sets the ppi, and writes it under `--name` (default `{name}-{preset}`; `{w}`, `{h}` and `{date}` too; an unknown field
stops it before anything is rendered). An existing file gets `-2` unless `--overwrite`, which never replaces the
master itself: the files are compared, not the names, so `CASE.JPG` can't be overwritten as `CASE.jpg` on a Mac's
case-insensitive disk. Options override every preset of the run: `--long-edge` (the presets sized by their long
edge: web, email, proof, archive), `--size WxH` (any preset's size and aspect), `--quality`, `--max-kb` (JPEGs
only), `--profile srgb|adobe-rgb|p3|keep` (`keep`: the master's own space, tagged with PhotoCraft's matching built-in
profile, the archive's default; like every option it reaches every preset of the run, so a screen file stays in a
Display P3 or Adobe RGB master's space, with a warning), `--bits` (8 converts any format down), `--format jpg|tif|png`,
`--sharpen none|screen|glossy|matte`, `--strength low|standard|high` (×0.5, ×1, ×1.5), and the metadata options
below. It never enlarges unless `--upscale`: a master with too few pixels is written at its own size with a warning,
and a print gets the ppi it can reach. `--watermark TEXT` goes on every screen file of the run, bottom right, 3 % of
the long edge high, at 40 %, black where that corner of the master is light and white where it's dark; never on the
print or the archive. The archive preset copies a layered master once; a later run reports the copy `unchanged`, or
copies a revised master as `-master-2`.

Each file is rendered once, straight to its format (a `--max-kb` file goes through PhotoCraft's own format so the
quality can be searched). It took 6.1 s for eight files from a 1600 px layered master and 7.5 s for four from an
18 MP JPEG; the 100 % proof crops are cut by the CLI, so a big archive TIFF is never decoded in Python (363 MB at
most for an 18 MP master).

## Step 3: check every file

The JSON lists each file as written: `size`, `ppi`, `bits`, `profile` (the embedded ICC description), `kb`,
`quality`, `crop`, `reduced` (master pixels per output pixel), `sharpen` (the Unsharp Mask used), `outOfGamut%`,
`metadata` (the mode, what was removed, and what the file now carries: EXIF, GPS entries in EXIF and XMP, a
thumbnail, the artist and copyright in EXIF and XMP) and `warnings` (any GPS or thumbnail left, two different notices,
a size or bit depth other than planned). It also warns when the copyright or artist going out is missing, a placeholder ("Copyright",
"Unknown") or the camera's name: equal to the EXIF make or model, or a camera brand with a model number and no ©, year
or rights wording. A NASA portrait's EXIF copyright read "Hasselblad H6D", and without `--copyright` it would have gone
into both screen files; pass `--copyright "© Name 2026"` and `--author "Name"`. The JSON also names the master's
`camera` and lists what each file carries.

Then look at the proof sheet. It goes beside the delivery folder, `<outdir>-proof.png` (or `--proof PATH`, anywhere
but inside that folder; `--proof none` for none), so check files never sit among the client's. It holds a 360 px crop
at 100 % of every file, all from the same place in the master, so the files compare: `--proof-at X,Y` (master
pixels), or by default the most detailed part of the face, the highest skin region (hands and arms sit lower; on the
test portrait it took the eyes and smile, where the plain most-detailed window had been the embroidered patch on a
sleeve, then the hands and a watch), or with no skin in the picture the most detailed part of the middle third (a
product, a landscape). `proofCrop` in the JSON says where and why. Screen files should look crisp with no light or dark
rims on edges; the print file a little crisp on screen (it is meant for paper). A print file in Adobe RGB looks duller
when viewed without its profile; that is the viewer, not the file.

## Output sharpening, measured

A slanted edge with a camera's softness and light capture sharpening (10–90 % rise 2.1 px, 5 % overshoot), reduced
with PhotoCraft's bicubic, then Unsharp Mask. MTF is the contrast kept at a quarter cycle per pixel (1.0 = full):

| Reduced | No sharpening | Screen sharpening deliver.py uses | Result |
|---|---|---|---|
| 1.5× | 0.70 | amount 100, radius 0.6 | 0.93, 8.7 % overshoot |
| 2× | 0.81 | amount 67, radius 0.6 | 0.99, 8.5 % overshoot |
| 3× | 0.88 | amount 40, radius 0.6 | 1.00, 6.7 % |
| 4× | 0.90 | amount 29, radius 0.6 | 0.99, 6.4 % |

The more a photo is reduced, the less of its capture softness is left, so screen sharpening gets weaker with the
reduction (amount = 100 ÷ (factor − 0.5), between 20 and 100), and none below 1.25× (the master's own sharpening
stands). Radius 0.4 needed amounts above 150 for the same gain; radius 0.6 got there with less overshoot. PhotoCraft's
lanczos reduction was a touch crisper than bicubic (0.75 against 0.70 at 1.5×) with more ringing (3.8–6.5 % overshoot
against 2.9–3.5 %), so bicubic plus this sharpening is the default.

Print (at the print's pixels, 300 ppi; the radius scales with the ppi): glossy amount 100, radius 0.8, threshold 2
took the master's edge from 0.40 to 0.60 at 16 % overshoot; matte amount 150, radius 1.0 to 0.81. That is visibly
crisp on screen by design, since paper and ink soften it again; proof it on the paper and the lab's printer.

## JPEG quality and file size, measured

At 2048 px on the long side, PSNR against the uncompressed render:

| Photo | q80 | q85 | q90 | q95 | q100 |
|---|---|---|---|---|---|
| Studio portrait, 2048 × 2560 | 588 KB, 36.1 dB | 710 KB, 37.0 | 930 KB, 38.1 | 1406 KB, 39.5 | 3095 KB, 40.9 |
| Landscape with a smooth sky, 2048 × 2048 | 132 KB, 46.3 | 151 KB, 47.2 | 202 KB, 48.2 | 375 KB, 49.4 | 1052 KB, 51.2 |
| Product on white, 2048 × 1536 | 237 KB, 43.1 | 296 KB, 44.3 | 391 KB, 45.9 | 587 KB, 48.5 | 1232 KB, 54.5 |

q85 is the web default (LightCraft's too), q90 for social uploads that recompress, q95 for a lab JPEG. q100 roughly
doubles the file for 1.4–6 dB. `--max-kb` takes the highest quality that fits; under quality 60 it warns, because a
smaller `--long-edge` keeps more quality per KB.

## Metadata: what each file carries

PhotoCraft copies the master's EXIF and XMP into a JPEG (APP1 segments) and a PNG (`eXIf` and an XMP `iTXt` chunk),
and only XMP into a TIFF (tag 700). It bakes the EXIF orientation into the pixels and resets the tag, so dropping EXIF
can't turn a photo. It also zeroes the pointer to the camera's thumbnail but copies the EXIF block as it was, so the
thumbnail of the unretouched, uncropped original (an 11 KB, 192 × 256 JPEG in one test) rides along unreferenced, and `file.fileInfo`
writes `--copyright` and `--author` into the XMP only, leaving the master's EXIF Copyright and Artist beside them.
`deliver.py` rewrites each file afterwards, in place (`--metadata`):

| Mode | Default for | The file then carries |
|---|---|---|
| `copyright` | screen presets | EXIF with only Artist and Copyright, XMP with only dc:creator and dc:rights: `--author` / `--copyright`, else the master's own. No GPS, no thumbnail, no camera data (a web JPEG's EXIF went from 12 269 bytes to 66) |
| `all` | print, archive | everything, minus every JPEG inside the EXIF (the thumbnail, referenced or not, and maker-note previews) and, on screen files or with `--strip-gps`, the GPS position in EXIF and XMP. `--author` / `--copyright` replace the EXIF Artist / Copyright as well, so EXIF and XMP agree |
| `none` | | no EXIF and no XMP; the colour profile stays |

`--keep-gps` keeps the position on screen files in `all` mode; `--strip-gps` removes it from print and archive files
too (a TIFF's XMP included: nothing of it is left in the file). Each file is read back afterwards, and a GPS entry,
a thumbnail or two different notices left in it is a warning. Checked with an independent EXIF and XMP reader on
masters with GPS in EXIF and in XMP, in both byte orders, with a camera thumbnail and with an old copyright notice.
macOS (`sips`, Finder) shows the EXIF artist only when the camera make or model is there too, so it shows none for a
`copyright`-mode file; the XMP creator is there for Lightroom, Bridge and the web.

## PhotoCraft specifics

- **JPEG halves the colour resolution (4:2:0) at every quality**, through `--quality 1..100` and `file.saveACopy`'s
  0..12 alike (Photoshop switches to full colour resolution from quality 7 of 12). Fine saturated detail (red text
  on blue, tight coloured fabric patterns, graphics) belongs in a PNG (`--format png`) or a TIFF.
- **TIFF writes no EXIF**, only XMP (with the ppi, compressed with Deflate): an archive of a layered master also gets
  a copy of the master; from a JPEG master the original file keeps the camera data.
- **The writers can drop a master's own profile.** A scan tagged with a compact v4 "sRGB IEC61966-2.1" profile
  (not PhotoCraft's built-in one of the same name) came out as an untagged TIFF and JPEG. So `keep` assigns the
  master's built-in twin (sRGB, Display P3, Adobe RGB-, ProPhoto-compatible, Rec. 2020, Gray Gamma 2.2: the same numbers, 0
  levels of difference over 8 MP), an untagged master is tagged sRGB, which is how it was shown, and any file that
  still comes out without a profile is warned about: viewers would guess its colours.
- **The gamut warning measures what a conversion will lose**: before converting, `view.gamutWarning {"on": true,
  "profile": "srgb"}` gives the share of pixels more than delta E 4 outside the target (a view setting; the exported
  pixels are unchanged, checked). A saturated Display P3 portrait read 7.1 % outside sRGB (warned above 3 %) and 0.4 %
  outside Adobe RGB. The print preset also lists the share outside a synthetic press CMYK, for information only: inkjet
  and lab printers hold far more, and an ordinary portrait read 52 % there.
- `image.crop` with `targetWidth` / `targetHeight` crops and resizes in one step, exactly to the size asked.
- `image.imageSize {"resolution": 300, "resample": "none"}` changes only the ppi tag.

## Tuning and false hits

| You see | Cause | Fix |
|---|---|---|
| Light or dark rims along edges at 100 % | Too much sharpening for this master (already crisp) | `--strength low`, or `--sharpen none` and look again |
| Soft at 100 % | A soft master, or barely reduced (no screen sharpening below 1.25×) | `--strength high`; capture sharpening belongs in the master |
| An Instagram or story file smaller than asked | The master has too few pixels for that crop | A wider `--focus` crop can't help: `--upscale` (say it's enlarged), or deliver it smaller |
| The crop cuts the subject | The aspect crop is centred | `--focus X,Y` on the subject, in the master's pixels |
| Colours flatter than in the master | A wide-gamut master converted to sRGB (`outOfGamut%` over 3) | `--profile p3` where the platform shows Display P3; or tame those colours in the master |
| `--max-kb` warns of a low quality | Too many pixels for the limit | A smaller `--long-edge` |
| The GPS position is still in a file | `--keep-gps`, or a print or archive file | `--strip-gps` |
| A screen file lost its camera data | `copyright` metadata, the screen default | `--metadata all` (still no thumbnail, no GPS unless `--keep-gps`) |
| Preview or Finder shows no author | macOS shows the EXIF artist only with a camera make or model | It's in the EXIF and the XMP; `--metadata all` keeps the camera tags |
| The archive TIFF has no camera data | PhotoCraft's TIFF writes no EXIF | A layered master's copy keeps it; else the original file |
| "no colour profile embedded" | The master's profile has no built-in twin (a camera or scanner profile) | Deliver it converted: `--profile srgb` (screen) or `adobe-rgb` (print, archive) |
| "a screen file in Display P3" | `--profile keep` reached a screen preset of the run | Run the screen presets without it (sRGB is their default) |
| An archive copy named `-master-2` | The master changed since the last delivery | Expected: the earlier copy stays as delivered |
| The proof shows the wrong part of the photo | No face found, or the highest skin isn't the subject | `--proof-at X,Y` in the master's pixels |
| "the copyright … looks like a camera's name" | The master's EXIF held the camera model, or nothing usable | `--copyright "© Name 2026" --author "Name"` |
| Red text or fine coloured patterns smear in the JPEG | 4:2:0 at every quality | `--format png`, or a TIFF |
| A print lab rejects the TIFF | It wants 8-bit sRGB JPEG | `--preset print --format jpg --bits 8 --profile srgb --quality 95` |
