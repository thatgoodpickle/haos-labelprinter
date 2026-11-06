"""Printer setup / Bluetooth wiring tests (HA venv). btadmin and all transports are faked:
nothing here may touch a real Bluetooth radio or the system D-Bus."""
import asyncio
import errno
import json
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.brother_ptouch import btutil
from custom_components.brother_ptouch.const import DOMAIN
from custom_components.brother_ptouch.ptouch import PtouchError, TransportError
from custom_components.brother_ptouch.ptouch import transport as transport_mod

from test_ha import Fake, _enable, setup, status  # noqa: F401

pytest_plugins = "pytest_homeassistant_custom_component"

ADDR = "AA:BB:CC:DD:EE:01"
PHONE = "AA:BB:CC:DD:EE:02"
BT_DATA = {"transport": "bluetooth", "address": ADDR, "channel": 1}


class BtErr(PtouchError):
    def __init__(self, reason, message=None):
        self.reason, self.message = reason, message or f"friendly {reason}"
        super().__init__(self.message)


class FakeBt:
    """Stand-in for ptouch.btadmin."""
    def __init__(self):
        self.ok, self.reason = True, "ok"
        self.calls = []
        self.gate = None                  # threading.Event: scan/pair block until set
        self.scan_error = self.pair_error = self.forget_error = None
        self.devices = [
            {"address": ADDR.lower(), "name": "PT-P710BT1234", "paired": False, "trusted": False,
             "connected": False, "rssi": -50, "is_printer": True, "secret": "x"},
            {"address": PHONE, "name": "Phone", "paired": True, "trusted": True, "connected": False,
             "rssi": None, "is_printer": False},
        ]

    def available(self, bus_address=None):
        self.calls.append(("available",))
        return self.ok, self.reason

    def adapters(self, bus_address=None):
        return [{"path": "/org/bluez/hci0", "address": "11:22:33:44:55:66", "name": "hci0", "powered": True}]

    def scan(self, duration=8.0, **kw):
        self.calls.append(("scan", duration))
        if self.gate:
            self.gate.wait(5)
        if self.scan_error:
            raise self.scan_error
        return [dict(d) for d in self.devices]

    def pair(self, address, *, pin="0000", **kw):
        self.calls.append(("pair", address, pin))
        if self.gate:
            self.gate.wait(5)
        if self.pair_error:
            raise self.pair_error
        dev = next(d for d in self.devices if d["address"].upper() == address)
        dev["paired"] = True
        return dict(dev)

    def forget(self, address, **kw):
        self.calls.append(("forget", address))
        if self.forget_error:
            raise self.forget_error


class BtFake(Fake):
    """Records the wake_timeout in force on every call."""
    def __init__(self):
        super().__init__()
        self.wakes = []
        self.reason = "error"

    def get_status(self):
        self.wakes.append(self.wake_timeout)
        if self.down:
            err = TransportError("offline")
            err.reason = self.reason
            raise err
        return self.st

    def print_job(self, data, pages=1):
        self.wakes.append(self.wake_timeout)
        if self.fail:
            raise self.fail
        self.jobs.append((data, pages))


@pytest.fixture
def bt(monkeypatch):
    fb = FakeBt()
    monkeypatch.setattr(btutil, "get_btadmin", lambda: fb)
    return fb


@pytest.fixture
def tr(monkeypatch):
    """One fake transport shared by every make_transport call (coordinator, flow, bluetooth_api)."""
    f = BtFake()
    for mod in ("coordinator", "config_flow", "bluetooth_api"):
        monkeypatch.setattr(f"custom_components.brother_ptouch.{mod}.make_transport", lambda kind, _f=f, **cfg: _f)
    return f


@pytest.fixture
async def ws(hass, hass_ws_client, bt, tr):
    assert await async_setup_component(hass, DOMAIN, {})
    return await hass_ws_client(hass)


async def call(client, type_, **kw):
    await client.send_json_auto_id({"type": f"brother_ptouch/{type_}", **kw})
    return await client.receive_json()


async def bt_entry(hass, options=None, data=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data or BT_DATA, unique_id=f"bt:{ADDR}",
                            options={"batch_window": 0, **(options or {})})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# ------------------------------------------------------------------ bluetooth/status|scan|pair|forget
