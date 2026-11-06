# Bluetooth: pairing, connecting and troubleshooting

Applies to the PT-P710BT over Bluetooth Classic (Serial Port Profile, RFCOMM) through BlueZ.
Code: `ptouch/btadmin.py` (scan, pair, forget, test), `ptouch/bluez.py` (the print transport),
`ptouch/_bluez_common.py` (shared D-Bus helpers). Shared vocabulary: `docs/BLUETOOTH_CONTRACT.md`.

## What Brother documents (and what I could not read)

Research done with web search/fetch. Brother's support site mostly returned only FAQ titles (answer bodies
missing) or HTTP 403 / bot-protection pages, so most of this is UNVERIFIED.

| Topic | Finding | Status |
|---|---|---|
| Pairing PIN | Quick Setup Guide (seen as a search-result snippet of the manual on manualshive.com): "If asked to enter a PIN Code, enter 0000". | Snippet only; full page not readable. Treat `0000` as the default. |
| Device name | Appears as "PT-P710BT" followed by the last four digits of the serial number. | Same snippet. |
| One connection at a time | The guide says that if the printer is not found it "may already be connected to another device": turn Bluetooth off on that device or power-cycle the printer. This matches our `busy` reason. | Snippet; the formal statement "one connection at a time" is UNVERIFIED but consistent with measured behaviour (a second RFCOMM connect fails while a phone holds the link). |
| LED | Green LED stays lit while a Bluetooth connection is established. | Snippet only. |
| Power off | Hold the power button until the LED goes out. | Snippet only. |
| Auto power-off / sleep timing | Not found. Brother's PT-P710BT FAQ list has an entry about reconnecting after the Bluetooth connection is cut off, but the answer text could not be fetched. | UNVERIFIED. The printer's own settings may include an auto power-off option (set with the P-touch Editor/Printer Setting Tool on the PC); not confirmed here. |
| Bluetooth on/off setting | Brother documents an on/off Bluetooth menu for the E-series labellers (PT-E310BT/E560BT, a different line). For the PT-P710BT it was not found. | UNVERIFIED for this model. |
| Waking the printer over Bluetooth | **Not possible.** The owner confirmed on a real PT-P710BT that a switched-off printer cannot be woken from software; the power button on the printer must be pressed. Measured on the same unit: while the printer stays switched on, the Bluetooth link answered normally after 5, 10 and 20 minutes idle (1.8 to 2.6 s per connect), so the earlier 'asleep' failures were the printer powering itself off, not Bluetooth sleeping. The Connect button therefore retries for the configured time (which lets the user press the button) and explains. | Verified |

Pages tried: brother.co.za / brother.co.uk / brother.com.au PT-P710BT FAQ pages (titles only),
manualmachine.com (403), manualshive.com (bot protection).

## How pairing works here

`btadmin.pair(address, pin="0000", timeout=45)`:

1. Connects to the system D-Bus (or a given `bus_address`), finds the `org.bluez.Device1` for the address through
   `ObjectManager`. If BlueZ does not know it yet, it runs a short Bluetooth Classic discovery (up to 10 s) and
   returns `not_found` if it never shows up.
2. If already paired, skips to step 4 (that is success).
3. Exports an `org.bluez.Agent1` object on its own connection and registers it with
   `AgentManager1.RegisterAgent(path, "NoInputNoOutput")`. It auto-accepts `RequestConfirmation`,
   `RequestAuthorization`, `AuthorizeService`; answers `RequestPinCode` with the PIN and `RequestPasskey` with
   `int(PIN)`; display callbacks and `Cancel`/`Release` are no-ops. Then calls `Device1.Pair()`, bounded by
   `timeout` (on expiry `CancelPairing` is called). The agent is always unregistered afterwards.
4. Sets `Trusted=True` (so BlueZ lets the printer reconnect) and disconnects the pairing link so the printer's
   single connection is free.

