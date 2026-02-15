"""Switch platform for Home Rules."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([HomeRulesCoolingEnabledSwitch(entry, coordinator)])


class HomeRulesCoolingEnabledSwitch(CoordinatorEntity[HomeRulesCoordinator], SwitchEntity):
    """Toggle whether cooling is allowed as an output mode."""

    _attr_has_entity_name = True
    _attr_name = "Cooling Enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_cooling_enabled"
        self._attr_suggested_object_id = f"{DOMAIN}_cooling_enabled"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Home Rules",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.controls.cooling_enabled)

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control("cooling_enabled", True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control("cooling_enabled", False)
