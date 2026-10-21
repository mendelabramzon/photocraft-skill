#!/usr/bin/env python3
"""Export a finished master (a layered PSD or .pcraft, a TIFF, a JPEG) to the files a client or a platform gets:
resized, output-sharpened for where it will be seen, converted to the right colour space, named, and checked.

Output sharpening is a separate step from capture sharpening: it compensates for the resampling and for the medium,
so it is applied last, at the output size, and judged at 100 % of the output. Measured on a slanted edge with a
camera's softness and capture sharpening (MTF at a quarter cycle per pixel, PhotoCraft's bicubic downscale): the
master reads 0.40; reduced 1.5x it reads 0.70, 2x 0.81, 3x 0.88, 4x 0.90, because the more a photo is reduced the
less of its capture softness is left. So screen sharpening (Unsharp Mask, radius 0.6 px) gets weaker with the
reduction: amount 100 / (factor - 0.5), between 20 and 100, which brought every factor to 0.93-1.00 with 6.4-8.7 %
overshoot; none below a factor of 1.25. Print sharpening is stronger, because ink spread and paper soften it again:
glossy radius 0.8, amount 100; matte radius 1.0, amount 150 (threshold 2, at 300 ppi; the radius scales with the
ppi). On screen at 100 % print sharpening looks too strong by design; proof it on the paper.

Screen files are converted (not assigned) to sRGB, 8-bit: browsers and phones assume sRGB, and converting keeps the
colours while assigning would change them. Print files keep 16 bits and go to Adobe RGB unless the lab asks for
sRGB. Before each conversion PhotoCraft's gamut warning measures how much of the photo the target can't hold (delta
E over 4): over 3 % is reported, since those colours flatten (a saturated Display P3 portrait: 7.1 % outside sRGB,
0.4 % outside Adobe RGB); for print the press CMYK share is listed for information only.

Metadata: PhotoCraft carries the master's EXIF (camera, GPS, the camera's thumbnail of the original) and XMP into a
JPEG and a PNG, and XMP alone into a TIFF. Each file is then tidied in place (--metadata):
  copyright  (screen presets) EXIF and XMP rebuilt with only the creator and the copyright notice: --author and
             --copyright, else the master's own. No GPS, no thumbnail of the unretouched original, no camera data.
  all        (print, archive) everything kept except the EXIF thumbnail; the GPS position (EXIF and XMP) goes from
             screen files, or anywhere with --strip-gps; --author / --copyright replace the EXIF Artist / Copyright too,
             so EXIF and XMP agree. The camera's maker notes stay (some hold a preview of the original).
  none       no EXIF and no XMP at all (the colour profile stays).

  deliver.py MASTER OUTDIR [--preset web|instagram|square|story|email|proof|print|archive ...]
             [--long-edge N | --size WxH | --print-size 8x10in|20x30cm] [--ppi 300] [--focus X,Y]
             [--sharpen none|screen|glossy|matte] [--strength low|standard|high] [--quality Q] [--max-kb N]
             [--profile srgb|adobe-rgb|p3|keep] [--bits 8|16] [--format jpg|tif|png] [--name "{name}-{preset}"]
             [--metadata copyright|all|none] [--author TEXT] [--copyright TEXT] [--keep-gps | --strip-gps]
             [--watermark TEXT] [--upscale] [--overwrite] [--proof PATH|none] [--proof-at X,Y]

Presets (the numbers LightCraft's export recipes use where both have one):
  web        long edge 2048, JPEG quality 85, sRGB, screen sharpening
  instagram  1080 x 1350 (4:5 portrait crop; --focus X,Y centres it), quality 90, sRGB, screen
  square     1080 x 1080, quality 90;   story  1080 x 1920 (9:16), quality 90
  email      long edge 1800, JPEG under 500 KB (the highest quality that fits), sRGB, screen
  proof      long edge 1600, quality 80, sRGB, screen; --watermark TEXT (bottom right, 40 %) goes on every screen file
  print      16-bit TIFF, Adobe RGB, 300 ppi, glossy sharpening (--sharpen matte for matte paper); --print-size gives
             the pixels (inches or cm x ppi, cropped to the print's aspect); without it the full size at 300 ppi
  archive    full size, 16-bit TIFF in the master's own profile, no sharpening, plus a copy of a layered master
PhotoCraft's writers can drop a master's own profile (a scan's compact v4 sRGB came out untagged), so --profile keep
(the archive's) assigns the master's built-in twin, same numbers. A file without a profile is a warning.
Options override every preset of the run (run it again for different overrides; --profile keep on a screen preset
leaves it in a wide-gamut master's space, with a warning); several --preset make several files from one master. --long-edge resizes the presets sized by their long edge (web, email, proof, archive);
--size WxH sets any preset's size and aspect; --max-kb applies to JPEGs only.
Names: {name} (the master's), {preset}, {w}, {h}, {date}; an existing file gets -2, -3 unless --overwrite (never the
master itself). Each output is read back and checked (size, ppi, bits, embedded profile, file size, what metadata
it carries; a copyright or artist that is missing, a placeholder or the camera's name is a warning: pass --copyright
and --author). The proof sheet, a 360 px crop at 100 % of every output from the same place, goes beside the folder
(<outdir>-proof.png, or --proof PATH; never among the client's files): at --proof-at X,Y in the master, else the
most detailed part of the face (the highest skin region), else of the middle third.
"""
import argparse
import datetime
import filecmp
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgops
import pc
import pngio
from cutout_check import icc_description

PRESETS = {
    "web": {"long": 2048, "format": "jpg", "quality": 85, "profile": "srgb", "sharpen": "screen"},
    "instagram": {"size": [1080, 1350], "format": "jpg", "quality": 90, "profile": "srgb", "sharpen": "screen"},
    "square": {"size": [1080, 1080], "format": "jpg", "quality": 90, "profile": "srgb", "sharpen": "screen"},
    "story": {"size": [1080, 1920], "format": "jpg", "quality": 90, "profile": "srgb", "sharpen": "screen"},
    "email": {"long": 1800, "format": "jpg", "quality": 85, "maxKb": 500, "profile": "srgb", "sharpen": "screen"},
    "proof": {"long": 1600, "format": "jpg", "quality": 80, "profile": "srgb", "sharpen": "screen"},
    "print": {"format": "tif", "bits": 16, "profile": "adobe-rgb", "ppi": 300, "sharpen": "glossy"},
    "archive": {"format": "tif", "bits": 16, "profile": "keep", "ppi": None, "sharpen": "none", "copyMaster": True},
}
SCREEN = ("web", "instagram", "square", "story", "email", "proof")
PROFILES = {"srgb": "srgb", "adobe-rgb": "adobe-rgb-compat", "p3": "display-p3"}
STRENGTH = {"low": 0.5, "standard": 1.0, "high": 1.5}
NAME_FIELDS = ("name", "preset", "w", "h", "date")
CLI = None


