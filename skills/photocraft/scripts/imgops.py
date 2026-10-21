"""Shared pixel maths for the planning scripts (stdlib only): images as flat row-major float lists.

Filters (Gaussian, max/min, downscale), connected components, the area polygons every script reads, PhotoCraft's
own Curves spline and Luminosity weights (so masks and previews match what the app renders), and colour
measures: CIE Lab (D50, as Photoshop's Info panel shows it) and vectorscope angle (the skin-tone line).
"""
import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import pngio


# ---------------------------------------------------------------- loading and saving

def load(path):
    """(w, h, R, G, B): flat float lists, 0..255."""
    w, h, P = pngio.read(path)
    return (w, h, [float(p[0]) for row in P for p in row], [float(p[1]) for row in P for p in row],
            [float(p[2]) for row in P for p in row])


def load_rgba(path):
    """(w, h, R, G, B, A): A in 0..1."""
    w, h, P = pngio.read_rgba(path)
    flat = [p for row in P for p in row]
    return (w, h, [float(p[0]) for p in flat], [float(p[1]) for p in flat], [float(p[2]) for p in flat],
            [p[3] / 255 for p in flat])


def _bytes(ch, k=1.0):
    """A flat channel as 8-bit samples: v * k, rounded and clipped to 0..255."""
    return bytes(0 if v <= 0 else 255 if v * k >= 255 else int(v * k + 0.5) for v in ch)


def _save(path, w, h, chans):
    """Interleave whole channels of 8-bit samples with byte slices (no tuple per pixel) into an RGB or RGBA PNG."""
    n = len(chans)
    raw = bytearray((n * w + 1) * h)
    for y in range(h):
        o = y * (n * w + 1) + 1
        for c, ch in enumerate(chans):
            raw[o + c:o + n * w:n] = ch[y * w:(y + 1) * w]
    pngio.write_raw(path, w, h, n, raw)


def save_rgb(path, w, h, R, G, B, A=None):
    """Write flat 0..255 channels (and optional 0..1 alpha) as an 8-bit PNG."""
    _save(path, w, h, [_bytes(R), _bytes(G), _bytes(B)] + ([_bytes(A, 255.0)] if A is not None else []))


def save_gray(path, w, h, vals):
    """A 0..1 mask as a grey PNG (all three channels equal; select.loadSelection reads its red channel)."""
    g = _bytes(vals, 255.0)
    _save(path, w, h, [g, g, g])


FONT = {  # 3x5 digits for labels on check images (grid.py, color_check.py, cutout_check.py)
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111",
}


# ---------------------------------------------------------------- filters on flat row-major float lists

def _box_rows(src, w, h, r):
    if r < 1:
        return src[:]
    inv = 1.0 / (2 * r + 1)
    out = []
    for y in range(h):
        row = src[y * w:(y + 1) * w]
        pad = [row[0]] * r + row + [row[-1]] * (r + 1)
        acc = sum(pad[:2 * r + 1])
        res = [0.0] * w
        for x in range(w):
            res[x] = acc * inv
            acc += pad[x + 2 * r + 1] - pad[x]
        out.extend(res)
    return out


def _transpose(src, w, h):
    rows = [src[y * w:(y + 1) * w] for y in range(h)]
    return [v for col in zip(*rows) for v in col]


