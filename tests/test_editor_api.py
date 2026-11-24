"""Label editor backend tests (HA venv). Renderer/assets are faked unless USE_REAL is set."""
import asyncio
import base64
import copy
import io
import types

import pytest
from PIL import Image, ImageDraw

from custom_components.brother_ptouch import editor_api
from custom_components.brother_ptouch.const import DOMAIN
from custom_components.brother_ptouch.ptouch import PtouchError, tape_pins

from test_ha import _enable, fake, setup, status  # noqa: F401  (shared with test_ha)

pytest_plugins = "pytest_homeassistant_custom_component"


class DesignError(PtouchError):
    pass


class AssetError(PtouchError):
    pass


def _fake_design_module():
    calls = []

    def normalize_design(design):
        if not isinstance(design, dict):
            raise DesignError("design must be an object")
        d = copy.deepcopy(design)
        d.setdefault("version", 1)
        d.setdefault("name", "")
        d.setdefault("variables", {})
        d.setdefault("elements", [])
        if d["name"] == "bad":
            raise DesignError("bad design")
        return d

    def render_design(design, tape_mm, *, variables=None, assets=None, model=None):
        calls.append((copy.deepcopy(design), tape_mm, variables, assets))
        texts = "".join(str(e.get("text", e.get("data", ""))) for e in design.get("elements", []))
        img = Image.new("1", (20 + 10 * len(texts), tape_pins(tape_mm, model)), 1)
        ImageDraw.Draw(img).rectangle((1, 1, 5, 5), fill=0)
        return img

    return types.SimpleNamespace(
        normalize_design=normalize_design, render_design=render_design,
        design_warnings=lambda d, t, **kw: ["fake warning"], DesignError=DesignError, calls=calls)


class FakeAssets:
    def __init__(self):
        self.ensured = []

    def search_fonts(self, query="", category=None, limit=50):
        return [{"family": "Roboto", "q": query, "limit": limit}]

    def ensure_font(self, family, weight=400, italic=False):
        if family == "Nope":
            raise AssetError("unknown font Nope")
        self.ensured.append((family, weight, italic))

    def search_icons(self, query, limit=100):
        return ["mdi:tag"]


@pytest.fixture
def design_mod(monkeypatch):
    mod = _fake_design_module()
    monkeypatch.setattr(editor_api, "_design_module", lambda: mod)
    return mod


@pytest.fixture
def assets(monkeypatch):
    a = FakeAssets()
    monkeypatch.setattr(editor_api, "_make_asset_manager", lambda cache: a)
    return a


def text_design(text="Hello", name="Spice jar", **kw):
    return {"name": name, "variables": {"name": "Paprika"},
            "elements": [{"id": "t", "type": "text", "x": 0, "y": 0, "w": 100, "h": 30, "text": text}], **kw}


async def call(client, type_, **kw):
    await client.send_json_auto_id({"type": f"brother_ptouch/{type_}", **kw})
    return await client.receive_json()


@pytest.fixture
async def ws(hass, hass_ws_client, design_mod, assets):
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, DOMAIN, {})
    return await hass_ws_client(hass)


async def test_crud_and_slugs(hass, ws, hass_storage):
    r = await call(ws, "designs/save", design=text_design())
    assert r["success"] and r["result"]["design"]["id"] == "spice-jar"
    r2 = await call(ws, "designs/save", design=text_design())
    assert r2["result"]["design"]["id"] == "spice-jar-2"
    d = r["result"]["design"]
    d["name"] = "Renamed"
    r3 = await call(ws, "designs/save", design=d)            # replace, same id
    assert r3["result"]["design"]["id"] == "spice-jar" and r3["result"]["design"]["updated"]
    r = await call(ws, "designs/list")
    assert [x["id"] for x in r["result"]["designs"]] == ["spice-jar-2", "spice-jar"] or \
        {x["id"] for x in r["result"]["designs"]} == {"spice-jar", "spice-jar-2"}
    r = await call(ws, "designs/get", design_id="spice-jar")
    assert r["result"]["design"]["name"] == "Renamed"
    assert "spice-jar" in hass_storage["brother_ptouch.designs"]["data"]["designs"]
    r = await call(ws, "designs/delete", design_id="spice-jar")
    assert r["success"] and r["result"] == {}
    r = await call(ws, "designs/get", design_id="spice-jar")
    assert not r["success"] and r["error"]["code"] == "not_found"
    r = await call(ws, "designs/delete", design_id="spice-jar")
    assert r["error"]["code"] == "not_found"