def cli(*args):
    r = subprocess.run([CLI] + [str(a) for a in args], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"error: photocraft-cli {' '.join(map(str, args))[:240]}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def info(path):
    return json.loads(cli("info", path, "--compact"))


def sharpening(kind, factor, strength, ppi):
    """Unsharp Mask params for the output, or None (see the module docstring for the measurements)."""
    k = STRENGTH[strength]
    if kind == "screen":
        if factor < 1.25:
            return None  # hardly reduced: the master's own capture sharpening stands
        return {"amount": round(k * min(100, max(20, 100 / (factor - 0.5)))), "radius": 0.6, "threshold": 0}
    if kind in ("glossy", "matte"):
        r, am = (0.8, 100) if kind == "glossy" else (1.0, 150)
        return {"amount": round(k * am), "radius": max(0.1, round(r * (ppi or 300) / 300, 2)), "threshold": 2}
    return None


def parse_size(s):
    w, h = (int(v) for v in s.lower().split("x"))
    return [w, h]


def parse_print(s):
    """'8x10in' / '20x30cm' -> (short, long) in inches."""
    s = s.lower().replace(" ", "")
    unit = 2.54 if s.endswith("cm") else 1.0
    a, b = (float(v) for v in s.rstrip("incm").split("x"))
    return sorted((a / unit, b / unit))


def fit_crop(W, H, aspect, focus):
    """The largest rectangle of aspect w/h inside W x H, centred on focus (clamped inside): (x, y, w, h)."""
    if W / H > aspect:
        ch, cw = H, H * aspect
    else:
        cw, ch = W, W / aspect
    cw, ch = int(cw), int(ch)
    fx, fy = focus
    x = int(round(min(max(0, fx - cw / 2), W - cw)))
    y = int(round(min(max(0, fy - ch / 2), H - ch)))
    return x, y, cw, ch


# ---------------------------------------------------------------- metadata: TIFF structures (EXIF blocks, TIFF files)

TIFF_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
ARTIST, COPYRIGHT, XMP_TAG, ICC_TAG, GPS_IFD = 0x013B, 0x8298, 700, 34675, 0x8825
XMP_NS = b"http://ns.adobe.com/xap/1.0/\0"
XMP_EXT = b"http://ns.adobe.com/xmp/extension/\0"


class Tiff:
    """A TIFF structure to read and patch: an EXIF payload in memory, or a TIFF file on disk (patched in place, new
    data appended at its end, so no strip or other offset ever moves)."""

    def __init__(self, data=None, path=None):
        self.f = open(path, "r+b") if path else None
        self.t = None if path else bytearray(data)
        self.bo = "<" if self.read(0, 2) == b"II" else ">"

    def read(self, o, n):
        if self.f:
            self.f.seek(o)
            return self.f.read(n)
        return bytes(self.t[o:o + n])

    def write(self, o, b):
        if self.f:
            self.f.seek(o)
            self.f.write(b)
        else:
            self.t[o:o + len(b)] = b

    def append(self, b):
        """Word-aligned offset where b now sits."""
        if self.f:
            end = self.f.seek(0, 2)
            if end % 2:
                self.f.write(b"\0")
                end += 1
            self.f.write(b)
            return end
        if len(self.t) % 2:
            self.t += b"\0"
        o = len(self.t)
        self.t += b
        return o

    def size(self):
        return self.f.seek(0, 2) if self.f else len(self.t)

    def u16(self, o):
        return struct.unpack(self.bo + "H", self.read(o, 2))[0]

    def u32(self, o):
        return struct.unpack(self.bo + "I", self.read(o, 4))[0]

    def entries(self, off):
        """[(entry offset, tag, type, count)] of the IFD at off."""
        if off + 2 > self.size():
            return []
        return [(off + 2 + 12 * k,) + struct.unpack(self.bo + "HHI", self.read(off + 2 + 12 * k, 8))
                for k in range(self.u16(off))]

    def span(self, e, typ, cnt):
        """(offset, size) of an entry's value: inline in the entry, or where it points."""
        size = TIFF_SIZES.get(typ, 1) * cnt
        return (e + 8, size) if size <= 4 else (self.u32(e + 8), size)

    def find(self, tag, off=None):
        for e, t, typ, cnt in self.entries(self.u32(4) if off is None else off):
            if t == tag:
                return e, typ, cnt
        return None

    def text(self, tag):
        hit = self.find(tag)
        if not hit or hit[1] != 2:
            return None
        o, s = self.span(*hit)
        return self.read(o, s).split(b"\0")[0].decode("utf-8", "replace").strip() or None

    def blob(self, tag):
        hit = self.find(tag)
        if not hit:
            return None
        o, s = self.span(*hit)
        return self.read(o, s)

    def gps_entries(self):
        hit = self.find(GPS_IFD)
        return len(self.entries(self.u32(hit[0] + 8))) if hit else 0

    def strip_gps(self):
        """Erase the position: zero the values the GPS entries point to, then the GPS directory itself (count 0, no
        next directory), which readers take as "no position". Returns the entries erased."""
        hit = self.find(GPS_IFD)
        if not hit:
            return 0
        g = self.u32(hit[0] + 8)
        ents = self.entries(g)
        for e, t, typ, cnt in ents:
            o, s = self.span(e, typ, cnt)
            if s > 4 and o + s <= self.size():
                self.write(o, bytes(s))
        self.write(g, bytes(2 + 12 * len(ents) + 4))
        return len(ents)

    def thumbnail(self):
        """(IFD1 offset, where the 'next IFD' pointer after IFD0 sits) or None: the camera's thumbnail of the original."""
        ifd0 = self.u32(4)
        p = ifd0 + 2 + 12 * self.u16(ifd0)
        nxt = self.u32(p) if p + 4 <= self.size() else 0
        return (nxt, p) if nxt and nxt + 2 <= self.size() else None

    def jpegs(self):
        """(start, end) of every JPEG stream inside an EXIF payload: the thumbnail, or a preview in the maker notes,
        referenced or not. PhotoCraft zeroes the pointer to the thumbnail but copies the EXIF block as it was, so
        the camera's picture of the original (11 KB, 192 x 256 in one test) is still there, just unreferenced."""
        if self.f:
            return []
        out, i = [], self.t.find(b"\xff\xd8\xff")
        while i >= 0:
            j = self.t.find(b"\xff\xd9", i + 4)
            nxt = self.t[i + 3] if i + 3 < len(self.t) else 0
            if j < 0:
                break
            if (0xE0 <= nxt <= 0xEF or nxt in (0xDB, 0xC4, 0xC0, 0xC2, 0xFE)) and j - i > 200:
                out.append((i, j + 2))
                i = self.t.find(b"\xff\xd8\xff", j + 2)
            else:
                i = self.t.find(b"\xff\xd8\xff", i + 3)
        return out

    def drop_thumbnail(self):
        found = False
        for s, e in self.jpegs():
            self.write(s, bytes(e - s))
            found = True
        hit = self.thumbnail()
        if not hit:
            return found
        nxt, p = hit
        ents = self.entries(nxt)
        found = {t: self.u32(e + 8) for e, t, typ, cnt in ents if t in (0x0201, 0x0202, 0x0111, 0x0117) and cnt == 1}
        for start, length in ((0x0201, 0x0202), (0x0111, 0x0117)):  # a JPEG thumbnail, or an uncompressed one
            if start in found and length in found and found[start] + found[length] <= self.size():
                self.write(found[start], bytes(found[length]))
        for e, t, typ, cnt in ents:
            o, s = self.span(e, typ, cnt)
            if s > 4 and o + s <= self.size():
                self.write(o, bytes(s))
        self.write(nxt, bytes(2 + 12 * len(ents) + 4))
        self.write(p, bytes(4))
        return True

    def set(self, values):
        """Set IFD0 tags {tag: (type, value bytes)}: an existing entry gets the new value (the old one zeroed, the new
        one appended); missing tags make IFD0 move to the end with them added, in tag order."""
        ifd0 = self.u32(4)
        ents = self.entries(ifd0)
        have = {t: (e, typ, cnt) for e, t, typ, cnt in ents}

        def place(typ, b):
            cnt = len(b) // TIFF_SIZES.get(typ, 1)
            val = b.ljust(4, b"\0") if len(b) <= 4 else struct.pack(self.bo + "I", self.append(b))
            return struct.pack(self.bo + "HI", typ, cnt) + val

        for t in values:  # the old values go, wherever they were
            if t in have:
                o, s = self.span(*have[t])
                if s > 4:
                    self.write(o, bytes(s))
        if all(t in have for t in values):
            for t, (typ, b) in values.items():
                self.write(have[t][0] + 2, place(typ, b))
            return
        rows = {t: self.read(e + 2, 10) for e, t, typ, cnt in ents if t not in values}
        rows.update({t: place(typ, b) for t, (typ, b) in values.items()})
        nxt = self.u32(ifd0 + 2 + 12 * len(ents))
        new = self.append(struct.pack(self.bo + "H", len(rows))
                          + b"".join(struct.pack(self.bo + "H", t) + rows[t] for t in sorted(rows))
                          + struct.pack(self.bo + "I", nxt))
        self.write(ifd0, bytes(2 + 12 * len(ents) + 4))
        self.write(4, struct.pack(self.bo + "I", new))

    def close(self):
        if self.f:
            self.f.close()


def minimal_tiff(values):
    """An EXIF payload holding only these IFD0 strings ({tag: text}), or None when there are none."""
    tags = sorted((t, v.encode("utf-8") + b"\0") for t, v in values.items() if v)
    if not tags:
        return None
    head = bytearray(b"II*\0" + struct.pack("<IH", 8, len(tags)))
    data, base = bytearray(), 8 + 2 + 12 * len(tags) + 4
    for t, b in tags:
        if len(b) <= 4:
            head += struct.pack("<HHI", t, 2, len(b)) + b.ljust(4, b"\0")
        else:
            head += struct.pack("<HHII", t, 2, len(b), base + len(data))
            data += b + (b"\0" if len(b) % 2 else b"")
    return bytes(head + b"\0\0\0\0" + data)


# ---------------------------------------------------------------- metadata: XMP

GPS_ATTR = re.compile(r'\s[\w.-]+:GPS[A-Za-z]*\s*=\s*("[^"]*"|\'[^\']*\')')
GPS_ELEM = re.compile(r'<([\w.-]+:GPS[A-Za-z]*)\b[^>]*?(?:/>|>.*?</\1\s*>)', re.S)
THUMBS = re.compile(r'<([\w.-]+:Thumbnails)\b[^>]*?(?:/>|>.*?</\1\s*>)', re.S)


def xmp_gps(x):
    return len(GPS_ATTR.findall(x)) + len(GPS_ELEM.findall(x)) if x else 0


def xmp_value(x, prop):
    """The first value of dc:creator / dc:rights (element or attribute form)."""
    if not x:
        return None
    m = re.search(r'<%s\b[^>]*>.*?<rdf:li[^>]*>(.*?)</rdf:li>' % re.escape(prop), x, re.S)
    if not m:
        m = re.search(r'\s%s\s*=\s*"([^"]*)"' % re.escape(prop), x)
    return (html.unescape(m.group(1)).strip() or None) if m else None


def minimal_xmp(author, rights):
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = (f"<dc:creator><rdf:Seq><rdf:li>{esc(author)}</rdf:li></rdf:Seq></dc:creator>" if author else "") + \
           (f'<dc:rights><rdf:Alt><rdf:li xml:lang="x-default">{esc(rights)}</rdf:li></rdf:Alt></dc:rights>' if rights else "")
    if not body:
        return None
    return ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">' + body + "</rdf:Description></rdf:RDF></x:xmpmeta>\n"
            '<?xpacket end="w"?>')


