# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **PT-P300BT support.** The printer reports its model in the status, and labels are sized for it: its print head is 64 dots tall, so 12 mm tape gets 64 printable dots instead of 70. It has no cutter, so no cut is requested (on this model that only prints a cut mark). The editor canvas uses the selected printer's dots per tape width.
- **Cutting and feed in the editor.** Next to Copies (on phones: in the menu and the print sheet), the editor offers **Chain** (no feed after a print, so the next label follows right after it instead of ~25 mm later; the last label stays inside until the next print or Feed), **Auto cut** (printers with a cutter) or **Cut marks** (a mark after every label, printers without one) and **Feed** (feeds the tape out). The choices are remembered per browser. The print services take `chain` and `cut_mark`, and printers without a cutter get a **Feed tape** button entity.

### Changed
- **A printer that is off no longer fails the integration's setup.** The entry loads and the device shows as unavailable until the printer answers. A printer that is switched off or held by another device is logged as a warning; other connection problems stay errors. The printer's model is remembered, so model-specific behaviour is there even when it is off at startup.

### Fixed
- Bluetooth printers could not be reached when another program on the host had registered the Serial Port profile with BlueZ: BlueZ allows one per UUID, so connecting failed with "Could not talk to the printer". The connection now falls back to a plain RFCOMM socket on the configured channel.

## [0.3.1]

### Changed
- **Phone layout redesigned.** On a phone the editor now opens on a Home screen with **New label**, **From template** and your saved labels. Editing has a bottom toolbar, a properties sheet that never hides the label, a Print sheet, and the Back button steps back inside the editor.
- The printer chip says **Not answering** instead of "Asleep" when the printer cannot be reached. The printer cannot be woken from Home Assistant; press its power button.

### Fixed
- Layout cut off and overlapping on phones: the screen's safe area was padded twice (Home Assistant already pads custom panels). Tapping empty canvas now deselects, touch targets are at least 44 px, and the keyboard and landscape layouts work.
- A crash when opening a label while an element was selected.

### Added
- A project icon (shown on the integration page) and README screenshots.
- A test rig that runs a real Home Assistant in a browser (`tools/ha-rig/`) for checking the editor on phone screens.

## [0.3.0]

### Added
- Printer setup in the label editor: printer drawer and setup wizard.
- Bluetooth scan, pair and connect, from the editor and from the integration setup.
- Setting for the Bluetooth wake time (how long to keep trying to reach the printer).
- Compatibility list, install guide, technical notes and issue forms.

### Changed
- Friendlier setup text and error messages.
- README rewritten for non-developers; technical content moved to docs/TECHNICAL.md.

### Fixed
- Icon warning.

## [0.2.0]

### Added
- Label editor in the Home Assistant sidebar (drag and drop).
- Google Fonts and Material Design Icons (downloaded on first use).
- 35 built-in templates.
- `brother_ptouch.print_template` service for saved designs and built-in templates, with variables.

## [0.1.0]

### Added
- Initial release: P-touch raster protocol for the PT-P710BT.
- Connections over USB, Bluetooth and an HTTP network bridge.
- Services `print_text`, `print_qr` and `print_image`.
- Strips: print requests close together print as one piece with one cut.
- Status entities (status, tape, problem).

[0.3.0]: https://github.com/thatgoodpickle/haos-labelprinter/releases
[0.2.0]: https://github.com/thatgoodpickle/haos-labelprinter/releases
[0.1.0]: https://github.com/thatgoodpickle/haos-labelprinter/releases
