"""Byte-pipe transports: USB, Bluetooth RFCOMM, device file, HTTP bridge.

Every transport exposes the same two calls:

* ``get_status()  -> PrinterStatus``
* ``print_job(data, pages=1)``   (blocks until the printer reports completion)

All I/O is blocking; call from an executor thread.
"""
from __future__ import annotations

import errno
import json
import logging
import os
import select
import socket
import threading
import time
import urllib.error
import urllib.request

from .errors import PrinterError, PtouchError, TransportError
from .protocol import (
    CMD_INIT,
    CMD_STATUS_REQUEST,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_LEN,
    PrinterStatus,
    split_status_packets,
)

_LOGGER = logging.getLogger(__name__)

BROTHER_VID = 0x04F9
# PT-P700, PT-P750W, PT-P710BT (set printer to "P-touch Template/EL off" so it is not in Editor Lite mode)
KNOWN_PIDS = (0x2061, 0x2062, 0x20AF)

DEFAULT_RFCOMM_CHANNEL = 1


class Transport:
    """Interface."""

    #: seconds a transport may spend waking / reaching a sleeping printer (None = transport default)
    wake_timeout: float | None = None

    def get_status(self) -> PrinterStatus:  # pragma: no cover - interface
        raise NotImplementedError

    def print_job(self, data: bytes, pages: int = 1) -> None:  # pragma: no cover
        raise NotImplementedError


class StreamTransport(Transport):
    """Shared logic for transports that are a raw bidirectional byte stream."""

    status_timeout = 3.0

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # subclasses implement these four
    def _open(self) -> None: raise NotImplementedError
    def _close(self) -> None: raise NotImplementedError
    def _write(self, data: bytes) -> None: raise NotImplementedError
    def _read_some(self, timeout: float) -> bytes: raise NotImplementedError

    def get_status(self) -> PrinterStatus:
        with self._lock:
            self._open()
            try:
                self._write(CMD_STATUS_REQUEST)  # no ESC @: init would finish a held strip
                buf = bytearray()
                deadline = time.monotonic() + self.status_timeout
                while time.monotonic() < deadline:
                    buf += self._read_some(0.5)
                    pkts = split_status_packets(buf)
                    if pkts:
                        return pkts[-1]
                raise TransportError("printer did not answer the status request")
            finally:
                self._close()

    def print_job(self, data: bytes, pages: int = 1) -> None:
        with self._lock:
            self._open()
            try:
                self._write(data)
                self._wait_completed(pages, 20.0 + 15.0 * pages)
            finally:
                self._close()

    def _wait_completed(self, pages: int, timeout: float) -> None:
        buf = bytearray()
        done = 0
        deadline = time.monotonic() + timeout
        while done < pages and time.monotonic() < deadline:
            buf += self._read_some(0.5)
            for st in split_status_packets(buf):
                if st.status_type == STATUS_ERROR or (st.errors and st.status_type != STATUS_COMPLETED):
                    raise PrinterError(st.errors)
                if st.status_type == STATUS_COMPLETED:
                    done += 1
        if done < pages:
            _LOGGER.warning("no completion report from printer after %.0fs; job was sent", timeout)