EMPTY_XMP = '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/"/><?xpacket end="w"?>'


def plan_metadata(tif, xmp, mode, strip_gps, author, rights):
    """What a file's EXIF (a Tiff or None) and XMP (text or None) become. Returns (exif bytes or None or 'same',
    xmp text or None, report); 'same' means the Tiff was patched in place."""
    old_author = (tif.text(ARTIST) if tif else None) or xmp_value(xmp, "dc:creator")
    old_rights = (tif.text(COPYRIGHT) if tif else None) or xmp_value(xmp, "dc:rights")
    rep = {"mode": mode, "gpsRemoved": 0, "thumbnailRemoved": False}
    if mode in ("copyright", "none"):
        rep["gpsRemoved"] = (tif.gps_entries() if tif else 0) + xmp_gps(xmp)
        rep["thumbnailRemoved"] = bool(tif and (tif.thumbnail() or tif.jpegs()))
        if mode == "none":
            return None, None, rep
        au, ri = author or old_author, rights or old_rights
        return minimal_tiff({ARTIST: au, COPYRIGHT: ri}), minimal_xmp(au, ri), rep
    if tif:
        rep["thumbnailRemoved"] = tif.drop_thumbnail()
        if strip_gps:
            rep["gpsRemoved"] += tif.strip_gps()
        new = {t: (2, v.encode("utf-8") + b"\0") for t, v in ((ARTIST, author), (COPYRIGHT, rights)) if v}
        if new:
            tif.set(new)
    if xmp:
        if strip_gps:
            n = xmp_gps(xmp)
            xmp = GPS_ELEM.sub("", GPS_ATTR.sub("", xmp))
            rep["gpsRemoved"] += n
        xmp = THUMBS.sub("", xmp)
    return "same", xmp, rep


