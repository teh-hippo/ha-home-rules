"""Shared base entity for Home Rules coordinator-backed platforms."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomeRulesConfigEntry, HomeRulesCoordinator


class HomeRulesEntity(CoordinatorEntity[HomeRulesCoordinator]):
    """Coordinator-backed base entity with common identity metadata."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        *,
        unique_id_suffix: str,
        object_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Home Rules",
        )
