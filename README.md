<p align="center"><img src="docs/images/logo-wordmark.png" alt="Brother P-touch for Home Assistant" width="420"></p>

<p align="center"><b>Design and print tape labels from Home Assistant, on your Brother P-touch.</b></p>

<p align="center">
<a href="https://hacs.xyz/docs/faq/custom_repositories"><img alt="HACS custom repository" src="https://img.shields.io/badge/HACS-Custom%20repository-orange.svg"></a>
<a href="https://github.com/thatgoodpickle/haos-labelprinter/releases"><img alt="Latest release" src="https://img.shields.io/github/v/release/thatgoodpickle/haos-labelprinter?include_prereleases"></a>
<a href="LICENSE"><img alt="MIT licence" src="https://img.shields.io/badge/licence-MIT-blue.svg"></a>
</p>

<p align="center"><img src="docs/images/editor-dark.png" alt="The label editor inside Home Assistant" width="800"></p>

## What you can do

- **Design labels in Home Assistant.** A **Labels** page in the sidebar lets you drag and drop text, icons, QR codes, barcodes, shapes and pictures. The preview is what prints.
- **Start from a template.** 35 ready-made labels: spice jars, freezer food, cables, breakers, Wi-Fi QR codes, battery dates and more.
- **Print from automations.** Print a label when something happens, with live values such as a date or a sensor reading.
- **Use it on your phone.** The editor works with touch.
- **Save tape.** Labels sent close together print as one strip with one cut.

## Does it work with my printer?

Short answer: it is **verified on the PT-P710BT only**. Other models might work, but nobody has confirmed it yet.

| Printer | Status | Notes |
|---|---|---|
| **PT-P710BT** | Verified by the maintainer | USB, Bluetooth and network bridge |
| **PT-P700** | Should work, untested | The code recognises its USB ID |
| **PT-P750W** | Should work, untested | The code recognises its USB ID |
| **PT-P300BT** | Reported working by users | Bluetooth only. 64 dots on 12 mm tape; cut by hand, with chain printing, cut marks and Feed |
| Other Brother P-touch (PT-E, PT-H, PT-P9xx) | Unknown, please test and report | Not promised to work |

Brother **QL** printers (the shipping and address label printers) are a different product line. They are **not supported**.

