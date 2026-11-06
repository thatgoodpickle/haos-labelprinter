# Technical notes

For developers and curious people. For installing, see [INSTALL.md](INSTALL.md).

## Documents

- [EDITOR_CONTRACT.md](EDITOR_CONTRACT.md): label design JSON, editor API.
- [BLUETOOTH_CONTRACT.md](BLUETOOTH_CONTRACT.md): printer setup, pairing and connect (shared vocabulary).
- [BLUETOOTH.md](BLUETOOTH.md): how pairing works, failure reasons, what Brother does and does not document.
- [TEMPLATES.md](TEMPLATES.md): the 35 built-in templates and the research behind them.
- [BROTHER_APP_PARITY.md](BROTHER_APP_PARITY.md): comparison with Brother's own app.
- [MOBILE_TESTING.md](MOBILE_TESTING.md): checklist for testing the editor on phones.
- [COMPATIBILITY.md](COMPATIBILITY.md): printer compatibility list.

## Architecture

```
custom_components/brother_ptouch/
  ptouch/            protocol core: no Home Assistant imports, relative imports, blocking code
                     (raster encoding, renderer, templates, transports, Bluetooth admin)
  __init__.py, config_flow.py, coordinator.py, services.py, sensor.py, binary_sensor.py, button.py
                     Home Assistant integration layer
  editor_api.py, printer_api.py, bluetooth_api.py
                     websocket/HTTP API used by the editor
  frontend/          the sidebar panel (Labels): plain JavaScript modules, no build step
bridge/              ptouch_bridge.py: small HTTP server that uses the same protocol core
tests/               core tests, Home Assistant tests, fake printers, fake BlueZ
```

The protocol core is shared by the integration and the bridge, so a printer behaves the same on both paths.
Core code is synchronous; the Home Assistant layer calls it in an executor.

Transports: USB (pyusb), Bluetooth through BlueZ, device path (`/dev/usb/lp0`, `/dev/rfcomm0`), and HTTP to a bridge.

### Connection modes

| Mode | Use when | Needs |
|---|---|---|
| USB | Printer is plugged into the HA host | `libusb-1.0` on the host; `/dev/bus/usb` visible to HA (udev permissions) |
| Bluetooth | HA host has a BT adapter and BlueZ | Printer paired with the host (the integration can pair it) |
| Bridge | Printer is far from HA, or HA cannot reach it | `bridge/ptouch_bridge.py` on a Linux machine next to the printer |

### Bluetooth route

The PT-P710BT speaks Bluetooth Classic (RFCOMM, serial port profile), not BLE. Home Assistant's BLE stack and ESPHome Bluetooth proxies therefore cannot carry it. The integration uses BlueZ over the system D-Bus (`dbus-fast`, which Home Assistant ships): it registers a client `Profile1` for the Serial Port UUID, calls `Device1.ConnectProfile`, and BlueZ hands over the connected RFCOMM file descriptor. If D-Bus is not reachable it can fall back to a raw RFCOMM socket. Pairing and scanning (`ptouch/btadmin.py`) use the same D-Bus route with an `Agent1`. Details and failure reasons: [BLUETOOTH.md](BLUETOOTH.md).

## Entities

`sensor`: status (idle/printing/error), tape width, tape type, tape colour, text colour.
`binary_sensor`: problem (with an `errors` attribute), tape loaded. Status is polled every 60 s.

## Services

All print services take an optional `device_id` (only needed with several printers), `copies`, `auto_cut`, `cut_each`, `margin_mm`. Labels are sized to the tape that is loaded. Field lists are in `custom_components/brother_ptouch/services.yaml`.

| Service | Main fields |
|---|---|
| `print_text` | `text`, `align`, `font_size`, `font` |
| `print_qr` | `data`, `text`, `font_size`, `font` |
| `print_image` | `image_path` (must be in `allowlist_external_dirs`) or `image_url`, `dither` |
| `print_template` | `template` (saved design id or name, or built-in template id), `variables` |

`text` supports Home Assistant templates.

## Saving tape (strips)

A P-touch wastes about 25 mm of blank tape (head-to-cutter distance) at the start of every job. It cannot be avoided or held across jobs: the printer finishes and cuts the previous label as soon as a new job starts. So requests that arrive within a few seconds of each other are merged into one job: one leader, no cut between labels, one cut at the end. The window is the **Strip window** option (default 3 s, 0 = off). Use `cut_each: true` for a cut after every label.

## Hardware findings (PT-P710BT)