Scanning (`btadmin.scan`) powers the adapter on if needed, sets a `bredr` discovery filter, scans for the
requested time, stops discovery only if it started it, and returns known and new devices (printers first, then by
signal strength; unnamed unpaired devices are dropped). `forget` calls `Adapter1.RemoveDevice`.

Printing (`BlueZTransport`) registers a client `Profile1` for the Serial Port UUID, calls
`Device1.ConnectProfile`, and BlueZ hands the connected RFCOMM file descriptor to `NewConnection`. Retries are
bounded by `wake_timeout` seconds (default 12; 0 means a single attempt).

### Failure reasons

| reason | typical BlueZ signal | meaning / what to do |
|---|---|---|
| `asleep` | `br-connection-page-timeout`, `page-timeout`, `host-down`, no answer before the deadline, `AuthenticationTimeout` when connecting | Printer is off, out of range, asleep or busy elsewhere. Press its power button, disconnect phones, move closer. |
| `not_paired` | device unknown to BlueZ, `AuthenticationFailed/Rejected/Canceled` while connecting, "not paired" | Pair it first (setup wizard or `btadmin.pair`). |
| `bluetooth_off` | `org.bluez.Error.NotReady`, adapter `Powered=false`, rfkill | Switch Bluetooth on (`btadmin.power_on`). |
| `busy` | `InProgress`, `br-connection-busy`, "resource busy" | Another device (phone) holds the printer. Disconnect it. Retried until the deadline. |
| `pairing_failed` | `AuthenticationFailed/Rejected/Canceled`, `ConnectionAttemptFailed`, `Failed` during pairing | Wrong PIN, printer refused, or it is paired to a phone. Retry; try PIN `0000`; forget and re-pair. |
| `pairing_timeout` | `AuthenticationTimeout`, or `timeout` expired | Nobody confirmed in time; printer asleep. |
| `not_found` | address never seen in discovery | Switch on, move close, scan again. |
| `permission` | `AccessDenied`, "not permitted" | The HA container is not allowed on the bus. |
| `profile_taken` | `NotPermitted` "UUID already registered" from `RegisterProfile` | Another program holds the Serial Port profile; BlueZ allows one per UUID. The print transport then falls back to a plain RFCOMM socket on the configured channel, so this only surfaces from `btadmin.connect_test`. |
| `no_dbus` / `no_adapter` / `no_library` | cannot reach the bus or BlueZ / no `Adapter1` / `dbus-fast` missing | HA cannot use Bluetooth here; use USB or the network bridge. |
| `error` | anything else (e.g. `Input/output error`) | Retry; see logs (debug level shows raw BlueZ text). |

## Troubleshooting

1. Printer on (power LED lit)? Press the power button; the first connect after switching on may need a few seconds
   (raise `wake_seconds`).
2. A phone or laptop may be connected to the printer. Turn Bluetooth off on it or forget the printer there. Only
   one connection works at a time.
3. Distance and interference: keep the printer within a few metres of the HA host's adapter.
4. Pairing keeps failing: forget the device (UI, or `btadmin.forget`), power-cycle the printer, pair again. The
   default PIN is `0000`.
5. Check `btadmin.available()`: `bluetooth_off` means the adapter is powered down or rfkill-blocked; `no_dbus`
   means HA's container has no access to `/run/dbus/system_bus_socket`.
6. In Home Assistant OS, Bluetooth adapters are managed by the Supervisor; make sure the adapter is not claimed
   by another integration with exclusive access.
7. Still stuck: use USB, or the network bridge (`bridge/`).

## Testing without hardware

`tests/fake_bluez.py` starts a private `dbus-daemon --session` and exports a fake `org.bluez` (adapter, devices,
AgentManager1, ProfileManager1; the fake `Pair` calls the registered agent back and `ConnectProfile` passes an
RFCOMM socketpair descriptor to `NewConnection`). Tests pass its address as `bus_address`; the real system bus is
never opened (a test fixture asserts this).