async def test_save_unknown_id_creates_and_invalid_maps_error(hass, ws):
    r = await call(ws, "designs/save", design=text_design(id="ghost"))
    assert r["result"]["design"]["id"] == "spice-jar"
    r = await call(ws, "designs/save", design=text_design(name="bad"))
    assert not r["success"] and r["error"]["code"] == "invalid_design" and "bad design" in r["error"]["message"]
    r = await call(ws, "designs/save", design=text_design(text="x" * (2 * 1024 * 1024)))
    assert not r["success"] and "1 MB" in r["error"]["message"]


async def test_persistence_across_reload(hass, hass_storage, design_mod):
    await editor_api.async_save_design(hass, text_design())
    hass.data.pop(editor_api.DATA_KEY)                         # simulate restart
    data = await editor_api.async_get_data(hass)
    assert list(data.designs) == ["spice-jar"]


async def test_preview(hass, ws, design_mod):
    r = await call(ws, "preview", design=text_design("Hi"), tape_mm=18)
    res = r["result"]
    png = Image.open(io.BytesIO(base64.b64decode(res["png"])))
    assert png.size == (res["width"], res["height"]) == (40, 112) and res["tape_mm"] == 18
    assert png.mode == "L" and res["warnings"] == ["fake warning"]
    assert res["length_mm"] == round(40 * 25.4 / 180, 2)
    r = await call(ws, "preview", design=text_design("Hi"))
    assert r["result"]["tape_mm"] == 12                        # no printer, no tape -> 12
    r = await call(ws, "preview", design=text_design("Hi"), tape_mm=3.5)
    assert r["result"]["tape_mm"] == 4


async def test_preview_errors(hass, ws):
    r = await call(ws, "preview", design=text_design(name="bad"))
    assert not r["success"] and r["error"]["code"] == "invalid_design"
    r = await call(ws, "preview", design=text_design(), tape_mm=7)
    assert not r["success"] and "unsupported tape" in r["error"]["message"]


async def test_preview_uses_printer_tape(hass, ws, fake):
    fake.st = status(width=24)
    await setup(hass)
    r = await call(ws, "preview", design=text_design())
    assert r["result"]["tape_mm"] == 24


async def test_template_resolution(hass, ws, design_mod):
    hass.states.async_set("sensor.temp", "21")
    d = text_design("{{ name }} {{ states('sensor.temp') }} {{ nope( }}")
    d["elements"].append({"id": "q", "type": "qr", "data": "id-{{ name }}"})
    r = await call(ws, "preview", design=d, tape_mm=12, variables={"name": "Salt"})
    assert r["success"]
    resolved, tape, variables, _ = design_mod.calls[-1]
    assert variables is None
    els = {e["id"]: e for e in resolved["elements"]}
    assert els["q"]["data"] == "id-Salt"
    assert any("Template error" in w for w in r["result"]["warnings"])
    assert els["t"]["text"].startswith("{{ name }}")           # bad template stays raw
    d["elements"][0]["text"] = "{{ name }} {{ states('sensor.temp') }}"
    r = await call(ws, "preview", design=d, tape_mm=12)
    assert design_mod.calls[-1][0]["elements"][0]["text"] == "Paprika 21"   # default variable


async def test_print_one_job(hass, ws, fake, design_mod):
    entry = await setup(hass)
    r = await call(ws, "print", design=text_design("{{ name }}"), copies=3, variables={"name": "A"})
    assert r["success"]
    (job, pages), = fake.jobs
    assert pages == 1 and job.count(b"\x1biz") == 1
    assert design_mod.calls[-1][0]["elements"][0]["text"] == "A"
    r = await call(ws, "printers")
    p, = r["result"]["printers"]
    assert p["entry_id"] == entry.entry_id and p["tape_mm"] == 12 and p["state"] == "idle"
    assert p["model"] is None and p["tape_pins"]["12"] == 70 and p["has_cutter"] is True
    r = await call(ws, "print", design=text_design(), design_id="x")
    assert not r["success"]
    r = await call(ws, "print")
    assert not r["success"]
    r = await call(ws, "print", design_id="missing")
    assert r["error"]["code"] == "not_found"
    r = await call(ws, "print", design=text_design(), copies=21)
    assert not r["success"]
    fake.st = status(width=0, media=0)
    r = await call(ws, "print", design=text_design())
    assert not r["success"] and "tape" in r["error"]["message"]
    assert len(fake.jobs) == 1