async def test_status(ws, bt):
    r = await call(ws, "bluetooth/status")
    assert r["result"] == {"available": True, "reason": "ok", "adapters": [
        {"path": "/org/bluez/hci0", "address": "11:22:33:44:55:66", "name": "hci0", "powered": True}]}
    bt.ok, bt.reason = False, "bluetooth_off"
    r = await call(ws, "bluetooth/status")
    assert r["result"] == {"available": False, "reason": "bluetooth_off", "adapters": []}


async def test_status_without_library(ws, monkeypatch):
    monkeypatch.setattr(btutil, "get_btadmin", lambda: None)
    r = await call(ws, "bluetooth/status")
    assert r["result"] == {"available": False, "reason": "no_library", "adapters": []}
    r = await call(ws, "bluetooth/scan")
    assert r["error"]["code"] == "bluetooth_unavailable"


async def test_scan(hass, ws, bt):
    await bt_entry(hass)
    r = await call(ws, "bluetooth/scan")
    devs = r["result"]["devices"]
    assert bt.calls[-1] == ("scan", 8.0)
    assert devs[0]["address"] == ADDR and devs[0]["configured"] is True and devs[0]["is_printer"] is True
    assert devs[1]["configured"] is False and devs[1]["rssi"] is None
    assert "secret" not in devs[0]                      # only BtDevice fields are passed through
    r = await call(ws, "bluetooth/scan", duration=15)
    assert bt.calls[-1] == ("scan", 15.0)
    for bad in (2, 21, "x"):
        r = await call(ws, "bluetooth/scan", duration=bad)
        assert not r["success"] and r["error"]["code"] == "invalid_format"


@pytest.mark.parametrize("avail,reason", [(False, "no_dbus"), (False, "bluetooth_off")])
async def test_scan_unavailable(ws, bt, avail, reason):
    bt.ok, bt.reason = avail, reason
    r = await call(ws, "bluetooth/scan")
    assert r["error"]["code"] == "bluetooth_unavailable" and "Bluetooth" in r["error"]["message"]
    assert not any(c[0] == "scan" for c in bt.calls)


async def test_scan_error(ws, bt):
    bt.scan_error = BtErr("no_adapter")
    r = await call(ws, "bluetooth/scan")
    assert r["error"]["code"] == "bluetooth_unavailable" and r["error"]["message"] == "friendly no_adapter"


async def test_pair(ws, bt):
    r = await call(ws, "bluetooth/pair", address=ADDR.lower().replace(":", "-"))
    assert r["success"] and r["result"]["device"]["paired"] is True and "secret" not in r["result"]["device"]
    assert bt.calls[-1] == ("pair", ADDR, "0000")
    await call(ws, "bluetooth/pair", address=ADDR, pin="1234")
    assert bt.calls[-1] == ("pair", ADDR, "1234")


@pytest.mark.parametrize("reason,code", [
    ("pairing_failed", "pairing_failed"), ("pairing_timeout", "pairing_timeout"),
    ("not_found", "device_not_found"), ("no_dbus", "bluetooth_unavailable"),
    ("bluetooth_off", "bluetooth_unavailable"), ("error", "pairing_failed")])
async def test_pair_errors(ws, bt, reason, code):
    bt.pair_error = BtErr(reason)
    r = await call(ws, "bluetooth/pair", address=ADDR)
    assert not r["success"] and r["error"]["code"] == code and r["error"]["message"]


