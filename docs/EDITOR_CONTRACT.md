# Label editor: shared contract

Four pieces are built in parallel against this document. **Do not change it**; if something
is impossible, work around it in your own files and report it. Repo root:
`~/claude-projects/ha-brother-ptouch/`. Integration dir: `custom_components/brother_ptouch/`.

Hard rules for every piece
* Python core code under `custom_components/brother_ptouch/ptouch/` has **no Home Assistant imports**,
  uses **relative imports** inside the package, is blocking/sync (callers use an executor).
* Only edit the files you own (listed per piece). Do not run `git commit/push/checkout`.
* Tests: core tests run with `.venv/bin/python -m pytest -q -p no:cacheprovider tests/<file>` ;
  Home Assistant tests run with `PYTHONPATH=. .venv-ha/bin/python -m pytest -q -p no:cacheprovider tests/<file>`.
  (The HA pytest plugin blocks real sockets, so network/server tests belong in the plain `.venv`.)
* Never download from hosts other than the allow-list in section 2. No secrets, no personal data.

## 1. Design JSON (version 1)

Coordinates are **dots at 180 dpi** (1 mm = 7.087 dots). Origin top-left of the label. `x` runs along
the tape length, `y` across the tape width (0 .. pins-1, where pins = `tape_pins(tape_mm, model)`:
3.5mm(4)->24, 6->32, 9->50, 12->70, 18->112, 24->128; the PT-P300BT prints 64 on 12 mm).

```json
{
  "version": 1,
  "id": "spice-jar",               // slug, assigned by storage on first save
  "name": "Spice jar",
  "length_mm": null,               // null = auto (content extent + padding_dots at the trailing end only); number = fixed
  "padding_dots": 6,               // only used when length_mm is null
  "variables": {"name": "Paprika", "date": ""},   // defaults for {{ name }} placeholders
  "elements": [ ... ]
}
```

