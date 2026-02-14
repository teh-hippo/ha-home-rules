"""Button platform for Home Rules."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([HomeRulesEvaluateButton(entry, entry.runtime_data)])


class HomeRulesEvaluateButton(CoordinatorEntity[HomeRulesCoordinator], ButtonEntity):
    """Manual evaluation button."""

    _attr_has_entity_name = True
    _attr_name = "Evaluate Now"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_evaluate"

    async def async_press(self) -> None:
        await self.coordinator.async_run_evaluation("manual")
