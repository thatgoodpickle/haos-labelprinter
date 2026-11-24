#!/usr/bin/env python3
"""Dev server for the label editor.

Serves the frontend directory and a tiny HTTP bridge: POST /api/ws with the
same JSON a hass.callWS message carries; answers {"result": ...} or
{"error": {"code", "message"}}. Uses the real ptouch.design / ptouch.assets
when importable, otherwise stub renderers (grey boxes, canned fonts/icons).

    python dev/mock_backend.py [--port 8765] [--offline]
"""
import argparse
import base64
import io
import json
import re
import sys
import os
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent
sys.path.insert(0, str(FRONTEND.parent))  # custom_components/brother_ptouch

from PIL import Image, ImageDraw  # noqa: E402

try:
    from ptouch import design as ptdesign  # type: ignore
except Exception as exc:  # noqa: BLE001
    ptdesign = None
    print(f"[mock] ptouch.design unavailable ({exc}); using stub renderer")
try:
    from ptouch import templates as pttemplates  # type: ignore
except Exception as exc:  # noqa: BLE001
    pttemplates = None
    print(f"[mock] ptouch.templates unavailable ({exc}); template commands disabled")
try:
    from ptouch import assets as ptassets  # type: ignore
except Exception as exc:  # noqa: BLE001
    ptassets = None
    print(f"[mock] ptouch.assets unavailable ({exc}); using stub fonts/icons")

PINS = {4: 24, 6: 32, 9: 50, 12: 70, 18: 112, 24: 128}
ASSETS = None
LOCK = threading.Lock()
DESIGNS: dict[str, dict] = {}
TAPE12 = {"width_mm": 12, "type": "laminated", "colour": "white", "text_colour": "black"}
TAPE35 = {"width_mm": 3.5, "type": "laminated", "colour": "clear", "text_colour": "black"}
PRINTERS: list[dict] = []   # filled by reset_state()
# Dev switches (env MOCK_*, query string of dev/index.html via _mock/set, or POST brother_ptouch/_mock/set)
SW: dict = {}
SCAN: list[dict] = []
SECRET_KEYS = {"token"}
PRINT_LOG: list[dict] = []
STUB_FONTS = [
    {"id": n.lower().replace(" ", "-"), "family": n, "category": c, "weights": [400, 700], "styles": ["normal", "italic"], "subsets": ["latin"]}
    for n, c in [("Roboto", "sans-serif"), ("Roboto Slab", "serif"), ("Lobster", "display"), ("Pacifico", "handwriting"), ("Roboto Mono", "monospace"), ("Open Sans", "sans-serif")]
]
STUB_ICONS = ["mdi:tag", "mdi:home", "mdi:heart", "mdi:star", "mdi:wifi", "mdi:lightbulb", "mdi:key", "mdi:fire", "mdi:flash", "mdi:food", "mdi:cog", "mdi:alert"]