async def test_pair_rejects_bad_input(ws, bt):
    for bad in ("nonsense", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:GG", "/org/bluez/hci0/dev_x", ADDR + ";rm"):
        r = await call(ws, "bluetooth/pair", address=bad)
        assert not r["success"] and r["error"]["code"] == "invalid_format", bad
    r = await call(ws, "bluetooth/pair", address=ADDR, pin="12 34")
    assert r["error"]["code"] == "invalid_format"
    assert not any(c[0] == "pair" for c in bt.calls)


async def test_forget(ws, bt):
    r = await call(ws, "bluetooth/forget", address=ADDR.lower())
    assert r["success"] and r["result"] == {} and bt.calls[-1] == ("forget", ADDR)
    bt.forget_error = BtErr("not_found")
    assert (await call(ws, "bluetooth/forget", address=ADDR))["success"]          # idempotent
    bt.forget_error = BtErr("no_dbus")
    assert (await call(ws, "bluetooth/forget", address=ADDR))["error"]["code"] == "bluetooth_unavailable"
    assert (await call(ws, "bluetooth/forget", address="bogus"))["error"]["code"] == "invalid_format"


NEW_COMMANDS = [
    ("bluetooth/status", {}), ("bluetooth/scan", {}), ("bluetooth/pair", {"address": ADDR}),
    ("bluetooth/forget", {"address": ADDR}), ("bluetooth/connect", {"entry_id": "x"}),
    ("printers/add", {"transport": "usb"}), ("printers/remove", {"entry_id": "x"}),
    ("printers/rename", {"entry_id": "x", "name": "n"}), ("printers/test_print", {"entry_id": "x"}),
]


async def test_all_new_commands_admin_only(hass, hass_ws_client, hass_read_only_access_token, bt, tr):
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for typ, extra in NEW_COMMANDS:
        r = await call(client, typ, **extra)
        assert not r["success"] and r["error"]["code"] == "unauthorized", typ
    assert not any(c[0] in ("scan", "pair", "forget") for c in bt.calls)


# ------------------------------------------------------------------ bluetooth/connect + button
async def test_connect_success_uses_wake_option_and_refreshes(hass, ws, tr):
    entry = await bt_entry(hass, {"wake_seconds": 33})
    tr.st = status(width=24)
    r = await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    res = r["result"]
    assert res["ok"] is True and res["reason"] == "ok" and isinstance(res["seconds"], float) and res["message"]
    assert tr.wakes[-1] == 33.0
    assert entry.runtime_data.data.media_width == 24                      # coordinator refreshed


async def test_connect_default_wake_is_20(hass, ws, tr):
    entry = await bt_entry(hass)
    assert tr.wakes[0] == 8.0                                           # the first poll is short
    await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    assert tr.wakes[-1] == 20.0


async def test_connect_failure_is_a_result_not_an_error(hass, ws, tr):
    entry = await bt_entry(hass)
    tr.down, tr.reason = True, "asleep"
    r = await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    assert r["success"] and r["result"]["ok"] is False and r["result"]["reason"] == "asleep"
    assert "power button" in r["result"]["message"]
    assert entry.runtime_data.last_reason == "asleep"
    tr.reason = "busy"
    r = await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    assert r["result"]["reason"] == "busy" and "phone" in r["result"]["message"]


async def test_connect_errors(hass, ws, tr):
    r = await call(ws, "bluetooth/connect", entry_id="nope")
    assert r["error"]["code"] == "not_found"
    entry = await setup(hass)                                            # a bridge printer
    r = await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    assert not r["success"] and "Bluetooth" in r["error"]["message"]


async def test_connect_entry_set_up_while_offline(hass, ws, tr):
    tr.down, tr.reason = True, "asleep"
    entry = MockConfigEntry(domain=DOMAIN, data=BT_DATA, unique_id=f"bt:{ADDR}", options={"batch_window": 0})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state.name == "LOADED"                                 # offline printers still load
    rows = (await call(ws, "printers"))["result"]["printers"]
    assert rows[0]["online"] is False and rows[0]["reason"] == "asleep" and "power button" in rows[0]["message"]
    r = await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    assert r["result"]["ok"] is False and r["result"]["reason"] == "asleep"
    tr.down = False
    r = await call(ws, "bluetooth/connect", entry_id=entry.entry_id)
    assert r["result"]["ok"] is True
    await hass.async_block_till_done()
    assert entry.state.name == "LOADED" and entry.data["model"] == 0    # connecting also learns the model


async def test_button(hass, tr):
    entry = await bt_entry(hass)
    state = hass.states.get("button.brother_p_touch_connect_bluetooth")
    assert state is not None
    await hass.services.async_call("button", "press", {"entity_id": state.entity_id}, blocking=True)
    assert tr.wakes[-1] == 20.0
    tr.down, tr.reason = True, "asleep"
    await entry.runtime_data.async_refresh()
    assert hass.states.get(state.entity_id).state != "unavailable"      # usable exactly when asleep
    with pytest.raises(HomeAssistantError, match="power button"):
        await hass.services.async_call("button", "press", {"entity_id": state.entity_id}, blocking=True)


async def test_no_button_for_other_transports(hass, tr):
    await setup(hass)
    assert hass.states.get("button.brother_p_touch_connect_bluetooth") is None


# ------------------------------------------------------------------ printers rows
async def test_printer_rows(hass, ws, tr):
    entry = await bt_entry(hass)
    bridge = await setup(hass)
    rows = {r["entry_id"]: r for r in (await call(ws, "printers"))["result"]["printers"]}
    row = rows[entry.entry_id]
    assert row["transport"] == "bluetooth" and row["address"] == ADDR and row["online"] is True
    assert row["reason"] == "ok" and row["message"] == "" and row["state"] == "idle"
    assert row["tape_mm"] == 12 and row["title"] == row["name"]
    assert row["tape"] == {"width_mm": 12, "type": "laminated", "colour": "white", "text_colour": "black"}
    b = rows[bridge.entry_id]
    assert b["url"] == "http://x" and "token" not in b and "address" not in b
    assert "token" not in json.dumps(rows)
    tr.st = status(width=4)
    await entry.runtime_data.async_refresh()
    row = {r["entry_id"]: r for r in (await call(ws, "printers"))["result"]["printers"]}[entry.entry_id]
    assert row["tape"]["width_mm"] == 3.5 and row["tape_mm"] == 4
    tr.down, tr.reason = True, "busy"
    await entry.runtime_data.async_refresh()
    row = {r["entry_id"]: r for r in (await call(ws, "printers"))["result"]["printers"]}[entry.entry_id]
    assert row["online"] is False and row["state"] == "offline" and row["reason"] == "busy"
    assert "phone" in row["message"]
    tr.st = status(width=0, media=0)
    tr.down = False
    await entry.runtime_data.async_refresh()
    row = {r["entry_id"]: r for r in (await call(ws, "printers"))["result"]["printers"]}[entry.entry_id]
    assert row["tape"] is None and row["tape_mm"] is None


# ------------------------------------------------------------------ printers/add
@pytest.mark.parametrize("payload,expected,uid", [
    ({"transport": "usb", "serial": "E1"}, {"transport": "usb", "serial": "E1"}, "usb:E1"),
    ({"transport": "bluetooth", "address": "aa-bb-cc-dd-ee-01", "channel": 3},
     {"transport": "bluetooth", "address": ADDR, "channel": 3}, f"bt:{ADDR}"),
    ({"transport": "bluetooth", "address": ADDR},
     {"transport": "bluetooth", "address": ADDR, "channel": 1}, f"bt:{ADDR}"),
    ({"transport": "bluetooth", "address": "/dev/rfcomm0"},
     {"transport": "bluetooth", "address": "/dev/rfcomm0", "channel": 1}, "bt:/dev/rfcomm0"),
    ({"transport": "bridge", "url": " https://10.0.0.5:8765/ ", "token": "sekret"},
     {"transport": "bridge", "url": "https://10.0.0.5:8765", "token": "sekret"}, "bridge:https://10.0.0.5:8765"),
])
async def test_add_all_transports(hass, ws, tr, payload, expected, uid):
    r = await call(ws, "printers/add", **payload)
    assert r["success"], r
    entry = hass.config_entries.async_get_entry(r["result"]["entry_id"])
    assert entry.data == {**expected, "model": 0} and entry.unique_id == uid
    assert r["result"]["title"] == entry.title
    assert "sekret" not in json.dumps(r)
    rows = (await call(ws, "printers"))["result"]["printers"]
    assert "sekret" not in json.dumps(rows)


async def test_add_name_becomes_title(hass, ws, tr):
    r = await call(ws, "printers/add", transport="bluetooth", address=ADDR, name="  Workshop  ")
    assert r["result"]["title"] == "Workshop"


async def test_add_already_configured(hass, ws, tr):
    await bt_entry(hass)
    r = await call(ws, "printers/add", transport="bluetooth", address=ADDR.lower())
    assert not r["success"] and r["error"]["code"] == "already_configured"
    n = len(tr.wakes)
    r = await call(ws, "printers/add", transport="bluetooth", address=ADDR)
    assert len(tr.wakes) == n                                            # didn't even probe


async def test_add_cannot_connect_carries_reason_text(hass, ws, tr):
    tr.down, tr.reason = True, "asleep"
    r = await call(ws, "printers/add", transport="bluetooth", address=ADDR)
    assert not r["success"] and r["error"]["code"] == "cannot_connect"
    assert "power button" in r["error"]["message"]
    assert tr.wakes == [20.0]                                            # probing waits as long as a print
    assert not hass.config_entries.async_entries(DOMAIN)
    tr.reason = "error"
    r = await call(ws, "printers/add", transport="usb")
    assert r["error"]["code"] == "cannot_connect" and "offline" in r["error"]["message"]


@pytest.mark.parametrize("payload", [
    {"transport": "bridge", "url": "file:///etc/passwd"},
    {"transport": "bridge", "url": "ftp://host/x"},
    {"transport": "bridge", "url": "javascript:alert(1)"},
    {"transport": "bridge", "url": "http://"},
    {"transport": "bridge", "url": "not a url"},
    {"transport": "bridge"},
    {"transport": "bluetooth", "address": "nonsense"},
    {"transport": "bluetooth", "address": "/etc/passwd"},
    {"transport": "bluetooth", "address": "/dev/../etc/passwd"},
    {"transport": "bluetooth"},
    {"transport": "wifi"},
    {"transport": "bluetooth", "address": ADDR, "channel": 99},
])
async def test_add_rejects_bad_input(hass, ws, tr, payload):
    r = await call(ws, "printers/add", **payload)
    assert not r["success"] and r["error"]["code"] in ("invalid_format",), r
    assert tr.wakes == [] and not hass.config_entries.async_entries(DOMAIN)


# ------------------------------------------------------------------ remove / rename / test print
async def test_remove(hass, ws, tr):
    entry = await bt_entry(hass)
    r = await call(ws, "printers/remove", entry_id=entry.entry_id)
    assert r["success"] and r["result"] == {}
    assert hass.config_entries.async_get_entry(entry.entry_id) is None
    assert (await call(ws, "printers/remove", entry_id=entry.entry_id))["error"]["code"] == "not_found"


async def test_rename_does_not_reload(hass, ws, tr):
    entry = await bt_entry(hass)
    coord = entry.runtime_data
    r = await call(ws, "printers/rename", entry_id=entry.entry_id, name="  Kitchen   printer ")
    assert r["success"] and r["result"] == {}
    await hass.async_block_till_done()
    assert entry.title == "Kitchen printer" and entry.runtime_data is coord       # same coordinator: no reload
    assert (await call(ws, "printers"))["result"]["printers"][0]["name"] == "Kitchen printer"
    assert (await call(ws, "printers/rename", entry_id=entry.entry_id, name=""))["error"]["code"] == "invalid_format"
    assert (await call(ws, "printers/rename", entry_id="zzz", name="x"))["error"]["code"] == "not_found"


async def test_options_change_still_reloads(hass, tr):
    entry = await bt_entry(hass)
    coord = entry.runtime_data
    hass.config_entries.async_update_entry(entry, options={"batch_window": 0, "wake_seconds": 5})
    await hass.async_block_till_done()
    assert entry.runtime_data is not coord


async def test_test_print_is_one_batched_job(hass, ws, tr):
    entry = await bt_entry(hass)
    hass.config_entries.async_update_entry(entry, options={"batch_window": 0.3})
    await hass.async_block_till_done()
    await ws.send_json_auto_id({"type": "brother_ptouch/printers/test_print", "entry_id": entry.entry_id})
    await ws.send_json_auto_id({"type": "brother_ptouch/printers/test_print", "entry_id": entry.entry_id})
    a, b = await ws.receive_json(), await ws.receive_json()
    assert a["success"] and b["success"] and a["result"] == {}
    (job, pages), = tr.jobs                                              # two requests -> ONE job
    assert pages == 1 and job.count(b"\x1biz") == 1


async def test_test_print_label_text(hass, ws, tr, monkeypatch):
    seen = []
    from custom_components.brother_ptouch import printer_api
    real = printer_api.render_text
    monkeypatch.setattr(printer_api, "render_text",
                        lambda text, tape, **kw: seen.append((text, tape)) or real(text, tape, **kw))
    entry = await bt_entry(hass)
    r = await call(ws, "printers/test_print", entry_id=entry.entry_id)
    assert r["success"]
    text, tape = seen[0]
    assert text.startswith("Printer OK\n") and text.endswith("12 mm") and tape == 12


async def test_test_print_failure_is_friendly(hass, ws, tr):
    entry = await bt_entry(hass)
    tr.down, tr.reason = True, "asleep"
    r = await call(ws, "printers/test_print", entry_id=entry.entry_id)
    assert not r["success"] and r["error"]["code"] == "home_assistant_error"
    assert "power button" in r["error"]["message"]
    assert (await call(ws, "printers/test_print", entry_id="nope"))["error"]["code"] == "not_found"


# ------------------------------------------------------------------ coordinator
async def test_coordinator_reasons_and_wake_timeouts(hass, tr):
    entry = await bt_entry(hass, {"wake_seconds": 14})
    coord = entry.runtime_data
    assert coord.last_reason == "ok" and coord.last_message == "" and tr.wakes == [8.0]
    tr.down, tr.reason = True, "asleep"
    await coord.async_refresh()
    assert coord.last_reason == "asleep" and "power button" in coord.last_message
    assert tr.wakes[-1] == 8.0                                           # polling is short
    tr.down = False
    await hass.services.async_call(DOMAIN, "print_text", {"text": "x"}, blocking=True)
    assert tr.wakes[-3:-1] == [14.0, 14.0] and coord.last_reason == "ok"   # status + job use the option


@pytest.mark.parametrize("reason,needle", [
    ("asleep", "power button"), ("busy", "phone"), ("not_paired", "isn't paired"),
    ("bluetooth_off", "switched off"), ("no_dbus", "USB or the network bridge")])
async def test_print_failure_surfaces_friendly_text(hass, tr, reason, needle):
    entry = await bt_entry(hass)
    err = TransportError("raw low level text")
    err.reason = reason
    tr.fail = err
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(DOMAIN, "print_text", {"text": "x"}, blocking=True)
    assert needle in str(exc.value) and "raw low level" not in str(exc.value)


async def test_unknown_reason_keeps_raw_text(hass, tr):
    await bt_entry(hass)
    tr.fail = TransportError("USB write failed: boom")                   # no reason attribute set
    with pytest.raises(HomeAssistantError, match="boom"):
        await hass.services.async_call(DOMAIN, "print_text", {"text": "x"}, blocking=True)


async def test_coordinator_reason_without_attribute_defaults_to_error(hass, tr):
    entry = await bt_entry(hass)
    tr.down = True
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.last_reason == "error" and entry.runtime_data.last_message == "offline"


# ------------------------------------------------------------------ options flow
async def test_options_flow_wake_seconds(hass, tr):
    entry = await bt_entry(hass)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert "wake_seconds" in r["data_schema"].schema and r["data_schema"]({"orientation": "normal", "batch_window": 0})["wake_seconds"] == 20
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"orientation": "normal", "batch_window": 0, "wake_seconds": 45})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["data"]["wake_seconds"] == 45
    await hass.async_block_till_done()
    assert entry.runtime_data.wake_seconds == 45.0
    r = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(Exception):
        r["data_schema"]({"orientation": "normal", "batch_window": 0, "wake_seconds": 61})


