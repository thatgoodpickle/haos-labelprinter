"""Private helpers shared by ``btadmin`` and ``bluez`` (BlueZ over D-Bus via dbus-fast).

No Home Assistant imports. Nothing here talks to a bus unless a caller passes
one in or asks ``open_bus`` for it. Deliberately has no ``from __future__
import annotations``: dbus-fast reads the string annotations ("o", "h"...)
of ServiceInterface methods as D-Bus signatures.
"""
import asyncio
import logging
import socket
import time
import uuid as uuidlib

_LOGGER = logging.getLogger(__name__)

BLUEZ = "org.bluez"
SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
IF_ADAPTER = "org.bluez.Adapter1"
IF_DEVICE = "org.bluez.Device1"
IF_PROPS = "org.freedesktop.DBus.Properties"
DEFAULT_WAKE_TIMEOUT = 12.0
MIN_ATTEMPT = 3.0  # the first ConnectProfile always gets at least this long, even for wake_timeout=0
FD_WAIT = 10.0

FRIENDLY = {
    "ok": "OK.",
    "asleep": "The printer isn't answering. Switch it on, make sure no phone is connected to it, "
              "and keep it close to Home Assistant.",
    "not_paired": "This printer isn't paired with Home Assistant yet.",
    "bluetooth_off": "Bluetooth is switched off on the Home Assistant host.",
    "no_adapter": "No Bluetooth adapter was found on the Home Assistant host.",
    "no_dbus": "Home Assistant can't reach the Bluetooth service (BlueZ) on this host.",
    "no_library": "The Bluetooth library (dbus-fast) is not installed.",
    "busy": "The printer is connected to something else (a phone?). Disconnect it and try again.",
    "pairing_failed": "Pairing failed. Check that the printer is on and in range, and that the PIN is right "
                      "(the default is 0000).",
    "pairing_timeout": "Pairing timed out. Switch the printer on, keep it close and try again.",
    "not_found": "The printer wasn't found. Switch it on, keep it close and scan again.",
    "permission": "Home Assistant isn't allowed to use Bluetooth on this host.",
    "profile_taken": "Another program on this host has registered the Serial Port profile with BlueZ.",
    "error": "Bluetooth connection failed.",
}

# reasons for which retrying ConnectProfile cannot help
FATAL = {"not_paired", "bluetooth_off", "no_adapter", "no_dbus", "no_library", "permission", "not_found"}


class LinkError(Exception):
    """Internal: failure with a reason code, a friendly message and the raw detail."""

    def __init__(self, reason, message=None, detail=""):
        self.reason = reason
        self.message = message or FRIENDLY.get(reason, FRIENDLY["error"])
        self.detail = detail
        super().__init__(self.message)


def classify(name, text="", context="connect"):
    """Map a D-Bus error name + message to a shared reason code.

    ``context`` is ``connect`` (ConnectProfile) or ``pair`` (Device1.Pair).
    """
    n = (name or "").rsplit(".", 1)[-1]
    t = (text or "").lower()
    if "page-timeout" in t or "page timeout" in t or "host-down" in t or "host is down" in t:
        return "asleep"
    if n == "NotReady" or "not powered" in t or "powered off" in t or "rfkill" in t:
        return "bluetooth_off"
    if n in ("InProgress", "Busy") or "busy" in t:
        return "busy"
    if n in ("AccessDenied", "NotPermitted", "PermissionDenied") or "not permitted" in t \
            or "permission denied" in t:
        return "permission"
    if n in ("ServiceUnknown", "NameHasNoOwner") or (name or "").endswith("Error.ServiceUnknown"):
        return "no_dbus"
    if n == "DoesNotExist":
        return "not_found"
    if n == "AuthenticationTimeout":
        return "pairing_timeout" if context == "pair" else "asleep"
    if n in ("AuthenticationFailed", "AuthenticationRejected", "AuthenticationCanceled"):
        return "pairing_failed" if context == "pair" else "not_paired"
    if "not paired" in t:
        return "not_paired"
    if context == "pair" and n in ("ConnectionAttemptFailed", "Failed", "NotSupported", "AlreadyConnected"):
        return "pairing_failed"
    return "error"