- **Single-page strips.** A strip of several labels is sent as one page, not as several pages.
- **Chain printing keeps the last page inside.** In chain mode the printer holds the last page in the machine; the job must end properly for it to come out and be cut.
- **Chaining is opt-in.** A print may pass `chain` (`ESC i K` without bit 3: no feed at the end, so the next job starts right after) and, on printers without a cutter (`has_cutter` false in the `printers` rows), `cut_mark` (`ESC i M` bit 6, which prints a mark instead of cutting; each label then becomes its own job so every label ends with one). A batch only chains if every request in it asked to. `feed` sends a one-blank-line page without chaining to push a held label out (never a bare `0x1A`).
- **A bare `0x1A` hangs the printer.** Never send the print command without page data. The printer faults into a flashing-red state until power-cycled.
- **No `ESC @` in status polling.** Status requests deliberately do not send initialize.
- **EBUSY retries.** The device can report busy right after a job; the transport retries.
- **BlueZ D-Bus profile route.** Raw RFCOMM sockets are not needed; see above.
- Printable pins per tape follow Brother's PT-P700 raster reference (9 mm = 50 pins, 39 margin, etc.).
- Per-model differences key on the model code in status byte 4 (`MODEL_TAPE_GEOMETRY`, `MODELS_WITHOUT_CUTTER` in `ptouch/protocol.py`). Labels are rendered at print time from the live status, so the renderer always knows the model. Unknown codes use the PT-P7xx table. The PT-P300BT (`0x72`) prints 64 dots on 12 mm tape and has no cutter.
- USB ID `04F9:20AF` is confirmed for the PT-P710BT. PT-P700 (`2061`) and PT-P750W (`2062`) are matched but untested.
- Orientation: on the PT-P710BT the default (Normal) is correct. The **Orientation** option offers flips if another unit differs.

## Label editor

Drag-and-drop editor with text (Google Fonts), MDI icons, QR codes, barcodes, shapes and images, 35 templates, `{{ variables }}` and Home Assistant templates such as `{{ states('sensor.x') }}`, and a preview that matches the print. Fonts and icons are downloaded on first use from Google Fonts and jsDelivr and cached on the Home Assistant host. The panel is for admin users. See [EDITOR_CONTRACT.md](EDITOR_CONTRACT.md).

## Bridge

```
python3 bridge/ptouch_bridge.py --usb --token SECRET
python3 bridge/ptouch_bridge.py --bluetooth AA:BB:CC:DD:EE:FF --token SECRET
python3 bridge/ptouch_bridge.py --device /dev/usb/lp0 --token SECRET
```

API: `GET /health`, `GET /status`, `POST /print?pages=N` (body = raw job bytes). With a token, requests need `Authorization: Bearer SECRET`. Docker: `docker build -f bridge/Dockerfile -t ptouch-bridge .`. A systemd unit is in `bridge/ptouch-bridge.service`.

## Development setup

```
python -m venv .venv    && .venv/bin/pip install pillow pytest segno pyusb
.venv/bin/python -m pytest tests/test_core.py            # protocol, renderer, bridge
python -m venv .venv-ha && .venv-ha/bin/pip install pytest-homeassistant-custom-component pyusb segno
PYTHONPATH=. .venv-ha/bin/python -m pytest tests/test_ha.py   # HA integration
```

Home Assistant tests block real sockets, so network and server tests belong in the plain `.venv`. Other test files: `test_btadmin.py`, `test_bluez_transport.py`, `test_bluetooth_ha.py`, `test_editor_api.py`, `test_design.py`, `test_templates.py`, `test_assets.py`, `test_frontend_contract.py`. Bluetooth tests use `tests/fake_bluez.py` (a private `dbus-daemon --session` with a fake `org.bluez`); they never open the real system bus. Frontend tests are run with `node dev/tests/<file>.mjs` from the `frontend` folder.

## Release process

1. Update `version` in `custom_components/brother_ptouch/manifest.json`.
2. Add an entry to [CHANGELOG.md](../CHANGELOG.md).
3. Run the tests above.
4. Tag `vX.Y.Z` and publish a GitHub release (mark it a pre-release while the project is early). HACS offers releases; pre-releases show only when "Show beta versions" is on.

## Contributing

Issues and pull requests are welcome. For printer reports use the [compatibility form](https://github.com/thatgoodpickle/haos-labelprinter/issues/new?template=compatibility-report.yml); for bugs the [bug form](https://github.com/thatgoodpickle/haos-labelprinter/issues/new?template=bug-report.yml). Keep the protocol core free of Home Assistant imports, add tests, and do not claim support for hardware nobody has verified. Never paste secrets or tokens into issues.