async def test_print_by_saved_id_and_no_printer(hass, ws, fake):
    await call(ws, "designs/save", design=text_design())
    r = await call(ws, "print", design_id="spice-jar")
    assert not r["success"] and "printer" in r["error"]["message"]
    await setup(hass)
    r = await call(ws, "print", design_id="spice-jar")
    assert r["success"] and len(fake.jobs) == 1


async def test_print_template_service(hass, fake, design_mod, assets):
    await setup(hass)
    await editor_api.async_save_design(hass, text_design("{{ name }}!"))
    await hass.services.async_call(DOMAIN, "print_template",
                                   {"template": "spice-jar", "variables": {"name": "Cumin"}, "copies": 2},
                                   blocking=True)
    assert design_mod.calls[-1][0]["elements"][0]["text"] == "Cumin!"
    await hass.services.async_call(DOMAIN, "print_template", {"template": "SPICE JAR"}, blocking=True)
    assert design_mod.calls[-1][0]["elements"][0]["text"] == "Paprika!"   # by name, default var
    assert len(fake.jobs) == 2
    with pytest.raises(Exception, match="No label design"):
        await hass.services.async_call(DOMAIN, "print_template", {"template": "zzz"}, blocking=True)


async def test_template_service_batches_with_other_prints(hass, fake, design_mod, assets):
    entry = await setup(hass)
    hass.config_entries.async_update_entry(entry, options={"batch_window": 0.3})
    await hass.async_block_till_done()
    await editor_api.async_save_design(hass, text_design())
    await asyncio.gather(
        hass.services.async_call(DOMAIN, "print_template", {"template": "spice-jar"}, blocking=True),
        hass.services.async_call(DOMAIN, "print_text", {"text": "x"}, blocking=True))
    assert len(fake.jobs) == 1


async def test_admin_only(hass, hass_ws_client, hass_read_only_access_token, design_mod, assets):
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for typ, extra in (("designs/list", {}), ("printers", {}), ("designs/save", {"design": text_design()}),
                       ("fonts/search", {}), ("icons/search", {}), ("preview", {"design": text_design()})):
        r = await call(client, typ, **extra)
        assert not r["success"] and r["error"]["code"] == "unauthorized", typ


async def test_fonts_and_icons(hass, ws, assets):
    r = await call(ws, "fonts/search", query="rob", category="serif", limit=5)
    assert r["result"]["fonts"] == [{"family": "Roboto", "q": "rob", "limit": 5}]
    r = await call(ws, "fonts/ensure", family="Roboto", weights=[400, 700], italic=True)
    assert r["result"] == {"ok": True}
    assert assets.ensured == [("Roboto", 400, True), ("Roboto", 700, True)]
    r = await call(ws, "fonts/ensure", family="Nope")
    assert not r["success"] and r["error"]["code"] == "asset_error" and "unknown font" in r["error"]["message"]
    r = await call(ws, "icons/search", query="tag")
    assert r["result"]["icons"] == ["mdi:tag"]


async def test_assets_unavailable(hass, ws, monkeypatch):
    def boom(cache):
        raise ImportError("nope")
    monkeypatch.setattr(editor_api, "_make_asset_manager", boom)
    r = await call(ws, "icons/search", query="x")
    assert not r["success"] and r["error"]["code"] == "asset_error"


