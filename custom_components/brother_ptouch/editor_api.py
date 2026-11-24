"""Label editor backend: design storage, WebSocket API, panel registration, templates."""
from __future__ import annotations

import base64
import copy
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.template import Template

from .const import DOMAIN
from .ptouch import PtouchError
from .ptouch.protocol import TAPE_GEOMETRY

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "brother_ptouch.designs"
STORAGE_VERSION = 1
DATA_KEY = "brother_ptouch_editor"
STATIC_URL = "/brother_ptouch_static"
PANEL_URL_PATH = "brother-ptouch"
PANEL_COMPONENT = "brother-ptouch-panel"
FRONTEND_DIR = Path(__file__).parent / "frontend"
MAX_DESIGN_BYTES = 1024 * 1024
DEFAULT_TAPE_MM = 12
TEMPLATE_FIELDS = {"text": "text", "qr": "data", "barcode": "data"}


@dataclass
class EditorData:
    store: Store
    designs: dict[str, dict] = field(default_factory=dict)
    assets: Any = None
    assets_ready: bool = False
    ws_registered: bool = False
    panel_registered: bool = False


# --------------------------------------------------------------------------
# Lazy access to the renderer / assets (written concurrently, no HA imports)
# --------------------------------------------------------------------------
def _design_module() -> Any:
    try:
        from .ptouch import design
    except ImportError as err:
        raise HomeAssistantError("The label renderer is not available") from err
    return design


def _make_asset_manager(cache_dir: str) -> Any:
    from .ptouch.assets import AssetManager
    return AssetManager(cache_dir=cache_dir)


async def async_get_assets(hass: HomeAssistant) -> Any:
    """The shared AssetManager, or None if it cannot be created."""
    data = await async_get_data(hass)
    if not data.assets_ready:
        cache = hass.config.path(".storage/brother_ptouch_cache")
        try:
            data.assets = await hass.async_add_executor_job(_make_asset_manager, cache)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Asset manager unavailable: %s", err)
            data.assets = None
        data.assets_ready = True
    return data.assets


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
async def async_get_data(hass: HomeAssistant) -> EditorData:
    data: EditorData | None = hass.data.get(DATA_KEY)
    if data is None:
        data = EditorData(Store(hass, STORAGE_VERSION, STORAGE_KEY))
        loaded = await data.store.async_load()
        if isinstance(loaded, dict) and isinstance(loaded.get("designs"), dict):
            data.designs = loaded["designs"]
        existing = hass.data.get(DATA_KEY)      # another task may have won the race
        if existing is not None:
            return existing
        hass.data[DATA_KEY] = data
    return data


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60].strip("-")
    return slug or "label"


def _unique_id(designs: dict, name: str) -> str:
    base = _slug(name)
    cand, n = base, 2
    while cand in designs:
        cand, n = f"{base}-{n}", n + 1
    return cand


def _check_size(design: Any) -> None:
    if not isinstance(design, dict):
        raise HomeAssistantError("design must be an object")
    if len(json.dumps(design, default=str)) > MAX_DESIGN_BYTES:
        raise HomeAssistantError("design is larger than 1 MB")


async def async_save_design(hass: HomeAssistant, design: dict) -> dict:
    _check_size(design)
    data = await async_get_data(hass)
    norm = _design_module().normalize_design(design)
    name = str(norm.get("name") or design.get("name") or "").strip()[:100] or "Untitled"
    design_id = design.get("id")
    if not isinstance(design_id, str) or design_id not in data.designs:
        design_id = _unique_id(data.designs, name)
    norm = copy.deepcopy(norm)
    norm.update(id=design_id, name=name, updated=datetime.now(UTC).isoformat())
    data.designs[design_id] = norm
    await data.store.async_save({"designs": data.designs})
    return norm


async def async_find_design(hass: HomeAssistant, ref: str) -> dict:
    """Find a stored design by id, else by (case-insensitive) name."""
    data = await async_get_data(hass)
    if ref in data.designs:
        return data.designs[ref]
    for d in data.designs.values():
        if str(d.get("name", "")).casefold() == ref.casefold():
            return d
    raise HomeAssistantError(f"No label design '{ref}'")