def link_error_from_dbus(err, context="connect"):
    name = getattr(err, "type", "") or ""
    text = getattr(err, "text", "") or str(err)
    reason = classify(name, text, context)
    return LinkError(reason, detail=f"{name}: {text}")


# -- bus helpers -----------------------------------------------------------------
async def open_bus(bus_address=None, timeout=5.0):
    """Connect a dbus-fast MessageBus (unix-fd capable). ``None`` = the real system bus."""
    try:
        from dbus_fast import BusType
        from dbus_fast.aio import MessageBus
    except ImportError as err:
        raise LinkError("no_library", detail=str(err)) from err
    try:
        if bus_address:
            bus = MessageBus(bus_address=bus_address, negotiate_unix_fd=True)
        else:
            bus = MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True)
        return await asyncio.wait_for(bus.connect(), timeout)
    except Exception as err:  # noqa: BLE001  (bad address, no socket, refused, timeout...)
        raise LinkError("no_dbus", detail=f"{type(err).__name__}: {err}") from err


async def call(bus, path, interface, member, signature="", body=(), destination=BLUEZ):
    """Plain method call (no introspection); raises ``DBusError`` on an error reply."""
    from dbus_fast import Message, MessageType
    from dbus_fast.errors import DBusError
    reply = await bus.call(Message(destination=destination, path=path, interface=interface,
                                   member=member, signature=signature, body=list(body)))
    if reply is None:
        return []
    if reply.message_type == MessageType.ERROR:
        raise DBusError(reply.error_name, reply.body[0] if reply.body else "", reply)
    return reply.body


def _plain(v):
    return v.value if hasattr(v, "signature") and hasattr(v, "value") else v


