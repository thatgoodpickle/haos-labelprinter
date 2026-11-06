"""Config flow: USB, Bluetooth (RFCOMM / device file) or HTTP bridge."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (NumberSelector, NumberSelectorConfig, SelectSelector,
                                            SelectSelectorConfig)
from homeassistant.helpers.service_info.usb import UsbServiceInfo

from . import btutil
from .const import (CONF_MODEL, CONF_WAKE_SECONDS, DEFAULT_WAKE_SECONDS, friendly_message, CONF_ADDRESS, CONF_BATCH_WINDOW, CONF_CHANNEL, CONF_ORIENTATION, DEFAULT_BATCH_WINDOW, CONF_TOKEN, CONF_TRANSPORT,
                    CONF_URL, CONF_USB_SERIAL, DEFAULT_ORIENTATION, DOMAIN, TRANSPORT_BLUETOOTH,
                    TRANSPORT_BRIDGE, TRANSPORT_USB)
from .ptouch import DEFAULT_RFCOMM_CHANNEL, ORIENTATIONS, PtouchError, make_transport

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE = "device"
CONF_MANUAL = "manual"
CONF_RESCAN = "rescan"
SCAN_SECONDS = 8.0
# probe failure reasons that get their own (more helpful) error text in the forms
SPECIFIC_ERRORS = ("asleep", "busy", "not_paired", "bluetooth_off")


def _title(data: dict[str, Any], name: str | None = None) -> str:
    if name and name.strip():
        return name.strip()[:100]
    kind = data[CONF_TRANSPORT]
    if kind == TRANSPORT_USB:
        return "Brother P-touch (USB)"
    if kind == TRANSPORT_BLUETOOTH:
        return f"Brother P-touch ({data[CONF_ADDRESS]})"
    return f"Brother P-touch ({data[CONF_URL]})"


class PTouchConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered_serial: str | None = None
        self._probe_reason = "error"
        self._probe_message = ""
        self._bt_note = ""                       # why the manual Bluetooth form is shown
        self._devices: dict[str, dict] = {}
        self._scan_task: asyncio.Task | None = None
        self._scan_error: str | None = None
        self._pair_task: asyncio.Task | None = None
        self._pair_error: str | None = None
        self._pick: dict | None = None
        self._skip_next_input = False

    @callback
    def async_remove(self) -> None:
        for task in (self._scan_task, self._pair_task):
            if task is not None and not task.done():
                task.cancel()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> "PTouchOptionsFlow":
        return PTouchOptionsFlow()

    async def _try(self, data: dict[str, Any]) -> str | None:
        """Talk to the printer once. Returns a form error key or None; keeps the reason for the caller."""
        cfg = dict(data)
        self._probe_reason, self._probe_message = "error", ""
        try:
            transport = make_transport(cfg.pop(CONF_TRANSPORT), **cfg)
            if data[CONF_TRANSPORT] == TRANSPORT_BLUETOOTH:
                transport.wake_timeout = float(DEFAULT_WAKE_SECONDS)
            status = await self.hass.async_add_executor_job(transport.get_status)
        except PtouchError as err:
            self._probe_reason = getattr(err, "reason", "error") or "error"
            self._probe_message = friendly_message(self._probe_reason, str(err))
            return self._probe_reason if self._probe_reason in SPECIFIC_ERRORS else "cannot_connect"
        except Exception:  # noqa: BLE001
            return "unknown"
        data[CONF_MODEL] = status.model
        return None

    # -- programmatic setup (WebSocket printers/add) -------------------------------------------
    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        kind = user_input.get(CONF_TRANSPORT)
        try:
            if kind == TRANSPORT_USB:
                data = {CONF_TRANSPORT: kind, CONF_USB_SERIAL: str(user_input.get(CONF_USB_SERIAL) or "").strip()}
                uid = f"usb:{data[CONF_USB_SERIAL] or 'default'}"
            elif kind == TRANSPORT_BLUETOOTH:
                addr = btutil.normalize_address_or_path(user_input.get(CONF_ADDRESS, ""))
                data = {CONF_TRANSPORT: kind, CONF_ADDRESS: addr,
                        CONF_CHANNEL: int(user_input.get(CONF_CHANNEL) or DEFAULT_RFCOMM_CHANNEL)}
                uid = f"bt:{addr}"
            elif kind == TRANSPORT_BRIDGE:
                url = str(user_input.get(CONF_URL, "")).strip().rstrip("/")
                parsed = urlparse(url)
                if parsed.scheme not in ("http", "https") or not parsed.netloc:
                    return self.async_abort(reason="invalid_url", description_placeholders={
                        "message": "The bridge URL must start with http:// or https://."})
                data = {CONF_TRANSPORT: kind, CONF_URL: url, CONF_TOKEN: str(user_input.get(CONF_TOKEN) or "")}
                uid = f"bridge:{url}"
            else:
                return self.async_abort(reason="invalid_format", description_placeholders={
                    "message": "Unknown connection type."})
        except ValueError:
            return self.async_abort(reason="invalid_format", description_placeholders={
                "message": "That is not a valid Bluetooth address (expected AA:BB:CC:DD:EE:FF)."})
        await self.async_set_unique_id(uid)
        self._abort_if_unique_id_configured()
        if await self._try(data):
            return self.async_abort(reason="cannot_connect", description_placeholders={
                "reason": self._probe_reason, "message": self._probe_message or "Could not talk to the printer."})
        return self.async_create_entry(title=_title(data, user_input.get("name")), data=data)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[TRANSPORT_USB, TRANSPORT_BLUETOOTH, TRANSPORT_BRIDGE])

    async def async_step_usb(self, user_input=None) -> ConfigFlowResult:
        """Manual USB setup (menu choice) or, when given UsbServiceInfo, discovery."""
        if isinstance(user_input, UsbServiceInfo):
            self._discovered_serial = user_input.serial_number
            await self.async_set_unique_id(f"usb:{self._discovered_serial or 'default'}")
            self._abort_if_unique_id_configured()
            self.context["title_placeholders"] = {"name": "Brother P-touch (USB)"}
            return await self.async_step_discovery_confirm()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TRANSPORT: TRANSPORT_USB, CONF_USB_SERIAL: user_input.get(CONF_USB_SERIAL, "").strip()}
            if not (err := await self._try(data)):
                await self.async_set_unique_id(f"usb:{data[CONF_USB_SERIAL] or 'default'}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Brother P-touch (USB)", data=data)
            errors["base"] = err
        return self.async_show_form(
            step_id="usb", errors=errors,
            data_schema=vol.Schema({vol.Optional(CONF_USB_SERIAL, default=(user_input or {}).get(CONF_USB_SERIAL, "")): str}))

    async def async_step_discovery_confirm(self, user_input=None) -> ConfigFlowResult:
        data = {CONF_TRANSPORT: TRANSPORT_USB, CONF_USB_SERIAL: self._discovered_serial or ""}
        if user_input is not None:
            return self.async_create_entry(title="Brother P-touch (USB)", data=data)
        return self.async_show_form(step_id="discovery_confirm")

    # -- Bluetooth: scan -> pick -> pair -> create, or manual entry -----------------------------
    async def async_step_bluetooth(self, user_input=None) -> ConfigFlowResult:
        mod = btutil.get_btadmin()
        if mod is None:
            self._bt_note = friendly_message("no_library")
            return await self.async_step_bluetooth_manual()
        try:
            ok, reason = await self.hass.async_add_executor_job(mod.available)
        except Exception:  # noqa: BLE001
            ok, reason = False, "error"
        if not ok:
            self._bt_note = friendly_message(reason, "Bluetooth is not available on this host.")
            return await self.async_step_bluetooth_manual()
        return await self.async_step_bluetooth_scan()

    async def _async_scan(self) -> None:
        self._scan_error = None
        try:
            mod = btutil.get_btadmin()
            found = await self.hass.async_add_executor_job(lambda: mod.scan(SCAN_SECONDS))
            self._devices = {d["address"]: d for d in map(btutil.clean_device, found) if d["address"]}
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self._devices = {}
            self._scan_error = getattr(err, "reason", "error")
            _LOGGER.debug("Bluetooth scan failed: %s", err)

    async def async_step_bluetooth_scan(self, user_input=None) -> ConfigFlowResult:
        if self._scan_task is None:
            self._scan_task = self.hass.async_create_task(self._async_scan())
        if not self._scan_task.done():
            return self.async_show_progress(
                step_id="bluetooth_scan", progress_action="scanning", progress_task=self._scan_task)
        return self.async_show_progress_done(next_step_id="bluetooth_pick")

    def _pick_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        options = []
        for dev in self._devices.values():
            label = f"{dev['name'] or dev['address']} ({dev['address']})"
            options.append({"value": dev["address"],
                            "label": label + (" - paired" if dev["paired"] else " - not paired")})
        schema: dict[Any, Any] = {}
        if options:
            schema[vol.Optional(CONF_DEVICE)] = SelectSelector(
                SelectSelectorConfig(options=options, mode="dropdown"))
        schema[vol.Optional(CONF_RESCAN, default=False)] = bool
        schema[vol.Optional(CONF_MANUAL, default=False)] = bool
        return self.async_show_form(step_id="bluetooth_pick", errors=errors or {},
                                    data_schema=vol.Schema(schema))

    async def async_step_bluetooth_pick(self, user_input=None) -> ConfigFlowResult:
        # A finished progress step passes the previous step's input along (which would repeat a rescan
        # forever); a real submit always has these keys.
        if self._skip_next_input or (
                user_input is not None and not {CONF_DEVICE, CONF_RESCAN, CONF_MANUAL} & set(user_input)):
            user_input, self._skip_next_input = None, False
        if user_input is None:
            errors = {}
            if self._scan_error:
                errors["base"] = "bluetooth_unavailable"
            elif not self._devices:
                errors["base"] = "no_devices"
            return self._pick_form(errors)
        if user_input.get(CONF_MANUAL):
            self._bt_note = ""
            return await self.async_step_bluetooth_manual()
        if user_input.get(CONF_RESCAN):
            self._scan_task, self._skip_next_input = None, True
            return await self.async_step_bluetooth_scan()
        dev = self._devices.get(user_input.get(CONF_DEVICE) or "")
        if dev is None:
            return self._pick_form({"base": "no_device_selected"})
        self._pick = dev
        if dev["paired"]:
            return await self._finish_bluetooth(dev["address"], DEFAULT_RFCOMM_CHANNEL, dev["name"])
        self._pair_task = None
        return await self.async_step_bluetooth_pair()

    async def _async_pair(self) -> None:
        self._pair_error = None
        try:
            mod = btutil.get_btadmin()
            addr = self._pick["address"]
            dev = await self.hass.async_add_executor_job(lambda: mod.pair(addr))
            self._pick = {**self._pick, **btutil.clean_device(dev)}
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self._pair_error = getattr(err, "reason", "error") or "error"
            _LOGGER.debug("Bluetooth pairing failed: %s", err)

    async def async_step_bluetooth_pair(self, user_input=None) -> ConfigFlowResult:
        if self._pair_task is None:
            self._pair_task = self.hass.async_create_task(self._async_pair())
        if not self._pair_task.done():
            return self.async_show_progress(
                step_id="bluetooth_pair", progress_action="pairing", progress_task=self._pair_task,
                description_placeholders={"name": self._pick["name"] or self._pick["address"]})
        return self.async_show_progress_done(next_step_id="bluetooth_paired")

    async def async_step_bluetooth_paired(self, user_input=None) -> ConfigFlowResult:
        if self._pair_error:
            reason = self._pair_error
            key = ("pairing_timeout" if reason == "pairing_timeout" else
                   "device_not_found" if reason == "not_found" else
                   "bluetooth_unavailable" if reason in ("no_dbus", "no_adapter", "no_library",
                                                         "bluetooth_off", "permission") else "pairing_failed")
            return self._pick_form({"base": key})
        return await self._finish_bluetooth(self._pick["address"], DEFAULT_RFCOMM_CHANNEL, self._pick["name"])

    async def _finish_bluetooth(self, address: str, channel: int, name: str) -> ConfigFlowResult:
        data = {CONF_TRANSPORT: TRANSPORT_BLUETOOTH, CONF_ADDRESS: address, CONF_CHANNEL: channel}
        await self.async_set_unique_id(f"bt:{address}")
        self._abort_if_unique_id_configured()
        if err := await self._try(data):
            return self._pick_form({"base": err})
        return self.async_create_entry(title=_title(data, name), data=data)

    async def async_step_bluetooth_manual(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                address = btutil.normalize_address_or_path(user_input[CONF_ADDRESS])
            except ValueError:
                address = None
                errors["base"] = "invalid_address"
            if address:
                data = {CONF_TRANSPORT: TRANSPORT_BLUETOOTH, CONF_ADDRESS: address,
                        CONF_CHANNEL: user_input[CONF_CHANNEL]}
                if not (err := await self._try(data)):
                    await self.async_set_unique_id(f"bt:{address}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title=_title(data), data=data)
                errors["base"] = err
        d = user_input or {}
        return self.async_show_form(
            step_id="bluetooth_manual", errors=errors,
            description_placeholders={"explanation": self._bt_note},
            data_schema=vol.Schema({
                vol.Required(CONF_ADDRESS, default=d.get(CONF_ADDRESS, "")): str,
                vol.Optional(CONF_CHANNEL, default=d.get(CONF_CHANNEL, DEFAULT_RFCOMM_CHANNEL)): vol.All(int, vol.Range(min=1, max=30)),
            }))

    async def async_step_bridge(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {CONF_TRANSPORT: TRANSPORT_BRIDGE, CONF_URL: user_input[CONF_URL].strip().rstrip("/"),
                    CONF_TOKEN: user_input.get(CONF_TOKEN, "")}
            if not (err := await self._try(data)):
                await self.async_set_unique_id(f"bridge:{data[CONF_URL]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"Brother P-touch ({data[CONF_URL]})", data=data)
            errors["base"] = err
        d = user_input or {}
        return self.async_show_form(
            step_id="bridge", errors=errors,
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default=d.get(CONF_URL, "http://")): str,
                vol.Optional(CONF_TOKEN, default=d.get(CONF_TOKEN, "")): str,
            }))


class PTouchOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_ORIENTATION, default=current): SelectSelector(
                SelectSelectorConfig(options=list(ORIENTATIONS), translation_key="orientation", mode="dropdown")),
            vol.Required(CONF_BATCH_WINDOW, default=self.config_entry.options.get(CONF_BATCH_WINDOW, DEFAULT_BATCH_WINDOW)):
                NumberSelector(NumberSelectorConfig(min=0, max=30, step=0.5, unit_of_measurement="s", mode="box")),
            vol.Required(CONF_WAKE_SECONDS, default=self.config_entry.options.get(CONF_WAKE_SECONDS, DEFAULT_WAKE_SECONDS)):
                NumberSelector(NumberSelectorConfig(min=0, max=60, step=1, unit_of_measurement="s", mode="box")),
        }))
