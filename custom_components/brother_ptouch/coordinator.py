"""Coordinator: polls printer status and serialises print jobs."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from PIL import Image

from .const import (CONF_BATCH_WINDOW, CONF_MODEL, CONF_ORIENTATION, CONF_TRANSPORT, CONF_WAKE_SECONDS,
                    DEFAULT_BATCH_WINDOW, DEFAULT_ORIENTATION, DEFAULT_WAKE_SECONDS, DOMAIN,
                    OFFLINE_REASONS, POLL_WAKE_SECONDS, REASON_ERROR, REASON_OK, SCAN_INTERVAL_SECONDS,
                    friendly_message)
from .ptouch import (JobOptions, PrinterError, PrinterStatus, PtouchError, build_feed_job, build_jobs,
                     make_transport, mm_to_dots)
from .ptouch.protocol import MEDIA_INCOMPATIBLE

_LOGGER = logging.getLogger(__name__)

type PTouchConfigEntry = ConfigEntry[PTouchCoordinator]

# render(tape_mm, model) -> list of 1-bit images (one label each)
Renderer = Callable[[int, int], list[Image.Image]]


@dataclass
class _Request:
    render: Renderer
    copies: int
    auto_cut: bool
    cut_each: bool
    margin_mm: float
    chain: bool
    cut_mark: bool
    future: asyncio.Future


class _FailureLogger(logging.LoggerAdapter):
    """Logs failed refreshes as warnings when the printer is merely offline (OFFLINE_REASONS)."""

    def __init__(self, logger: logging.Logger, coordinator: "PTouchCoordinator") -> None:
        super().__init__(logger, {})
        self.coordinator = coordinator

    def error(self, msg, *args, **kwargs) -> None:
        log = self.warning if self.coordinator.last_reason in OFFLINE_REASONS else super().error
        log(msg, *args, **kwargs)


class PTouchCoordinator(DataUpdateCoordinator[PrinterStatus]):
    config_entry: PTouchConfigEntry

    def __init__(self, hass: HomeAssistant, entry: PTouchConfigEntry) -> None:
        self.last_reason: str = REASON_OK        # docs/BLUETOOTH_CONTRACT.md section 1
        self.last_message: str = ""
        super().__init__(hass, _FailureLogger(_LOGGER, self), config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS))
        cfg = dict(entry.data)
        cfg.pop(CONF_MODEL, None)
        self.transport = make_transport(cfg.pop(CONF_TRANSPORT), **cfg)
        self._print_lock = asyncio.Lock()
        self._pending: list[_Request] = []
        self._flush_task: asyncio.Task | None = None

    @property
    def model(self) -> int | None:
        """Model code of the last status, else the stored one."""
        if self.data is not None:
            return self.data.model
        return self.config_entry.data.get(CONF_MODEL)

    # -- reason tracking ------------------------------------------------------
    @property
    def wake_seconds(self) -> float:
        try:
            return max(0.0, float(self.config_entry.options.get(CONF_WAKE_SECONDS, DEFAULT_WAKE_SECONDS)))
        except (TypeError, ValueError):
            return float(DEFAULT_WAKE_SECONDS)

    def _record_ok(self) -> None:
        self.last_reason, self.last_message = REASON_OK, ""

    def _record_failure(self, err: Exception) -> str:
        """Remember why talking to the printer failed; returns the friendly text."""
        reason = getattr(err, "reason", REASON_ERROR) or REASON_ERROR
        self.last_reason = reason
        self.last_message = friendly_message(reason, str(err))
        return self.last_message

    def _status_call(self, wake: float):
        """Blocking get_status with the given wake timeout (runs in the executor)."""
        self.transport.wake_timeout = wake
        return self.transport.get_status()

    async def _async_update_data(self) -> PrinterStatus:
        if self._print_lock.locked():          # don't fight a running job for the link
            return self.data
        try:
            status = await self.hass.async_add_executor_job(self._status_call, POLL_WAKE_SECONDS)
        except PtouchError as err:
            raise UpdateFailed(self._record_failure(err)) from err
        self._record_ok()
        self._remember_model(status)
        return status

    def _remember_model(self, status: PrinterStatus) -> None:
        """Store the model in the entry (which reloads it once). Not called mid-print."""
        entry = self.config_entry
        if entry.data.get(CONF_MODEL) != status.model:
            self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_MODEL: status.model})

    async def async_connect(self) -> dict:
        """Try to reach the printer now (Connect button / bluetooth/connect); never raises for expected failures."""
        if self._print_lock.locked():
            return {"ok": False, "reason": "busy", "seconds": 0.0,
                    "message": "The printer is printing right now."}
        start = time.monotonic()
        async with self._print_lock:
            try:
                status = await self.hass.async_add_executor_job(self._status_call, self.wake_seconds)
            except PtouchError as err:
                msg = self._record_failure(err)
                return {"ok": False, "reason": self.last_reason,
                        "seconds": round(time.monotonic() - start, 1), "message": msg}
        self._record_ok()
        self.async_set_updated_data(status)
        self._remember_model(status)
        return {"ok": True, "reason": REASON_OK, "seconds": round(time.monotonic() - start, 1),
                "message": "Connected."}

    async def async_print(self, render: Renderer, *, copies: int = 1, auto_cut: bool = True,
                          cut_each: bool = False, margin_mm: float = 2.0, chain: bool = False,
                          cut_mark: bool = False) -> None:
        """Queue a label. Requests arriving within the batch window print as ONE strip.

        A printer wastes ~25 mm of blank leader at the start of every job, so
        labels sent in a burst are merged into one job (one leader, one cut).
        """
        req = _Request(render, copies, auto_cut, cut_each, margin_mm, chain, cut_mark,
                       self.hass.loop.create_future())
        self._pending.append(req)
        if self._flush_task is None:
            window = float(self.config_entry.options.get(CONF_BATCH_WINDOW, DEFAULT_BATCH_WINDOW))
            self._flush_task = self.config_entry.async_create_background_task(
                self.hass, self._flush(window), f"{DOMAIN}_print_batch")
        await req.future

    async def _flush(self, window: float) -> None:
        await asyncio.sleep(window)
        batch, self._pending, self._flush_task = self._pending, [], None
        try:
            await self._print_batch(batch)
        except Exception as err:  # noqa: BLE001  - delivered to every waiting caller
            for r in batch:
                if not r.future.done():
                    r.future.set_exception(err)
        else:
            for r in batch:
                if not r.future.done():
                    r.future.set_result(None)
        await self.async_request_refresh()

    async def _ready_status(self) -> PrinterStatus:
        """Fresh status of a printer that can print now (call with the print lock held)."""
        status = await self.hass.async_add_executor_job(self._status_call, self.wake_seconds)
        self._record_ok()
        self.async_set_updated_data(status)
        if status.errors:
            raise HomeAssistantError(f"Printer reports: {', '.join(status.errors)}")
        if not status.has_tape or status.media_type == MEDIA_INCOMPATIBLE:
            raise HomeAssistantError("No compatible tape loaded in the printer")
        return status

    async def async_feed(self) -> None:
        """Feed the tape out, e.g. to release a chained label."""
        async with self._print_lock:
            try:
                status = await self._ready_status()
                job = build_feed_job(JobOptions(tape_mm=status.media_width, media_type=status.media_type,
                                                model=status.model))

                def work() -> None:
                    self.transport.wake_timeout = self.wake_seconds
                    self.transport.print_job(job, pages=1)

                await self.hass.async_add_executor_job(work)
            except PrinterError as err:
                raise HomeAssistantError(f"Printer error: {err}") from err
            except PtouchError as err:
                raise HomeAssistantError(self._record_failure(err)) from err

    async def _print_batch(self, batch: list[_Request]) -> None:
        orientation = self.config_entry.options.get(CONF_ORIENTATION, DEFAULT_ORIENTATION)
        async with self._print_lock:
            try:
                status = await self._ready_status()

                def work() -> None:
                    images: list[Image.Image] = []
                    ok: list[_Request] = []
                    for r in batch:             # a bad request fails alone, not the batch
                        try:
                            images += r.render(status.media_width, status.model) * r.copies
                            ok.append(r)
                        except Exception as err:  # noqa: BLE001
                            if not r.future.done():
                                r.future.get_loop().call_soon_threadsafe(r.future.set_exception, err)
                    if not images:
                        return
                    jobs = build_jobs(images, JobOptions(
                        tape_mm=status.media_width, media_type=status.media_type,
                        auto_cut=any(r.auto_cut for r in ok), cut_each=any(r.cut_each for r in ok),
                        margin_dots=mm_to_dots(ok[0].margin_mm), orientation=orientation,
                        model=status.model,
                        chain=all(r.chain for r in ok),      # feed out unless every request chains
                        cut_mark=any(r.cut_mark for r in ok)))
                    self.transport.wake_timeout = self.wake_seconds
                    for job in jobs:
                        self.transport.print_job(job, pages=1)

                await self.hass.async_add_executor_job(work)
            except PrinterError as err:
                raise HomeAssistantError(f"Printer error: {err}") from err
            except PtouchError as err:
                raise HomeAssistantError(self._record_failure(err)) from err
