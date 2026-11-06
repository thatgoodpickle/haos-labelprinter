"""Ready-made label templates for the label editor.

Every template is a *builder*: a function of the tape geometry that returns design elements
(see docs/EDITOR_CONTRACT.md section 1), so one definition works at 12 mm (70 dots) as well as at
24 mm (128 dots). Content uses ``{{ variable }}`` placeholders with defaults, so a template
previews well immediately. No Home Assistant imports.

Public API: ``TEMPLATE_VERSION``, ``CATEGORIES``, ``list_templates()``, ``build_template()``.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Callable

from .errors import PtouchError
from .protocol import tape_pins

TEMPLATE_VERSION = 1

CATEGORIES = [
    "Kitchen & Food",
    "Home & Storage",
    "Cables & Network",
    "Electronics & Maker",
    "Office & Admin",
    "People & Names",
    "Smart Home",
    "Safety & Warning",
]

# Fonts used by the templates (Google Fonts families, weights verified against the catalogue).
BOLD = {"font": "Roboto", "weight": 800}
MED = {"font": "Roboto", "weight": 600}
COND = {"font": "Roboto Condensed", "weight": 800}
COND_SUB = {"font": "Roboto Condensed", "weight": 600}
MONO = {"font": "Roboto Mono", "weight": 700}
HAND = {"font": "Permanent Marker", "weight": 400}
SERIF = {"font": "Roboto Slab", "weight": 800}
FONTS_USED = ("Roboto", "Roboto Condensed", "Roboto Mono", "Permanent Marker", "Roboto Slab")

# Every icon the templates use, in one place (validated against the MDI list by the live test).
ICONS = {
    "pantry": "mdi:grain",
    "freezer": "mdi:snowflake",
    "box": "mdi:package-variant",
    "key": "mdi:key-variant",
    "water": "mdi:water",
    "reminder": "mdi:calendar-clock",
    "network": "mdi:lan",
    "wifi": "mdi:wifi",
    "mail": "mdi:mailbox-outline",
    "chip": "mdi:chip",
    "check": "mdi:check-decagram",
    "kid": "mdi:star-outline",
    "light": "mdi:lightbulb-outline",
    "home": "mdi:home-automation",
    "fragile": "mdi:glass-fragile",
    "alert": "mdi:alert",
    "unplug": "mdi:power-plug-off",
    "valve": "mdi:valve",
    "battery": "mdi:battery-outline",
    "spool": "mdi:printer-3d-nozzle",
}


class TemplateError(PtouchError):
    """Unknown template or unsupported tape width."""


# ---------------------------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------------------------
class Geo:
    """Tape geometry: H = pins; m = margin; the inner band is y0..y0+ih."""

    def __init__(self, tape_mm: int, model: int | None = None):
        self.tape = tape_mm
        self.H = tape_pins(tape_mm, model)
        self.m = max(2, round(self.H * 0.07))
        self.g = max(2, round(self.H * 0.04))
        self.y0 = self.m
        self.ih = self.H - 2 * self.m
        self.qm = 3  # smaller margin for QR codes (more modules per dot)
        self.qs = self.H - 2 * self.qm  # QR box edge

    def rows(self, *weights: float) -> list[tuple[int, int]]:
        """Split the inner band into rows (y, h) with the given weights and gap g between."""
        n = len(weights)
        avail = self.ih - self.g * (n - 1)
        total = float(sum(weights))
        out, y, used = [], self.y0, 0
        for i, w in enumerate(weights):
            h = round(avail * w / total) if i < n - 1 else avail - used
            out.append((y, h))
            used += h
            y += h + self.g
        return out


class Els:
    """Collects elements with auto ids."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def _add(self, kind: str, x, y, w, h, **kw) -> None:
        el = {"id": f"{kind}{len(self.items) + 1}", "type": kind,
              "x": int(round(x)), "y": int(round(y)), "w": int(round(w)), "h": int(round(h))}
        el.update(kw)
        self.items.append(el)

    def text(self, x, y, w, h, text, style=BOLD, align="center", valign="middle", **kw):
        self._add("text", x, y, w, h, text=text, size="auto", align=align, valign=valign,
                  **style, **kw)

    def icon(self, x, y, w, h, icon, **kw):
        self._add("icon", x, y, w, h, icon=icon, **kw)

    def qr(self, x, y, w, h, data, ecc="m", quiet=0):
        self._add("qr", x, y, w, h, data=data, ecc=ecc, quiet=quiet)

    def barcode(self, x, y, w, h, data, fmt="code128", show_text=True):
        self._add("barcode", x, y, w, h, format=fmt, data=data, show_text=show_text)

    def rect(self, x, y, w, h, stroke=2, fill=False):
        self._add("rect", x, y, w, h, stroke=stroke, fill=fill)


