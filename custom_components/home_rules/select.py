"""Select platform for Home Rules."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, ControlMode
from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]

OPTIONS: list[str] = [mode.value for mode in ControlMode]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HomeRulesModeSelect(entry, entry.runtime_data)])


class HomeRulesModeSelect(CoordinatorEntity[HomeRulesCoordinator], SelectEntity):
    """Select entity that controls integration operational mode."""

    _attr_has_entity_name = True
    _attr_name = "Control Mode"
    _attr_options = OPTIONS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune-variant"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_control_mode"
        self._attr_suggested_object_id = f"{DOMAIN}_control_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Home Rules",
        )

    @property
    def current_option(self) -> str:
        return self.coordinator.control_mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(ControlMode(option))