async def managed_objects(bus):
    """``{path: {interface: {prop: value}}}`` with Variants unwrapped."""
    from dbus_fast.errors import DBusError
    try:
        body = await call(bus, "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
    except DBusError as err:
        raise link_error_from_dbus(err) from err
    out = {}
    for path, ifaces in (body[0] if body else {}).items():
        out[path] = {i: {k: _plain(v) for k, v in props.items()} for i, props in ifaces.items()}
    return out


async def get_props(bus, path, interface):
    body = await call(bus, path, IF_PROPS, "GetAll", "s", [interface])
    return {k: _plain(v) for k, v in body[0].items()}


async def set_prop(bus, path, interface, name, signature, value):
    from dbus_fast import Variant
    await call(bus, path, IF_PROPS, "Set", "ssv", [interface, name, Variant(signature, value)])


def adapters_in(objs):
    """Sorted ``[(path, props)]`` of Adapter1 objects."""
    return sorted(((p, i[IF_ADAPTER]) for p, i in objs.items() if IF_ADAPTER in i), key=lambda x: x[0])


def pick_adapter(objs, adapter=None):
    """Choose by path, ``hciN`` or address; default: first powered, else first."""
    found = adapters_in(objs)
    if not found:
        raise LinkError("no_adapter")
    if adapter:
        a = str(adapter).upper()
        for path, props in found:
            if a in (path.upper(), path.rsplit("/", 1)[-1].upper(), str(props.get("Address", "")).upper()):
                return path, props
        raise LinkError("no_adapter", message=f"Bluetooth adapter {adapter} was not found.")
    for path, props in found:
        if props.get("Powered"):
            return path, props
    return found[0]


def find_device(objs, address):
    """``(path, props)`` of the Device1 with this address, or ``None``."""
    want = str(address).upper().replace("-", ":")
    for path, ifaces in objs.items():
        d = ifaces.get(IF_DEVICE)
        if d and str(d.get("Address", "")).upper() == want:
            return path, d
    return None


def make_profile_class(got):
    """Client ``org.bluez.Profile1`` whose NewConnection resolves ``got`` with the RFCOMM fd."""
    from dbus_fast.service import ServiceInterface, method

    class Profile(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.Profile1")

        @method()
        def Release(self):  # noqa: N802
            pass

        @method()
        def NewConnection(self, device: "o", fd: "h", props: "a{sv}"):  # noqa: N802,F821
            if not got.done():
                got.set_result(fd)

        @method()
        def RequestDisconnection(self, device: "o"):  # noqa: N802,F821
            pass

    return Profile()


async def unregister_profile(bus, profile_path):
    try:
        await call(bus, "/org/bluez", "org.bluez.ProfileManager1", "UnregisterProfile", "o", [profile_path])
    except Exception:  # noqa: BLE001
        pass
    try:
        bus.unexport(profile_path)
    except Exception:  # noqa: BLE001
        pass


async def spp_connect(bus, address, profile_uuid=SPP_UUID, timeout=DEFAULT_WAKE_TIMEOUT):
    """Register a client profile and ``ConnectProfile`` with retries bounded by ``timeout`` seconds.

    Returns ``(sock, device_path, profile_path)``; the caller must later call
    ``unregister_profile``. Raises ``LinkError`` with a reason code.
    """
    from dbus_fast import Variant
    from dbus_fast.errors import DBusError

    objs = await managed_objects(bus)
    hit = find_device(objs, address)
    if hit is None:
        raise LinkError("not_paired", detail="device unknown to BlueZ")
    dev_path, dev = hit
    adapter = objs.get(dev.get("Adapter"), {}).get(IF_ADAPTER)
    if adapter is not None and adapter.get("Powered") is False:
        raise LinkError("bluetooth_off")

    loop = asyncio.get_running_loop()
    got = loop.create_future()
    profile_path = f"/org/ptouch/p{uuidlib.uuid4().hex}"
    bus.export(profile_path, make_profile_class(got))
    try:
        await call(bus, "/org/bluez", "org.bluez.ProfileManager1", "RegisterProfile", "osa{sv}", [
            profile_path, profile_uuid, {
                "Role": Variant("s", "client"),
                "RequireAuthentication": Variant("b", False),
                "RequireAuthorization": Variant("b", False),
            }])
    except DBusError as err:
        bus.unexport(profile_path)
        # BlueZ allows one Profile1 per UUID and answers NotPermitted "UUID already registered"
        # when another program holds it; callers can fall back to a plain socket.
        if "already registered" in (err.text or "").lower():
            raise LinkError("profile_taken", detail=f"{err.type}: {err.text}") from err
        raise link_error_from_dbus(err) from err

    try:
        deadline = time.monotonic() + max(0.0, float(timeout))
        attempt = 0
        last = LinkError("asleep")
        connected = False
        while not connected:
            remaining = deadline - time.monotonic()
            per = max(remaining, MIN_ATTEMPT) if attempt == 0 else remaining
            if per <= 0:
                break
            try:
                await asyncio.wait_for(
                    call(bus, dev_path, IF_DEVICE, "ConnectProfile", "s", [profile_uuid]), per)
                connected = True
                break
            except asyncio.TimeoutError:
                last = LinkError("asleep", detail="ConnectProfile gave no answer in time")
                break
            except DBusError as err:
                last = link_error_from_dbus(err)
                _LOGGER.debug("ConnectProfile attempt %d failed: %s", attempt + 1, last.detail)
                if last.reason in FATAL:
                    raise last from err
            attempt += 1
            delay = min(0.75 * attempt, deadline - time.monotonic())
            if delay <= 0:
                break
            await asyncio.sleep(delay)
        if not connected:
            raise last
        try:
            fd = await asyncio.wait_for(got, FD_WAIT)
        except asyncio.TimeoutError as err:
            raise LinkError("error", "BlueZ connected but gave no RFCOMM descriptor.") from err
        return socket.socket(fileno=fd), dev_path, profile_path
    except BaseException:
        await unregister_profile(bus, profile_path)
        raise