def _box_radii(sigma, n=3):
    wi = math.sqrt(12 * sigma * sigma / n + 1)
    wl = int(wi)
    if wl % 2 == 0:
        wl -= 1
    m = round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4))
    return [(wl - 1) // 2 if i < m else (wl + 1) // 2 for i in range(n)]


def gauss(src, w, h, sigma):
    """Gaussian blur (three box passes each way), edges clamped."""
    if sigma <= 0:
        return src[:]
    rs = _box_radii(sigma)
    a = src
    for r in rs:
        a = _box_rows(a, w, h, r)
    a = _transpose(a, w, h)
    for r in rs:
        a = _box_rows(a, h, w, r)
    return _transpose(a, h, w)


def box(src, w, h, r):
    """Mean over a (2r+1) square, edges clamped."""
    a = _transpose(_box_rows(src, w, h, r), w, h)
    return _transpose(_box_rows(a, h, w, r), h, w)


def _extreme_rows(src, w, h, r, fn):
    out = []
    for y in range(h):
        row = src[y * w:(y + 1) * w]
        out.extend(fn(row[max(0, x - r):x + r + 1]) for x in range(w))
    return out


def maxf(src, w, h, r):
    """Maximum over a (2r+1) square (grey dilation)."""
    if r < 1:
        return src[:]
    a = _transpose(_extreme_rows(src, w, h, r, max), w, h)
    return _transpose(_extreme_rows(a, h, w, r, max), h, w)


def minf(src, w, h, r):
    """Minimum over a (2r+1) square (grey erosion)."""
    if r < 1:
        return src[:]
    a = _transpose(_extreme_rows(src, w, h, r, min), w, h)
    return _transpose(_extreme_rows(a, h, w, r, min), h, w)


def downscale(src, w, h, k):
    """Box-average by an integer factor k: (values, w // k, h // k)."""
    if k <= 1:
        return src[:], w, h
    W, H = w // k, h // k
    inv = 1.0 / (k * k)
    out = [0.0] * (W * H)
    for Y in range(H):
        for X in range(W):
            s = 0.0
            for y in range(Y * k, Y * k + k):
                base = y * w + X * k
                s += sum(src[base:base + k])
            out[Y * W + X] = s * inv
    return out, W, H


def components(mask, w, h):
    """8-connected components of the truthy pixels: a list of index lists."""
    seen = bytearray(w * h)
    comps = []
    for i0 in range(w * h):
        if not mask[i0] or seen[i0]:
            continue
        seen[i0] = 1
        st, pix = [i0], []
        while st:
            i = st.pop(); pix.append(i)
            x, y = i % w, i // w
            for dy in (-1, 0, 1):
                yy = y + dy
                if 0 <= yy < h:
                    for dx in (-1, 0, 1):
                        xx = x + dx
                        j = yy * w + xx
                        if 0 <= xx < w and mask[j] and not seen[j]:
                            seen[j] = 1; st.append(j)
        comps.append(pix)
    return comps


def percentile(vals, p):
    """p in 0..100 of a list (sorted copy, linear interpolation)."""
    s = sorted(vals)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100
    i = int(k)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (k - i)


# ---------------------------------------------------------------- PhotoCraft's tone maths

def spline_lut(pts):
    """PhotoCraft Curves = natural cubic spline through the points, the end values held beyond the first and last
    point (verified against 0.7.0)."""
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; n = len(pts)
    hs = [xs[i + 1] - xs[i] for i in range(n - 1)]
    a = [[0.0] * n for _ in range(n)]; b = [0.0] * n
    a[0][0] = a[n - 1][n - 1] = 1.0
    for i in range(1, n - 1):
        a[i][i - 1], a[i][i], a[i][i + 1] = hs[i - 1], 2 * (hs[i - 1] + hs[i]), hs[i]
        b[i] = 6 * ((ys[i + 1] - ys[i]) / hs[i] - (ys[i] - ys[i - 1]) / hs[i - 1])
    for i in range(n):
        for j in range(i + 1, n):
            f = a[j][i] / a[i][i]
            for k in range(n):
                a[j][k] -= f * a[i][k]
            b[j] -= f * b[i]
    m = [0.0] * n
    for i in range(n - 1, -1, -1):
        m[i] = (b[i] - sum(a[i][k] * m[k] for k in range(i + 1, n))) / a[i][i]
    lut = []
    for x in range(256):
        if x < xs[0] or x > xs[-1]:
            lut.append(max(0, min(255, round(ys[0] if x < xs[0] else ys[-1]))))
            continue
        i = next((k for k in range(n - 1) if x <= xs[k + 1]), n - 2)
        t0, t1, hh = xs[i + 1] - x, x - xs[i], hs[i]
        v = (m[i] * t0 ** 3 + m[i + 1] * t1 ** 3) / (6 * hh) + (ys[i] / hh - m[i] * hh / 6) * t0 + (ys[i + 1] / hh - m[i + 1] * hh / 6) * t1
        lut.append(max(0, min(255, round(v))))
    return lut


def lut_f(lut, v):
    v = 0.0 if v < 0 else 255.0 if v > 255 else v
    i = int(v)
    if i >= 255:
        return float(lut[255])
    t = v - i
    return lut[i] * (1 - t) + lut[i + 1] * t


def lum(r, g, b):
    return 0.3 * r + 0.59 * g + 0.11 * b  # PhotoCraft's Luminosity / Color blend weights


def set_lum(r, g, b, l):
    d = l - lum(r, g, b)
    r, g, b = r + d, g + d, b + d
    L = lum(r, g, b); n = min(r, g, b); x = max(r, g, b)
    if n < 0 and L - n > 1e-9:
        k = L / (L - n); r, g, b = L + (r - L) * k, L + (g - L) * k, L + (b - L) * k
    if x > 255 and x - L > 1e-9:
        k = (255 - L) / (x - L); r, g, b = L + (r - L) * k, L + (g - L) * k, L + (b - L) * k
    return r, g, b


def set_sat(r, g, b, s):
    """The colour with its saturation (max - min) set to s, hue kept (the Hue and Saturation blends)."""
    c = [r, g, b]
    hi, lo = max(range(3), key=c.__getitem__), min(range(3), key=c.__getitem__)
    if c[hi] - c[lo] < 1e-9:
        return 0.0, 0.0, 0.0
    mid = 3 - hi - lo
    out = [0.0, 0.0, 0.0]
    out[mid], out[hi] = (c[mid] - c[lo]) * s / (c[hi] - c[lo]), s
    return tuple(out)


def _dodge(b, s):
    return 0.0 if b <= 0 else 1.0 if s >= 1 else min(1.0, b / (1 - s))


def _burn(b, s):
    return 1.0 if b >= 1 else 0.0 if s <= 0 else max(0.0, 1 - (1 - b) / s)


# one channel, below b and layer s in 0..1 (PhotoCraft 0.7.0, checked on all 65536 8-bit pairs: exact, or 1 level
# of rounding). Soft Light is Photoshop's classic formula; the W3C/CSS one differs by up to 17 levels.
SEPARABLE = {
    "normal": lambda b, s: s,
    "multiply": lambda b, s: b * s,
    "screen": lambda b, s: 1 - (1 - b) * (1 - s),
    "overlay": lambda b, s: 2 * b * s if b < 0.5 else 1 - 2 * (1 - b) * (1 - s),
    "hardlight": lambda b, s: 2 * b * s if s < 0.5 else 1 - 2 * (1 - b) * (1 - s),
    "softlight": lambda b, s: (2 * b * s + b * b * (1 - 2 * s) if s <= 0.5
                               else 2 * b * (1 - s) + math.sqrt(b) * (2 * s - 1)),
    "linearlight": lambda b, s: b + 2 * s - 1,
    "vividlight": lambda b, s: (0.0 if s <= 0 else 1.0 if s >= 1  # a black or white layer wins, whatever is below
                               else _burn(b, 2 * s) if s <= 0.5 else _dodge(b, 2 * s - 1)),
    "pinlight": lambda b, s: min(b, 2 * s) if s <= 0.5 else max(b, 2 * s - 1),
    "lighten": max,
    "darken": min,
    "colordodge": _dodge,
    "colorburn": _burn,
    "lineardodge": lambda b, s: b + s,
    "linearburn": lambda b, s: b + s - 1,
    "subtract": lambda b, s: b - s,
    "divide": lambda b, s: (1.0 if b > 0 else 0.0) if s <= 0 else b / s,
    "difference": lambda b, s: abs(b - s),
    "exclusion": lambda b, s: b + s - 2 * b * s,
}


def blend_key(mode):
    """'Soft Light', 'softLight', 'Linear Dodge (Add)' -> the keys above (and 'color', 'luminosity', 'hue', ...)."""
    k = mode.lower().replace(" ", "").replace("(add)", "")
    return {"add": "lineardodge"}.get(k, k)


def blend(mode, below, layer, opacity=1.0):
    """An RGB layer pixel over the RGB below it as PhotoCraft renders it, 0..255 floats in and out (not rounded):
    the separable modes channel by channel, Color / Luminosity / Hue / Saturation with PhotoCraft's luminosity
    weights (lum, set_lum: checked on random colour pairs, within 1 level). opacity mixes the result in, as a
    layer's opacity or mask value does."""
    k = blend_key(mode)
    if k == "color":
        out = set_lum(*layer, lum(*below))
    elif k == "luminosity":
        out = set_lum(*below, lum(*layer))
    elif k == "hue":
        out = set_lum(*set_sat(*layer, max(below) - min(below)), lum(*below))
    elif k == "saturation":
        out = set_lum(*set_sat(*below, max(layer) - min(layer)), lum(*below))
    else:
        f = SEPARABLE[k]
        out = [255 * min(1.0, max(0.0, f(b / 255, s / 255))) for b, s in zip(below, layer)]
    return tuple(b + opacity * (o - b) for b, o in zip(below, out))


# ---------------------------------------------------------------- grain

NOISE_PER_AMOUNT = 0.643  # filter.noise.addNoise, gaussian, monochromatic: standard deviation per unit of amount


def grain(L, w, h, idx):
    """Robust grain of a luminance image at pixels idx: 1.4826 x median |L - 3x3 mean| (0.943 x sigma for white
    noise; divide by 0.943 for the sigma that Add Noise or noise() should add)."""
    d = []
    for i in idx:
        x, y = i % w, i // w
        if 0 < x < w - 1 and 0 < y < h - 1:
            m = (L[i - w - 1] + L[i - w] + L[i - w + 1] + L[i - 1] + L[i] + L[i + 1] + L[i + w - 1] + L[i + w] + L[i + w + 1]) / 9
            d.append(abs(L[i] - m))
    d.sort()
    return 1.4826 * d[len(d) // 2] if d else 0.0


def grain_floor(L, w, h, mask, block=8, q=0.2):
    """Grain the way a noise-floor estimate reads it: grain()'s statistic in every 8 x 8 block inside mask, then a
    low percentile of those blocks. Texture (knitwear, foliage, brick, leather) only raises some blocks; the quietest
    ones are grain, so two different materials can be compared. Clipped blocks are skipped; None with < 8 blocks."""
    vals = []
    for by in range(1, h - block - 1, block):
        for bx in range(1, w - block - 1, block):
            idx = [(by + y) * w + bx + x for y in range(block) for x in range(block)]
            if not all(mask[i] for i in idx):
                continue
            mu = sum(L[i] for i in idx) / len(idx)
            if mu < 10 or mu > 245:
                continue
            d = sorted(abs(L[i] - (L[i - w - 1] + L[i - w] + L[i - w + 1] + L[i - 1] + L[i] + L[i + 1] + L[i + w - 1]
                                   + L[i + w] + L[i + w + 1]) / 9) for i in idx)
            vals.append(1.4826 * d[len(d) // 2])
    if len(vals) < 8:
        return None
    vals.sort()
    return vals[int(q * (len(vals) - 1))]


def noise(n, sigma, seed=1):
    """n samples of reproducible Gaussian noise (mean 0): grain baked into a planner's pixel layer, so the preview
    holds the exact pixels (PhotoCraft's own Add Noise can't be predicted pixel by pixel)."""
    import random
    rnd = random.Random(seed)
    return [rnd.gauss(0.0, sigma) for _ in range(n)]


# ---------------------------------------------------------------- area polygons (area.json)

def raster(cfg, ox, oy, w, h):
    """Binary skin mask of the crop: skin polygon(s) minus exclusion boxes/polygons."""
    def fill(m, pts, val):
        n = len(pts)
        for y in range(h):
            Y = y + oy
            xs = []
            for i in range(n):
                (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
                if (y0 > Y) != (y1 > Y):
                    xs.append(x0 + (Y - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                a = max(0, math.ceil(xs[k] - ox)); b = min(w - 1, math.floor(xs[k + 1] - ox))
                for x in range(a, b + 1):
                    m[y * w + x] = val
    m = [0.0] * (w * h)
    skins = cfg["skin"] if isinstance(cfg["skin"][0][0], (list, tuple)) else [cfg["skin"]]
    for pts in skins:
        fill(m, pts, 1.0)
    for e in cfg.get("exclude", []):
        if isinstance(e[0], (list, tuple)):
            fill(m, e, 0.0)
        else:
            x0, y0, x1, y1 = (int(round(v)) for v in e)
            for y in range(max(0, y0 - oy), min(h, y1 - oy + 1)):
                for x in range(max(0, x0 - ox), min(w, x1 - ox + 1)):
                    m[y * w + x] = 0.0
    return m


def polygon_mask(polys, ox, oy, w, h, exclude=()):
    """Mask of any region polygons (full-image coords) in a crop at (ox, oy): area.json without the 'skin' key."""
    return raster({"skin": polys, "exclude": list(exclude)}, ox, oy, w, h)


# ---------------------------------------------------------------- colour measures

def _mat(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _inv(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


_BRADFORD_D65_D50 = [[1.0478112, 0.0228866, -0.0501270], [0.0295424, 0.9904844, -0.0170491], [-0.0092345, 0.0150436, 0.7521316]]
_TO_XYZ = {  # linear RGB -> XYZ (D65); both spaces share sRGB's tone curve
    "srgb": [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]],
    "p3": [[0.4865709, 0.2656677, 0.1982173], [0.2289746, 0.6917385, 0.0792869], [0.0, 0.0451134, 1.0439444]],
}
_TO_D50 = {k: _mat(_BRADFORD_D65_D50, m) for k, m in _TO_XYZ.items()}
_FROM_D50 = {k: _inv(m) for k, m in _TO_D50.items()}
_WHITE = (0.9642, 1.0, 0.8249)


def to_linear(c):
    """An 8-bit sRGB (or Display P3: same tone curve) value -> linear light, 0..1."""
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def from_linear(c):
    """Linear light 0..1 -> an 8-bit sRGB (or Display P3) value, 0..255, not clipped above."""
    c = c * 12.92 if c <= 0.0031308 else 1.055 * max(c, 0) ** (1 / 2.4) - 0.055
    return 255 * c


def _f(t):
    return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116


def _finv(t):
    return t ** 3 if t > 6 / 29 else (116 * t - 16) * 27 / 24389


def lab(r, g, b, space="srgb"):
    """CIE L*a*b* (D50, Bradford-adapted like Photoshop's Info panel) of an 8-bit RGB triple in sRGB or Display P3."""
    lr, lg, lb = to_linear(r), to_linear(g), to_linear(b)
    m = _TO_D50[space]
    fx, fy, fz = (_f((m[i][0] * lr + m[i][1] * lg + m[i][2] * lb) / _WHITE[i]) for i in range(3))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def lab_to_rgb(L, a, b, space="srgb"):
    """Inverse of lab(): 0..255 floats, not clipped (out-of-gamut values fall outside 0..255)."""
    fy = (L + 16) / 116
    xyz = (_finv(fy + a / 500) * _WHITE[0], _finv(fy) * _WHITE[1], _finv(fy - b / 200) * _WHITE[2])
    m = _FROM_D50[space]
    return tuple(from_linear(m[i][0] * xyz[0] + m[i][1] * xyz[1] + m[i][2] * xyz[2]) for i in range(3))


def vectorscope(r, g, b):
    """(angle in degrees, saturation) on a video vectorscope: U = 0.492 (B - Y) to the right, V = 0.877 (R - Y) up.
    Skin of every complexion sits near the skin-tone ('I') line at about 123 degrees; lower = pinker/magenta,
    higher = yellower/greener."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    u, v = 0.492 * (b - y), 0.877 * (r - y)
    return math.degrees(math.atan2(v, u)) % 360, math.hypot(u, v)