async def test_unexpected_error_hides_traceback(hass, ws, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(editor_api, "async_resolve_templates", boom)
    r = await call(ws, "preview", design=text_design())
    assert r["error"]["code"] == "unknown_error" and "secret" not in r["error"]["message"]


async def test_panel_registration_idempotent(hass, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, patch
    monkeypatch.setattr(editor_api, "FRONTEND_DIR", tmp_path)
    from homeassistant.setup import async_setup_component
    with patch("homeassistant.components.panel_custom.async_register_panel", new=AsyncMock()) as panel, \
         patch("homeassistant.components.http.HomeAssistantHTTP.async_register_static_paths",
               new=AsyncMock()) as static:
        assert await async_setup_component(hass, DOMAIN, {})
        await editor_api.async_setup_editor(hass)
        await editor_api.async_setup_editor(hass)
    mine = [c for c in static.await_args_list if c.args[0][0].url_path == "/brother_ptouch_static"]
    assert panel.await_count == 1 and len(mine) == 1
    kw = panel.await_args.kwargs
    assert kw["frontend_url_path"] == "brother-ptouch" and kw["require_admin"] is True
    assert kw["module_url"].startswith("/brother_ptouch_static/brother-ptouch-panel.js?v=")
    assert mine[0].args[0][0].path == str(tmp_path)


async def test_missing_frontend_dir_skips(hass, tmp_path, monkeypatch):
    monkeypatch.setattr(editor_api, "FRONTEND_DIR", tmp_path / "nope")
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, DOMAIN, {})
    assert not editor_api._state(hass)["panel"]


async def test_real_renderer_end_to_end(hass, hass_ws_client, fake, monkeypatch):
    """Real normalize/render, assets disabled (offline fallback fonts)."""
    pytest.importorskip("custom_components.brother_ptouch.ptouch.design")
    def no_assets(cache):
        raise ImportError("offline")
    monkeypatch.setattr(editor_api, "_make_asset_manager", no_assets)
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    hass.states.async_set("sensor.temp", "21")
    design = {"name": "Real", "variables": {"n": "Z"}, "elements": [
        {"id": "a", "type": "text", "x": 0, "y": 0, "w": 200, "h": 60, "text": "{{ n }} {{ states('sensor.temp') }}"},
        {"id": "b", "type": "qr", "x": 210, "y": 0, "w": 60, "h": 60, "data": "https://example.com"}]}
    r = await call(client, "preview", design=design, tape_mm=12)
    assert r["success"], r
    res = r["result"]
    png = Image.open(io.BytesIO(base64.b64decode(res["png"])))
    assert png.size == (res["width"], 70) and png.getextrema() == (0, 255)
    r = await call(client, "designs/save", design=design)
    assert r["result"]["design"]["id"] == "real"
    await setup(hass)
    r = await call(client, "print", design_id="real", copies=2)
    assert r["success"] and len(fake.jobs) == 1
    r = await call(client, "preview", design={"elements": "nope"})
    assert "error" in r or r["success"]


async def test_print_without_auto_cut(hass, ws, fake, design_mod):
    await setup(hass)
    r = await call(ws, "print", design=text_design(), auto_cut=False)
    assert r["success"] and b"\x1biM\x00" in fake.jobs[-1][0]


async def test_p300bt_printer_row_and_preview(hass, ws, fake):
    from custom_components.brother_ptouch.ptouch.protocol import MODEL_P300BT
    fake.st = status(model=MODEL_P300BT)
    entry = await setup(hass)
    p, = (await call(ws, "printers"))["result"]["printers"]
    assert p["model"] == "PT-P300BT" and p["tape_pins"] == {"4": 24, "6": 32, "9": 50, "12": 64,
                                                             "18": 112, "24": 128}
    assert p["has_cutter"] is False
    r = await call(ws, "print", design=text_design(), chain=True, cut_mark=True)
    assert r["success"]
    job, _ = fake.jobs[-1]
    assert b"\x1biK\x00" in job and b"\x1biM\x40" in job
    r = await call(ws, "feed", entry_id=entry.entry_id)
    assert r["success"] and fake.jobs[-1][0].endswith(b"Z\x1a")
    r = await call(ws, "preview", design=text_design())                 # tape from the printer
    assert r["result"]["height"] == 64
    r = await call(ws, "preview", design=text_design(), tape_mm=12, entry_id=entry.entry_id)
    assert r["result"]["height"] == 64


async def test_templates_list_build_and_print(hass, hass_ws_client, fake, monkeypatch):
    pytest.importorskip("custom_components.brother_ptouch.ptouch.templates")
    def no_assets(cache):
        raise ImportError("offline")
    monkeypatch.setattr(editor_api, "_make_asset_manager", no_assets)
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, DOMAIN, {})
    await setup(hass)
    client = await hass_ws_client(hass)
    r = await call(client, "templates/list")
    tpls = r["result"]["templates"]
    assert len(tpls) >= 25 and "Kitchen & Food" in r["result"]["categories"]
    tid = next(t["id"] for t in tpls if 12 in t["tapes"])
    r = await call(client, "templates/build", template_id=tid)       # tape from the printer (12 mm)
    assert r["success"] and r["result"]["tape_mm"] == 12
    design = r["result"]["design"]
    r = await call(client, "templates/build", template_id=tid, tape_mm=24)
    assert r["result"]["tape_mm"] == 24
    r = await call(client, "templates/build", template_id="nope", tape_mm=12)
    assert not r["success"]
    r = await call(client, "templates/build", template_id=tid, tape_mm=7)
    assert not r["success"]
    r = await call(client, "preview", design=design, tape_mm=12)      # template -> preview with defaults
    assert r["success"] and r["result"]["height"] == 70
    r = await call(client, "print", design=design, copies=1)
    assert r["success"] and len(fake.jobs) == 1
    fake.st = status(model=0x72)                                       # PT-P300BT: 64 dots on 12 mm
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()
    r = await call(client, "templates/build", template_id=tid)
    assert all(e["y"] + e["h"] <= 64 for e in r["result"]["design"]["elements"])
    r = await call(client, "preview", design=r["result"]["design"], tape_mm=12)
    assert r["result"]["height"] == 64