# ------------------------------------------------------------------ config flow: bluetooth
async def _settle(hass, r):
    """Let progress tasks finish and follow the flow to the next real result."""
    for _ in range(5):
        if r["type"] is not FlowResultType.SHOW_PROGRESS:
            break
        await hass.async_block_till_done()
        r = await hass.config_entries.flow.async_configure(r["flow_id"])
    return r


async def _to_pick(hass, fb_bt):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "bluetooth"})
    r = await _settle(hass, r)
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "bluetooth_pick", r
    return r


async def test_flow_shows_progress_while_scanning_and_pairing(hass, bt, tr):
    import threading
    bt.gate = threading.Event()
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "bluetooth"})
    assert r["type"] is FlowResultType.SHOW_PROGRESS and r["progress_action"] == "scanning"
    bt.gate.set()
    r = await _settle(hass, r)
    assert r["step_id"] == "bluetooth_pick"
    bt.gate = threading.Event()
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"device": ADDR})
    assert r["type"] is FlowResultType.SHOW_PROGRESS and r["progress_action"] == "pairing"
    assert r["description_placeholders"]["name"] == "PT-P710BT1234"
    bt.gate.set()
    r = await _settle(hass, r)
    assert r["type"] is FlowResultType.CREATE_ENTRY


async def test_flow_scan_pick_pair_create(hass, bt, tr):
    r = await _to_pick(hass, bt)
    options = r["data_schema"].schema[next(k for k in r["data_schema"].schema if k == "device")].config["options"]
    assert [o["value"] for o in options] == [ADDR, PHONE] and "not paired" in options[0]["label"]
    r = await _settle(hass, await hass.config_entries.flow.async_configure(r["flow_id"], {"device": ADDR}))
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["data"] == {**BT_DATA, "model": 0} and r["title"] == "PT-P710BT1234"
    assert ("pair", ADDR, "0000") in bt.calls and r["result"].unique_id == f"bt:{ADDR}"


