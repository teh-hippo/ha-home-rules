"""Button platform for Home Rules."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([HomeRulesEvaluateButton(entry, entry.runtime_data)])


class HomeRulesEvaluateButton(HomeRulesEntity, ButtonEntity):
    """Manual evaluation button."""

    _attr_name = "Evaluate Now"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(
            entry,
            coordinator,
            unique_id_suffix="evaluate",
            object_id=f"{DOMAIN}_evaluate_now",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_run_evaluation("manual")