class USBTransport(StreamTransport):
    def __init__(self, serial: str | None = None) -> None:
        super().__init__()
        self._serial = serial
        self._dev = None
        self._ep_in = None
        self._ep_out = None
        self._intf_no = 0

    def _open(self) -> None:
        try:
            import usb.core
            import usb.util
        except ImportError as err:  # pragma: no cover
            raise TransportError("pyusb is not installed") from err
        try:
            devs = [d for d in usb.core.find(find_all=True, idVendor=BROTHER_VID)
                    if d.idProduct in KNOWN_PIDS]
        except usb.core.NoBackendError as err:
            raise TransportError("libusb backend not found (install libusb-1.0)") from err
        if self._serial:
            devs = [d for d in devs if _usb_serial(d) == self._serial]
        if not devs:
            raise TransportError("no PT-P700/P750W/P710BT found on USB")
        dev = devs[0]
        try:
            cfg = dev.get_active_configuration()
        except usb.core.USBError:
            dev.set_configuration()
            cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceClass=7) or cfg[(0, 0)]
        self._intf_no = intf.bInterfaceNumber
        try:
            if dev.is_kernel_driver_active(self._intf_no):
                dev.detach_kernel_driver(self._intf_no)
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            usb.util.claim_interface(dev, self._intf_no)
        except usb.core.USBError as err:
            raise TransportError(f"cannot claim USB interface (permissions/udev?): {err}") from err
        match = lambda direction: (lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == direction)  # noqa: E731
        self._ep_out = usb.util.find_descriptor(intf, custom_match=match(usb.util.ENDPOINT_OUT))
        self._ep_in = usb.util.find_descriptor(intf, custom_match=match(usb.util.ENDPOINT_IN))
        if self._ep_out is None or self._ep_in is None:
            usb.util.release_interface(dev, self._intf_no)
            raise TransportError("USB bulk endpoints not found")
        self._dev = dev

    def _close(self) -> None:
        if self._dev is not None:
            import usb.util
            try:
                usb.util.release_interface(self._dev, self._intf_no)
            except Exception:  # noqa: BLE001
                pass
            usb.util.dispose_resources(self._dev)
        self._dev = self._ep_in = self._ep_out = None

    def _write(self, data: bytes) -> None:
        import usb.core
        try:
            for i in range(0, len(data), 16384):
                self._ep_out.write(data[i:i + 16384], timeout=10000)
        except usb.core.USBError as err:
            raise TransportError(f"USB write failed: {err}") from err

    def _read_some(self, timeout: float) -> bytes:
        import usb.core
        try:
            return bytes(self._ep_in.read(64, timeout=int(timeout * 1000)))
        except usb.core.USBTimeoutError:
            return b""
        except usb.core.USBError as err:
            if getattr(err, "errno", None) == 110:
                return b""
            raise TransportError(f"USB read failed: {err}") from err


def _usb_serial(dev) -> str | None:
    try:
        return dev.serial_number
    except Exception:  # noqa: BLE001
        return None


