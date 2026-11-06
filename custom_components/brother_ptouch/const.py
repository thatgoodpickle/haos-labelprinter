"""Constants."""
DOMAIN = "brother_ptouch"

CONF_TRANSPORT = "transport"
CONF_USB_SERIAL = "serial"
CONF_ADDRESS = "address"
CONF_CHANNEL = "channel"
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_MODEL = "model"          # status byte 4, kept for when the printer is offline

TRANSPORT_USB = "usb"
TRANSPORT_BLUETOOTH = "bluetooth"
TRANSPORT_BRIDGE = "bridge"

CONF_ORIENTATION = "orientation"
DEFAULT_ORIENTATION = "normal"

SCAN_INTERVAL_SECONDS = 60

CONF_BATCH_WINDOW = "batch_window"
DEFAULT_BATCH_WINDOW = 3.0   # seconds: print requests inside this window become one strip

CONF_WAKE_SECONDS = "wake_seconds"
DEFAULT_WAKE_SECONDS = 20     # how long a print / Connect waits for a sleeping Bluetooth printer
POLL_WAKE_SECONDS = 8.0       # polling gives up quickly: it must not keep a sleeping printer's radio busy

# Failure reasons shared with ptouch.btadmin / TransportError.reason (docs/BLUETOOTH_CONTRACT.md section 1)
REASON_OK = "ok"
REASON_ERROR = "error"
# Switched off or held by another device: expected, so logged as a warning
OFFLINE_REASONS = frozenset({"asleep", "busy"})
REASON_MESSAGES = {
    "asleep": "The printer isn't answering. Press its power button to switch it on, make sure no phone is "
              "connected to it, then try again.",
    "not_paired": "This printer isn't paired with Home Assistant yet.",
    "bluetooth_off": "Bluetooth is switched off on the Home Assistant host.",
    "busy": "The printer is connected to something else (a phone?). Disconnect it and try again.",
    "no_dbus": "Home Assistant can't use Bluetooth here. Use USB or the network bridge.",
    "no_adapter": "Home Assistant can't use Bluetooth here. Use USB or the network bridge.",
    "no_library": "Home Assistant can't use Bluetooth here. Use USB or the network bridge.",
    "pairing_failed": "Pairing failed. Check the PIN (usually 0000) and try again.",
    "pairing_timeout": "Pairing took too long. Make sure the printer is on and close by, then try again.",
    "not_found": "The printer was not found. Switch it on and keep it close to the Home Assistant host.",
    "permission": "Home Assistant is not allowed to use Bluetooth here.",
}


def friendly_message(reason: str | None, fallback: str = "") -> str:
    """Plain-English text for a failure reason ("" for ok)."""
    if not reason or reason == REASON_OK:
        return ""
    return REASON_MESSAGES.get(reason) or fallback or "The printer could not be reached."
