"""Brother P-touch raster protocol (PT-P700 / P750W / P710BT / P300BT family).

Pure Python + Pillow. No Home Assistant imports, so it is shared by the
integration and the standalone bridge.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from PIL import Image, ImageOps

from .errors import ProtocolError

DPI = 180
TOTAL_PINS = 128
LINE_BYTES = TOTAL_PINS // 8
STATUS_LEN = 32

# tape width (mm; 4 == 3.5 mm) -> (printable pins, left margin pins)
TAPE_GEOMETRY: dict[int, tuple[int, int]] = {
    4: (24, 52),
    6: (32, 48),
    9: (50, 39),
    12: (70, 29),
    18: (112, 8),
    24: (128, 0),
}

# Per-model differences, keyed by the model code (status byte 4). Unknown models
# use TAPE_GEOMETRY and have a cutter.
MODEL_P300BT = 0x72
MODEL_NAMES: dict[int, str] = {MODEL_P300BT: "PT-P300BT"}
# model -> tape width -> (printable pins, left margin pins), overriding TAPE_GEOMETRY
MODEL_TAPE_GEOMETRY: dict[int, dict[int, tuple[int, int]]] = {
    MODEL_P300BT: {12: (64, 32)},   # 64-dot head, centred in the 128-pin raster
}
# models with a manual cutter only; for them "auto cut" (ESC i M bit 6) prints a cut mark
MODELS_WITHOUT_CUTTER: frozenset[int] = frozenset({MODEL_P300BT})

MEDIA_NONE = 0x00
MEDIA_LAMINATED = 0x01
MEDIA_NON_LAMINATED = 0x03
MEDIA_HS_2_1 = 0x11
MEDIA_HS_3_1 = 0x17
MEDIA_INCOMPATIBLE = 0xFF

MEDIA_TYPES = {
    MEDIA_NONE: "no_tape",
    MEDIA_LAMINATED: "laminated",
    MEDIA_NON_LAMINATED: "non_laminated",
    MEDIA_HS_2_1: "heat_shrink_2_1",
    MEDIA_HS_3_1: "heat_shrink_3_1",
    MEDIA_INCOMPATIBLE: "incompatible",
}

TAPE_COLOURS = {
    0x01: "white", 0x02: "other", 0x03: "clear", 0x04: "red", 0x05: "blue",
    0x06: "yellow", 0x07: "green", 0x08: "black", 0x09: "clear_white_text",
    0x20: "matte_white", 0x21: "matte_clear", 0x22: "matte_silver",
    0x23: "satin_gold", 0x24: "satin_silver", 0x30: "blue_d", 0x31: "red_d",
    0x40: "fluorescent_orange", 0x41: "fluorescent_yellow", 0x50: "berry_pink",
    0x51: "light_gray", 0x52: "lime_green", 0x60: "yellow_f", 0x61: "pink_f",
    0x62: "blue_f", 0x70: "white_heat_shrink", 0x90: "white_flex",
    0x91: "yellow_flex", 0xF0: "cleaning", 0xF1: "stencil", 0xFF: "incompatible",
}

TEXT_COLOURS = {
    0x01: "white", 0x02: "other", 0x04: "red", 0x05: "blue", 0x08: "black",
    0x0A: "gold", 0x62: "blue_f", 0xF0: "cleaning", 0xF1: "stencil",
    0xFF: "incompatible",
}

ERROR1 = {0: "no_media", 1: "end_of_media", 2: "cutter_jam", 3: "weak_battery",
          4: "high_voltage_adapter"}
ERROR2 = {0: "replace_media", 1: "expansion_buffer_full", 2: "communication_error",
          3: "communication_buffer_full", 4: "cover_open", 5: "cancel_key",
          6: "media_cannot_be_fed", 7: "system_error"}

STATUS_REPLY = 0x00
STATUS_COMPLETED = 0x01
STATUS_ERROR = 0x02
STATUS_NOTIFICATION = 0x05
STATUS_PHASE_CHANGE = 0x06

ORIENTATIONS = ("normal", "flip_pins", "flip_feed", "rotate_180")

CMD_INVALIDATE = b"\x00" * 100
CMD_INIT = b"\x1b@"
CMD_STATUS_REQUEST = b"\x1biS"
CMD_RASTER_MODE = b"\x1bia\x01"


@dataclass(frozen=True)
class PrinterStatus:
    """Decoded 32-byte status reply."""

    raw: bytes
    error1: int
    error2: int
    media_width: int
    media_type: int
    status_type: int
    phase: int
    tape_colour: int
    text_colour: int
    model: int = 0

    @classmethod
    def parse(cls, raw: bytes) -> "PrinterStatus":
        if len(raw) != STATUS_LEN or raw[0] != 0x80 or raw[1] != 0x20:
            raise ProtocolError(f"invalid status packet: {raw.hex()}")
        return cls(raw=bytes(raw), error1=raw[8], error2=raw[9], media_width=raw[10],
                   media_type=raw[11], status_type=raw[18], phase=raw[19],
                   tape_colour=raw[24], text_colour=raw[25], model=raw[4])

    @property
    def errors(self) -> list[str]:
        out = [n for b, n in ERROR1.items() if self.error1 & (1 << b)]
        out += [n for b, n in ERROR2.items() if self.error2 & (1 << b)]
        return out

    @property
    def has_tape(self) -> bool:
        return self.media_width in TAPE_GEOMETRY and self.media_type != MEDIA_NONE

    @property
    def state(self) -> str:
        if self.errors:
            return "error"
        return "printing" if self.phase == 0x01 else "idle"

    @property
    def model_name(self) -> str | None:
        return MODEL_NAMES.get(self.model)

    @property
    def media_type_name(self) -> str:
        return MEDIA_TYPES.get(self.media_type, f"unknown_{self.media_type:#04x}")

    @property
    def tape_colour_name(self) -> str:
        return TAPE_COLOURS.get(self.tape_colour, f"unknown_{self.tape_colour:#04x}")

    @property
    def text_colour_name(self) -> str:
        return TEXT_COLOURS.get(self.text_colour, f"unknown_{self.text_colour:#04x}")


def split_status_packets(buf: bytearray) -> list[PrinterStatus]:
    """Pop every complete status packet out of ``buf`` (resyncing on 0x80 0x20)."""
    out: list[PrinterStatus] = []
    while True:
        idx = buf.find(b"\x80\x20")
        if idx < 0:
            del buf[:max(0, len(buf) - 1)]
            return out
        del buf[:idx]
        if len(buf) < STATUS_LEN:
            return out
        out.append(PrinterStatus.parse(bytes(buf[:STATUS_LEN])))
        del buf[:STATUS_LEN]


# --------------------------------------------------------------------------
# TIFF PackBits
# --------------------------------------------------------------------------
def packbits(data: bytes) -> bytes:
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        run = 1
        while i + run < n and run < 128 and data[i + run] == data[i]:
            run += 1
        if run >= 2:
            out.append(257 - run)
            out.append(data[i])
            i += run
            continue
        start = i
        i += 1
        while i < n and i - start < 128 and not (i + 1 < n and data[i] == data[i + 1]):
            i += 1
        out.append(i - start - 1)
        out += data[start:i]
    return bytes(out)


def unpackbits(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        h = data[i]
        i += 1
        if h < 128:
            out += data[i:i + h + 1]
            i += h + 1
        elif h > 128:
            out += bytes([data[i]]) * (257 - h)
            i += 1
    return bytes(out)


# --------------------------------------------------------------------------
# Image -> raster lines -> job
# --------------------------------------------------------------------------
def tape_geometry(tape_mm: int, model: int | None = None) -> tuple[int, int]:
    """(printable pins, left margin pins) of *tape_mm* tape on printer *model*."""
    try:
        return MODEL_TAPE_GEOMETRY.get(model, {}).get(tape_mm) or TAPE_GEOMETRY[tape_mm]
    except KeyError:
        raise ProtocolError(f"unsupported tape width {tape_mm} mm") from None


def tape_pins(tape_mm: int, model: int | None = None) -> int:
    return tape_geometry(tape_mm, model)[0]


def has_cutter(model: int | None) -> bool:
    return model not in MODELS_WITHOUT_CUTTER


def image_to_lines(img: Image.Image, tape_mm: int, orientation: str = "normal",
                   model: int | None = None) -> list[bytes]:
    """Convert a label image (height == printable pins) into 16-byte raster lines.

    One raster line is one column of the image; x=0 is the first line fed.
    """
    pins, left = tape_geometry(tape_mm, model)
    if orientation not in ORIENTATIONS:
        raise ProtocolError(f"unknown orientation {orientation!r}")
    if img.height != pins:
        raise ProtocolError(f"image height {img.height}px != {pins}px for {tape_mm} mm tape")
    if orientation in ("flip_pins", "rotate_180"):
        img = ImageOps.flip(img.convert("L"))
    if orientation in ("flip_feed", "rotate_180"):
        img = ImageOps.mirror(img.convert("L"))
    ink = img.convert("L").point(lambda p: 255 if p < 128 else 0)
    cols = ink.transpose(Image.Transpose.TRANSPOSE)  # (pins, width)
    canvas = Image.new("L", (TOTAL_PINS, cols.height), 0)
    canvas.paste(cols, (left, 0))
    data = canvas.convert("1", dither=Image.Dither.NONE).tobytes()
    return [data[i * LINE_BYTES:(i + 1) * LINE_BYTES] for i in range(cols.height)]


MAX_STRIP_DOTS = 6000        # ~850 mm; stays well inside the printer's maximum length


@dataclass
class JobOptions:
    tape_mm: int
    media_type: int = MEDIA_LAMINATED
    auto_cut: bool = True
    cut_each: bool = False       # one standalone job per label instead of one strip
    margin_dots: int = 14        # feed margin / gap between labels; 14 dots == ~2 mm at 180 dpi
    compress: bool = True
    orientation: str = "normal"
    model: int | None = None     # status byte 4; None = PT-P7xx geometry
    chain: bool = False          # no feed at the end: the label stays inside until the next job
    cut_mark: bool = False       # models without a cutter: a cut mark after each label


def mm_to_dots(mm: float) -> int:
    return round(mm * DPI / 25.4)


def compose_strip(images: Sequence[Image.Image], gap_dots: int) -> Image.Image:
    """Lay labels side by side (blank gap between) as ONE label image."""
    if len(images) == 1:
        return images[0]
    h = images[0].height
    if any(i.height != h for i in images):
        raise ProtocolError("all labels in a strip must have the same height")
    width = sum(i.width for i in images) + gap_dots * (len(images) - 1)
    strip = Image.new("1", (width, h), 1)
    x = 0
    for img in images:
        strip.paste(img.convert("1"), (x, 0))
        x += img.width + gap_dots
    return strip


def build_job(images: Sequence[Image.Image], opts: JobOptions) -> bytes:
    """Build ONE print job: a single page, so one leader and one cut.

    Several images become one continuous strip (see compose_strip). Hardware
    testing showed this is the only mode that always feeds and cuts at the end:
    chain printing keeps the last page inside the printer until the next job.
    """
    if not images:
        raise ProtocolError("no images to print")
    if opts.media_type not in (MEDIA_LAMINATED, MEDIA_NON_LAMINATED, MEDIA_HS_2_1, MEDIA_HS_3_1):
        raise ProtocolError(f"cannot print on media type {opts.media_type:#04x}")
    img = compose_strip(images, max(0, opts.margin_dots))
    if img.width > MAX_STRIP_DOTS:
        raise ProtocolError(f"label is {img.width} dots long; the maximum is {MAX_STRIP_DOTS}")
    lines = image_to_lines(img, opts.tape_mm, opts.orientation, opts.model)
    margin = max(0, min(opts.margin_dots, 0xFFFF))
    out = bytearray(CMD_INVALIDATE + CMD_INIT + CMD_RASTER_MODE)
    # print information: flags(kind|width|recover), type, width, length, lines, page, 0
    out += b"\x1biz" + bytes([0x02 | 0x04 | 0x80, opts.media_type, opts.tape_mm, 0])
    out += len(lines).to_bytes(4, "little") + bytes([0, 0])
    # bit 6 cuts; on a model without a cutter it prints a cut mark instead
    cut = opts.auto_cut if has_cutter(opts.model) else opts.cut_mark
    out += b"\x1biM" + bytes([0x40 if cut else 0x00])
    out += b"\x1biK" + (b"\x00" if opts.chain else b"\x08")   # 0x08: no chain printing, feed at the end
    out += b"\x1bid" + margin.to_bytes(2, "little")
    out += b"M" + (b"\x02" if opts.compress else b"\x00")
    for line in lines:
        if not any(line):
            out += b"Z"
        elif opts.compress:
            packed = packbits(line)
            out += b"G" + len(packed).to_bytes(2, "little") + packed
        else:
            out += b"G" + LINE_BYTES.to_bytes(2, "little") + line
    out += b"\x1a"
    return bytes(out)


def build_jobs(images: Sequence[Image.Image], opts: JobOptions) -> list[bytes]:
    """One job per label with ``cut_each`` or cut marks (a mark ends a job); otherwise as few strips as fit."""
    if not images:
        raise ProtocolError("no images to print")
    if opts.cut_each or (opts.cut_mark and not has_cutter(opts.model)):
        groups = [[i] for i in images]
    else:
        groups, cur, length = [], [], 0
        for img in images:
            extra = img.width + (opts.margin_dots if cur else 0)
            if cur and length + extra > MAX_STRIP_DOTS:
                groups.append(cur)
                cur, length, extra = [], 0, img.width
            cur.append(img)
            length += extra
        groups.append(cur)
    return [build_job(g, opts) for g in groups]


def build_feed_job(opts: JobOptions) -> bytes:
    """Feed the tape out without printing, e.g. to release a label held by chain printing.

    A bare print command hangs the printer, so this is a page of one blank line.
    """
    blank = Image.new("1", (1, tape_pins(opts.tape_mm, opts.model)), 1)
    return build_job([blank], replace(opts, chain=False, auto_cut=False, cut_mark=False, margin_dots=0))