Builder = Callable[[Geo, Els], int]  # fills elements, returns used length in dots


@dataclass
class _Tpl:
    id: str
    name: str
    category: str
    description: str
    tape_mm_hint: int
    tapes: tuple
    variables: dict
    build: Builder


def _v(label: str, default: str) -> dict:
    return {"label": label, "default": default}


ALL = (4, 6, 9, 12, 18, 24)  # 4 = 3.5 mm tape, as the printer reports it
T6 = (6, 9, 12, 18, 24)
T9 = (9, 12, 18, 24)
T12 = (12, 18, 24)

_REGISTRY: dict[str, _Tpl] = {}


def _tpl(id, name, category, description, hint, tapes, variables):
    def deco(fn: Builder) -> Builder:
        assert category in CATEGORIES, category
        assert id not in _REGISTRY, id
        _REGISTRY[id] = _Tpl(id, name, category, description, hint, tuple(tapes), variables, fn)
        return fn
    return deco


# ---------------------------------------------------------------------------------------------
# Kitchen & Food
# ---------------------------------------------------------------------------------------------
@_tpl("pantry-jar", "Pantry jar", "Kitchen & Food",
      "Icon and a big name for jars, canisters and bins.", 12, ALL,
      {"name": _v("Contents", "Flour")})
def _pantry(g: Geo, e: Els) -> int:
    x = 0
    if g.H >= 50:
        e.icon(0, g.y0, g.ih, g.ih, ICONS["pantry"])
        x = g.ih + g.m
    e.text(x, g.y0, 240, g.ih, "{{ name }}", BOLD, align="left" if x else "center")
    return x + 240


@_tpl("spice-jar", "Spice jar", "Kitchen & Food",
      "Spice name with a short note (ground, smoked, best before ...).", 12, T12,
      {"name": _v("Spice", "Paprika"), "note": _v("Note", "Smoked, ground")})
def _spice(g: Geo, e: Els) -> int:
    (y1, h1), (y2, h2) = g.rows(0.62, 0.38)
    e.text(0, y1, 250, h1, "{{ name }}", COND)
    e.text(0, y2, 250, h2, "{{ note }}", COND_SUB)
    return 250


@_tpl("freezer-date", "Freezer food", "Kitchen & Food",
      "Food name, date frozen and portions - for freezer boxes and bags.", 12, T12,
      {"name": _v("Food", "Chili con carne"), "date": _v("Frozen on", "2026-11-06"),
       "portions": _v("Portions", "4")})
def _freezer(g: Geo, e: Els) -> int:
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(0, y1, 420, h1, "{{ name }}", BOLD, align="left")
    e.icon(0, y2, h2, h2, ICONS["freezer"])
    e.text(h2 + 6, y2, 190, h2, "{{ date }}", MONO, align="left")
    e.text(h2 + 206, y2, 214 - h2, h2, "{{ portions }}x", MONO, align="right")
    return 420


@_tpl("use-by", "Use by / leftovers", "Kitchen & Food",
      "Inverted 'USE BY' tag with a big date for leftovers and opened packs.", 12, T9,
      {"date": _v("Date", "12 NOV")})
def _useby(g: Geo, e: Els) -> int:
    w1 = round(g.ih * 2.9)
    e.text(0, g.y0, w1, g.ih, "USE BY", COND, invert=True)
    e.text(w1 + g.m, g.y0, round(g.ih * 3.6), g.ih, "{{ date }}", COND, align="left")
    return w1 + g.m + round(g.ih * 3.6)


# ---------------------------------------------------------------------------------------------
# Home & Storage
# ---------------------------------------------------------------------------------------------
@_tpl("storage-bin-qr", "Storage bin with QR", "Home & Storage",
      "QR code plus title and contents - scan to open the bin in your inventory app.", 12, T12,
      {"code": _v("QR content / bin ID", "BIN-042"), "title": _v("Title", "Winter clothes"),
       "contents": _v("Contents", "Gloves, scarves, hats")})
