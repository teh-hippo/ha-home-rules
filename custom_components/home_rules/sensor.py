"""Sensor platform for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import HomeRulesCoordinator

type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]


@dataclass(frozen=True)
class SensorDescription(SensorEntityDescription):
    """Home Rules sensor description, extending HA's base with suggested_object_id."""

    object_id: str | None = None


SENSORS = (
    SensorDescription(key="mode", name="Mode", object_id=f"{DOMAIN}_mode", icon="mdi:home-automation"),
    SensorDescription(
        key="current",
        name="Current State",
        object_id=f"{DOMAIN}_current_state",
        icon="mdi:information-outline",
    ),
    SensorDescription(key="adjustment", name="Action", object_id=f"{DOMAIN}_action", icon="mdi:flash"),
    SensorDescription(
        key="decision",
        name="Decision",
        object_id=f"{DOMAIN}_decision",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:comment-question-outline",
    ),
    SensorDescription(
        key="last_evaluated",
        name="Last Evaluated",
        device_class=SensorDeviceClass.TIMESTAMP,
        object_id=f"{DOMAIN}_last_evaluated",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock-outline",
    ),
    SensorDescription(
        key="last_changed",
        name="Last Changed",
        device_class=SensorDeviceClass.TIMESTAMP,
        object_id=f"{DOMAIN}_last_changed",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:clock-check-outline",
    ),
    SensorDescription(
        key="timer_countdown",
        name="Timer Countdown",
        object_id=f"{DOMAIN}_timer_countdown",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
    ),
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
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_suggested_object_id = description.object_id or f"{DOMAIN}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Home Rules",
        )

    @property
    def native_value(self) -> str | datetime | None:
        value: object = getattr(self.coordinator.data, self.entity_description.key)

        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            if value is None:
                return None
            parsed = dt_util.parse_datetime(str(value))
            return parsed or None

        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "decision":
            return None

        recent = list(self.coordinator.data.recent_evaluations)[:10]
        return {
            "reason": self.coordinator.data.reason,
            "control_mode": self.coordinator.control_mode.value,
            "current": self.coordinator.data.current.value,
            "adjustment": self.coordinator.data.adjustment.value,
            "mode": self.coordinator.data.mode.value,
            "solar_online": self.coordinator.data.solar_online,
            "solar_generation_w": self.coordinator.data.solar_generation_w,
            "grid_usage_w": self.coordinator.data.grid_usage_w,
            "temperature_c": self.coordinator.data.temperature_c,
            "humidity_percent": self.coordinator.data.humidity_percent,
            "tolerated": self.coordinator.data.tolerated,
            "reactivate_delay": self.coordinator.data.reactivate_delay,
            "auto_mode": self.coordinator.data.auto_mode,
            "dry_run": self.coordinator.data.dry_run,
            "recent": recent,
        }