def jpeg_segments(d):
    """([(marker, payload)] up to the scan, the rest from SOS on)."""
    segs, pos = [], 2
    while pos + 4 <= len(d) and d[pos] == 0xFF and d[pos + 1] != 0xDA:
        ln = struct.unpack(">H", d[pos + 2:pos + 4])[0]
        segs.append((d[pos + 1], d[pos + 4:pos + 2 + ln]))
        pos += 2 + ln
    return segs, d[pos:]


def png_chunks(d):
    out, pos = [], 8
    while pos + 8 <= len(d):
        ln, typ = struct.unpack(">I4s", d[pos:pos + 8])
        out.append((typ, d[pos + 8:pos + 8 + ln]))
        pos += 12 + ln
    return out


def png_xmp(data):
    """The text of an iTXt chunk if it is XMP, else None."""
    if not data.startswith(b"XML:com.adobe.xmp\0"):
        return None
    rest = data[len(b"XML:com.adobe.xmp\0"):]
    comp, rest = rest[0], rest[2:]
    rest = rest[rest.index(b"\0") + 1:]  # language
    rest = rest[rest.index(b"\0") + 1:]  # translated keyword
    return (zlib.decompress(rest) if comp else rest).decode("utf-8", "replace")


def png_chunk(typ, data):
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)


def tidy_metadata(path, fmt, mode, strip_gps, author, rights):
    """Rewrite a delivered file's EXIF and XMP for --metadata (see the module docstring). Returns the report."""
    if fmt == "tif":
        # PhotoCraft's TIFF has no EXIF, only XMP (tag 700); the notices also go in the TIFF Artist / Copyright tags
        tif = Tiff(path=path)
        try:
            raw = tif.blob(XMP_TAG)
            xmp = raw.decode("utf-8", "replace").rstrip("\0") if raw else None
            rep = {"mode": mode, "gpsRemoved": 0, "thumbnailRemoved": False}
            if mode in ("copyright", "none") or strip_gps:
                rep["gpsRemoved"] = tif.strip_gps() + xmp_gps(xmp)
            if mode == "copyright":
                au = author or tif.text(ARTIST) or xmp_value(xmp, "dc:creator")
                ri = rights or tif.text(COPYRIGHT) or xmp_value(xmp, "dc:rights")
                new_xmp = minimal_xmp(au, ri)
            elif mode == "none":
                au = ri = new_xmp = None
            else:
                au, ri = author, rights
                new_xmp = GPS_ELEM.sub("", GPS_ATTR.sub("", xmp)) if xmp and strip_gps else xmp
            vals = {t: (2, v.encode("utf-8") + b"\0") for t, v in ((ARTIST, au), (COPYRIGHT, ri)) if v}
            if new_xmp != xmp:
                vals[XMP_TAG] = (1, (new_xmp or EMPTY_XMP).encode("utf-8"))
            if vals:
                tif.set(vals)
        finally:
            tif.close()
        return rep
    d = open(path, "rb").read()
    if fmt == "jpg":
        segs, rest = jpeg_segments(d)
        exif = next((p[6:] for m, p in segs if m == 0xE1 and p[:6] == b"Exif\0\0"), None)
        xmp = next((p[len(XMP_NS):].decode("utf-8", "replace") for m, p in segs if m == 0xE1 and p.startswith(XMP_NS)), None)
    else:
        chunks = png_chunks(d)
        exif = next((c for t, c in chunks if t == b"eXIf"), None)
        xmp = next((png_xmp(c) for t, c in chunks if t == b"iTXt" and png_xmp(c) is not None), None)
    tif = Tiff(exif) if exif else None
    new_exif, new_xmp, rep = plan_metadata(tif, xmp, mode, strip_gps, author, rights)
    if new_exif == "same":
        new_exif = bytes(tif.t) if tif else None
    if fmt == "jpg":
        if new_exif and len(new_exif) + 8 > 65535:  # a JPEG segment can't hold it: keep only the notices
            new_exif = minimal_tiff({ARTIST: tif.text(ARTIST), COPYRIGHT: tif.text(COPYRIGHT)})
            rep["warning"] = "the EXIF grew past a JPEG segment: only the creator and copyright kept"
        seg = lambda m, p: b"\xff" + bytes([m]) + struct.pack(">H", len(p) + 2) + p
        drop = lambda m, p: m == 0xE1 and (p[:6] == b"Exif\0\0" or p.startswith(XMP_NS) or
                                           (p.startswith(XMP_EXT) and mode != "all")) or (m == 0xED and mode != "all")
        out = bytearray(b"\xff\xd8")
        out += b"".join(seg(m, p) for m, p in segs if m == 0xE0)
        if new_exif:
            out += seg(0xE1, b"Exif\0\0" + new_exif)
        if new_xmp:
            out += seg(0xE1, XMP_NS + new_xmp.encode("utf-8"))
        out += b"".join(seg(m, p) for m, p in segs if m != 0xE0 and not drop(m, p))
        open(path, "wb").write(bytes(out) + rest)
    else:
        out = bytearray(d[:8])
        placed = False
        for t, c in chunks:
            if t == b"eXIf" or (t == b"iTXt" and png_xmp(c) is not None):
                continue
            if t == b"IDAT" and not placed:  # eXIf and XMP go before the image data
                if new_exif:
                    out += png_chunk(b"eXIf", new_exif)
                if new_xmp:
                    out += png_chunk(b"iTXt", b"XML:com.adobe.xmp\0\0\0\0\0" + new_xmp.encode("utf-8"))
                placed = True
            out += png_chunk(t, c)
        open(path, "wb").write(bytes(out))
    return rep