# --------------------------------------------------------------------------
# Templates and rendering
# --------------------------------------------------------------------------
async def async_resolve_templates(hass: HomeAssistant, design: dict,
                                  variables: dict | None) -> tuple[dict, list[str]]:
    """Normalise the design and render HA templates in its text fields."""
    _check_size(design)
    resolved = copy.deepcopy(_design_module().normalize_design(design))
    values: dict[str, Any] = {}
    if isinstance(resolved.get("variables"), dict):
        values.update(resolved["variables"])
    values.update(variables or {})
    warnings: list[str] = []
    for i, el in enumerate(resolved.get("elements") or []):
        key = TEMPLATE_FIELDS.get(el.get("type")) if isinstance(el, dict) else None
        text = el.get(key) if key else None
        if not isinstance(text, str) or ("{{" not in text and "{%" not in text and "{#" not in text):
            continue
        try:
            el[key] = Template(text, hass).async_render(values, parse_result=False)
        except TemplateError as err:
            label = el.get("id") or f"#{i + 1}"
            warnings.append(f"Template error in {el.get('type')} {label}: {err}")
    return resolved, warnings


def _render_callable(resolved: dict, assets: Any) -> Callable[[int, int], list]:
    render_design = _design_module().render_design

    def render(tape_mm: int, model: int) -> list:
        return [render_design(resolved, tape_mm, variables=None, assets=assets, model=model)]
    return render


async def async_print_design(hass: HomeAssistant, coordinator: Any, design: dict,
                             variables: dict | None, *, copies: int = 1, auto_cut: bool = True,
                             cut_each: bool = False, margin_mm: float = 2.0, chain: bool = False,
                             cut_mark: bool = False) -> None:
    resolved, _warnings = await async_resolve_templates(hass, design, variables)
    assets = await async_get_assets(hass)
    await coordinator.async_print(_render_callable(resolved, assets), copies=copies,
                                  auto_cut=auto_cut, cut_each=cut_each, margin_mm=margin_mm,
                                  chain=chain, cut_mark=cut_mark)


def _loaded_coordinators(hass: HomeAssistant) -> list:
    return [e for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED]


def find_coordinator(hass: HomeAssistant, entry_id: str | None) -> Any:
    entries = _loaded_coordinators(hass)
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise HomeAssistantError("Printer not found or not loaded")
    if not entries:
        raise HomeAssistantError("No Brother P-touch printer is set up")
    if len(entries) > 1:
        raise HomeAssistantError("Several printers are configured; choose one")
    return entries[0].runtime_data


def _loaded_coordinator(hass: HomeAssistant, entry_id: str | None) -> Any:
    """Coordinator of the printer *entry_id* (or of the only printer), else None."""
    entries = _loaded_coordinators(hass)
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    return entries[0].runtime_data if len(entries) == 1 else None


def _png_b64(img: Any) -> str:
    buf = io.BytesIO()
    img.convert("L").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _preview_sync(resolved: dict, tape_mm: int, assets: Any,
                  model: int | None = None) -> tuple[Any, list[str]]:
    mod = _design_module()
    img = mod.render_design(resolved, tape_mm, variables=None, assets=assets, model=model)
    try:
        warnings = list(mod.design_warnings(resolved, tape_mm, assets=assets, model=model))
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("design_warnings failed: %s", err)
        warnings = []
    return img, warnings


def _norm_tape(value: Any) -> int:
    if value == 3.5:
        return 4
    try:
        mm = int(value)
    except (TypeError, ValueError):
        raise HomeAssistantError(f"unsupported tape width {value}") from None
    if mm not in TAPE_GEOMETRY:
        raise HomeAssistantError(f"unsupported tape width {value} mm")
    return mm


# --------------------------------------------------------------------------
# WebSocket API
# --------------------------------------------------------------------------
def _handle_errors(func):
    """Map expected errors to WS error frames; never leak tracebacks."""
    async def wrapper(hass: HomeAssistant, connection: Any, msg: dict) -> None:
        try:
            await func(hass, connection, msg)
        except _NotFound as err:
            connection.send_error(msg["id"], "not_found", str(err))
        except PtouchError as err:
            names = {k.__name__ for k in type(err).__mro__}
            code = getattr(err, "ws_code", None) or (
                "asset_error" if "AssetError" in names else
                "invalid_design" if "DesignError" in names else "ptouch_error")
            connection.send_error(msg["id"], code, str(err))
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "home_assistant_error", str(err))
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error in %s", msg.get("type"))
            connection.send_error(msg["id"], "unknown_error", "Unexpected error, see the Home Assistant log")
    wrapper.__name__ = func.__name__
    return wrapper


class _NotFound(Exception):
    pass


def _command(schema: dict):
    def deco(func):
        wrapped = _handle_errors(func)
        wrapped = websocket_api.async_response(wrapped)
        wrapped = websocket_api.websocket_command(schema)(wrapped)
        return websocket_api.require_admin(wrapped)
    return deco


def _need(designs: dict, design_id: str) -> dict:
    if design_id not in designs:
        raise _NotFound(f"Label design '{design_id}' not found")
    return designs[design_id]


