"""WebSocket commands for managing printers: add, remove, rename, test_print, plus the rich `printers` rows."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .bluetooth_api import _WsError, _cmd, find_entry
from .const import (CONF_ADDRESS, CONF_CHANNEL, CONF_TRANSPORT, CONF_URL, CONF_USB_SERIAL, DOMAIN,
                    REASON_ERROR, REASON_OK, TRANSPORT_BLUETOOTH, TRANSPORT_BRIDGE, TRANSPORT_USB,
                    friendly_message)
from .editor_api import find_coordinator
from .ptouch import TAPE_GEOMETRY, has_cutter, render_text, tape_pins
from .ptouch.protocol import MODEL_NAMES

_LOGGER = logging.getLogger(__name__)

def _pretty(name: str) -> str:
    return str(name).replace("_", " ")


def printer_rows(hass: HomeAssistant) -> list[dict]:
    """Rows of the `printers` command. The token is never included."""
    rows = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        data = entry.data
        row: dict[str, Any] = {
            "entry_id": entry.entry_id, "title": entry.title, "name": entry.title,
            "transport": data.get(CONF_TRANSPORT), "model": None, "has_cutter": None, "tape_pins": None,
            "tape_mm": None, "tape": None,
            "state": "offline", "online": False, "reason": REASON_ERROR, "message": ""}
        for key, conf in (("address", CONF_ADDRESS), ("url", CONF_URL), ("serial", CONF_USB_SERIAL)):
            if data.get(conf):
                row[key] = data[conf]
        coord = entry.runtime_data if entry.state is ConfigEntryState.LOADED else None
        if coord is not None:
            row["online"] = bool(coord.last_update_success)
            row["reason"] = REASON_OK if row["online"] else (coord.last_reason or REASON_ERROR)
            status = coord.data
            row["state"] = "offline" if not row["online"] else getattr(status, "state", "idle")
            if (model := coord.model) is not None:   # also known while the printer is offline
                row["model"] = MODEL_NAMES.get(model)
                row["has_cutter"] = has_cutter(model)
                row["tape_pins"] = {mm: tape_pins(mm, model) for mm in TAPE_GEOMETRY}
            if status is not None and getattr(status, "has_tape", False):
                width = int(status.media_width)
                row["tape_mm"] = width
                row["tape"] = {"width_mm": 3.5 if width == 4 else width,
                               "type": _pretty(status.media_type_name),
                               "colour": _pretty(status.tape_colour_name),
                               "text_colour": _pretty(status.text_colour_name)}
            if not row["online"]:
                row["message"] = coord.last_message or friendly_message(row["reason"], "")
        else:
            row["message"] = friendly_message(REASON_ERROR, "The printer could not be reached.")
        rows.append(row)
    return rows


# -- add -------------------------------------------------------------------------------------
@_cmd({vol.Required("type"): "brother_ptouch/printers/add",
       vol.Required("transport"): vol.In([TRANSPORT_USB, TRANSPORT_BLUETOOTH, TRANSPORT_BRIDGE]),
       vol.Optional("serial"): str, vol.Optional("address"): str,
       vol.Optional("channel"): vol.All(int, vol.Range(min=1, max=30)),
       vol.Optional("url"): str, vol.Optional("token"): str, vol.Optional("name"): str})
async def ws_add(hass, connection, msg):
    data = {k: msg[k] for k in ("transport", "serial", "address", "channel", "url", "token", "name") if k in msg}
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "import"}, data=data)
    if result["type"] is FlowResultType.CREATE_ENTRY:
        connection.send_result(msg["id"], {"entry_id": result["result"].entry_id, "title": result["title"]})
        return
    reason = result.get("reason", "unknown")
    ph = result.get("description_placeholders") or {}
    if reason == "already_configured":
        raise _WsError("already_configured", "This printer is already set up.")
    if reason == "cannot_connect":
        raise _WsError("cannot_connect", ph.get("message") or "Could not talk to the printer.")
    raise _WsError("invalid_format", ph.get("message") or "The printer details are not valid.")


# -- remove / rename -------------------------------------------------------------------------
@_cmd({vol.Required("type"): "brother_ptouch/printers/remove", vol.Required("entry_id"): str})
async def ws_remove(hass, connection, msg):
    entry = find_entry(hass, msg["entry_id"])
    await hass.config_entries.async_remove(entry.entry_id)
    connection.send_result(msg["id"], {})


@_cmd({vol.Required("type"): "brother_ptouch/printers/rename", vol.Required("entry_id"): str,
       vol.Required("name"): vol.All(str, vol.Length(min=1, max=100))})
async def ws_rename(hass, connection, msg):
    entry = find_entry(hass, msg["entry_id"])
    name = " ".join(msg["name"].split())
    if not name:
        raise _WsError("invalid_format", "The name cannot be empty.")
    hass.config_entries.async_update_entry(entry, title=name)
    connection.send_result(msg["id"], {})


# -- test print ------------------------------------------------------------------------------
def _test_label(tape_mm: int, model: int):
    width = "3.5" if tape_mm == 4 else str(tape_mm)
    text = f"Printer OK\n{dt_util.now().strftime('%Y-%m-%d')}  {width} mm"
    return [render_text(text, tape_mm, model=model)]


@_cmd({vol.Required("type"): "brother_ptouch/printers/test_print", vol.Required("entry_id"): str})
async def ws_test_print(hass, connection, msg):
    find_entry(hass, msg["entry_id"])
    coordinator = find_coordinator(hass, msg["entry_id"])
    await coordinator.async_print(_test_label)
    connection.send_result(msg["id"], {})


COMMANDS = (ws_add, ws_remove, ws_rename, ws_test_print)
