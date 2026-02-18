"""Binary sensor platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HomeRulesConfigEntry, HomeRulesCoordinator
from .entity import HomeRulesEntity


@dataclass(frozen=True)
class BinaryDescription(BinarySensorEntityDescription):
    """Home Rules binary sensor description, extending HA's base."""


BINARY_SENSORS = (
    BinaryDescription(
        key="solar_available",
        name="Solar Available",
        icon="mdi:white-balance-sunny",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinaryDescription(
        key="auto_mode",
        name="Auto Mode",
        icon="mdi:autorenew",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(HomeRulesBinarySensor(entry, coordinator, description) for description in BINARY_SENSORS)


class HomeRulesBinarySensor(HomeRulesEntity, BinarySensorEntity):
    """Coordinator-backed binary sensor."""

    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        description: BinaryDescription,
    ) -> None:
        super().__init__(
            entry,
            coordinator,
            unique_id_suffix=description.key,
            object_id=f"{DOMAIN}_{description.key}",
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.data, self.entity_description.key))