def reset_state(printers=2):
    """(Re)create the fake printers, the fake Bluetooth scan list and the switches."""
    SW.clear()
    SW.update({
        "pair": os.environ.get("MOCK_PAIR", "ok"),            # ok | fail | timeout
        "connect": os.environ.get("MOCK_CONNECT", "ok"),      # ok | asleep | asleep_once | busy
        "bt": os.environ.get("MOCK_BT", "ok"),                # ok | no_dbus | bluetooth_off | no_adapter
        "add": os.environ.get("MOCK_ADD", "ok"),              # ok | asleep | fail
        "pair_secs": float(os.environ.get("MOCK_PAIR_SECS", "2")),
        "wake_secs": float(os.environ.get("MOCK_WAKE_SECS", "3")),   # how long a print/connect waits on a sleeping printer (real: up to 20)
        "scan_secs": float(os.environ.get("MOCK_SCAN_SECS", "1.5")),
    })
    PRINTERS.clear()
    if printers >= 1:
        PRINTERS.append({"entry_id": "p1", "title": "Office", "name": "Office", "transport": "bluetooth", "address": "AA:BB:CC:00:10:01",
                         "online": True, "reason": "ok", "message": "", "tape_mm": 12, "tape": dict(TAPE12), "state": "idle",
                         "model": None, "has_cutter": True, "tape_pins": None})
    if printers >= 2:
        PRINTERS.append({"entry_id": "p2", "title": "Workshop", "name": "Workshop", "transport": "usb", "serial": "A1B2C3D4",
                         "online": True, "reason": "ok", "message": "", "tape_mm": 4, "tape": dict(TAPE35), "state": "idle",
                         "model": None, "has_cutter": True, "tape_pins": None})
    SCAN[:] = [
        {"address": "AA:BB:CC:48:21:00", "name": "PT-P710BT4821", "paired": False, "trusted": False, "connected": False, "rssi": -58, "is_printer": True},
        {"address": "AA:BB:CC:00:10:01", "name": "PT-P710BT1001", "paired": True, "trusted": True, "connected": False, "rssi": -49, "is_printer": True},
        {"address": "11:22:33:44:55:01", "name": "Pixel 7", "paired": True, "trusted": True, "connected": False, "rssi": -63, "is_printer": False},
        {"address": "11:22:33:44:55:02", "name": "Sam's iPhone", "paired": False, "trusted": False, "connected": False, "rssi": -72, "is_printer": False},
        {"address": "11:22:33:44:55:03", "name": "WH-1000XM4", "paired": True, "trusted": False, "connected": True, "rssi": -80, "is_printer": False},
        {"address": "11:22:33:44:55:04", "name": "JBL Flip 5", "paired": False, "trusted": False, "connected": False, "rssi": None, "is_printer": False},
        {"address": "11:22:33:44:55:05", "name": "", "paired": False, "trusted": False, "connected": False, "rssi": -90, "is_printer": False},
    ]


def public(p):
    return {k: v for k, v in p.items() if k not in SECRET_KEYS and not k.startswith("_")}


def find_printer(m):
    p = next((p for p in PRINTERS if p["entry_id"] == m.get("entry_id")), None)
    if not p:
        raise WsError("not_found", "Printer not found")
    return p


REASON_TEXT = {
    "asleep": "The printer isn't answering. Press its power button to switch it on, make sure no phone is connected to it, then try again.",
    "busy": "The printer is connected to something else (a phone?). Disconnect it and try again.",
    "bluetooth_off": "Bluetooth is switched off on the Home Assistant host.",
    "no_dbus": "Home Assistant can't use Bluetooth here. Use USB or the network bridge.",
    "no_adapter": "Home Assistant can't use Bluetooth here. Use USB or the network bridge.",
}


def pre_delay(m):
    """Sleep part of slow commands OUTSIDE the global lock so previews and other calls keep working."""
    t = m.get("type", "")
    if t == "bluetooth/scan":
        time.sleep(min(float(m.get("duration", 8)), SW.get("scan_secs", 1.5)))
    elif t == "bluetooth/pair":
        time.sleep(SW.get("pair_secs", 2))
    elif t in ("bluetooth/connect", "print", "feed", "printers/test_print", "printers/add"):
        p = next((p for p in PRINTERS if p["entry_id"] == m.get("entry_id")), None)
        sleeping = (p is not None and not p["online"]) or (t == "bluetooth/connect" and SW.get("connect") in ("asleep", "busy", "asleep_once"))
        if t == "printers/add":
            sleeping = SW.get("add") in ("asleep", "fail")
        if sleeping:
            time.sleep(SW.get("wake_secs", 3))
        elif t not in ("print", "feed"):
            time.sleep(0.4)


class WsError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def slug(name):
    base = re.sub(r"[^a-z0-9]+", "-", (name or "label").lower()).strip("-") or "label"
    cand, n = base, 1
    while cand in DESIGNS:
        n += 1
        cand = f"{base}-{n}"
    return cand


def stub_render(design, tape_mm):
    pins = PINS.get(tape_mm, 70)
    els = design.get("elements") or []
    pad = design.get("padding_dots", 6)
    if design.get("length_mm"):
        length = max(1, round(design["length_mm"] * 180 / 25.4))
    else:
        length = max(1, max((e["x"] + e["w"] for e in els), default=0) + 2 * pad)
    img = Image.new("1", (length, pins), 1)
    d = ImageDraw.Draw(img)
    for e in els:
        box = [e["x"], e["y"], e["x"] + e["w"] - 1, e["y"] + e["h"] - 1]
        if e.get("type") == "rect" and e.get("fill"):
            d.rectangle(box, fill=0)
        else:
            d.rectangle(box, outline=0)
            d.line([box[0], box[1], box[2], box[3]], fill=0)
        d.text((e["x"] + 3, e["y"] + 2), e.get("type", "?"), fill=0)
    return img, []


