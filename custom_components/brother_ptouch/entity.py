"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PTouchCoordinator
from .ptouch.protocol import MODEL_NAMES


class PTouchEntity(CoordinatorEntity[PTouchCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PTouchCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, manufacturer="Brother",
            model=MODEL_NAMES.get(coordinator.model, "PT-P710BT"), name="Brother P-touch")
