"""Buttons: Connect Bluetooth (reach the printer now); Feed tape on printers without a cutter."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TRANSPORT, TRANSPORT_BLUETOOTH
from .coordinator import PTouchConfigEntry
from .entity import PTouchEntity
from .ptouch import has_cutter


async def async_setup_entry(hass: HomeAssistant, entry: PTouchConfigEntry, add: AddEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    buttons = []
    if entry.data.get(CONF_TRANSPORT) == TRANSPORT_BLUETOOTH:
        buttons.append(PTouchConnectButton(coordinator))
    if coordinator.model is not None and not has_cutter(coordinator.model):
        buttons.append(PTouchFeedButton(coordinator))
    add(buttons)


class PTouchConnectButton(PTouchEntity, ButtonEntity):
    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "connect_bluetooth")

    @property
    def available(self) -> bool:      # most useful exactly when the printer is asleep
        return True

    async def async_press(self) -> None:
        result = await self.coordinator.async_connect()
        if not result["ok"]:
            raise HomeAssistantError(result["message"])


class PTouchFeedButton(PTouchEntity, ButtonEntity):
    """Feed the tape out to cut it by hand, e.g. after a chained print."""

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "feed")

    async def async_press(self) -> None:
        await self.coordinator.async_feed()