async def test_print_template_service_accepts_builtin_id(hass, fake, monkeypatch):
    pytest.importorskip("custom_components.brother_ptouch.ptouch.templates")
    def no_assets(cache):
        raise ImportError("offline")
    monkeypatch.setattr(editor_api, "_make_asset_manager", no_assets)
    from homeassistant.setup import async_setup_component
    from custom_components.brother_ptouch.ptouch import templates
    assert await async_setup_component(hass, DOMAIN, {})
    await setup(hass)
    tid = next(t["id"] for t in templates.list_templates() if 12 in t["tapes"] and "name" in t["variables"] or 12 in t["tapes"])
    await hass.services.async_call(DOMAIN, "print_template", {"template": tid, "variables": {}}, blocking=True)
    assert len(fake.jobs) == 1
    with pytest.raises(Exception, match="No label design"):
        await hass.services.async_call(DOMAIN, "print_template", {"template": "no-such-thing"}, blocking=True)


async def test_preview_has_no_false_icon_warning(hass, hass_ws_client, fake, monkeypatch):
    """Regression: warnings must be computed with the asset manager, else every icon reads 'not available'."""
    import glob
    pytest.importorskip("custom_components.brother_ptouch.ptouch.design")
    fonts = glob.glob("/usr/share/fonts/**/DejaVuSans.ttf", recursive=True)
    if not fonts:
        pytest.skip("no system TTF to act as an icon font")

    class Assets:
        def font_path(self, *a, **k): return None
        def icon_glyph(self, name): return (fonts[0], "\u2605") if name == "mdi:tag" else None
        def search_fonts(self, *a, **k): return []
        def search_icons(self, *a, **k): return []
        def ensure_font(self, *a, **k): return None
    monkeypatch.setattr(editor_api, "_make_asset_manager", lambda cache: Assets())
    from homeassistant.setup import async_setup_component
    assert await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    ok = {"elements": [{"id": "i", "type": "icon", "icon": "mdi:tag", "x": 0, "y": 0, "w": 60, "h": 60}]}
    r = await call(client, "preview", design=ok, tape_mm=12)
    assert r["success"] and not any("not available" in w for w in r["result"]["warnings"]), r["result"]["warnings"]
    bad = {"elements": [{"id": "i", "type": "icon", "icon": "mdi:does-not-exist", "x": 0, "y": 0, "w": 60, "h": 60}]}
    r = await call(client, "preview", design=bad, tape_mm=12)
    assert any("not available" in w for w in r["result"]["warnings"])     # a genuinely missing icon still warns
