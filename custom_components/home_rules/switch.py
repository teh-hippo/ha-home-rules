"""Switch platform for Home Rules."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HomeRulesConfigEntry, HomeRulesCoordinator
from .entity import HomeRulesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([HomeRulesCoolingEnabledSwitch(entry, coordinator)])


class HomeRulesCoolingEnabledSwitch(HomeRulesEntity, SwitchEntity):
    """Toggle whether cooling is allowed as an output mode."""

    _attr_name = "Cooling Enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(
            entry,
            coordinator,
            unique_id_suffix="cooling_enabled",
            object_id=f"{DOMAIN}_cooling_enabled",
        )

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.controls.cooling_enabled)

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control("cooling_enabled", True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control("cooling_enabled", False)