async def test_flow_paired_device_skips_pairing(hass, bt, tr):
    r = await _to_pick(hass, bt)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"device": PHONE})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert not any(c[0] == "pair" for c in bt.calls)


async def test_flow_pairing_failure_returns_to_list(hass, bt, tr):
    bt.pair_error = BtErr("pairing_timeout")
    r = await _to_pick(hass, bt)
    r = await _settle(hass, await hass.config_entries.flow.async_configure(r["flow_id"], {"device": ADDR}))
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "bluetooth_pick"
    assert r["errors"] == {"base": "pairing_timeout"}


async def test_flow_printer_asleep_after_pairing(hass, bt, tr):
    tr.down, tr.reason = True, "asleep"
    r = await _to_pick(hass, bt)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"device": PHONE})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"base": "asleep"}


async def test_flow_rescan_and_manual_option(hass, bt, tr):
    r = await _to_pick(hass, bt)
    r = await _settle(hass, await hass.config_entries.flow.async_configure(r["flow_id"], {"rescan": True}))
    assert r["step_id"] == "bluetooth_pick"
    assert sum(1 for c in bt.calls if c[0] == "scan") == 2
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"manual": True})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "bluetooth_manual"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"address": "aa:bb:cc:dd:ee:09", "channel": 2})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["data"] == {"transport": "bluetooth", "address": "AA:BB:CC:DD:EE:09", "channel": 2, "model": 0}


