"""Render text / QR / images into 1-bit label bitmaps sized for a tape width."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw, ImageFont

from .errors import ProtocolError
from .protocol import tape_pins

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf",
)

_PAD_X = 6   # blank dots at each end of text labels
_PAD_Y = 2


def load_font(size: int, path: str | None = None) -> ImageFont.ImageFont:
    for p in ([path] if path else []) + list(_FONT_CANDIDATES):
        if p and os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    if path:
        raise ProtocolError(f"font not found: {path}")
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow without FreeType
        return ImageFont.load_default()


def _line_metrics(font: ImageFont.ImageFont) -> tuple[int, int]:
    """(top, height) of a representative line, so lines stack consistently."""
    l, t, r, b = font.getbbox("Hgjpq|Ä")
    return t, b - t


def _fit_font(lines: list[str], max_h: int, font_path: str | None) -> ImageFont.ImageFont:
    lo, hi, best = 4, max(8, max_h), 4
    while lo <= hi:
        mid = (lo + hi) // 2
        f = load_font(mid, font_path)
        _, lh = _line_metrics(f)
        if lh * len(lines) + (len(lines) - 1) * max(1, mid // 8) <= max_h:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    return load_font(best, font_path)


def render_text(text: str, tape_mm: int, *, font_size: int | None = None,
                font_path: str | None = None, align: str = "center",
                model: int | None = None) -> Image.Image:
    pins = tape_pins(tape_mm, model)
    lines = text.split("\n") or [""]
    avail = pins - 2 * _PAD_Y
    font = load_font(font_size, font_path) if font_size else _fit_font(lines, avail, font_path)
    top, lh = _line_metrics(font)
    gap = max(1, getattr(font, "size", 8) // 8)
    scratch = ImageDraw.Draw(Image.new("1", (1, 1)))
    widths = [int(scratch.textlength(l, font=font)) for l in lines]
    block_h = lh * len(lines) + gap * (len(lines) - 1)
    img = Image.new("1", (max(widths + [1]) + 2 * _PAD_X, pins), 1)
    d = ImageDraw.Draw(img)
    y = (pins - block_h) // 2
    for line, w in zip(lines, widths):
        x = {"left": _PAD_X, "right": img.width - _PAD_X - w}.get(align, (img.width - w) // 2)
        d.text((x, y - top), line, font=font, fill=0)
        y += lh + gap
    return img


def render_qr(data: str, tape_mm: int, *, text: str | None = None,
              font_path: str | None = None, font_size: int | None = None,
              model: int | None = None) -> Image.Image:
    try:
        import segno
    except ImportError as err:  # pragma: no cover
        raise ProtocolError("segno is required for QR labels") from err
    pins = tape_pins(tape_mm, model)
    qr = segno.make(data, error="m", micro=False)
    n = qr.symbol_size(scale=1, border=0)[0]
    avail = pins - 2 * _PAD_Y
    scale = max(1, avail // n)
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=scale, border=0, dark="black", light="white")
    buf.seek(0)
    code = Image.open(buf).convert("1")
    if code.height > pins:
        raise ProtocolError("QR code too large for this tape; use shorter data or wider tape")
    parts = [code]
    if text:
        parts.append(render_text(text, tape_mm, font_size=font_size, font_path=font_path, align="left",
                                 model=model))
    gap = 8
    img = Image.new("1", (_PAD_X + sum(p.width for p in parts) + gap * (len(parts) - 1) + _PAD_X, pins), 1)
    x = _PAD_X
    for p in parts:
        img.paste(p, (x, (pins - p.height) // 2))
        x += p.width + gap
    return img


def render_image(src: Image.Image | bytes, tape_mm: int, *, dither: bool = True,
                 model: int | None = None) -> Image.Image:
    pins = tape_pins(tape_mm, model)
    if isinstance(src, (bytes, bytearray)):
        src = Image.open(io.BytesIO(src))
    if src.mode in ("RGBA", "LA", "P"):
        src = src.convert("RGBA")
        bg = Image.new("RGBA", src.size, "white")
        src = Image.alpha_composite(bg, src)
    gray = src.convert("L")
    w = max(1, round(gray.width * pins / gray.height))
    gray = gray.resize((w, pins), Image.Resampling.LANCZOS)
    return gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE)
