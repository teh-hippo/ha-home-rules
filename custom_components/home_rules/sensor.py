"""Sensor platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


@dataclass(frozen=True)
class SensorDescription:
    key: str
    name: str
    device_class: SensorDeviceClass | None = None


SENSORS = (
    SensorDescription("mode", "Mode"),
    SensorDescription("current", "Current State"),
    SensorDescription("adjustment", "Action"),
    SensorDescription("last_evaluated", "Last Evaluated", SensorDeviceClass.TIMESTAMP),
    SensorDescription("last_changed", "Last Changed", SensorDeviceClass.TIMESTAMP),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeRulesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(HomeRulesSensor(entry, coordinator, description) for description in SENSORS)


class HomeRulesSensor(CoordinatorEntity[HomeRulesCoordinator], SensorEntity):
    """Coordinator-backed sensor entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        description: SensorDescription,
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
        self._attr_device_class = description.device_class

    @property
    def native_value(self) -> str | datetime | None:
        value: object = getattr(self.coordinator.data, self._description.key)

        if self._description.device_class == SensorDeviceClass.TIMESTAMP:
            if value is None:
                return None
            parsed = dt_util.parse_datetime(str(value))
            return parsed or None

        if hasattr(value, "value"):
            return str(value.value)
        return str(value)
