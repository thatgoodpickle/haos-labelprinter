"""Render a label *design* (JSON, see docs/EDITOR_CONTRACT.md) into a 1-bit bitmap.

No Home Assistant imports. Blocking/sync. Designs come from a browser, so everything is
type-checked and clamped; the only exception this module raises is :class:`DesignError`.
"""
from __future__ import annotations

import base64
import binascii
import io
import math
import os
import re
from functools import lru_cache
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from .errors import PtouchError
from .protocol import MAX_STRIP_DOTS, tape_pins
from .render import _FONT_CANDIDATES

DESIGN_VERSION = 1

MAX_ELEMENTS = 200
COORD_LIMIT = 20000
SIZE_LIMIT = 20000
FONT_MIN, FONT_MAX = 4, 400
LAYER_LIMIT = 6000           # largest element layer edge actually allocated
PIXEL_BUDGET = 300_000_000   # total layer pixels per render
MAX_TEXT = 5000
MAX_DATA = 4000
MAX_SRC = 12_000_000         # chars of data URI
MAX_IMAGE_PIXELS = 25_000_000
MAX_VARS = 100

ELEMENT_TYPES = ("text", "icon", "qr", "barcode", "rect", "image")
BARCODE_FORMATS = ("code128", "code39", "ean13", "ean8", "upca", "itf", "codabar")


class DesignError(PtouchError):
    """The design is invalid."""


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------
def _num(v: Any, default: float, lo: float, hi: float) -> float:
    if isinstance(v, bool):
        return default
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return default
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return min(hi, max(lo, v))


def _int(v: Any, default: int, lo: int, hi: int) -> int:
    return int(round(_num(v, default, lo, hi)))


