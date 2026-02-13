"""Switch platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HomeRulesCoordinator


type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


@dataclass(frozen=True)
class ControlDescription:
    key: str
    name: str


CONTROLS = (
    ControlDescription("enabled", "Enabled"),
    ControlDescription("cooling_enabled", "Cooling Enabled"),
    ControlDescription("aggressive_cooling", "Aggressive Cooling"),
    ControlDescription("dry_run", "Dry Run"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(HomeRulesControlSwitch(entry, coordinator, description) for description in CONTROLS)


class HomeRulesControlSwitch(CoordinatorEntity[HomeRulesCoordinator], SwitchEntity, RestoreEntity):
    """Integration control switch."""

    _attr_has_entity_name = True

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator, description: ControlDescription) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.controls, self._description.key))

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control(self._description.key, True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control(self._description.key, False)