def do_preview(m):
    design = m["design"]
    tape = m.get("tape_mm")
    if tape == 3.5:
        tape = 4
    if tape is None:
        p = next((p for p in PRINTERS if p["entry_id"] == m.get("entry_id")), None)
        tape = (p or {}).get("tape_mm") or 12
    warnings = []
    if ptdesign:
        try:
            design = ptdesign.normalize_design(design)
            img = ptdesign.render_design(design, tape, variables=(m.get("variables") or {}), assets=ASSETS)
            if hasattr(ptdesign, "design_warnings"):
                warnings = ptdesign.design_warnings(design, tape, variables=(m.get("variables") or {}), assets=ASSETS)
        except Exception as exc:  # noqa: BLE001
            raise WsError("invalid_design", str(exc))
    else:
        img, warnings = stub_render(design, tape)
    buf = io.BytesIO()
    img.convert("1").save(buf, "PNG")
    return {"png": base64.b64encode(buf.getvalue()).decode(), "width": img.width, "height": img.height, "tape_mm": tape,
            "length_mm": round(img.width * 25.4 / 180, 1), "warnings": warnings}


def mock_control(t, m):
    """Dev-only: _mock/set {key: value, ...} changes switches; _mock/reset {printers: 0..2}; _mock/get; _mock/printer {entry_id, ...fields}."""
    if t == "_mock/reset":
        reset_state(int(m.get("printers", 2)))
    elif t == "_mock/set":
        for k, v in m.items():
            if k != "type":
                SW[k] = v
    elif t == "_mock/printer":
        p = find_printer(m)
        p.update({k: v for k, v in m.items() if k not in ("type", "entry_id")})
    return {"switches": SW, "printers": [public(p) for p in PRINTERS], "print_log": PRINT_LOG}


def handle_printers(t, m):
    if t == "bluetooth/status":
        r = SW["bt"]
        return {"available": r == "ok", "reason": r, "adapters": [{"path": "/org/bluez/hci0", "address": "00:11:22:33:44:55", "name": "hci0", "powered": r != "bluetooth_off"}] if r in ("ok", "bluetooth_off") else []}
    if t.startswith("bluetooth/") and SW["bt"] != "ok" and t != "bluetooth/forget":
        raise WsError("bluetooth_unavailable", REASON_TEXT.get(SW["bt"], "Bluetooth is not available."))
    if t == "bluetooth/scan":
        configured = {p.get("address") for p in PRINTERS}
        return {"devices": [dict(d, configured=d["address"] in configured) for d in SCAN if d["name"] or d["paired"]]}
    if t == "bluetooth/pair":
        d = next((d for d in SCAN if d["address"] == m.get("address")), None)
        if not d:
            raise WsError("device_not_found", "Home Assistant can't see that printer. Switch it on, keep it close and scan again.")
        if SW["pair"] == "fail":
            raise WsError("pairing_failed", "Pairing didn't work. Switch the printer off and on, keep it close, make sure no phone is connected to it, then try again.")
        if SW["pair"] == "timeout":
            raise WsError("pairing_timeout", "The printer didn't respond while pairing. Switch it on, keep it close and try again.")
        d["paired"] = d["trusted"] = True
        return {"device": dict(d)}
    if t == "bluetooth/forget":
        d = next((d for d in SCAN if d["address"] == m.get("address")), None)
        if d:
            d["paired"] = d["trusted"] = False
        return {}
    if t == "bluetooth/connect":
        p = find_printer(m)
        mode = SW["connect"]
        if mode == "asleep_once":
            SW["connect"] = "ok"
            mode = "asleep"
        if mode in ("asleep", "busy"):
            p.update(online=False, reason=mode, message=REASON_TEXT[mode])
            return {"ok": False, "reason": mode, "seconds": SW["wake_secs"], "message": REASON_TEXT[mode]}
        p.update(online=True, reason="ok", message="", state="idle")
        p["tape"] = p.get("tape") or dict(TAPE12)
        p["tape_mm"] = 4 if p["tape"]["width_mm"] == 3.5 else p["tape"]["width_mm"]
        return {"ok": True, "reason": "ok", "seconds": 1.2, "message": ""}
    if t == "printers/add":
        tr = m.get("transport")
        if tr not in ("usb", "bluetooth", "bridge"):
            raise WsError("invalid_format", "unknown transport")
        key = {"bluetooth": m.get("address"), "usb": m.get("serial") or "usb", "bridge": m.get("url")}[tr]
        if any(p.get(k) == key for p in PRINTERS for k in ("address", "serial", "url")):
            raise WsError("already_configured", "This printer is already configured")
        if SW["add"] != "ok":
            raise WsError("cannot_connect", REASON_TEXT["asleep"])
        n = 1 + max([int(p["entry_id"][1:]) for p in PRINTERS] + [0])
        name = m.get("name") or {"bluetooth": "PT-P710BT", "usb": "PT-P710BT (USB)", "bridge": "PT-P710BT (bridge)"}[tr]
        row = {"entry_id": f"p{n}", "title": name, "name": name, "transport": tr, "online": True, "reason": "ok", "message": "",
               "tape_mm": 12, "tape": dict(TAPE12), "state": "idle"}
        row.update({"bluetooth": {"address": m.get("address")}, "usb": {"serial": m.get("serial") or "A0B1C2D3"}, "bridge": {"url": m.get("url"), "_token": m.get("token")}}[tr])
        PRINTERS.append(row)
        return {"entry_id": row["entry_id"], "title": name}
    if t == "printers/remove":
        PRINTERS.remove(find_printer(m))
        return {}
    if t == "printers/rename":
        p = find_printer(m)
        name = (m.get("name") or "").strip()
        if not name:
            raise WsError("invalid_format", "name must not be empty")
        p["title"] = p["name"] = name
        return {}
    if t == "printers/test_print":
        p = find_printer(m)
        if not p["online"]:
            raise WsError("home_assistant_error", REASON_TEXT.get(p["reason"], p.get("message") or "Printing failed."))
        PRINT_LOG.append({"test_print": p["entry_id"]})
        print("[mock] TEST PRINT", p["entry_id"])
        return {}
    if t == "printers":
        return {"printers": [public(p) for p in PRINTERS]}
    raise WsError("unknown_command", t)


