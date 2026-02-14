"""Binary sensor platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


@dataclass(frozen=True)
class BinaryDescription:
    key: str
    name: str


BINARY_SENSORS = (
    BinaryDescription("solar_available", "Solar Available"),
    BinaryDescription("auto_mode", "Auto Mode"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(HomeRulesBinarySensor(entry, coordinator, description) for description in BINARY_SENSORS)


class HomeRulesBinarySensor(CoordinatorEntity[HomeRulesCoordinator], BinarySensorEntity):
    """Coordinator-backed binary sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        description: BinaryDescription,
    ) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.data, self._description.key))