def _bool(v: Any, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def _str(v: Any, default: str = "", maxlen: int = MAX_TEXT) -> str:
    if isinstance(v, bool) or v is None:
        return default
    if isinstance(v, (int, float)):
        v = str(v)
    if not isinstance(v, str):
        return default
    return v[:maxlen]


def _choice(v: Any, options: tuple[str, ...], default: str) -> str:
    if isinstance(v, str) and v.strip().lower() in options:
        return v.strip().lower()
    return default


_TYPE_DEFAULTS: dict[str, tuple[int, int]] = {
    "text": (100, 40), "icon": (48, 48), "qr": (64, 64), "barcode": (160, 64),
    "rect": (100, 20), "image": (64, 64),
}


def _valid_image_src(src: str) -> bool:
    return bool(re.match(r"data:image/(png|jpeg|jpg);base64,", src[:40], re.I))


def _normalize_element(raw: Any, index: int) -> dict | None:
    if not isinstance(raw, dict):
        raise DesignError(f"element {index} is not an object")
    etype = raw.get("type")
    if not isinstance(etype, str) or etype not in ELEMENT_TYPES:
        return None  # junk: dropped
    dw, dh = _TYPE_DEFAULTS[etype]
    rot = _int(raw.get("rotation"), 0, -100000, 100000)
    el: dict = {
        "id": _str(raw.get("id"), f"e{index + 1}", 64) or f"e{index + 1}",
        "type": etype,
        "x": _int(raw.get("x"), 0, -COORD_LIMIT, COORD_LIMIT),
        "y": _int(raw.get("y"), 0, -COORD_LIMIT, COORD_LIMIT),
        "w": _int(raw.get("w"), dw, 0, SIZE_LIMIT),
        "h": _int(raw.get("h"), dh, 0, SIZE_LIMIT),
        "rotation": (int(round(rot / 90.0)) * 90) % 360,
        "invert": _bool(raw.get("invert"), False),
    }
    if etype == "text":
        size = raw.get("size", "auto")
        if isinstance(size, str) and size.strip().lower() == "auto":
            size = "auto"
        else:
            size = _int(size, 0, FONT_MIN, FONT_MAX) if _num(size, -1, -1, 1e9) >= 0 else "auto"
            if size == 0:
                size = "auto"
        el.update(
            text=_str(raw.get("text"), "", MAX_TEXT),
            font=_str(raw.get("font"), "", 80).strip(),
            weight=_int(raw.get("weight"), 400, 100, 900),
            italic=_bool(raw.get("italic"), False),
            size=size,
            align=_choice(raw.get("align"), ("left", "center", "right"), "center"),
            valign=_choice(raw.get("valign"), ("top", "middle", "bottom"), "middle"),
            line_spacing=round(_num(raw.get("line_spacing"), 1.0, 0.5, 4.0), 3),
        )
    elif etype == "icon":
        el["icon"] = _str(raw.get("icon"), "mdi:tag", 80).strip() or "mdi:tag"
    elif etype == "qr":
        el.update(data=_str(raw.get("data"), "", MAX_DATA),
                  ecc=_choice(raw.get("ecc"), ("l", "m", "q", "h"), "m"),
                  quiet=_int(raw.get("quiet"), 1, 0, 8))
    elif etype == "barcode":
        el.update(format=_choice(raw.get("format"), BARCODE_FORMATS, "code128"),
                  data=_str(raw.get("data"), "", 200),
                  show_text=_bool(raw.get("show_text"), True))
    elif etype == "rect":
        el.update(stroke=_int(raw.get("stroke"), 2, 0, 1000), fill=_bool(raw.get("fill"), False))
    elif etype == "image":
        src = _str(raw.get("src"), "", MAX_SRC)
        el.update(src=src if _valid_image_src(src) else "", dither=_bool(raw.get("dither"), True))
    return el


def normalize_design(design: dict) -> dict:
    """Return a clean copy of *design*: defaults filled, numbers clamped, junk dropped."""
    if not isinstance(design, dict):
        raise DesignError("design must be an object")
    version = design.get("version", DESIGN_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= DESIGN_VERSION:
        raise DesignError(f"unsupported design version {version!r}")
    raw_elements = design.get("elements", [])
    if raw_elements is None:
        raw_elements = []
    if not isinstance(raw_elements, list):
        raise DesignError("elements must be a list")
    if len(raw_elements) > MAX_ELEMENTS:
        raise DesignError(f"too many elements (maximum {MAX_ELEMENTS})")
    raw_vars = design.get("variables", {})
    if raw_vars is None:
        raw_vars = {}
    if not isinstance(raw_vars, dict):
        raise DesignError("variables must be an object")
    variables: dict[str, str] = {}
    for k, v in raw_vars.items():
        if len(variables) >= MAX_VARS:
            break
        if isinstance(k, str) and k.strip():
            variables[k.strip()[:64]] = _str(v, "", 2000)
    length = design.get("length_mm")
    max_mm = MAX_STRIP_DOTS * 25.4 / 180
    length_mm = None if length is None or isinstance(length, bool) or not isinstance(length, (int, float)) \
        or not math.isfinite(length) else round(min(max_mm, max(0.5, float(length))), 2)
    elements = []
    for i, raw in enumerate(raw_elements):
        el = _normalize_element(raw, i)
        if el is not None:
            elements.append(el)
    return {
        "version": DESIGN_VERSION,
        "id": _str(design.get("id"), "", 80),
        "name": _str(design.get("name"), "", 120),
        "length_mm": length_mm,
        "padding_dots": _int(design.get("padding_dots"), 6, 0, 500),
        "variables": variables,
        "elements": elements,
    }


# --------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------
_VAR_RE = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")


def _substitute(text: str, values: dict[str, str]) -> str:
    return _VAR_RE.sub(lambda m: values.get(m.group(1), ""), text)


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
def _system_font_path(weight: int, italic: bool) -> str | None:
    dirs = []
    for c in _FONT_CANDIDATES:
        d = os.path.dirname(c)
        if d not in dirs:
            dirs.append(d)
    bold = weight >= 600
    name = "DejaVuSans" + ("-Bold" if bold else "") + (
        ("Oblique" if bold else "-Oblique") if italic else "") + ".ttf"
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return None


@lru_cache(maxsize=256)
def _truetype(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=64)
def _default_font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow without FreeType
        return ImageFont.load_default()


class _Fonts:
    """Resolves (family, weight, italic, size) -> a PIL font, never failing."""

    def __init__(self, assets: Any) -> None:
        self.assets = assets
        self._paths: dict[tuple, str | None] = {}

    def path(self, family: str, weight: int, italic: bool) -> str | None:
        key = (family, weight, italic)
        if key not in self._paths:
            p = None
            if family and self.assets is not None:
                try:
                    found = self.assets.font_path(family, weight, italic)
                    if found is not None and os.path.exists(str(found)):
                        p = str(found)
                except Exception:  # noqa: BLE001 - assets must never break rendering
                    p = None
            if p is None:
                p = _system_font_path(weight, italic)
            self._paths[key] = p
        return self._paths[key]

    def get(self, family: str, weight: int, italic: bool, size: int):
        size = max(FONT_MIN, int(size))
        p = self.path(family, weight, italic)
        if p:
            f = _truetype(p, size)
            if f is not None:
                return f
        return _default_font(size)


def _text_w(font, s: str) -> float:
    if not s:
        return 0.0
    try:
        return float(font.getlength(s))
    except Exception:  # noqa: BLE001
        l, _, r, _ = font.getbbox(s)
        return float(r - l)


def _line_box(font) -> tuple[int, int]:
    """(ascent, descent) used for line boxes."""
    try:
        a, d = font.getmetrics()
        return int(a), int(d)
    except Exception:  # noqa: BLE001
        l, t, r, b = font.getbbox("Hgjpq")
        return int(-t if t < 0 else b), 0 if t < 0 else 0


def _wrap(text: str, font, maxw: int, break_long: bool) -> tuple[list[str], bool]:
    """Greedy whitespace wrap. Returns (lines, too_wide) - too_wide when a word cannot fit."""
    lines: list[str] = []
    too_wide = False
    for para in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            trial = f"{cur} {word}" if cur else word
            if _text_w(font, trial) <= maxw:
                cur = trial
                continue
            if cur:
                lines.append(cur)
                cur = ""
            if _text_w(font, word) <= maxw:
                cur = word
                continue
            too_wide = True
            if not break_long:
                cur = word
                continue
            piece = ""
            for ch in word:
                if piece and _text_w(font, piece + ch) > maxw:
                    lines.append(piece)
                    piece = ch
                else:
                    piece += ch
            cur = piece
        lines.append(cur)
    return lines, too_wide


def _layout_text(el: dict, text: str, cw: int, ch: int, fonts: _Fonts):
    """Choose size/wrap. Returns (font, lines, pitch, asc, block_h, overflow)."""
    fam, wt, it = el["font"], el["weight"], el["italic"]
    spacing = el["line_spacing"]

    def build(size: int, break_long: bool):
        font = fonts.get(fam, wt, it, size)
        asc, desc = _line_box(font)
        lines, wide = _wrap(text, font, cw, break_long)
        pitch = max(1, int(round((asc + desc) * spacing)))
        block = pitch * (len(lines) - 1) + asc + desc
        return font, lines, pitch, asc, block, wide

    if el["size"] == "auto":
        lo, hi, best = FONT_MIN, min(FONT_MAX, max(8, ch * 2)), FONT_MIN
        while lo <= hi:
            mid = (lo + hi) // 2
            _, _, _, _, block, wide = build(mid, False)
            if block <= ch and not wide:
                best, lo = mid, mid + 1
            else:
                hi = mid - 1
        size = best
    else:
        size = int(el["size"])
    font, lines, pitch, asc, block, wide = build(size, True)
    return font, lines, pitch, asc, block, wide or block > ch


# --------------------------------------------------------------------------
# Element painters. Each returns an "L" ink mask (255 = ink) of the content size
# (cw x ch), or None to draw nothing, appending to `warn` as needed.
# --------------------------------------------------------------------------
class _Ctx:
    def __init__(self, assets: Any, variables: dict[str, str] | None) -> None:
        self.fonts = _Fonts(assets)
        self.assets = assets
        self.variables = variables
        self.warnings: list[str] = []
        self.pixels = 0

    def sub(self, s: str) -> str:
        return s if self.variables is None else _substitute(s, self.variables)


def _paint_text(el: dict, cw: int, ch: int, ctx: _Ctx, label: str):
    text = ctx.sub(el["text"])
    if not text.strip():
        return None
    font, lines, pitch, asc, block, overflow = _layout_text(el, text, cw, ch, ctx.fonts)
    mask = Image.new("L", (cw, ch), 0)
    d = ImageDraw.Draw(mask)
    y0 = {"top": 0, "bottom": ch - block}.get(el["valign"], (ch - block) // 2)
    for i, line in enumerate(lines):
        if not line:
            continue
        w = _text_w(font, line)
        x = {"left": 0, "right": cw - w}.get(el["align"], (cw - w) / 2)
        try:
            d.text((round(x), y0 + i * pitch + asc), line, font=font, fill=255, anchor="ls")
        except (ValueError, TypeError):
            d.text((round(x), y0 + i * pitch), line, font=font, fill=255)
    if overflow:
        ctx.warnings.append(f"{label}: text is clipped (box too small)")
    return mask.point(lambda v: 255 if v >= 128 else 0)


def _paint_icon(el: dict, cw: int, ch: int, ctx: _Ctx, label: str):
    glyph = None
    if ctx.assets is not None:
        try:
            glyph = ctx.assets.icon_glyph(el["icon"])
        except Exception:  # noqa: BLE001
            glyph = None
    if not glyph:
        ctx.warnings.append(f"{label}: icon {el['icon']!r} not available")
        return None
    try:
        path, char = str(glyph[0]), str(glyph[1])
    except Exception:  # noqa: BLE001
        return None
    side = min(cw, ch)
    if side < 1 or not char:
        return None

    def bbox(size: int):
        f = _truetype(path, size)
        if f is None:
            return None, None
        return f, f.getbbox(char, anchor="ls")

    lo, hi, best = FONT_MIN, max(FONT_MIN, side * 2), None
    while lo <= hi:
        mid = (lo + hi) // 2
        f, bb = bbox(mid)
        if f is None:
            ctx.warnings.append(f"{label}: icon font cannot be loaded")
            return None
        if bb[2] - bb[0] <= side and bb[3] - bb[1] <= side:
            best, lo = (f, bb), mid + 1
        else:
            hi = mid - 1
    if best is None:
        f, bb = bbox(FONT_MIN)
        best = (f, bb)
    f, bb = best
    gw, gh = bb[2] - bb[0], bb[3] - bb[1]
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).text(((cw - gw) // 2 - bb[0], (ch - gh) // 2 - bb[1]), char, font=f,
                              fill=255, anchor="ls")
    return mask.point(lambda v: 255 if v >= 128 else 0)


def _paint_qr(el: dict, cw: int, ch: int, ctx: _Ctx, label: str):
    data = ctx.sub(el["data"])
    if not data:
        return None
    try:
        import segno
        qr = segno.make(data, error=el["ecc"], micro=False)
        matrix = [list(row) for row in qr.matrix]
    except Exception as err:  # noqa: BLE001
        ctx.warnings.append(f"{label}: QR code could not be generated ({err.__class__.__name__})")
        return None
    q = el["quiet"]
    n = len(matrix) + 2 * q
    scale = min(cw, ch) // n
    if scale < 1:
        ctx.warnings.append(f"{label}: box too small for this QR code (needs {n}x{n} dots)")
        return None
    mask = Image.new("L", (cw, ch), 0)
    d = ImageDraw.Draw(mask)
    ox, oy = (cw - n * scale) // 2 + q * scale, (ch - n * scale) // 2 + q * scale
    for r, row in enumerate(matrix):
        c = 0
        while c < len(row):
            if row[c]:
                c2 = c
                while c2 + 1 < len(row) and row[c2 + 1]:
                    c2 += 1
                d.rectangle((ox + c * scale, oy + r * scale,
                             ox + (c2 + 1) * scale - 1, oy + (r + 1) * scale - 1), fill=255)
                c = c2 + 1
            else:
                c += 1
    return mask


def _digits_ok(s: str, lengths: tuple[int, ...]) -> bool:
    return s.isdigit() and len(s) in lengths


def _ean_check(body: str) -> str:
    """Check digit for EAN-13/EAN-8/UPC-A body (without check digit)."""
    total = sum(int(c) * (3 if (len(body) - i) % 2 else 1) for i, c in enumerate(body))
    return str((10 - total % 10) % 10)


def _barcode_modules(fmt: str, data: str) -> tuple[str, str]:
    """Return (module string of 0/1, human-readable text). Raises ValueError on bad data."""
    import barcode
    data = data.strip()
    if not data:
        raise ValueError("no data")
    lengths = {"ean13": (12, 13), "ean8": (7, 8), "upca": (11, 12)}
    if fmt in lengths:
        if not _digits_ok(data, lengths[fmt]):
            raise ValueError(f"{fmt} needs {' or '.join(map(str, lengths[fmt]))} digits")
        if len(data) == lengths[fmt][1] and _ean_check(data[:-1]) != data[-1]:
            raise ValueError("bad check digit")
    elif fmt == "itf":
        if not data.isdigit():
            raise ValueError("itf needs digits")
    try:
        cls = barcode.get_barcode_class(fmt)
        if fmt == "code39":
            code = cls(data, add_checksum=False)
        elif fmt in ("itf", "codabar"):
            code = cls(data, narrow=1, wide=3)   # library default is 2/5 dots; keep modules 1:3
        else:
            code = cls(data)
        modules = code.build()[0]
        text = code.get_fullcode()
    except Exception as err:  # noqa: BLE001 - library raises assorted errors on bad data
        raise ValueError(f"invalid data ({err.__class__.__name__})") from err
    if not modules or set(modules) - {"0", "1"}:
        raise ValueError("encoder returned no bars")
    return modules, text


def _paint_barcode(el: dict, cw: int, ch: int, ctx: _Ctx, label: str):
    data = ctx.sub(el["data"])
    if not data.strip():
        return None
    try:
        modules, human = _barcode_modules(el["format"], data)
    except ValueError as err:
        ctx.warnings.append(f"{label}: barcode not drawn: {err}")
        return None
    n = len(modules)
    quiet = 5
    mw = cw // (n + 2 * quiet)
    if mw < 1:
        quiet = 0
        mw = cw // n
    if mw < 1:
        ctx.warnings.append(f"{label}: box too narrow for this barcode (needs {n} dots)")
        return None
    mask = Image.new("L", (cw, ch), 0)
    d = ImageDraw.Draw(mask)
    text_h = 0
    font = None
    if el["show_text"] and ch >= 24:
        size = max(6, min(48, int(ch * 0.28)))
        while size > 6:
            font = ctx.fonts.get("", 400, False, size)
            if _text_w(font, human) <= cw:
                break
            size -= 1
        font = ctx.fonts.get("", 400, False, size)
        asc, desc = _line_box(font)
        text_h = asc + desc + 2
        if text_h > ch * 0.6:
            text_h, font = 0, None
    bar_h = max(1, ch - text_h)
    total = n * mw
    ox = (cw - total) // 2
    i = 0
    while i < n:
        if modules[i] == "1":
            j = i
            while j + 1 < n and modules[j + 1] == "1":
                j += 1
            d.rectangle((ox + i * mw, 0, ox + (j + 1) * mw - 1, bar_h - 1), fill=255)
            i = j + 1
        else:
            i += 1
    if font is not None:
        asc, _ = _line_box(font)
        tw = _text_w(font, human)
        try:
            d.text((round((cw - tw) / 2), bar_h + 1 + asc), human, font=font, fill=255, anchor="ls")
        except (ValueError, TypeError):
            d.text((round((cw - tw) / 2), bar_h + 1), human, font=font, fill=255)
        mask = mask.point(lambda v: 255 if v >= 128 else 0)
    return mask


def _paint_rect(el: dict, cw: int, ch: int, ctx: _Ctx, label: str):
    mask = Image.new("L", (cw, ch), 0)
    d = ImageDraw.Draw(mask)
    s = el["stroke"]
    if el["fill"] or s * 2 >= min(cw, ch):
        d.rectangle((0, 0, cw - 1, ch - 1), fill=255)
    elif s > 0:
        d.rectangle((0, 0, cw - 1, ch - 1), fill=255)
        d.rectangle((s, s, cw - 1 - s, ch - 1 - s), fill=0)
    return mask


def _decode_image(src: str) -> Image.Image:
    head, _, b64 = src.partition(",")
    try:
        raw = base64.b64decode(b64, validate=False)
    except (binascii.Error, ValueError) as err:
        raise ValueError("bad base64") from err
    try:
        img = Image.open(io.BytesIO(raw), formats=("PNG", "JPEG"))
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise ValueError("image has too many pixels")
        img.load()
    except ValueError:
        raise
    except Exception as err:  # noqa: BLE001 - Pillow raises many things on junk
        raise ValueError("not a valid PNG/JPEG image") from err
    return img


def _paint_image(el: dict, cw: int, ch: int, ctx: _Ctx, label: str):
    if not el["src"]:
        return None
    try:
        img = _decode_image(el["src"])
    except ValueError as err:
        ctx.warnings.append(f"{label}: image not drawn: {err}")
        return None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        img = Image.alpha_composite(Image.new("RGBA", img.size, "white"), img)
    gray = img.convert("L")
    scale = min(cw / gray.width, ch / gray.height)
    nw, nh = max(1, round(gray.width * scale)), max(1, round(gray.height * scale))
    gray = gray.resize((nw, nh), Image.Resampling.LANCZOS)
    if el["dither"]:
        bw = gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    else:
        bw = gray.point(lambda v: 255 if v >= 128 else 0)
    mask = Image.new("L", (cw, ch), 0)
    mask.paste(ImageOps.invert(bw), ((cw - nw) // 2, (ch - nh) // 2))
    return mask


_PAINTERS = {
    "text": _paint_text, "icon": _paint_icon, "qr": _paint_qr,
    "barcode": _paint_barcode, "rect": _paint_rect, "image": _paint_image,
}

_ROTATE = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
           270: Image.Transpose.ROTATE_90}


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------
def _label_length(design: dict) -> int:
    if design["length_mm"] is not None:
        return max(1, round(design["length_mm"] * 180 / 25.4))
    ext = max((e["x"] + e["w"] for e in design["elements"]), default=0)
    # Content is painted at its own x, so only the trailing end gets padding; place an
    # element at x = padding_dots for a symmetric margin.
    return max(1, ext + design["padding_dots"])


def _paste(canvas: Image.Image, layer: Image.Image, x: int, y: int, opaque: bool) -> None:
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(canvas.width, x + layer.width), min(canvas.height, y + layer.height)
    if x1 <= x0 or y1 <= y0:
        return
    part = layer.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    if opaque:
        canvas.paste(part, (x0, y0))
    else:
        region = canvas.crop((x0, y0, x1, y1))
        canvas.paste(ImageChops.lighter(region, part), (x0, y0))


def _render(design: dict, tape_mm: int, variables: dict | None, assets: Any,
            model: int | None = None) -> tuple[Image.Image, list[str]]:
    try:
        pins = tape_pins(tape_mm, model)
    except PtouchError as err:
        raise DesignError(str(err)) from err
    d = normalize_design(design)
    values = None
    if variables is not None:
        if not isinstance(variables, dict):
            raise DesignError("variables must be an object")
        values = dict(d["variables"])
        values.update({str(k): _str(v, "", 2000) for k, v in variables.items()})
    length = _label_length(d)
    if length > MAX_STRIP_DOTS:
        raise DesignError(f"label is {length} dots long; the maximum is {MAX_STRIP_DOTS}")
    ctx = _Ctx(assets, values)
    canvas = Image.new("L", (length, pins), 0)
    if d["length_mm"] is not None:
        ext = max((e["x"] + e["w"] for e in d["elements"]), default=0)
        if ext > length:
            ctx.warnings.append("content extends past the end of the fixed-length label")
    for i, el in enumerate(d["elements"]):
        label = f"{el['type']} {el['id']}"
        w, h = el["w"], el["h"]
        if w < 1 or h < 1:
            ctx.warnings.append(f"{label}: has no size")
            continue
        if el["x"] + w <= 0 or el["y"] + h <= 0 or el["x"] >= length or el["y"] >= pins:
            ctx.warnings.append(f"{label}: is outside the label")
            continue
        if el["x"] < 0 or el["y"] < 0 or el["x"] + w > length or el["y"] + h > pins:
            ctx.warnings.append(f"{label}: extends beyond the label")
        w, h = min(w, LAYER_LIMIT), min(h, LAYER_LIMIT)
        ctx.pixels += w * h
        if ctx.pixels > PIXEL_BUDGET:
            raise DesignError("design is too large to render")
        cw, ch = (w, h) if el["rotation"] in (0, 180) else (h, w)
        mask = _PAINTERS[el["type"]](el, cw, ch, ctx, label)
        if mask is None:
            if not el["invert"]:
                continue
            mask = Image.new("L", (cw, ch), 0)
        if el["rotation"]:
            mask = mask.transpose(_ROTATE[el["rotation"]])
        if el["invert"]:
            mask = ImageChops.invert(mask)
        _paste(canvas, mask, el["x"], el["y"], el["invert"])
    out = ImageOps.invert(canvas).point(lambda v: 255 if v >= 128 else 0).convert("1")
    return out, ctx.warnings


def render_design(design: dict, tape_mm: int, *, variables: dict | None = None,
                  assets=None, model: int | None = None) -> Image.Image:
    """Render *design* for *tape_mm* tape on printer *model*; returns a mode "1" image of
    height tape_pins(tape_mm, model)."""
    try:
        img, _ = _render(design, tape_mm, variables, assets, model)
    except PtouchError:
        raise
    except MemoryError as err:
        raise DesignError("design is too large to render") from err
    except Exception as err:  # noqa: BLE001 - never leak anything but DesignError
        raise DesignError(f"cannot render design: {err.__class__.__name__}: {err}") from err
    return img


def design_warnings(design: dict, tape_mm: int, *, variables: dict | None = None,
                    assets=None, model: int | None = None) -> list[str]:
    """Human-readable problems (element outside the label, text clipped, bad barcode ...)."""
    try:
        return _render(design, tape_mm, variables, assets, model)[1]
    except PtouchError as err:
        return [str(err)]
    except Exception as err:  # noqa: BLE001
        return [f"cannot render design: {err.__class__.__name__}"]
