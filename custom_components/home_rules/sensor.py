"""Sensor platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


@dataclass(frozen=True)
class SensorDescription:
    key: str
    name: str
    device_class: SensorDeviceClass | None = None
    unit: str | None = None


SENSORS = (
    SensorDescription("mode", "Mode"),
    SensorDescription("solar_generation_w", "Solar Generation", SensorDeviceClass.POWER, UnitOfPower.WATT),
    SensorDescription("grid_usage_w", "Grid Usage", SensorDeviceClass.POWER, UnitOfPower.WATT),
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
        self._attr_native_unit_of_measurement = description.unit

    @property
    def native_value(self) -> str | float:
        value: object = getattr(self.coordinator.data, self._description.key)
        if self._description.key == "mode":
            # Coordinator stores a HomeOutput enum for mode
            return str(value)
        return float(value)  # type: ignore[arg-type]