What the statuses mean, and the full list: [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

### Tried it on your printer? Tell us

Whether it worked or not, we want to know. It takes two minutes, and it is how this list grows.
**[Fill in the compatibility report](https://github.com/thatgoodpickle/haos-labelprinter/issues/new?template=compatibility-report.yml)**

## Install in 5 steps

1. In Home Assistant open **HACS**. Click the three dots at the top right and choose **Custom repositories**.
2. Paste `https://github.com/thatgoodpickle/haos-labelprinter`, choose the type **Integration**, and click **Add**.
3. Find **Brother P-touch** in HACS and click **Download**.
4. **Restart Home Assistant.**
5. Go to **Settings > Devices & services > Add integration**, search for **Brother P-touch**, and follow the steps.

More detail with every click: [docs/INSTALL.md](docs/INSTALL.md).

## Connect your printer

You have three choices. Pick the one that fits where your printer sits.

- **USB.** Plug the printer into the computer that runs Home Assistant. Home Assistant usually finds it by itself.
- **Bluetooth.** Home Assistant scans for the printer and pairs it for you, from the setup steps or from the label editor. The Home Assistant computer needs a Bluetooth adapter. Only one device can talk to the printer at a time, so disconnect your phone first.
- **Network bridge.** A tiny program runs on any Linux computer next to the printer (a Raspberry Pi, for example). Home Assistant talks to it over your network. Use this if the printer is far away or Home Assistant cannot use USB or Bluetooth.

Step-by-step help for each: [docs/INSTALL.md](docs/INSTALL.md).

## Make your first label in 2 minutes

1. Open **Labels** in the Home Assistant sidebar. (It is only shown to admin users.)
2. Tap **From template** and pick one, for example **Spice jar**. (Or tap **New label** to start from blank.)
3. Click the text and change it.
4. Click **Print**.

The first time you use a font or an icon it is downloaded, so the editor needs internet access once.

<p align="center"><img src="docs/images/template-gallery.png" alt="The template gallery" width="600"></p>

## Print from automations

Print a built-in template or one of your saved designs:

```yaml
action: brother_ptouch.print_template
data:
  template: freezer-date
  variables:
    name: Chili con carne
    portions: "4"
    date: "{{ now().strftime('%Y-%m-%d') }}"
```

Print some text:

```yaml
action: brother_ptouch.print_text
data:
  text: "Kitchen\nSpices"
  copies: 2
```

Print a QR code with a caption:

```yaml
action: brother_ptouch.print_qr
data:
  data: "https://home.example.com/box/42"
  text: "Box 42"
```

There is also `brother_ptouch.print_image` for pictures. If you have several printers, add `device_id`. All fields are listed in Developer tools > Actions. The labels fit the tape that is loaded.

## Screenshots

<p align="center">
<img src="docs/images/editor-light.png" alt="The label editor, light theme" width="420">
<img src="docs/images/phone-home.png" alt="The Labels home screen on a phone" width="150">
<img src="docs/images/phone-editor.png" alt="Editing a label on a phone" width="150">
</p>
<p align="center">
<img src="docs/images/printer-wizard.png" alt="Setting up a printer" width="300">
<img src="docs/images/printer-drawer.png" alt="The printer drawer in the editor" width="300">
<img src="docs/images/template-sheet.png" alt="A few of the 35 ready-made templates" width="300">
</p>

## Troubleshooting

- **I do not see Labels in the sidebar.** Restart Home Assistant after installing. Only admin users see it. Then hard-refresh the browser (Ctrl+Shift+R).
- **The printer is not answering.** The printer switches itself off after a while, and **it cannot be woken from Home Assistant: you have to press the power button on the printer.** Then press **Connect** (or just print again). If it is already on, disconnect any phone from it and move it closer. **Connect** tells you what went wrong.
- **Fonts or icons are missing.** They are downloaded from Google Fonts and jsDelivr the first time you use them. Check that Home Assistant has internet access.
- **Bluetooth does not connect.** The printer talks to one device at a time. Close the Brother app on your phone and turn off its Bluetooth for the printer.
- **I updated and the editor looks old.** Restart Home Assistant, then hard-refresh the browser. In the Companion app, clear the app cache.
- **The label is mirrored or upside down.** Open the integration, click **Configure**, and change the orientation.

## Status and known limits

This is early software. Here is what has and has not been checked.

**Checked on a real PT-P710BT:** USB, Bluetooth (through the computer's own Bluetooth) and the network bridge; printing text, QR codes, icons and templates; tape detection; strips of several labels as one piece. The editor was also checked in a simulated browser on desktop and touch, with demo data. Automated tests with fake printers pass.

**Not checked yet:**
- Running inside a live Home Assistant. This is the next test.
- The Home Assistant Companion app, and iOS.
- Pairing a real printer with the new pairing tool.
- Any printer other than the PT-P710BT.
- Home Assistant versions other than 2026.10.4.

Other limits: the label editor is for admin users. Brother tape (TZe) must be loaded. You need internet once for fonts and icons.

## Not affiliated with Brother

This is an independent, community project. It is not made, endorsed or supported by Brother Industries. Brother and P-touch are trademarks of their respective owners.

## More

- [Install and setup guide](docs/INSTALL.md)
- [Printer compatibility](docs/COMPATIBILITY.md)
- [Technical notes for developers](docs/TECHNICAL.md)
- [Changelog](CHANGELOG.md)
- Questions: [GitHub Discussions](https://github.com/thatgoodpickle/haos-labelprinter/discussions). Bugs: [open an issue](https://github.com/thatgoodpickle/haos-labelprinter/issues/new/choose).
- Want to help? See "Contributing" in [docs/TECHNICAL.md](docs/TECHNICAL.md#contributing).

Licence: [MIT](LICENSE).
