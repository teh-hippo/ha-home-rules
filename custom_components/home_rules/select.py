"""Select platform for Home Rules."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ControlMode
from .coordinator import HomeRulesConfigEntry, HomeRulesCoordinator
from .entity import HomeRulesEntity

OPTIONS: list[str] = [mode.value for mode in ControlMode]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HomeRulesModeSelect(entry, entry.runtime_data)])


class HomeRulesModeSelect(HomeRulesEntity, SelectEntity):
    """Select entity that controls integration operational mode."""

    _attr_name = "Control Mode"
    _attr_options = OPTIONS
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune-variant"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(
            entry,
            coordinator,
            unique_id_suffix="control_mode",
            object_id=f"{DOMAIN}_control_mode",
        )

    @property
    def current_option(self) -> str:
        return self.coordinator.control_mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(ControlMode(option))
