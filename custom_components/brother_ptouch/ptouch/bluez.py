"""Bluetooth Classic via BlueZ's D-Bus Profile API (dbus-fast).

This is the Bluetooth route that works wherever Home Assistant's own Bluetooth
works: HA already talks to BlueZ over the system D-Bus with ``dbus-fast``.
Instead of opening a raw AF_BLUETOOTH socket (often not allowed inside the HA
container), we register a client ``org.bluez.Profile1`` for the Serial Port
UUID, ask BlueZ to ``ConnectProfile`` and receive the connected RFCOMM file
descriptor in ``NewConnection``.

BlueZ allows one registered profile per UUID: if another program holds the
Serial Port one, the transport falls back to a plain RFCOMM socket on
``channel``.

The printer must already be paired/trusted in BlueZ (see ``btadmin.pair`` or
``bluetoothctl``). ``wake_timeout`` (seconds, ``None`` = 12) bounds the total
time spent retrying ``ConnectProfile``; failures raise ``TransportError`` with a
plain-English message and a ``reason`` code (see docs/BLUETOOTH.md).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time

from . import _bluez_common as _c
from .errors import TransportError
from .transport import DEFAULT_RFCOMM_CHANNEL, RFCOMMTransport

_LOGGER = logging.getLogger(__name__)

SPP_UUID = _c.SPP_UUID
SYSTEM_BUS_SOCKET = "/run/dbus/system_bus_socket"


def available() -> bool:
    try:
        import dbus_fast  # noqa: F401
    except ImportError:
        return False
    return os.path.exists(SYSTEM_BUS_SOCKET)


class BlueZTransport(RFCOMMTransport):
    """RFCOMM link obtained through BlueZ D-Bus; I/O reuses RFCOMMTransport."""

    def __init__(self, address: str, profile_uuid: str = SPP_UUID, bus_address: str | None = None,
                 channel: int = DEFAULT_RFCOMM_CHANNEL) -> None:
        super().__init__(address, channel)  # channel: only for the plain-socket fallback
        self._uuid = profile_uuid
        self._bus_address = bus_address  # None = the system bus; tests pass a private bus
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bus = None
        self._profile_path: str | None = None

    # -- async helpers (run on a private loop owned by this thread) ----------
    async def _connect(self) -> socket.socket:
        wake = getattr(self, "wake_timeout", None)
        timeout = _c.DEFAULT_WAKE_TIMEOUT if wake is None else max(0.0, float(wake))
        self._bus = await _c.open_bus(self._bus_address)
        sock, _dev, self._profile_path = await _c.spp_connect(self._bus, self._address, self._uuid, timeout)
        return sock

    async def _cleanup(self) -> None:
        bus, self._bus = self._bus, None
        if bus is None:
            return
        if self._profile_path:
            await _c.unregister_profile(bus, self._profile_path)
        bus.disconnect()
        self._profile_path = None

    # -- transport hooks ------------------------------------------------------
    def _open(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._sock = self._loop.run_until_complete(self._connect())
        except _c.LinkError as err:
            _LOGGER.debug("BlueZ connect to %s failed (%s): %s", self._address, err.reason, err.detail)
            self._close()
            if err.reason == "profile_taken":
                _LOGGER.debug("Serial Port profile is taken; using an RFCOMM socket on channel %d",
                              self._channel)
                super()._open()
                return
            raise TransportError(err.message, reason=err.reason) from err
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("BlueZ connect to %s failed: %r", self._address, err)
            self._close()
            raise TransportError(_c.FRIENDLY["error"], reason="error") from err

    def _close(self) -> None:
        super()._close()
        if self._loop is not None:
            try:
                self._loop.run_until_complete(self._cleanup())
            except Exception:  # noqa: BLE001
                pass
            self._loop.close()
            self._loop = None
        time.sleep(0.3)  # let the printer drop the link before the next connect