async def test_flow_pick_nothing_and_scan_failure(hass, bt, tr):
    r = await _to_pick(hass, bt)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"rescan": False, "manual": False})
    assert r["errors"] == {"base": "no_device_selected"}
    bt.scan_error = BtErr("bluetooth_off")
    r = await _settle(hass, await hass.config_entries.flow.async_configure(r["flow_id"], {"rescan": True}))
    assert r["step_id"] == "bluetooth_pick" and r["errors"] == {"base": "bluetooth_unavailable"}


@pytest.mark.parametrize("module_missing", [False, True])
async def test_flow_falls_back_to_manual_when_unavailable(hass, bt, tr, monkeypatch, module_missing):
    if module_missing:
        monkeypatch.setattr(btutil, "get_btadmin", lambda: None)
    else:
        bt.ok, bt.reason = False, "no_dbus"
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "bluetooth"})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "bluetooth_manual"
    assert "USB or the network bridge" in r["description_placeholders"]["explanation"]
    assert not any(c[0] == "scan" for c in bt.calls)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"address": "nope", "channel": 1})
    assert r["errors"] == {"base": "invalid_address"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"address": ADDR.lower(), "channel": 1})
    assert r["type"] is FlowResultType.CREATE_ENTRY and r["data"] == {**BT_DATA, "model": 0}