Common element keys: `id` (string), `type`, `x`, `y`, `w`, `h` (the element's box, dots, numbers),
`rotation` (0, 90, 180 or 270; rotates the rendered element inside/around its box centre), `invert`
(bool; white content on a black filled box). Unknown keys are ignored, missing keys take defaults.

| type | extra keys (defaults) |
|---|---|
| `text` | `text` (""), `font` ("" = built-in default, otherwise a Google Fonts family name like "Roboto Slab"), `weight` (400, 100..900), `italic` (false), `size` (number of dots, or `"auto"` = largest size that fits the box), `align` (`left`/`center`/`right`, "center"), `valign` (`top`/`middle`/`bottom`, "middle"), `line_spacing` (1.0). Text wraps on whitespace to the box width and honours `\n`. Content outside the box is clipped. |
| `icon` | `icon` ("mdi:tag"). Drawn as a glyph, as large as fits the box (square, centred). |
| `qr` | `data` (""), `ecc` ("m"; l/m/q/h), `quiet` (1; quiet-zone modules). Largest integer-module scale that fits the box, centred. |
| `barcode` | `format` ("code128"; code128, code39, ean13, ean8, upca, itf, codabar), `data` (""), `show_text` (true). Integer module width, as wide as fits the box; human-readable text below when `show_text`. |
| `rect` | `stroke` (2 dots), `fill` (false). `fill: true` makes it a solid bar (use thin w or h for lines). |
| `image` | `src` (`data:image/png;base64,...` or jpeg), `dither` (true). Scaled to fit the box, centred. |

Placeholders: in `text.text`, `qr.data`, `barcode.data`, `{{ name }}` is replaced from variables.
The Home Assistant layer resolves full HA templates (`{{ states('sensor.x') }}`) into plain strings
**before** calling the renderer, then passes `variables=None` so nothing is substituted twice.

## 2. Pieces and interfaces

### A. Renderer (`ptouch/design.py`)  [owner: agent A]
```python
DESIGN_VERSION = 1
class DesignError(PtouchError)               # invalid design
def normalize_design(design: dict) -> dict   # fill defaults, clamp, drop junk; raises DesignError on non-dict/bad types
def render_design(design: dict, tape_mm: int, *, variables: dict | None = None,
                  assets=None, model=None) -> PIL.Image.Image   # mode "1", height == tape_pins(tape_mm, model)
```
`assets` is any object with `font_path(family, weight, italic) -> Path | None` and
`icon_glyph(name) -> tuple[Path, str] | None` (the `AssetManager` below implements both). If `assets`
is None, or a lookup raises/returns None, fall back to a system DejaVu font, then Pillow's
`ImageFont.load_default(size)`. Missing icons draw nothing (never crash). `variables is None` means
"do not substitute". Elements are painted in list order; black = ink (0), white = 1.
Auto length = max(x+w) over elements + 2*padding_dots (min 1); fixed length = round(length_mm*180/25.4).
Also export `design_warnings(design, tape_mm) -> list[str]` (e.g. element outside the label, text clipped).
Tests: `tests/test_design.py`.

### B. Assets (`ptouch/assets.py`)  [owner: agent B]
```python
class AssetError(PtouchError)
Fetch = Callable[[str, dict | None], bytes]    # (url, headers) -> body; default uses urllib, 20s timeout, 30 MB cap
class AssetManager:
    def __init__(self, cache_dir, fetch: Fetch | None = None)
    # fonts (Google Fonts)
    def font_catalog(self, refresh=False) -> list[dict]   # [{"id","family","category","weights":[int],"styles":["normal","italic"],"subsets":[str]}]
    def search_fonts(self, query="", category=None, limit=50) -> list[dict]   # case-insensitive substring/prefix on family; popular-first order is fine
    def ensure_font(self, family, weight=400, italic=False) -> Path   # downloads the TTF once, caches on disk
    def font_path(self, family, weight=400, italic=False) -> Path | None   # = ensure_font but returns None on any failure (never raises)
    # icons (Material Design Icons)
    def icon_names(self) -> list[str]                      # ["mdi:abacus", ...] sorted
    def search_icons(self, query, limit=100) -> list[str]
    def icon_glyph(self, name) -> tuple[Path, str] | None # (icon font ttf, single char); accepts "mdi:x" or "x"; None if unknown
```
Allowed hosts ONLY: `api.fontsource.org`, `fonts.googleapis.com`, `fonts.gstatic.com`, `cdn.jsdelivr.net`
(reject any other host, non-https, redirects to other hosts). Family names are validated
(`^[A-Za-z0-9][A-Za-z0-9 .&'-]{0,59}$` and must exist in the catalog) before any URL is built.
Font catalog: `https://api.fontsource.org/v1/fonts?type=google` (cache JSON for 7 days; keep only
the fields above). TTF for a family/weight/style: request
`https://fonts.googleapis.com/css2?family=<Family+Name>:ital,wght@<0|1>,<weight>&display=swap`
with **no/`curl/8.0` User-Agent** (this makes Google answer with `.ttf` URLs; a browser UA gives woff);
the response has one `@font-face` per unicode-range subset, each preceded by a `/* latin */`-style
comment; take the **latin** block's `src: url(...ttf)` and download it from fonts.gstatic.com. Clamp
requested weight to the nearest weight the family offers; fall back to `normal` if no italic exists.
Icons: pinned `https://cdn.jsdelivr.net/npm/@mdi/font@7.4.47/fonts/materialdesignicons-webfont.ttf`
and `.../css/materialdesignicons.min.css` (class `.mdi-<name>::before{content:"\F0001"}` gives the
codepoints); cache both. Cache layout is the manager's choice under `cache_dir`. Thread-safe
(a `threading.Lock` around downloads) and atomic file writes. Tests: `tests/test_assets.py`
(offline with fake `fetch`; an optional live test guarded by env `PTOUCH_LIVE=1`).

### C. Home Assistant backend  [owner: agent C]
Owns: `custom_components/brother_ptouch/editor_api.py` (new), `__init__.py`, `manifest.json`
(`dependencies`: add `http`, `frontend`, `panel_custom`, `websocket_api`; do not touch requirements),
`services.py`, `services.yaml`, `translations/en.json`, `const.py`, `coordinator.py` (only if needed),
`tests/test_editor_api.py`, `tests/test_ha.py` (only to keep it passing).
* Storage: `homeassistant.helpers.storage.Store`, key `brother_ptouch.designs`, one dict of designs
  keyed by id; ids are slugs of the name, unique (`spice-jar`, `spice-jar-2`). `updated` ISO timestamp.
* Assets: one `AssetManager(cache_dir=hass.config.path(".storage/brother_ptouch_cache"))` per hass.
* Panel: static path `/brother_ptouch_static` -> `custom_components/brother_ptouch/frontend/`, then
  `panel_custom.async_register_panel(hass, webcomponent_name="brother-ptouch-panel",
  frontend_url_path="brother-ptouch", module_url="/brother_ptouch_static/brother-ptouch-panel.js?v=<manifest version>",
  sidebar_title="Labels", sidebar_icon="mdi:label-outline", require_admin=True)`.
  Register once in `async_setup`. The frontend files are written by agent D; do not create them
  (tests must not require them to exist).
* All WebSocket commands are admin-only (`@websocket_api.require_admin`), type prefix `brother_ptouch/`:
  * `printers` {} -> `{"printers":[{"entry_id","title","tape_mm": int|null,"state": "idle|printing|error|offline"}]}`
  * `designs/list` {} -> `{"designs":[{"id","name","updated"}]}`
  * `designs/get` {id} -> `{"design": {...}}` (error `not_found` if missing)
  * `designs/save` {design} -> `{"design": {...}}` (create when `id` missing/unknown, else replace; normalizes via `normalize_design`)
  * `designs/delete` {id} -> `{}`
  * `preview` {design, tape_mm?: int, entry_id?: str, variables?: object} -> `{"png": "<base64 PNG, 1:1 dots>", "width": int, "height": int, "tape_mm": int, "length_mm": number, "warnings": [str]}`.
    tape_mm: explicit, else the loaded tape of `entry_id`/the only printer, else 12. Resolves HA templates
    in text fields using `variables` over the design's default `variables`, then renders in the executor.
  * `print` {design?: object, id?: str, entry_id?: str, variables?: object, copies?: int(1..20)} -> `{}`.
    Exactly one of `design`/`id`. Goes through `coordinator.async_print` (so it is batched like the services).
  * `fonts/search` {query?, category?, limit?} -> `{"fonts":[...]}` (executor; AssetManager.search_fonts)
  * `fonts/ensure` {family, weights?: [int], italic?: bool} -> `{"ok": true}` (downloads; errors map to a WS error `asset_error`)
  * `icons/search` {query?, limit?} -> `{"icons":["mdi:..."]}`
* Service `brother_ptouch.print_template`: `template` (design id or name, required), `variables` (object),
  `copies`, `auto_cut`, `cut_each`, `margin_mm`, `device_id`; same batching path as the other services.
  Add to `services.yaml` and `translations/en.json`.
* Errors raise `HomeAssistantError`/send WS errors with readable messages; no unhandled exceptions.
Tests with fakes for the renderer/assets if A/B are not on disk yet (they land concurrently); re-run
against the real modules at the end if they appeared.

### D. Frontend panel  [owner: agent D]
Owns: everything under `custom_components/brother_ptouch/frontend/` (new). Custom element
`brother-ptouch-panel` as a **plain ES module, no build step, no npm dependencies at runtime**
(file `brother-ptouch-panel.js`; you may split into more `.js` files imported by relative path).
HA passes it `hass` (use `hass.callWS({type: "brother_ptouch/..."})`, `hass.localize` optional),
`narrow`, `panel`. Must work with HA's light and dark themes (use `var(--primary-text-color)`,
`--card-background-color`, `--divider-color`, `--primary-color` ...) and on a phone-width screen.
Features (v1): top bar (design name, tape picker with "from printer" default + 3.5/6/9/12/18/24 mm,
length auto / fixed mm, undo/redo, Save, Print with copies, printer picker if several); design list
(open/new/duplicate/delete); a canvas showing the **server-rendered preview PNG** (1 dot = n screen px,
zoom 100-600%) with an overlay for selecting, dragging, resizing (8 handles), rotating by 90 deg steps,
arrow-key nudging, Delete, Ctrl+Z/Y, Ctrl+D, snapping to label centre/edges; add buttons for Text, Icon,
QR, Barcode, Rectangle/line, Image (file picker -> data URI, downscaled to the label height); inspector
per element type (text: textarea, **Google font picker** with search + category filter calling
`fonts/search`, weight, italic, size/auto, align, valign, invert; icon: **MDI picker** with search
calling `icons/search` and showing glyphs via `<ha-icon icon="mdi:...">` when available; qr: data, ecc;
barcode: format, data, show_text; rect: stroke, fill; common x/y/w/h/rotation); a variables editor
(name -> default) plus "test values" for preview; a warnings strip from the preview response.
Call `fonts/ensure` when a font is chosen, before previewing. Debounce preview (~150 ms), drop stale
responses with a sequence counter, keep the last image on screen while loading, show errors inline.
The designer's whole state is the design JSON of section 1. Also provide `frontend/dev/`:
`index.html` that mounts the element with a fake `hass`, and `mock_backend.py` (stdlib HTTP server)
that implements the section-3 WS commands over a small HTTP POST bridge, using the real
`ptouch.design.render_design` / `ptouch.assets.AssetManager` when importable and otherwise a stub
(grey boxes) so the UI is usable on its own. Verify in a real browser if you can obtain one (try
`pip install playwright && playwright install chromium` in a venv inside the scratchpad dir, NOT the repo);
otherwise at least `node --check` every JS file and unit-test the pure logic.

## 3. Wire details shared by C and D
* WebSocket error responses use HA's standard error frame (`code`, `message`); the panel shows `message`.
* `png` is plain base64 (no `data:` prefix). `design` objects are exactly section 1.
* The saved design returned by `designs/save` is the normalized one with `id`, `name`, `updated`.
* `printers[].tape_mm` is the integer the printer reports (4 means 3.5 mm tape).