def inspect_metadata(path, fmt):
    """What a delivered file carries: EXIF tags of note, GPS entries (EXIF and XMP), a thumbnail, the notices."""
    if fmt == "tif":
        tif = Tiff(path=path)
        try:
            raw = tif.blob(XMP_TAG)
            xmp = raw.decode("utf-8", "replace") if raw else None
            return {"exif": False, "gps": tif.gps_entries() + xmp_gps(xmp), "thumbnail": False,
                    "artist": tif.text(ARTIST), "copyright": tif.text(COPYRIGHT),
                    "xmpCreator": xmp_value(xmp, "dc:creator"), "xmpRights": xmp_value(xmp, "dc:rights")}
        finally:
            tif.close()
    d = open(path, "rb").read()
    if fmt == "jpg":
        segs, _ = jpeg_segments(d)
        exif = next((p[6:] for m, p in segs if m == 0xE1 and p[:6] == b"Exif\0\0"), None)
        xmp = next((p[len(XMP_NS):].decode("utf-8", "replace") for m, p in segs if m == 0xE1 and p.startswith(XMP_NS)), None)
    else:
        chunks = png_chunks(d)
        exif = next((c for t, c in chunks if t == b"eXIf"), None)
        xmp = next((png_xmp(c) for t, c in chunks if t == b"iTXt" and png_xmp(c) is not None), None)
    tif = Tiff(exif) if exif else None
    return {"exif": bool(tif), "gps": (tif.gps_entries() if tif else 0) + xmp_gps(xmp),
            "thumbnail": bool(tif and (tif.thumbnail() or tif.jpegs())), "artist": tif.text(ARTIST) if tif else None,
            "copyright": tif.text(COPYRIGHT) if tif else None,
            "xmpCreator": xmp_value(xmp, "dc:creator"), "xmpRights": xmp_value(xmp, "dc:rights")}


def tiff_profile(path):
    """The ICC description embedded in a TIFF (tag 34675), '' if none."""
    tif = Tiff(path=path)
    try:
        prof = tif.blob(ICC_TAG)
    finally:
        tif.close()
    if not prof or len(prof) < 132:
        return ""
    for j in range(struct.unpack(">I", prof[128:132])[0]):
        sig, so, sz = struct.unpack(">4sII", prof[132 + 12 * j:144 + 12 * j])
        if sig == b"desc":
            t = prof[so:so + sz]
            if t[:4] == b"desc":
                return t[12:12 + struct.unpack(">I", t[8:12])[0]].split(b"\0")[0].decode("latin-1")
            if t[:4] == b"mluc":
                ln, sof = struct.unpack(">II", t[20:28])
                return t[sof:sof + ln].decode("utf-16-be", "replace")
    return ""


# ---------------------------------------------------------------- the 100 % proof crop