def _bin(g: Geo, e: Els) -> int:
    e.qr(0, g.qm, g.qs, g.qs, "{{ code }}", "m", 0)
    x = g.qs + 12
    (y1, h1), (y2, h2) = g.rows(0.55, 0.45)
    e.text(x, y1, 330, h1, "{{ title }}", BOLD, align="left")
    e.text(x, y2, 330, h2, "{{ contents }}", COND_SUB, align="left")
    return x + 330


@_tpl("drawer-shelf", "Drawer / shelf", "Home & Storage",
      "Numbered inverted square plus the name of what is inside.", 12, T6,
      {"number": _v("Number", "3"), "name": _v("Contents", "Batteries & tape")})
def _drawer(g: Geo, e: Els) -> int:
    e.text(0, g.y0, g.ih, g.ih, "{{ number }}", BOLD, invert=True)
    e.text(g.ih + g.m + 2, g.y0, 260, g.ih, "{{ name }}", COND, align="left")
    return g.ih + g.m + 2 + 260


@_tpl("storage-box", "Storage box", "Home & Storage",
      "Icon, title and a short contents line for seasonal and moving boxes.", 12, T12,
      {"title": _v("Title", "Christmas"), "sub": _v("Contents", "Lights & ornaments")})
def _storage_box(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["box"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 340, h1, "{{ title }}", BOLD, align="left")
    e.text(x, y2, 340, h2, "{{ sub }}", COND_SUB, align="left")
    return x + 340


@_tpl("key-tag", "Key tag", "Home & Storage",
      "Framed key label: which door or lock the key belongs to.", 12, T9,
      {"name": _v("Name", "Garage")})
def _key(g: Geo, e: Els) -> int:
    w = 220
    e.rect(0, 0, w + g.ih + 3 * g.m, g.H, stroke=3)
    e.icon(g.m + 3, g.y0 + 3, g.ih - 6, g.ih - 6, ICONS["key"])
    e.text(g.ih + 2 * g.m, g.y0 + 2, w, g.ih - 4, "{{ name }}", BOLD)
    return w + g.ih + 3 * g.m


@_tpl("plant-marker", "Plant marker", "Home & Storage",
      "Plant name in a handwriting font with a watering hint.", 12, T12,
      {"name": _v("Plant", "Basil"), "water": _v("Watering", "every 2 days")})
def _plant(g: Geo, e: Els) -> int:
    (y1, h1), (y2, h2) = g.rows(0.62, 0.38)
    e.text(0, y1, 250, h1, "{{ name }}", HAND)
    e.icon(0, y2, h2, h2, ICONS["water"])
    e.text(h2 + 4, y2, 246 - h2, h2, "{{ water }}", COND_SUB, align="left")
    return 250


@_tpl("daily-reminder", "Daily reminder", "Home & Storage",
      "Neutral reminder tag (time of day plus a note you choose), e.g. for a pill box.", 12, T12,
      {"when": _v("When", "Morning"), "note": _v("Note", "With breakfast")})
def _reminder(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["reminder"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.6, 0.4)
    e.text(x, y1, 300, h1, "{{ when }}", BOLD, align="left")
    e.text(x, y2, 300, h2, "{{ note }}", COND_SUB, align="left")
    return x + 300


# ---------------------------------------------------------------------------------------------
# Cables & Network
# ---------------------------------------------------------------------------------------------
@_tpl("cable-flag", "Cable flag", "Cables & Network",
      "Text printed twice with a blank middle: fold it around a cable so both sides read.",
      12, (6, 9, 12, 18),
      {"name": _v("Cable name", "NAS-01 LAN1")})
def _flag(g: Geo, e: Els) -> int:
    tw, gap = 230, 150
    e.text(0, g.y0, tw, g.ih, "{{ name }}", COND)
    e.rect(tw + gap // 2 - 1, round(g.H * 0.25), 2, round(g.H * 0.5), fill=True)
    e.text(tw + gap, g.y0, tw, g.ih, "{{ name }}", COND)
    return 2 * tw + gap


@_tpl("patch-port", "Patch panel port", "Cables & Network",
      "Port number in an inverted box plus where the cable goes.", 12, T6,
      {"port": _v("Port", "07"), "dest": _v("Destination", "Office desk")})
def _port(g: Geo, e: Els) -> int:
    w1 = round(g.ih * 1.6)
    e.text(0, g.y0, w1, g.ih, "{{ port }}", MONO, invert=True)
    e.text(w1 + g.m + 2, g.y0, 300, g.ih, "{{ dest }}", COND, align="left")
    return w1 + g.m + 2 + 300


@_tpl("network-device", "Network device", "Cables & Network",
      "Hostname and IP address for switches, servers and access points.", 12, T12,
      {"host": _v("Hostname", "nas-01"), "ip": _v("IP address", "192.168.1.20")})
def _netdev(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["network"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 330, h1, "{{ host }}", BOLD, align="left")
    e.text(x, y2, 330, h2, "{{ ip }}", MONO, align="left")
    return x + 330


@_tpl("wifi-qr", "Wi-Fi guest label", "Cables & Network",
      "Scannable Wi-Fi QR (WPA) with network name and password. Needs 18 mm or wider tape.",
      18, (18, 24),
      {"ssid": _v("Network name", "HomeNet"), "password": _v("Password", "welcome123")})
def _wifi(g: Geo, e: Els) -> int:
    e.qr(0, g.qm, g.qs, g.qs, "WIFI:T:WPA;S:{{ ssid }};P:{{ password }};;", "l", 0)
    x = g.qs + 14
    r = g.rows(0.28, 0.36, 0.36)
    e.icon(x, r[0][0], r[0][1], r[0][1], ICONS["wifi"])
    e.text(x + r[0][1] + 6, r[0][0], 280, r[0][1], "Wi-Fi", MED, align="left")
    e.text(x, r[1][0], 330, r[1][1], "{{ ssid }}", BOLD, align="left")
    e.text(x, r[2][0], 330, r[2][1], "{{ password }}", MONO, align="left")
    return x + 330


@_tpl("breaker", "Breaker / fuse", "Cables & Network",
      "Circuit number in an inverted square plus what the breaker feeds.", 12, T6,
      {"no": _v("Circuit", "7"), "name": _v("Feeds", "Kitchen sockets")})
def _breaker(g: Geo, e: Els) -> int:
    e.text(0, g.y0, g.ih, g.ih, "{{ no }}", BOLD, invert=True)
    e.text(g.ih + g.m + 2, g.y0, 270, g.ih, "{{ name }}", COND, align="left")
    return g.ih + g.m + 2 + 270


# ---------------------------------------------------------------------------------------------
# Electronics & Maker
# ---------------------------------------------------------------------------------------------
@_tpl("component-bin", "Component bin", "Electronics & Maker",
      "Value in big monospace plus the part type: resistor, capacitor, screws ...", 12, T12,
      {"value": _v("Value", "4.7 k"), "kind": _v("Part", "Resistor 1/4 W 1%")})
def _component(g: Geo, e: Els) -> int:
    (y1, h1), (y2, h2) = g.rows(0.62, 0.38)
    e.text(0, y1, 300, h1, "{{ value }}", MONO)
    e.text(0, y2, 300, h2, "{{ kind }}", COND_SUB)
    return 300


@_tpl("filament-spool", "Filament spool", "Electronics & Maker",
      "Material in an inverted box, colour and print temperatures for 3D printer spools.",
      12, T12,
      {"material": _v("Material", "PETG"), "color": _v("Colour", "Galaxy black"),
       "temps": _v("Nozzle / bed", "230 / 70 °C")})
def _filament(g: Geo, e: Els) -> int:
    w1 = round(g.ih * 2.8)
    e.text(0, g.y0, w1, g.ih, "{{ material }}", BOLD, invert=True)
    x = w1 + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 340, h1, "{{ color }}", BOLD, align="left")
    e.text(x, y2, 340, h2, "{{ temps }}", MONO, align="left")
    return x + 340


@_tpl("test-tag", "Tested / inspected", "Electronics & Maker",
      "Check mark, status, date and initials for tested equipment and QC.", 12, T12,
      {"status": _v("Status", "TESTED OK"), "date": _v("Date", "2026-11-06"),
       "who": _v("Initials", "AE")})
def _testtag(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["check"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 330, h1, "{{ status }}", BOLD, align="left")
    e.text(x, y2, 330, h2, "{{ date }}  {{ who }}", MONO, align="left")
    return x + 330


@_tpl("project-tag", "Project / version", "Electronics & Maker",
      "Chip icon, project name and an inverted version box for prototypes and boards.", 12, T9,
      {"name": _v("Project", "Garage sensor"), "version": _v("Version", "v1.2")})
def _project(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["chip"])
    x = g.ih + 10
    e.text(x, g.y0, 290, g.ih, "{{ name }}", BOLD, align="left")
    e.text(x + 300, g.y0, round(g.ih * 2.3), g.ih, "{{ version }}", MONO, invert=True)
    return x + 300 + round(g.ih * 2.3)


# ---------------------------------------------------------------------------------------------
# Office & Admin
# ---------------------------------------------------------------------------------------------
@_tpl("file-folder", "File folder / tab", "Office & Admin",
      "Folder title with the year in an inverted box.", 12, T9,
      {"name": _v("Title", "Taxes"), "year": _v("Year", "2026")})
def _folder(g: Geo, e: Els) -> int:
    e.text(0, g.y0, 330, g.ih, "{{ name }}", BOLD, align="left")
    e.text(344, g.y0, round(g.ih * 2.6), g.ih, "{{ year }}", MONO, invert=True)
    return 344 + round(g.ih * 2.6)


@_tpl("binder-spine", "Binder spine", "Office & Admin",
      "Long serif title between two rules, for ring binders and book spines.", 18, T12,
      {"title": _v("Title", "Household & Insurance"), "year": _v("Year", "2026")})
def _spine(g: Geo, e: Els) -> int:
    W = 900
    e.rect(0, g.y0 - 1, W, 2, fill=True)
    e.rect(0, g.H - g.y0 - 1, W, 2, fill=True)
    ty, th = g.y0 + g.g + 2, g.ih - 2 * g.g - 4
    e.text(0, ty, 700, th, "{{ title }}", SERIF, align="left")
    e.text(720, ty, W - 720, th, "{{ year }}", SERIF, align="right")
    return W


@_tpl("asset-tag", "Asset tag (Code 128)", "Office & Admin",
      "Code 128 barcode with human-readable ID and an owner box.", 12, T12,
      {"tag": _v("Asset ID", "A-00123"), "owner": _v("Owner", "Maker Lab")})
def _asset(g: Geo, e: Els) -> int:
    e.barcode(0, g.qm, 370, g.qs, "{{ tag }}")
    e.text(384, g.y0, 200, g.ih, "Property of\n{{ owner }}", COND, invert=True)
    return 584


@_tpl("return-address", "Return address", "Office & Admin",
      "Name and one-line address for parcels, returns and borrowed items.", 12, T12,
      {"name": _v("Name", "Alex Example"), "address": _v("Address", "12 Example St, 12345 Town")})
def _address(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["mail"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.5, 0.5)
    e.text(x, y1, 460, h1, "{{ name }}", BOLD, align="left")
    e.text(x, y2, 460, h2, "{{ address }}", COND_SUB, align="left")
    return x + 460


# ---------------------------------------------------------------------------------------------
# People & Names
# ---------------------------------------------------------------------------------------------
@_tpl("name-plate", "Mailbox / door name", "People & Names",
      "Serif name between thin rules for mailboxes, doors and bells.", 12, T9,
      {"name": _v("Name", "The Example Family")})
def _plate(g: Geo, e: Els) -> int:
    W = 460
    e.rect(0, 1, W, 2, fill=True)
    e.rect(0, g.H - 3, W, 2, fill=True)
    e.text(0, g.y0 + 2, W, g.ih - 4, "{{ name }}", SERIF)
    return W


@_tpl("kids-name", "Kid's belongings", "People & Names",
      "Friendly handwriting name with a star, for lunch boxes, bottles and kit.", 12, T6,
      {"name": _v("Name", "Emma")})
def _kid(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["kid"])
    e.text(g.ih + 8, g.y0, 240, g.ih, "{{ name }}", HAND)
    return g.ih + 8 + 240


@_tpl("property-of", "Property of", "People & Names",
      "Inverted 'PROPERTY OF' band over a bold name - for tools and borrowed items.", 12, T12,
      {"name": _v("Name", "Alex Example")})
def _propof(g: Geo, e: Els) -> int:
    (y1, h1), (y2, h2) = g.rows(0.4, 0.6)
    e.text(0, y1, 380, h1, "PROPERTY OF", COND, invert=True)
    e.text(0, y2, 380, h2, "{{ name }}", BOLD)
    return 380


@_tpl("lost-found-qr", "Lost & found", "People & Names",
      "Tap-to-call QR code with your name and phone number. Keep the phone number short.",
      12, T12,
      {"name": _v("Name", "Alex Example"), "phone": _v("Phone (international)", "+15550100")})
def _lost(g: Geo, e: Els) -> int:
    e.qr(0, g.qm, g.qs, g.qs, "tel:{{ phone }}", "m", 0)
    x = g.qs + 14
    (y1, h1), (y2, h2) = g.rows(0.55, 0.45)
    e.text(x, y1, 330, h1, "{{ name }}", BOLD, align="left")
    e.text(x, y2, 330, h2, "{{ phone }}", MONO, align="left")
    return x + 330


# ---------------------------------------------------------------------------------------------
# Smart Home
# ---------------------------------------------------------------------------------------------
@_tpl("zigbee-device", "Zigbee / smart device", "Smart Home",
      "QR with the IEEE address, device name and address text for pairing and support.", 12, T12,
      {"name": _v("Device", "Hall motion sensor"), "ieee": _v("IEEE address", "00158D0001A2B3C4")})
def _zigbee(g: Geo, e: Els) -> int:
    e.qr(0, g.qm, g.qs, g.qs, "{{ ieee }}", "m", 0)
    x = g.qs + 14
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 340, h1, "{{ name }}", BOLD, align="left")
    e.text(x, y2, 340, h2, "{{ ieee }}", MONO, align="left")
    return x + 340


@_tpl("ha-device", "Device & entity", "Smart Home",
      "Icon, friendly name and entity ID for switches, plugs and bulbs.", 12, T12,
      {"name": _v("Name", "Hallway light"), "entity": _v("Entity ID", "light.hallway")})
def _hadev(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["light"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 380, h1, "{{ name }}", BOLD, align="left")
    e.text(x, y2, 380, h2, "{{ entity }}", MONO, align="left")
    return x + 380


@_tpl("scan-to-open", "Scan to open", "Smart Home",
      "QR code to a dashboard, manual or page - with title. Needs 18 mm or wider tape.",
      18, (18, 24),
      {"url": _v("Link", "https://ha.example/heat"), "title": _v("Title", "Heating control")})
def _scan(g: Geo, e: Els) -> int:
    e.qr(0, g.qm, g.qs, g.qs, "{{ url }}", "m", 0)
    x = g.qs + 14
    r = g.rows(0.36, 0.64)
    e.icon(x, r[0][0], r[0][1], r[0][1], ICONS["home"])
    e.text(x + r[0][1] + 8, r[0][0], 300, r[0][1], "Scan to open", MED, align="left")
    e.text(x, r[1][0], 340, r[1][1], "{{ title }}", BOLD, align="left")
    return x + 340


@_tpl("battery-date", "Battery changed", "Smart Home",
      "Battery type in an inverted box with the date it was changed.", 12, T12,
      {"type": _v("Battery", "CR2032"), "date": _v("Changed", "2026-11")})
def _battery(g: Geo, e: Els) -> int:
    w1 = round(g.ih * 3.0)
    e.text(0, g.y0, w1, g.ih, "{{ type }}", MONO, invert=True)
    x = w1 + 12
    (y1, h1), (y2, h2) = g.rows(0.4, 0.6)
    e.text(x, y1, 220, h1, "Changed", COND_SUB, align="left")
    e.text(x, y2, 220, h2, "{{ date }}", MONO, align="left")
    return x + 220


# ---------------------------------------------------------------------------------------------
# Safety & Warning
# ---------------------------------------------------------------------------------------------
@_tpl("fragile", "Fragile", "Safety & Warning",
      "White glass icon and FRAGILE on a solid black bar - impossible to miss.", 12, T9,
      {"text": _v("Text", "FRAGILE")})
def _fragile(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih + 6, g.ih, ICONS["fragile"], invert=True)
    w = 340
    e.text(g.ih + 6, g.y0, w, g.ih, "{{ text }}", BOLD, invert=True)
    return g.ih + 6 + w


@_tpl("warning", "Warning", "Safety & Warning",
      "Framed warning triangle and text, e.g. HIGH VOLTAGE or HOT SURFACE.", 12, T9,
      {"text": _v("Warning", "HIGH VOLTAGE")})
def _warning(g: Geo, e: Els) -> int:
    w = 420
    total = g.ih + w + 3 * g.m
    e.rect(0, 0, total, g.H, stroke=max(3, g.H // 18))
    pad = max(3, g.H // 14)
    e.icon(g.m + pad, g.y0 + pad, g.ih - 2 * pad, g.ih - 2 * pad, ICONS["alert"])
    e.text(g.ih + 2 * g.m, g.y0 + pad, w, g.ih - 2 * pad, "{{ text }}", BOLD)
    return total


@_tpl("do-not-unplug", "Do not unplug", "Safety & Warning",
      "For routers, NAS and servers: icon, bold warning and the reason.", 12, T12,
      {"reason": _v("Reason", "Runs 24/7 - home server")})
def _unplug(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["unplug"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 400, h1, "DO NOT UNPLUG", BOLD, align="left")
    e.text(x, y2, 400, h2, "{{ reason }}", COND_SUB, align="left")
    return x + 400


@_tpl("shutoff-valve", "Shut-off valve", "Safety & Warning",
      "Valve icon, what it shuts off and how to close it (water, gas, heating).", 12, T12,
      {"what": _v("Shuts off", "MAIN WATER"), "hint": _v("How", "Turn clockwise to close")})
def _valve(g: Geo, e: Els) -> int:
    e.icon(0, g.y0, g.ih, g.ih, ICONS["valve"])
    x = g.ih + 12
    (y1, h1), (y2, h2) = g.rows(0.58, 0.42)
    e.text(x, y1, 380, h1, "{{ what }}", BOLD, align="left")
    e.text(x, y2, 380, h2, "{{ hint }}", COND_SUB, align="left")
    return x + 380


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------
def _tapes_out(tpl: _Tpl) -> list:
    return list(tpl.tapes)


def list_templates() -> list[dict]:
    """Catalogue of templates (JSON-serialisable, safe to mutate)."""
    out = []
    for t in _REGISTRY.values():
        out.append({
            "id": t.id, "name": t.name, "category": t.category, "description": t.description,
            "tape_mm_hint": t.tape_mm_hint,
            "tapes": _tapes_out(t),
            "variables": copy.deepcopy(t.variables),
        })
    return out


def supported_tapes(template_id: str) -> list:
    return _tapes_out(_get(template_id))


def _get(template_id: str) -> _Tpl:
    try:
        return _REGISTRY[template_id]
    except (KeyError, TypeError):
        raise TemplateError(f"unknown template: {template_id!r}") from None


def build_template(template_id: str, tape_mm: int, model: int | None = None) -> dict:
    """Return a design (contract section 1) for *template_id* sized for *tape_mm* on printer *model*.

    *tape_mm* is the tape width as the printer reports it (4 for 3.5 mm tape; 3.5 is accepted too).
    Raises TemplateError for an unknown id or a tape the template does not support.
    """
    tpl = _get(template_id)
    tape = 4 if tape_mm == 3.5 else tape_mm
    if tape not in tpl.tapes:
        raise TemplateError(
            f"template {template_id!r} does not support {tape_mm} mm tape "
            f"(supported: {', '.join(str(t) for t in tpl.tapes)})")
    geo = Els(), Geo(tape, model)
    els, g = geo
    tpl.build(g, els)
    return {
        "version": 1,
        "id": "",
        "name": tpl.name,
        "length_mm": None,
        "padding_dots": max(4, g.m),
        "variables": {k: v["default"] for k, v in tpl.variables.items()},
        "elements": els.items,
    }


_VAR_RE = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")


def used_variables(design: dict) -> set[str]:
    """Names referenced by {{ placeholders }} in a design's text/qr/barcode fields."""
    names: set[str] = set()
    for el in design.get("elements", []):
        for key in ("text", "data"):
            val = el.get(key)
            if isinstance(val, str):
                names.update(_VAR_RE.findall(val))
    return names