@_command({vol.Required("type"): "brother_ptouch/printers"})
async def ws_printers(hass, connection, msg):
    from .printer_api import printer_rows       # lazy: printer_api imports this module
    connection.send_result(msg["id"], {"printers": printer_rows(hass)})


@_command({vol.Required("type"): "brother_ptouch/designs/list"})
async def ws_list(hass, connection, msg):
    data = await async_get_data(hass)
    out = [{"id": i, "name": d.get("name", i), "updated": d.get("updated")}
           for i, d in data.designs.items()]
    out.sort(key=lambda d: str(d["name"]).casefold())
    connection.send_result(msg["id"], {"designs": out})


# NOTE: "id" is HA's own message-id key, so the design id travels as "design_id".
@_command({vol.Required("type"): "brother_ptouch/designs/get", vol.Required("design_id"): str})
async def ws_get(hass, connection, msg):
    data = await async_get_data(hass)
    connection.send_result(msg["id"], {"design": _need(data.designs, msg["design_id"])})


@_command({vol.Required("type"): "brother_ptouch/designs/save", vol.Required("design"): dict})
async def ws_save(hass, connection, msg):
    connection.send_result(msg["id"], {"design": await async_save_design(hass, msg["design"])})


@_command({vol.Required("type"): "brother_ptouch/designs/delete", vol.Required("design_id"): str})
async def ws_delete(hass, connection, msg):
    data = await async_get_data(hass)
    _need(data.designs, msg["design_id"])
    del data.designs[msg["design_id"]]
    await data.store.async_save({"designs": data.designs})
    connection.send_result(msg["id"], {})


@_command({
    vol.Required("type"): "brother_ptouch/preview",
    vol.Required("design"): dict,
    vol.Optional("tape_mm"): vol.Any(int, float),
    vol.Optional("entry_id"): str,
    vol.Optional("variables"): dict,
})
async def ws_preview(hass, connection, msg):
    coord = _loaded_coordinator(hass, msg.get("entry_id"))
    status, model = getattr(coord, "data", None), getattr(coord, "model", None)
    if "tape_mm" in msg:
        tape_mm = _norm_tape(msg["tape_mm"])
    else:
        tape = int(status.media_width) if getattr(status, "has_tape", False) else None
        tape_mm = tape if tape in TAPE_GEOMETRY else DEFAULT_TAPE_MM
    resolved, warnings = await async_resolve_templates(hass, msg["design"], msg.get("variables"))
    assets = await async_get_assets(hass)
    img, more = await hass.async_add_executor_job(_preview_sync, resolved, tape_mm, assets, model)
    png = await hass.async_add_executor_job(_png_b64, img)
    connection.send_result(msg["id"], {
        "png": png, "width": img.width, "height": img.height, "tape_mm": tape_mm,
        "length_mm": round(img.width * 25.4 / 180, 2), "warnings": warnings + more})


