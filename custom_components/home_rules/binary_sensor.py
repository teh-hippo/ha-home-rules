"""Binary sensor platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


@dataclass(frozen=True)
class BinaryDescription:
    key: str
    name: str
    icon: str | None = None
    entity_category: EntityCategory | None = None


BINARY_SENSORS = (
    BinaryDescription(
        "solar_available",
        "Solar Available",
        icon="mdi:white-balance-sunny",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinaryDescription(
        "auto_mode",
        "Auto Mode",
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
        self._attr_suggested_object_id = f"{DOMAIN}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Home Rules",
        )
        self._attr_icon = description.icon
        self._attr_entity_category = description.entity_category

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.data, self._description.key))
