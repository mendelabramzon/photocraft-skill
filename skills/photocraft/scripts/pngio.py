"""Minimal PNG reader/writer (stdlib only): 8- and 16-bit grey, grey+alpha, RGB and RGBA in, 8-bit RGB(A) out."""
import struct
import zlib

CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}  # colour type -> samples per pixel: grey, RGB, grey+alpha, RGBA


def _decode(path):
    """(w, h, samples per pixel, 8-bit samples row-major as a bytearray)."""
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path}: not a PNG"
    pos, idat, w = 8, b"", None
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
            assert depth in (8, 16) and interlace == 0 and ctype in CHANNELS, (depth, ctype, interlace)
            nch = CHANNELS[ctype]
            bpp = nch * depth // 8
        elif typ == b"IDAT":
            idat += chunk
        pos += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * bpp
    out = bytearray(h * stride)
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        f = raw[i]; i += 1
        line = bytearray(raw[i:i + stride]); i += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * stride:(y + 1) * stride] = line
        prev = line
    if depth == 16:  # to the nearest 8-bit level: rounding down read every 16-bit render half a level dark
        out = bytearray(((out[k] * 256 + out[k + 1]) * 255 + 32767) // 65535 for k in range(0, len(out), 2))
    return w, h, nch, out


def _rows(w, h, nch, s, alpha):
    """Rows of (r, g, b) or (r, g, b, a) tuples from decoded samples."""
    if nch >= 3:
        k = nch
        px = [[tuple(s[(y * w + x) * k:(y * w + x) * k + 3]) for x in range(w)] for y in range(h)]
    else:
        px = [[(s[(y * w + x) * nch],) * 3 for x in range(w)] for y in range(h)]
    if alpha:
        ai = 3 if nch == 4 else 1 if nch == 2 else None
        px = [[p + ((s[(y * w + x) * nch + ai],) if ai is not None else (255,)) for x, p in enumerate(row)]
              for y, row in enumerate(px)]
    return px


def read(path):
    """(w, h, rows of (r, g, b)). Grey is expanded to RGB, alpha dropped, 16-bit reduced to 8-bit."""
    w, h, nch, s = _decode(path)
    return w, h, _rows(w, h, nch, s, False)


def read_rgba(path):
    """(w, h, rows of (r, g, b, a)); a is 255 where the PNG has no alpha."""
    w, h, nch, s = _decode(path)
    return w, h, _rows(w, h, nch, s, True)


def write(path, w, h, px):
    """Write rows of (r, g, b) or (r, g, b, a) 8-bit tuples as an RGB or RGBA PNG."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw.extend(px[y][x])
    write_raw(path, w, h, len(px[0][0]), raw)


def write_raw(path, w, h, nch, raw):
    """Write unfiltered scanlines (a 0 filter byte, then w * nch samples, per row) as an RGB (3) or RGBA (4) PNG."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6 if nch == 4 else 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)