def proof_point(path, tmp):
    """Where the proof crops go, in this file's pixels, and why: the most detailed window of the highest skin region
    (in a portrait the face, so the eyes; not the hands or the embroidered patch on a sleeve), else the most detailed
    part of the middle third. Found on a copy the CLI shrinks to about 300 px, with windows 12 % of its long side."""
    w, h = (lambda d: (d["width"], d["height"]))(info(path))
    k = max(1, max(w, h) // 300)
    small = os.path.join(tmp, "point-small.png")
    cli("run", path, "--cmd", "layer.flattenImage", "--cmd", "image.imageSize", "--params",
        json.dumps({"width": max(1, w // k), "resample": "bilinear"}), "--out", small)
    sw, sh, P = pngio.read(small)
    px = [q for row in P for q in row]
    L = [imgops.lum(*q) for q in px]
    g = [abs(L[i + 1] - L[i]) + abs(L[i + sw] - L[i]) if (i % sw) < sw - 1 and i // sw < sh - 1 else 0.0
         for i in range(sw * sh)]
    skin = [0.0] * (sw * sh)  # skin of every complexion sits near the vectorscope's skin line, moderately saturated
    for i, q in enumerate(px):
        ang, sat = imgops.vectorscope(*q)
        if 100 <= ang <= 140 and 8 <= sat <= 70 and 40 <= L[i] <= 235:
            skin[i] = 1.0
    r = max(1, int(0.06 * max(sw, sh)))
    m, s = imgops.box(g, sw, sh, r), imgops.box(skin, sw, sh, r)
    inner = [i for i in range(sw * sh) if r <= i % sw < sw - r and r <= i // sw < sh - r] or [(sh // 2) * sw + sw // 2]
    # the face: the highest skin region of some size (hands and arms sit lower), then its most detailed window
    blobs = [c for c in imgops.components(skin, sw, sh) if len(c) >= 0.005 * sw * sh]
    cand = []
    if blobs:
        face = min(blobs, key=lambda c: sum(i // sw for i in c) / len(c))
        fx0, fx1 = min(i % sw for i in face), max(i % sw for i in face)
        fy0, fy1 = min(i // sw for i in face), max(i // sw for i in face)
        cand = [i for i in inner if fx0 <= i % sw <= fx1 and fy0 <= i // sw <= fy1 and s[i] >= 0.3]
    if cand:
        best, how = max(cand, key=m.__getitem__), "skin"
    else:
        mid = [i for i in inner if sw / 3 <= i % sw <= 2 * sw / 3 and sh / 3 <= i // sw <= 2 * sh / 3] or inner
        best, how = max(mid, key=m.__getitem__), "middle third"
    return [(best % sw + 0.5) * w / sw, (best // sw + 0.5) * h / sh], how


def detail_tile(path, tmp, tag, at, side=360):
    """A side x side crop at 100 % of a file, centred on `at` (its pixels, clamped inside), cut by the CLI: a big
    archive TIFF is never decoded in Python. Returns (tile path, (x, y) of the tile)."""
    w, h = (lambda d: (d["width"], d["height"]))(info(path))
    tw_, th_ = min(side, w), min(side, h)
    x = int(max(0, min(w - tw_, at[0] - tw_ / 2)))
    y = int(max(0, min(h - th_, at[1] - th_ / 2)))
    tile = os.path.join(tmp, f"{tag}-tile.png")
    cli("run", path, "--cmd", "image.crop", "--params", json.dumps({"x": x, "y": y, "width": tw_, "height": th_}),
        "--out", tile)
    return tile, (x, y)


CAMERA_BRANDS = ("canon", "nikon", "sony", "fujifilm", "fuji", "hasselblad", "leica", "olympus", "om system",
                 "panasonic", "lumix", "pentax", "ricoh", "phase one", "sigma", "apple", "iphone", "samsung", "google",
                 "pixel", "huawei", "xiaomi", "dji", "gopro", "kodak", "minolta", "mamiya", "zeiss", "epson", "nokia")
PLACEHOLDERS = ("copyright", "unknown", "none", "n/a", "na", "owner", "(c)", "©", "c", "-", "default",
                "copyright owner", "your name", "all rights reserved", "photographer", "author", "artist", "user")


def suspect_notice(text, make, model):
    """Why a copyright or artist about to go out looks wrong, or None: missing, a placeholder, or the camera's name
    (a camera writes its model there, or software leaves it: a NASA portrait carried "Hasselblad H6D" as its
    copyright). Text with a copyright mark or a year is trusted."""
    if not text or not text.strip():
        return "missing"
    t = text.strip().lower()
    if t in PLACEHOLDERS:
        return "a placeholder"
    if re.search(r"©|\(c\)|copyright|\b(1[89]|20)\d\d\b|rights|public domain|creative commons|\bcc[ -]", t):
        return None
    for cam in (make, model):
        if cam and cam.strip() and (cam.strip().lower() in t or t in cam.strip().lower()):
            return "the camera's name"
    if re.search(r"\d", t) and any(re.search(r"\b%s\b" % re.escape(b), t) for b in CAMERA_BRANDS):
        return "a camera's name"  # a brand and a model number: "Hasselblad H6D", "NIKON D850", "iPhone 15 Pro"
    return None


def main():
    global CLI
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master"); ap.add_argument("outdir")
    ap.add_argument("--preset", action="append", choices=sorted(PRESETS), help="repeat for several files")
    ap.add_argument("--long-edge", type=int); ap.add_argument("--size", help="WxH in px (cropped to that aspect)")
    ap.add_argument("--print-size", help="e.g. 8x10in or 20x30cm: pixels = size x --ppi, cropped to the print's aspect")
    ap.add_argument("--ppi", type=float)
    ap.add_argument("--focus", help="X,Y in the master: centre of an aspect crop (default: the centre)")
    ap.add_argument("--sharpen", choices=["none", "screen", "glossy", "matte"])
    ap.add_argument("--strength", choices=sorted(STRENGTH), default="standard")
    ap.add_argument("--quality", type=int); ap.add_argument("--max-kb", type=int)
    ap.add_argument("--profile", choices=["srgb", "adobe-rgb", "p3", "keep"])
    ap.add_argument("--bits", type=int, choices=[8, 16]); ap.add_argument("--format", choices=["jpg", "tif", "png"])
    ap.add_argument("--name", default="{name}-{preset}")
    ap.add_argument("--metadata", choices=["copyright", "all", "none"],
                    help="default: copyright for screen presets, all for print and archive")
    ap.add_argument("--author"); ap.add_argument("--copyright")
    gps = ap.add_mutually_exclusive_group()
    gps.add_argument("--keep-gps", action="store_true", help="--metadata all on screen files: keep the GPS position")
    gps.add_argument("--strip-gps", action="store_true", help="also remove the GPS position from print and archive files")
    ap.add_argument("--watermark")
    ap.add_argument("--upscale", action="store_true", help="allow enlarging when the master has too few pixels")
    ap.add_argument("--overwrite", action="store_true", help="replace earlier deliverables of the same name (never the master)")
    ap.add_argument("--proof", help="where the 100 %% crops go (default: <outdir>-proof.png, beside the folder, never in it); "
                                    "'none' for no proof sheet")
    ap.add_argument("--proof-at", help="X,Y in the master: the crops are taken there (default: detail in skin, else the "
                                       "middle third)")
    a = ap.parse_args()
    presets = a.preset or ["web"]
    if a.print_size and "print" not in presets:
        ap.error("--print-size goes with --preset print")
    try:
        a.name.format(**{f: "x" for f in NAME_FIELDS})
    except (KeyError, IndexError, ValueError) as e:
        ap.error(f"--name {a.name!r}: {e}; the fields are " + ", ".join("{%s}" % f for f in NAME_FIELDS))
    CLI = str(pc.find_cli() or "")
    if not CLI:
        sys.exit("error: needs photocraft-cli (`pc.py cli-info` says which one)")
    master = os.path.abspath(os.path.expanduser(a.master))
    outdir = os.path.abspath(os.path.expanduser(a.outdir))
    proof_path = None if (a.proof or "").lower() == "none" else \
        os.path.abspath(os.path.expanduser(a.proof)) if a.proof else outdir.rstrip(os.sep) + "-proof.png"
    if proof_path and os.path.commonpath([proof_path, outdir]) == outdir:
        sys.exit("error: --proof goes outside the delivery folder: check files never sit among the client's files")
    proof_at = [float(v) for v in a.proof_at.split(",")] if a.proof_at else None
    os.makedirs(a.outdir, exist_ok=True)
    mi = info(master)
    W, H = mi["width"], mi["height"]
    base = os.path.splitext(os.path.basename(master))[0]
    layered = os.path.splitext(master)[1].lower() in (".psd", ".psb", ".pcraft")

    def is_master(path):  # the disk may be case-insensitive (macOS): compare files, not strings
        return os.path.exists(path) and os.path.samefile(path, master)

    def free_name(stem, ext):
        out = os.path.join(a.outdir, f"{stem}.{ext}")
        if is_master(out) or (os.path.exists(out) and not a.overwrite):
            n = 2
            while os.path.exists(os.path.join(a.outdir, f"{stem}-{n}.{ext}")):
                n += 1
            out = os.path.join(a.outdir, f"{stem}-{n}.{ext}")
        return out

    tmp = tempfile.mkdtemp(prefix="deliver-")
    outputs, tiles = [], []
    try:
        # the master's own camera and notices, once: a copyright that is really the camera's name gets caught
        probe = os.path.join(tmp, "master-meta.jpg")
        cli("run", master, "--cmd", "layer.flattenImage", "--cmd", "image.imageSize", "--params",
            json.dumps({"width": 64, "resample": "bilinear"}), "--out", probe, "--quality", 50)
        segs_, _ = jpeg_segments(open(probe, "rb").read())
        mexif = next((pl[6:] for mk, pl in segs_ if mk == 0xE1 and pl[:6] == b"Exif\0\0"), None)
        mt = Tiff(mexif) if mexif else None
        make, model = (mt.text(0x010F), mt.text(0x0110)) if mt else (None, None)
        # the master's own profile as one of PhotoCraft's builtins: a TIFF (and some JPEGs) keep only a builtin
        # profile, so a scan tagged with a compact v4 "sRGB IEC61966-2.1" came out of --profile keep untagged
        pinfo = {}
        for line in cli("run", master, "--cmd", "edit.profileInfo", "--params", json.dumps({"profile": "document"})).splitlines():
            if '"edit.profileInfo"' in line:
                pinfo = json.loads(line).get("result") or {}
        mprof = (pinfo.get("profile") or {}).get("description")
        builtins = {b["description"]: b["id"] for b in pinfo.get("builtins", [])}
        master_builtin = builtins.get(mprof) or next(
            (bid for key, bid in (("prophoto", "prophoto-compat"), ("romm", "prophoto-compat"), ("adobe rgb", "adobe-rgb-compat"),
                                  ("display p3", "display-p3"), ("2020", "rec2020"), ("srgb", "srgb"), ("gray gamma 2.2", "gray-gamma-2.2"))
             if mprof and key in mprof.lower() and bid in builtins.values()), None)
        how_at = "--proof-at"
        if proof_path and not proof_at:  # one place in the master, the same in every file, so they compare
            proof_at, how_at = proof_point(master, tmp)
        for preset in presets:
            p = dict(PRESETS[preset])
            for key, val in (("long", a.long_edge), ("quality", a.quality), ("maxKb", a.max_kb), ("profile", a.profile),
                             ("bits", a.bits), ("format", a.format), ("sharpen", a.sharpen), ("ppi", a.ppi)):
                if val is not None and (key != "long" or "size" not in p):
                    p[key] = val
            if a.size:
                p["size"] = parse_size(a.size)
                p.pop("long", None)
            fmt = p.get("format", "jpg")
            bits = 8 if fmt == "jpg" else p.get("bits", 16 if preset in ("print", "archive") else 8)
            screen = preset in SCREEN
            meta_mode = a.metadata or ("copyright" if screen else "all")
            strip_gps = a.strip_gps or (screen and not a.keep_gps)
            warnings = []
            steps = [("layer.flattenImage", {})]  # filters act on the active layer: the composite first
            focus = [float(v) for v in a.focus.split(",")] if a.focus else [W / 2, H / 2]
            x, y, cw, ch = 0, 0, W, H
            tw, th = W, H
            ppi = p.get("ppi")
            if a.print_size and preset == "print":
                short, long_ = parse_print(a.print_size)
                ppi = ppi or 300
                land = W >= H
                aspect = long_ / short if land else short / long_
                x, y, cw, ch = fit_crop(W, H, aspect, focus)
                tw, th = (round(long_ * ppi), round(short * ppi)) if land else (round(short * ppi), round(long_ * ppi))
                if tw > cw and not a.upscale:
                    eff = cw / (long_ if land else short)
                    warnings.append(f"the master has {cw} x {ch} px for this print: {eff:.{0 if eff >= 10 else 1}f} ppi at {a.print_size}; "
                                    "fine from about 240 ppi, else --upscale")
                    tw, th, ppi = cw, ch, round(eff, 1)
            elif p.get("size"):
                sw_, sh_ = p["size"]
                x, y, cw, ch = fit_crop(W, H, sw_ / sh_, focus)
                tw, th = sw_, sh_
                if tw > cw and not a.upscale:
                    warnings.append(f"the master has only {cw} x {ch} px for {sw_} x {sh_}: written at that size "
                                    "(--upscale enlarges it)")
                    tw, th = cw, ch
            elif p.get("long"):
                L = p["long"]
                if max(W, H) > L or a.upscale:
                    tw, th = (L, round(H * L / W)) if W >= H else (round(W * L / H), L)
            if (x, y, cw, ch) != (0, 0, W, H) or (tw, th) != (cw, ch):
                steps.append(("image.crop", {"x": x, "y": y, "width": cw, "height": ch, "targetWidth": tw,
                                             "targetHeight": th, "resample": "bicubic"}))
            factor = cw / tw
            if bits == 16:  # work in 16 bits; an 8-bit file is converted at the very end
                steps.append(("image.mode.bits16", {}))
            prof = p.get("profile", "keep")
            if prof == "keep":  # the master's own space, tagged with its builtin twin: same numbers, same colours
                if master_builtin:
                    steps.append(("edit.assignProfile", {"profile": master_builtin}))
                    if screen and master_builtin != "srgb":  # --profile keep reaches every preset of the run
                        warnings.append(f"a screen file in {mprof}: browsers and apps that ignore profiles show it "
                                        "duller (deliver screen files with --profile srgb, the default)")
                elif not mprof:
                    steps.append(("edit.assignProfile", {"profile": "srgb"}))
                    warnings.append("the master has no colour profile: tagged sRGB, which is how it displays")
                else:
                    warnings.append(f"the master's profile {mprof!r} has no builtin twin, so this file may come out "
                                    "untagged: deliver it converted (--profile srgb or adobe-rgb)")
            else:
                # how much of the photo the target space can't hold (PhotoCraft's gamut warning: delta E over 4); a
                # view setting, it leaves the pixels alone (checked). For print also the press CMYK gamut, for
                # information only: inkjet and lab printers hold far more (a NASA portrait's blue suit read 52 %).
                steps.append(("view.gamutWarning", {"on": True, "profile": PROFILES[prof]}))
                if preset == "print":
                    steps.append(("view.gamutWarning", {"on": True, "profile": "coated-cmyk"}))
                steps += [("view.gamutWarning", {"on": False}),
                          ("edit.convertToProfile", {"profile": PROFILES[prof], "intent": "relative", "bpc": True})]
            usm = sharpening(p.get("sharpen", "none"), factor, a.strength, ppi)
            if usm:
                steps.append(("filter.sharpen.unsharpMask", usm))
            if bits == 8:
                steps.append(("image.mode.bits8", {}))
            if ppi or preset != "archive":  # the archive keeps the master's own ppi
                steps.append(("image.imageSize", {"resolution": ppi or 72, "resample": "none"}))
            notice = {k: v for k, v in (("copyright", a.copyright), ("author", a.author)) if v}
            if notice:
                steps.append(("file.fileInfo", notice))
            if a.watermark and screen:
                # 3 % of the long edge high, bottom right, at 40 %: white text, or black where the corner is light
                # (white text vanishes on a product shot on white); never on the print or the archive. The corner's
                # brightness is read off the master, at the same place, so one render does everything.
                bx, by = round(0.03 * tw), round(0.03 * th)
                ox, oy, ow, oh = tw - round(0.4 * tw), th - by - round(0.06 * th), round(0.4 * tw) - bx, round(0.06 * th)
                sx_, sy_ = cw / tw, ch / th
                probe = os.path.join(tmp, "corner.png")
                cli("run", master, "--cmd", "layer.flattenImage", "--cmd", "image.crop", "--params", json.dumps(
                    {"x": x + int(ox * sx_), "y": y + int(oy * sy_), "width": max(1, int(ow * sx_)),
                     "height": max(1, int(oh * sy_))}), "--cmd", "image.imageSize", "--params",
                    json.dumps({"width": max(1, min(400, ow)), "resample": "bilinear"}), "--out", probe)
                _, _, CP = pngio.read(probe)
                bright = sum(imgops.lum(*c_) for row in CP for c_ in row) / sum(len(row) for row in CP)
                steps += [("image.imageSize", {"resolution": 72, "resample": "none"}),  # 1 pt = 1 px for the type size
                          ("type.create", {"x": tw - bx, "y": th - by, "text": a.watermark,
                                           "size": max(12, round(0.03 * max(tw, th))),
                                           "color": "#000000" if bright > 150 else "#ffffff", "align": "right",
                                           "name": "Watermark"}),
                          ("layer.setProps", {"opacity": 0.4}),
                          ("image.imageSize", {"resolution": ppi or 72, "resample": "none"})]
            out = free_name(a.name.format(name=base, preset=preset, w=tw, h=th,
                                          date=datetime.date.today().strftime("%Y%m%d")), fmt)
            q = p.get("quality", 90) if fmt == "jpg" else None
            cap = p.get("maxKb") if fmt == "jpg" else None
            # one render straight to the deliverable; a file-size limit renders to PhotoCraft's own format first (it
            # keeps EXIF, XMP and the profile) and searches the quality on that
            mid = os.path.join(tmp, f"{preset}.pcraft") if cap else out
            args = ["run", master]
            for c, prm in steps:
                args += ["--cmd", c, "--params", json.dumps(prm)]
            gamut = {}
            for line in cli(*args, "--out", mid, *(["--quality", q] if q and not cap else [])).splitlines():
                if '"view.gamutWarning"' in line:
                    r = json.loads(line).get("result") or {}
                    if r.get("on"):
                        gamut[r["profile"]] = round(100 * r["fraction"], 2)
            for target, pct in gamut.items():
                if pct > 3 and "CMYK" not in target:
                    warnings.append(f"{pct} % of the photo is more saturated than {target} holds (delta E over 4): those "
                                    "colours flatten in the conversion; look at them, or deliver Display P3 "
                                    "(--profile p3) where the platform shows it")
            if cap:
                cli("convert", mid, out, "--quality", q)
                if os.path.getsize(out) > cap * 1024:
                    floor = max(1, min(30, q - 1))
                    lo_q, hi_q, best = floor, q - 1, None  # the highest quality that fits
                    while lo_q <= hi_q:
                        m_ = (lo_q + hi_q) // 2
                        cli("convert", mid, out, "--quality", m_)
                        if os.path.getsize(out) <= cap * 1024:
                            best, lo_q = m_, m_ + 1
                        else:
                            hi_q = m_ - 1
                    if best is None:
                        warnings.append(f"even quality {floor} is over {cap} KB: make it smaller (--long-edge)")
                        best = floor
                    elif best < 60:
                        warnings.append(f"quality {best} to fit {cap} KB shows blocks in skies and skin: a smaller "
                                        "--long-edge keeps more quality per KB")
                    q = best
                    cli("convert", mid, out, "--quality", q)
            meta = tidy_metadata(out, fmt, meta_mode, strip_gps, a.author, a.copyright)
            out_at = None
            if proof_at:  # master pixels -> this file's pixels (through its crop and resize)
                out_at = [(proof_at[0] - x) * tw / cw, (proof_at[1] - y) * th / ch]
            # check it as delivered
            oi = info(out)
            prof_desc = icc_description(out) if fmt in ("jpg", "png") else tiff_profile(out)
            carried = inspect_metadata(out, fmt)
            rec = {"preset": preset, "file": out, "size": [oi["width"], oi["height"]], "bits": oi["depth"],
                   "ppi": oi.get("resolution"), "profile": prof_desc or "none (untagged)", "kb": round(os.path.getsize(out) / 1024),
                   "quality": q, "crop": [x, y, cw, ch] if (x, y, cw, ch) != (0, 0, W, H) else None,
                   "reduced": round(factor, 2), "sharpen": usm, "outOfGamut%": gamut or None,
                   "metadata": {**meta, **carried}}
            if p.get("maxKb") and fmt == "jpg":
                rec["underKb"] = rec["kb"] <= p["maxKb"]
            if (oi["width"], oi["height"]) != (tw, th):
                warnings.append(f"written {oi['width']} x {oi['height']}, planned {tw} x {th}")
            if oi["depth"] != bits:
                warnings.append(f"written {oi['depth']}-bit, planned {bits}-bit")
            if not prof_desc:
                warnings.append("no colour profile embedded: viewers will guess (usually sRGB)")
            if strip_gps and carried["gps"]:
                warnings.append(f"{carried['gps']} GPS entries are still in the file")
            if carried["thumbnail"]:
                warnings.append("an EXIF thumbnail (the original's) is still in the file")
            for k_ex, k_xmp, opt in (("artist", "xmpCreator", a.author), ("copyright", "xmpRights", a.copyright)):
                vals = {v for v in (carried[k_ex], carried[k_xmp]) if v}
                if len(vals) > 1:
                    warnings.append(f"two different {k_ex} notices in the file: {sorted(vals)}")
            if meta.get("warning"):
                warnings.append(meta["warning"])
            if meta_mode != "none":
                for field, val, opt in (("copyright", carried["copyright"] or carried["xmpRights"], "--copyright"),
                                        ("artist", carried["artist"] or carried["xmpCreator"], "--author")):
                    why = suspect_notice(val, make, model)
                    if why and (val or field == "copyright"):
                        src = "given" if (a.copyright if field == "copyright" else a.author) else "taken from the master"
                        warnings.append(f"the {field} in this file, {val!r} ({src}), looks like {why}: pass {opt}"
                                        if val else f"no copyright notice in this file: pass --copyright")
            if preset == "archive" and not layered:
                warnings.append("the master isn't layered: this TIFF carries no EXIF (PhotoCraft writes none to TIFF); "
                                "keep the original file for the camera data")
            rec["warnings"] = warnings
            outputs.append(rec)
            if proof_path:
                tile, txy = detail_tile(out, tmp, preset, out_at)
                tiles.append(tile)
                rec["proofCrop"] = {"at": list(txy), "size": 360, "chosen": how_at}
            if p.get("copyMaster") and layered:
                ext = os.path.splitext(master)[1].lstrip(".")
                dst = os.path.join(a.outdir, f"{base}-master.{ext}")
                if os.path.exists(dst) and (is_master(dst) or not filecmp.cmp(dst, master, shallow=False)):
                    dst = free_name(f"{base}-master", ext) if not a.overwrite or is_master(dst) else dst
                state = "unchanged" if os.path.exists(dst) and filecmp.cmp(dst, master, shallow=False) else "copied"
                if state == "copied":
                    shutil.copy2(master, dst)
                outputs.append({"preset": preset, "file": dst, "layered": True, "copy": state,
                                "kb": round(os.path.getsize(dst) / 1024)})
        # proof.png: a 360 px crop at 100 % of each output, side by side
        side, gap = 360, 8
        ims = [pngio.read(t) for t in tiles]
        if ims:
            Ht = max(h_ for _, h_, _ in ims)
            Wt = sum(w_ for w_, _, _ in ims) + gap * (len(ims) - 1)
            img = [[(255, 255, 255)] * Wt for _ in range(Ht)]
            ox = 0
            for w_, h_, P in ims:
                for yy in range(h_):
                    img[yy][ox:ox + w_] = P[yy]
                ox += w_ + gap
            pngio.write(proof_path, Wt, Ht, img)
    finally:
        shutil.rmtree(tmp, True)
    print(json.dumps({"master": master, "size": [W, H], "camera": {"make": make, "model": model}, "outputs": outputs,
                      "proof": proof_path if tiles else None}))


if __name__ == "__main__":
    main()
