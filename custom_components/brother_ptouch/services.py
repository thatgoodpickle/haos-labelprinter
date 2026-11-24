"""print_text / print_qr / print_image services."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN
from .coordinator import PTouchCoordinator
from .editor_api import async_find_design, async_print_design
from .ptouch import ProtocolError, PtouchError, render_image, render_qr, render_text

MAX_IMAGE_BYTES = 10 * 1024 * 1024

COMMON = {
    vol.Optional("device_id"): cv.string,
    vol.Optional("copies", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    vol.Optional("auto_cut", default=True): cv.boolean,
    vol.Optional("cut_each", default=False): cv.boolean,
    vol.Optional("margin_mm", default=2.0): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
    vol.Optional("chain", default=False): cv.boolean,
    vol.Optional("cut_mark", default=False): cv.boolean,
}
FONT = {
    vol.Optional("font_size"): vol.All(vol.Coerce(int), vol.Range(min=6, max=200)),
    vol.Optional("font"): cv.string,
}

TEXT_SCHEMA = vol.Schema({
    **COMMON, **FONT,
    vol.Required("text"): cv.string,
    vol.Optional("align", default="center"): vol.In(["left", "center", "right"]),
})
QR_SCHEMA = vol.Schema({
    **COMMON, **FONT,
    vol.Required("data"): cv.string,
    vol.Optional("text"): cv.string,
})
IMAGE_SCHEMA = vol.All(
    vol.Schema({
        **COMMON,
        vol.Optional("image_path"): cv.string,
        vol.Optional("image_url"): cv.url,
        vol.Optional("dither", default=True): cv.boolean,
    }),
    cv.has_at_least_one_key("image_path", "image_url"),
)
TEMPLATE_SCHEMA = vol.Schema({
    **COMMON,
    vol.Required("template"): cv.string,
    vol.Optional("variables", default=dict): dict,
})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> PTouchCoordinator:
    entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]
    if device_id := call.data.get("device_id"):
        device = dr.async_get(hass).async_get(device_id)
        entries = [e for e in entries if device and e.entry_id in device.config_entries]
    if not entries:
        raise ServiceValidationError("No matching Brother P-touch printer is set up")
    if len(entries) > 1:
        raise ServiceValidationError("Several printers are configured; pass device_id")
    return entries[0].runtime_data


def _job_args(call: ServiceCall) -> dict:
    return {k: call.data[k] for k in ("copies", "auto_cut", "cut_each", "margin_mm", "chain", "cut_mark")}


def _check_font(hass: HomeAssistant, call: ServiceCall) -> str | None:
    font = call.data.get("font")
    if font and not hass.config.is_allowed_path(font):
        raise ServiceValidationError(f"font path {font} is not in allowlist_external_dirs")
    return font


async def _load_image_bytes(hass: HomeAssistant, call: ServiceCall) -> bytes:
    if path := call.data.get("image_path"):
        if not hass.config.is_allowed_path(path):
            raise ServiceValidationError(f"{path} is not in allowlist_external_dirs")

        def read() -> bytes:
            with open(path, "rb") as fh:
                return fh.read(MAX_IMAGE_BYTES + 1)
        try:
            data = await hass.async_add_executor_job(read)
        except OSError as err:
            raise HomeAssistantError(f"cannot read {path}: {err}") from err
    else:
        url = call.data["image_url"]
        try:
            async with async_get_clientsession(hass).get(url, timeout=20) as resp:
                resp.raise_for_status()
                data = await resp.content.read(MAX_IMAGE_BYTES + 1)
        except Exception as err:  # noqa: BLE001
            raise HomeAssistantError(f"cannot fetch {url}: {err}") from err
    if len(data) > MAX_IMAGE_BYTES:
        raise ServiceValidationError("image is larger than 10 MB")
    return data


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def print_text(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        font = _check_font(hass, call)
        await coord.async_print(
            lambda mm, model: [render_text(call.data["text"], mm, font_size=call.data.get("font_size"),
                                           font_path=font, align=call.data["align"], model=model)],
            **_job_args(call))

    async def print_qr(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        font = _check_font(hass, call)

        def render(mm: int, model: int):
            try:
                return [render_qr(call.data["data"], mm, text=call.data.get("text"),
                                  font_size=call.data.get("font_size"), font_path=font, model=model)]
            except ProtocolError as err:
                raise HomeAssistantError(str(err)) from err
        await coord.async_print(render, **_job_args(call))

    async def print_image(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        data = await _load_image_bytes(hass, call)

        def render(mm: int, model: int):
            try:
                return [render_image(data, mm, dither=call.data["dither"], model=model)]
            except (OSError, ProtocolError) as err:
                raise HomeAssistantError(f"cannot use image: {err}") from err
        await coord.async_print(render, **_job_args(call))

    async def print_template(call: ServiceCall) -> None:
        coord = _coordinator(hass, call)
        ref = call.data["template"]
        try:
            design = await async_find_design(hass, ref)
        except HomeAssistantError:
            # Not a saved design: maybe a built-in template id (e.g. "freezer-food").
            from .ptouch import templates
            if ref not in {t["id"] for t in templates.list_templates()}:
                raise
            await coord.async_refresh()           # sized for the tape that is in the printer now
            status = coord.data
            if status is None or not status.has_tape:
                raise HomeAssistantError("No compatible tape loaded in the printer") from None
            try:
                design = templates.build_template(ref, status.media_width, status.model)
            except PtouchError as err:
                raise HomeAssistantError(str(err)) from err
        await async_print_design(hass, coord, design, call.data["variables"], **_job_args(call))

    hass.services.async_register(DOMAIN, "print_template", print_template, schema=TEMPLATE_SCHEMA)
    hass.services.async_register(DOMAIN, "print_text", print_text, schema=TEXT_SCHEMA)
    hass.services.async_register(DOMAIN, "print_qr", print_qr, schema=QR_SCHEMA)
    hass.services.async_register(DOMAIN, "print_image", print_image, schema=IMAGE_SCHEMA)
