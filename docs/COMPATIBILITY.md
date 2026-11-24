# Printer compatibility

Only one printer has been tested by the maintainer. This list grows with your reports.

## Status legend

| Status | Meaning |
|---|---|
| Verified by the maintainer | The maintainer tested it on real hardware. |
| Reported working by users | Users reported it works in the compatibility form. |
| Should work, untested | The code recognises the model, but nobody has confirmed it. Not a promise. |
| Unknown, please test and report | Nothing is known. May or may not work. |
| Not supported | Known not to work, or a different product line. |

## Models

"Untested" means no one has checked it. It does not mean it fails.

| Model | Status | USB | Bluetooth | Bridge | Auto-cut | Tape detection |
|---|---|---|---|---|---|---|
| PT-P710BT | Verified by the maintainer | Verified | Verified | Verified | Verified | Verified |
| PT-P700 | Should work, untested | Untested (USB ID recognised) | n/a (no Bluetooth on this model, not checked) | Untested | Untested | Untested |
| PT-P750W | Should work, untested | Untested (USB ID recognised) | Untested | Untested | Untested | Untested |
| PT-E550W | Unknown, please test and report | Untested | Untested | Untested | Untested | Untested |
| PT-P900W / PT-P950NW | Unknown, please test and report | Untested | Untested | Untested | Untested | Untested |
| PT-H500 | Unknown, please test and report | Untested | Untested | Untested | Untested | Untested |
| PT-E500 | Unknown, please test and report | Untested | Untested | Untested | Untested | Untested |
| PT-P300BT | Reported working by users | n/a (no USB data connection) | Reported working | Untested | n/a (manual cutter) | Reported working |
| Brother QL series | Not supported | | | | | Different product line (shipping and address labels) |

Notes on the PT-P710BT: "Auto-cut" and "Tape detection" were observed on the real printer. Text, QR codes, icons, templates and strips of several labels were printed. The editor, the Home Assistant Companion app and the new pairing tool are not part of the printer verification; see the README for what is checked.

Notes on the PT-P300BT: the printer reports model code `0x72` in its status. Its print head is 64 dots tall, so 12 mm tape prints 64 dots (pins 32 to 95 of the 128-pin raster) instead of 70; narrower tapes are the same as on the PT-P7xx. It has no cutter: "auto cut" would only print a cut mark, so the editor offers that as **Cut marks**, together with **Chain** (no feed between prints) and **Feed**. Printed over Bluetooth on 12 mm laminated tape: text, chain printing, cut marks and Feed. Protocol details from [Ircama/PT-P300BT](https://github.com/Ircama/PT-P300BT).

## How to report

1. Open the [compatibility report form](https://github.com/thatgoodpickle/haos-labelprinter/issues/new?template=compatibility-report.yml).
2. Choose your model and how you connected.
3. Tick what worked. Leave unticked what you did not try or what failed.
4. Add your Home Assistant version, install type and integration version.
5. Add notes or a log excerpt. Check that no password, token, address or other secret is in what you paste.

Failures are useful too. Please report them.

## How maintainers update the list

1. Read the report. Look for the ticked features, versions and logs.
2. A model moves to **Reported working by users** after at least one clear report where printing worked. Fill only the columns that the reporter ticked; leave the rest as untested.
3. A model moves to **Verified by the maintainer** only after the maintainer tests it on hardware.
4. Move a model to **Not supported** only with evidence (for example a protocol difference), and say why.
5. Update this file and the short table in the README, link the issue, and add a line in [CHANGELOG.md](../CHANGELOG.md).