async def test_flow_manual_reports_reason_specific_error(hass, bt, tr):
    bt.ok, bt.reason = False, "no_adapter"
    tr.down, tr.reason = True, "busy"
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"next_step_id": "bluetooth"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"address": ADDR, "channel": 1})
    assert r["errors"] == {"base": "busy"}


async def test_flow_already_configured_aborts(hass, bt, tr):
    await bt_entry(hass)
    r = await _to_pick(hass, bt)
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"device": PHONE})   # paired, other address
    assert r["type"] is FlowResultType.CREATE_ENTRY
    r = await _to_pick(hass, bt)
    r = await _settle(hass, await hass.config_entries.flow.async_configure(r["flow_id"], {"device": ADDR}))
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "already_configured"


# ------------------------------------------------------------------ RFCOMM wake_timeout
class _Clock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def _rfcomm(monkeypatch, exc):
    clock = _Clock()
    attempts = []

    class FakeSock:
        def __init__(self, *a):
            pass

        def settimeout(self, t):
            pass

        def connect(self, addr):
            attempts.append(addr)
            raise exc

        def close(self):
            pass

    monkeypatch.setattr(transport_mod, "time", types.SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep))
    monkeypatch.setattr(transport_mod.socket, "socket", FakeSock)
    monkeypatch.setattr(transport_mod.socket, "AF_BLUETOOTH", 31, raising=False)
    monkeypatch.setattr(transport_mod.socket, "BTPROTO_RFCOMM", 3, raising=False)
    return clock, attempts