class DeviceFileTransport(StreamTransport):
    """A character device: /dev/usb/lp0 or a bound /dev/rfcomm0."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._fd: int | None = None

    def _open(self) -> None:
        try:
            self._fd = os.open(self._path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as err:
            raise TransportError(f"cannot open {self._path}: {err}") from err

    def _close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
        self._fd = None

    def _write(self, data: bytes) -> None:
        view = memoryview(data)
        try:
            while view:
                _, w, _ = select.select([], [self._fd], [], 10)
                if not w:
                    raise TransportError(f"timeout writing to {self._path}")
                try:
                    n = os.write(self._fd, view[:4096])
                except BlockingIOError:
                    continue
                view = view[n:]
        except OSError as err:
            raise TransportError(f"write to {self._path} failed: {err}") from err

    def _read_some(self, timeout: float) -> bytes:
        r, _, _ = select.select([self._fd], [], [], timeout)
        if not r:
            return b""
        try:
            return os.read(self._fd, 64)
        except BlockingIOError:
            return b""
        except OSError as err:
            raise TransportError(f"read from {self._path} failed: {err}") from err


class RFCOMMTransport(StreamTransport):
    """Bluetooth Classic RFCOMM socket (Linux, BlueZ; printer must be paired)."""

    def __init__(self, address: str, channel: int = DEFAULT_RFCOMM_CHANNEL) -> None:
        super().__init__()
        self._address = address
        self._channel = channel
        self._sock: socket.socket | None = None

    def _open(self) -> None:
        if not hasattr(socket, "AF_BLUETOOTH") or not hasattr(socket, "BTPROTO_RFCOMM"):
            raise TransportError("this Python build has no Bluetooth socket support")
        # The printer keeps the single RFCOMM link busy for a moment after a
        # disconnect (EBUSY / ECONNREFUSED / ECONNRESET), so retry briefly.
        err: OSError | None = None
        wake = self.wake_timeout
        deadline = None if wake is None else time.monotonic() + max(0.0, float(wake))
        attempt = 0
        while True:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(15 if deadline is None else max(1.0, min(15.0, deadline - time.monotonic())))
            try:
                s.connect((self._address, self._channel))
            except OSError as e:
                s.close()
                err = e
                if e.errno not in (errno.EBUSY, errno.ECONNREFUSED, errno.ECONNRESET, errno.EAGAIN,
                                   errno.EHOSTDOWN, errno.ETIMEDOUT, errno.EHOSTUNREACH) \
                        and not isinstance(e, socket.timeout):
                    break
                attempt += 1
                delay = 0.75 * attempt
                if deadline is None:
                    if attempt >= 8:
                        break
                elif time.monotonic() + delay >= deadline:
                    break
                time.sleep(delay)
                continue
            self._sock = s
            return
        reason = "error"
        if err is not None:
            if err.errno in (errno.EHOSTDOWN, errno.ETIMEDOUT, errno.EHOSTUNREACH) or isinstance(err, socket.timeout):
                reason = "asleep"
            elif err.errno in (errno.EBUSY, errno.ECONNREFUSED, errno.ECONNRESET, errno.EAGAIN):
                reason = "busy"
            elif err.errno in (errno.EPERM, errno.EACCES):
                reason = "permission"
        exc = TransportError(
            f"cannot connect to {self._address} ch {self._channel}: {err} "
            "(paired? powered on? connected to a phone?)")
        exc.reason = reason          # optional attribute, see docs/BLUETOOTH_CONTRACT.md section 1
        raise exc from err

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _write(self, data: bytes) -> None:
        try:
            self._sock.settimeout(15)
            self._sock.sendall(data)
        except OSError as err:
            raise TransportError(f"Bluetooth write failed: {err}") from err

    def _read_some(self, timeout: float) -> bytes:
        self._sock.settimeout(timeout)
        try:
            return self._sock.recv(64)
        except socket.timeout:
            return b""
        except OSError as err:
            raise TransportError(f"Bluetooth read failed: {err}") from err


class HTTPTransport(Transport):
    """Talks to ``bridge/ptouch_bridge.py`` running next to the printer."""

    def __init__(self, url: str, token: str | None = None) -> None:
        self._url = url.rstrip("/")
        self._token = token

    def _request(self, method: str, path: str, body: bytes | None = None, timeout: float = 30) -> dict:
        req = urllib.request.Request(self._url + path, data=body, method=method)
        if self._token:
            req.add_header("Authorization", f"Bearer {self._token}")
        if body is not None:
            req.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            try:
                detail = json.loads(err.read()).get("error", err.reason)
            except Exception:  # noqa: BLE001
                detail = err.reason
            if err.code == 409:
                raise PrinterError(str(detail).split(",")) from err
            raise TransportError(f"bridge returned {err.code}: {detail}") from err
        except (urllib.error.URLError, OSError, ValueError) as err:
            raise TransportError(f"cannot reach bridge at {self._url}: {err}") from err

    def get_status(self) -> PrinterStatus:
        raw = bytes.fromhex(self._request("GET", "/status", timeout=15)["status"])
        if len(raw) != STATUS_LEN:
            raise TransportError("bridge returned a malformed status")
        return PrinterStatus.parse(raw)

    def print_job(self, data: bytes, pages: int = 1) -> None:
        self._request("POST", f"/print?pages={pages}", body=data, timeout=30 + 15 * pages)


def make_transport(kind: str, **cfg) -> Transport:
    """kind: 'usb' | 'bluetooth' | 'bridge'."""
    if kind == "usb":
        return USBTransport(cfg.get("serial") or None)
    if kind == "bluetooth":
        addr = cfg["address"]
        if addr.startswith("/"):
            return DeviceFileTransport(addr)
        backend = cfg.get("backend") or "auto"   # auto | dbus | socket
        channel = int(cfg.get("channel") or DEFAULT_RFCOMM_CHANNEL)
        if backend != "socket":
            from . import bluez
            if backend == "dbus" or bluez.available():
                return bluez.BlueZTransport(addr, channel=channel)
        return RFCOMMTransport(addr, channel)
    if kind == "bridge":
        return HTTPTransport(cfg["url"], cfg.get("token") or None)
    raise PtouchError(f"unknown transport {kind!r}")