@_command({
    vol.Required("type"): "brother_ptouch/print",
    vol.Optional("design"): dict,
    vol.Optional("design_id"): str,
    vol.Optional("entry_id"): str,
    vol.Optional("variables"): dict,
    vol.Optional("copies", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
    vol.Optional("auto_cut", default=True): bool,
    vol.Optional("chain", default=False): bool,
    vol.Optional("cut_mark", default=False): bool,     # printers without a cutter
})
async def ws_print(hass, connection, msg):
    if ("design" in msg) == ("design_id" in msg):
        raise HomeAssistantError("Pass exactly one of design / design_id")
    if "design" in msg:
        design = msg["design"]
    else:
        data = await async_get_data(hass)
        design = _need(data.designs, msg["design_id"])
    coord = find_coordinator(hass, msg.get("entry_id"))
    await async_print_design(hass, coord, design, msg.get("variables"), copies=msg["copies"],
                             auto_cut=msg["auto_cut"], chain=msg["chain"], cut_mark=msg["cut_mark"])
    connection.send_result(msg["id"], {})


@_command({vol.Required("type"): "brother_ptouch/feed", vol.Optional("entry_id"): str})
async def ws_feed(hass, connection, msg):
    """Feed the tape out, e.g. to release a chained label."""
    await find_coordinator(hass, msg.get("entry_id")).async_feed()
    connection.send_result(msg["id"], {})


async def _require_assets(hass: HomeAssistant) -> Any:
    assets = await async_get_assets(hass)
    if assets is None:
        raise _AssetsMissing("Font and icon assets are not available")
    return assets


class _AssetsMissing(PtouchError):
    ws_code = "asset_error"


@_command({
    vol.Required("type"): "brother_ptouch/fonts/search",
    vol.Optional("query", default=""): str,
    vol.Optional("category"): vol.Any(str, None),
    vol.Optional("limit", default=50): vol.All(vol.Coerce(int), vol.Range(min=1, max=500)),
})
async def ws_fonts_search(hass, connection, msg):
    assets = await _require_assets(hass)
    fonts = await hass.async_add_executor_job(
        lambda: assets.search_fonts(msg["query"], msg.get("category"), msg["limit"]))
    connection.send_result(msg["id"], {"fonts": fonts})


@_command({
    vol.Required("type"): "brother_ptouch/fonts/ensure",
    vol.Required("family"): str,
    vol.Optional("weights"): [vol.All(vol.Coerce(int), vol.Range(min=1, max=1000))],
    vol.Optional("italic", default=False): bool,
})
async def ws_fonts_ensure(hass, connection, msg):
    assets = await _require_assets(hass)
    weights = list(dict.fromkeys(msg.get("weights") or [400]))[:9]

    def work() -> None:
        for w in weights:
            assets.ensure_font(msg["family"], w, msg["italic"])
    await hass.async_add_executor_job(work)
    connection.send_result(msg["id"], {"ok": True})


@_command({
    vol.Required("type"): "brother_ptouch/icons/search",
    vol.Optional("query", default=""): str,
    vol.Optional("limit", default=100): vol.All(vol.Coerce(int), vol.Range(min=1, max=1000)),
})
async def ws_icons_search(hass, connection, msg):
    assets = await _require_assets(hass)
    icons = await hass.async_add_executor_job(assets.search_icons, msg["query"], msg["limit"])
    connection.send_result(msg["id"], {"icons": icons})


@_command({vol.Required("type"): "brother_ptouch/templates/list"})
async def ws_templates_list(hass, connection, msg):
    from .ptouch import templates
    connection.send_result(msg["id"], {"templates": templates.list_templates(),
                                       "categories": list(templates.CATEGORIES)})


@_command({
    vol.Required("type"): "brother_ptouch/templates/build",
    vol.Required("template_id"): str,
    vol.Optional("tape_mm"): vol.Any(int, float),
    vol.Optional("entry_id"): str,
})
async def ws_templates_build(hass, connection, msg):
    """A ready-made design sized for a tape (explicit, else the printer's, else 12 mm)."""
    from .ptouch import templates
    tape = _norm_tape(msg["tape_mm"]) if "tape_mm" in msg else None
    if tape is None:
        coord = find_coordinator(hass, msg.get("entry_id"))
        status = getattr(coord, "data", None)
        tape = status.media_width if status is not None and status.has_tape else 12
    else:
        coord = _loaded_coordinator(hass, msg.get("entry_id"))
    design = templates.build_template(msg["template_id"], tape, getattr(coord, "model", None))
    connection.send_result(msg["id"], {"design": design, "tape_mm": tape})


COMMANDS = (ws_printers, ws_list, ws_get, ws_save, ws_delete, ws_preview, ws_print, ws_feed,
            ws_fonts_search, ws_fonts_ensure, ws_icons_search, ws_templates_list,
            ws_templates_build)


# --------------------------------------------------------------------------
# Setup: commands, static path, panel
# --------------------------------------------------------------------------
def _state(hass: HomeAssistant) -> dict:
    return hass.data.setdefault(DATA_KEY + "_setup", {"ws": False, "panel": False})


async def async_setup_editor(hass: HomeAssistant) -> None:
    state = _state(hass)
    if not state["ws"]:
        from . import bluetooth_api, printer_api
        for cmd in (*COMMANDS, *bluetooth_api.COMMANDS, *printer_api.COMMANDS):
            websocket_api.async_register_command(hass, cmd)
        state["ws"] = True
    if state["panel"]:
        return
    if not FRONTEND_DIR.is_dir():
        _LOGGER.info("Label editor frontend directory %s is missing; panel not registered", FRONTEND_DIR)
        return
    state["panel"] = True
    try:
        from homeassistant.components.http import StaticPathConfig
        from homeassistant.components.panel_custom import async_register_panel
        from homeassistant.loader import async_get_integration

        version = (await async_get_integration(hass, DOMAIN)).version
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)])
        await async_register_panel(
            hass, webcomponent_name=PANEL_COMPONENT, frontend_url_path=PANEL_URL_PATH,
            module_url=f"{STATIC_URL}/brother-ptouch-panel.js?v={version}",
            sidebar_title="Labels", sidebar_icon="mdi:label-outline", require_admin=True)
    except Exception as err:  # noqa: BLE001  - the editor must never break the integration
        _LOGGER.warning("Could not register the label editor panel: %s", err)