def test_transport_base_has_wake_timeout():
    assert transport_mod.Transport.wake_timeout is None
    assert transport_mod.RFCOMMTransport(ADDR).wake_timeout is None


def test_rfcomm_default_retries_eight_times(monkeypatch):
    clock, attempts = _rfcomm(monkeypatch, OSError(errno.EBUSY, "busy"))
    with pytest.raises(TransportError) as exc:
        transport_mod.RFCOMMTransport(ADDR)._open()
    assert len(attempts) == 8 and getattr(exc.value, "reason", "error") == "busy"


def test_rfcomm_honours_wake_timeout(monkeypatch):
    clock, attempts = _rfcomm(monkeypatch, OSError(errno.EHOSTDOWN, "down"))
    t = transport_mod.RFCOMMTransport(ADDR)
    t.wake_timeout = 5.0
    with pytest.raises(TransportError) as exc:
        t._open()
    assert 2 <= len(attempts) < 8 and clock.now <= 5.0
    assert exc.value.reason == "asleep" and "paired?" in str(exc.value)


def test_rfcomm_zero_wake_tries_once(monkeypatch):
    clock, attempts = _rfcomm(monkeypatch, OSError(errno.ECONNREFUSED, "refused"))
    t = transport_mod.RFCOMMTransport(ADDR)
    t.wake_timeout = 0
    with pytest.raises(TransportError):
        t._open()
    assert len(attempts) == 1 and clock.sleeps == []


def test_rfcomm_permission_is_not_retried(monkeypatch):
    clock, attempts = _rfcomm(monkeypatch, OSError(errno.EACCES, "denied"))
    t = transport_mod.RFCOMMTransport(ADDR)
    t.wake_timeout = 30
    with pytest.raises(TransportError) as exc:
        t._open()
    assert len(attempts) == 1 and exc.value.reason == "permission"


# ------------------------------------------------------------------ helpers / translations
def test_normalize_address():
    assert btutil.normalize_address("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    for bad in ("", "aabbccddeeff", "AA:BB:CC:DD:EE:FF:00", "../x", "AA:BB:CC:DD:EE:F\n"):
        with pytest.raises(ValueError):
            btutil.normalize_address(bad)
    assert btutil.normalize_address_or_path("/dev/rfcomm0") == "/dev/rfcomm0"
    for bad in ("/dev/../etc/passwd", "/etc/passwd", "/dev/"):
        with pytest.raises(ValueError):
            btutil.normalize_address_or_path(bad)


def test_translations_cover_new_ui():
    path = Path(__file__).parent.parent / "custom_components/brother_ptouch/translations/en.json"
    d = json.loads(path.read_text())
    steps = d["config"]["step"]
    for step in ("bluetooth", "bluetooth_scan", "bluetooth_pick", "bluetooth_pair", "bluetooth_paired", "bluetooth_manual"):
        assert steps[step]["title"], step
    assert set(d["config"]["progress"]) == {"scanning", "pairing"}
    assert "{name}" in d["config"]["progress"]["pairing"]
    assert {"device", "rescan", "manual"} <= set(steps["bluetooth_pick"]["data"])
    assert {"address", "channel"} <= set(steps["bluetooth_manual"]["data"])
    for key in ("asleep", "busy", "not_paired", "bluetooth_off", "bluetooth_unavailable", "pairing_failed",
                "pairing_timeout", "device_not_found", "no_devices", "no_device_selected", "invalid_address",
                "cannot_connect"):
        assert d["config"]["error"][key], key
    for key in ("cannot_connect", "invalid_url", "invalid_format", "already_configured"):
        assert d["config"]["abort"][key], key
    assert d["entity"]["button"]["connect_bluetooth"]["name"] == "Connect Bluetooth"
    assert d["options"]["step"]["init"]["data"]["wake_seconds"]
    assert d["options"]["step"]["init"]["data_description"]["wake_seconds"]


def test_no_hardcoded_real_address():
    root = Path(__file__).parent.parent / "custom_components/brother_ptouch"
    for f in list(root.glob("*.py")) + list(root.glob("ptouch/*.py")):
        assert "EC:79:49" not in f.read_text(), f