def handle(m):
    t = m.get("type", "")
    if not t.startswith("brother_ptouch/"):
        raise WsError("unknown_command", t)
    t = t.split("/", 1)[1]
    if t.startswith("_mock/"):
        return mock_control(t, m)
    if t.startswith(("bluetooth/", "printers/")):
        return handle_printers(t, m)
    if t == "printers":
        return {"printers": [public(p) for p in PRINTERS]}
    if t == "designs/list":
        return {"designs": [{"id": k, "name": v.get("name", k), "updated": v.get("updated", "")} for k, v in DESIGNS.items()]}
    if t == "designs/get":
        if m.get("design_id") not in DESIGNS:
            raise WsError("not_found", "design not found")
        return {"design": DESIGNS[m["design_id"]]}
    if t == "designs/save":
        d = dict(m["design"])
        if ptdesign:
            try:
                d = ptdesign.normalize_design(d)
            except Exception as exc:  # noqa: BLE001
                raise WsError("invalid_design", str(exc))
        if d.get("id") not in DESIGNS:
            d["id"] = slug(d.get("name"))
        from datetime import datetime, timezone
        d["updated"] = datetime.now(timezone.utc).isoformat()
        DESIGNS[d["id"]] = d
        return {"design": d}
    if t == "designs/delete":
        DESIGNS.pop(m.get("design_id"), None)
        return {}
    if t == "templates/list":
        if not pttemplates:
            raise WsError("unknown_command", t)
        return {"templates": pttemplates.list_templates(), "categories": list(pttemplates.CATEGORIES)}
    if t == "templates/build":
        if not pttemplates:
            raise WsError("unknown_command", t)
        tape = m.get("tape_mm")
        if tape is None:
            p = next((p for p in PRINTERS if p["entry_id"] == m.get("entry_id")), PRINTERS[0])
            tape = p.get("tape_mm") or 12
        if tape == 3.5:
            tape = 4
        try:
            return {"design": pttemplates.build_template(m["template_id"], tape), "tape_mm": tape}
        except pttemplates.TemplateError as exc:
            raise WsError("home_assistant_error", str(exc))
    if t == "preview":
        return do_preview(m)
    if t == "print":
        if ("design" in m) == ("design_id" in m):
            raise WsError("home_assistant_error", "exactly one of design / design_id")
        pr = next((p for p in PRINTERS if p["entry_id"] == m.get("entry_id")), PRINTERS[0] if len(PRINTERS) == 1 else None)
        if pr is not None and not pr["online"]:
            raise WsError("home_assistant_error", REASON_TEXT.get(pr["reason"], pr.get("message") or "Printing failed."))
        if pr is not None and pr["state"] == "error":
            raise WsError("home_assistant_error", pr.get("message") or "The printer reports an error.")
        if "design" in m:
            do_preview(m)  # validates
        PRINT_LOG.append({k: v for k, v in m.items() if k != "design"})
        print("[mock] PRINT", PRINT_LOG[-1])
        return {}
    if t == "feed":
        pr = next((p for p in PRINTERS if p["entry_id"] == m.get("entry_id")), PRINTERS[0] if len(PRINTERS) == 1 else None)
        if pr is not None and not pr["online"]:
            raise WsError("home_assistant_error", REASON_TEXT.get(pr["reason"], pr.get("message") or "Feeding failed."))
        PRINT_LOG.append(dict(m))
        print("[mock] FEED", PRINT_LOG[-1])
        return {}
    if t == "fonts/search":
        q = (m.get("query") or "").lower()
        if ASSETS:
            try:
                return {"fonts": ASSETS.search_fonts(q, m.get("category"), m.get("limit", 50))}
            except Exception as exc:  # noqa: BLE001
                raise WsError("asset_error", str(exc))
        fonts = [f for f in STUB_FONTS if q in f["family"].lower() and (not m.get("category") or f["category"] == m["category"])]
        return {"fonts": fonts[: m.get("limit", 50)]}
    if t == "fonts/ensure":
        if ASSETS:
            try:
                for w in m.get("weights") or [400]:
                    ASSETS.ensure_font(m["family"], w, bool(m.get("italic")))
            except Exception as exc:  # noqa: BLE001
                raise WsError("asset_error", str(exc))
        return {"ok": True}
    if t == "icons/search":
        q = (m.get("query") or "").lower()
        if ASSETS:
            try:
                return {"icons": ASSETS.search_icons(q, m.get("limit", 100))}
            except Exception as exc:  # noqa: BLE001
                raise WsError("asset_error", str(exc))
        return {"icons": [i for i in STUB_ICONS if q in i][: m.get("limit", 100)]}
    raise WsError("unknown_command", t)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(FRONTEND), **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):  # noqa: N802
        if self.path != "/api/ws":
            self.send_error(404)
            return
        try:
            msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            pre_delay({**msg, "type": str(msg.get("type", "")).replace("brother_ptouch/", "", 1)})
            with LOCK:
                body = {"result": handle(msg)}
        except WsError as exc:
            body = {"error": {"code": exc.code, "message": exc.message}}
        except Exception as exc:  # noqa: BLE001
            body = {"error": {"code": "unknown_error", "message": f"{type(exc).__name__}: {exc}"}}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        if "/api/ws" not in (args[0] if args else ""):
            super().log_message(fmt, *args)


reset_state()


def main():
    global ASSETS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1). Use 0.0.0.0 to test from a phone on the LAN: "
                         "the server is UNAUTHENTICATED and its print command is only a mock")
    ap.add_argument("--offline", action="store_true", help="use the stub font/icon lists even if ptouch.assets exists")
    ap.add_argument("--cache", default=str(Path(tempfile.gettempdir()) / "ptouch-dev-cache"))
    a = ap.parse_args()
    if ptassets and not a.offline:
        try:
            ASSETS = ptassets.AssetManager(Path(a.cache))
            print(f"[mock] real AssetManager, cache {a.cache}")
        except Exception as exc:  # noqa: BLE001
            print(f"[mock] AssetManager failed: {exc}")
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"[mock] WARNING: listening on {a.host}: anyone on this network can reach this unauthenticated dev server. "
              "Print is a mock (nothing is sent to a printer). Stop it when you are done.")
    shown = "<this-computer-LAN-ip>" if a.host in ("0.0.0.0", "::") else a.host
    print(f"[mock] http://{shown}:{a.port}/dev/index.html")
    srv.serve_forever()


if __name__ == "__main__":
    main()
