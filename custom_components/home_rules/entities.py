from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_GENERATION_COOL_THRESHOLD,
    CONF_GENERATION_DRY_THRESHOLD,
    CONF_HUMIDITY_THRESHOLD,
    CONF_TEMPERATURE_COOL,
    CONF_TEMPERATURE_THRESHOLD,
    DEFAULT_GENERATION_COOL_THRESHOLD,
    DEFAULT_GENERATION_DRY_THRESHOLD,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_TEMPERATURE_COOL,
    DEFAULT_TEMPERATURE_THRESHOLD,
    DOMAIN,
    ControlMode,
)
from .coordinator import HomeRulesConfigEntry, HomeRulesCoordinator

AEC = AddEntitiesCallback
HCE = HomeRulesConfigEntry


class HomeRulesEntity(CoordinatorEntity[HomeRulesCoordinator]):
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        *,
        unique_id_suffix: str,
        object_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"
        self._attr_suggested_object_id = object_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)}, name="Home Rules")


@dataclass(frozen=True)
class SensorDescription(SensorEntityDescription):
    object_id: str | None = None


SENSORS = (
    SensorDescription(key="mode", name="Mode", icon="mdi:home-automation", object_id=f"{DOMAIN}_mode"),
    SensorDescription(
        key="current",
        name="Current State",
        icon="mdi:information-outline",
        object_id=f"{DOMAIN}_current_state",
    ),
    SensorDescription(key="adjustment", name="Action", icon="mdi:flash", object_id=f"{DOMAIN}_action"),
    SensorDescription(
        key="decision",
        name="Decision",
        icon="mdi:comment-question-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        object_id=f"{DOMAIN}_decision",
    ),
    SensorDescription(
        key="last_evaluated",
        name="Last Evaluated",
        icon="mdi:clock-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        object_id=f"{DOMAIN}_last_evaluated",
    ),
    SensorDescription(
        key="last_changed",
        name="Last Changed",
        icon="mdi:clock-check-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        object_id=f"{DOMAIN}_last_changed",
    ),
    SensorDescription(
        key="timer_finishes_at",
        name="Timer Countdown",
        icon="mdi:timer-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        object_id=f"{DOMAIN}_timer_countdown",
    ),
)

BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="solar_available",
        name="Solar Available",
        icon="mdi:white-balance-sunny",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="auto_mode",
        name="Auto Mode",
        icon="mdi:autorenew",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


class HomeRulesSensor(HomeRulesEntity, SensorEntity):
    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        description: SensorDescription,
    ) -> None:
        super().__init__(
            entry,
            coordinator,
            unique_id_suffix=description.key,
            object_id=description.object_id or f"{DOMAIN}_{description.key}",
        )
        self.entity_description = description

    @property
    def native_value(self) -> str | datetime | None:
        value: object = getattr(self.coordinator.data, self.entity_description.key)
        if self.entity_description.device_class != SensorDeviceClass.TIMESTAMP:
            return str(value.value if hasattr(value, "value") else value)
        if value is None:
            return None
        return value if isinstance(value, datetime) else dt_util.parse_datetime(str(value)) or None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "decision":
            return None
        data = self.coordinator.data
        return {
            "reason": data.reason,
            "control_mode": self.coordinator.control_mode.value,
            "current": data.current.value,
            "adjustment": data.adjustment.value,
            "mode": data.mode.value,
            "solar_online": data.solar_online,
            "solar_generation_w": data.solar_generation_w,
            "grid_usage_w": data.grid_usage_w,
            "temperature_c": data.temperature_c,
            "humidity_percent": data.humidity_percent,
            "tolerated": data.tolerated,
            "reactivate_delay": data.reactivate_delay,
            "auto_mode": data.auto_mode,
            "dry_run": data.dry_run,
            "recent": list(data.recent_evaluations)[:10],
        }


class HomeRulesBinarySensor(HomeRulesEntity, BinarySensorEntity):
    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(entry, coordinator, unique_id_suffix=description.key, object_id=f"{DOMAIN}_{description.key}")
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.coordinator.data, self.entity_description.key))


class HomeRulesModeSelect(HomeRulesEntity, SelectEntity):
    _attr_translation_key = "control_mode"
    _attr_options = [mode.value for mode in ControlMode]
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:tune-variant"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(entry, coordinator, unique_id_suffix="control_mode", object_id=f"{DOMAIN}_control_mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.control_mode.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_mode(ControlMode(option))


class HomeRulesCoolingEnabledSwitch(HomeRulesEntity, SwitchEntity):
    _attr_translation_key = "cooling_enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:snowflake"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(entry, coordinator, unique_id_suffix="cooling_enabled", object_id=f"{DOMAIN}_cooling_enabled")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.controls.cooling_enabled)

    async def async_turn_on(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control("cooling_enabled", True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self.coordinator.async_set_control("cooling_enabled", False)


class HomeRulesEvaluateButton(HomeRulesEntity, ButtonEntity):
    _attr_translation_key = "evaluate_now"

    def __init__(self, entry: HomeRulesConfigEntry, coordinator: HomeRulesCoordinator) -> None:
        super().__init__(entry, coordinator, unique_id_suffix="evaluate", object_id=f"{DOMAIN}_evaluate_now")

    async def async_press(self) -> None:
        await self.coordinator.async_run_evaluation("manual")


@dataclass(frozen=True)
class NumberDescription(NumberEntityDescription):
    conf_key: str = ""
    default: float = 0.0
    object_id: str | None = None


NUMBERS = (
    NumberDescription(
        key="temperature_threshold",
        name="Temperature Threshold",
        icon="mdi:thermometer-alert",
        native_min_value=0,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        conf_key=CONF_TEMPERATURE_THRESHOLD,
        default=DEFAULT_TEMPERATURE_THRESHOLD,
        object_id=f"{DOMAIN}_temperature_threshold",
    ),
    NumberDescription(
        key="temperature_cool",
        name="Cool Setpoint",
        icon="mdi:thermometer-chevron-down",
        native_min_value=0,
        native_max_value=40,
        native_step=0.5,
        native_unit_of_measurement="°C",
        entity_category=EntityCategory.CONFIG,
        conf_key=CONF_TEMPERATURE_COOL,
        default=DEFAULT_TEMPERATURE_COOL,
        object_id=f"{DOMAIN}_cool_setpoint",
    ),
    NumberDescription(
        key="generation_cool_threshold",
        name="Cool Generation Threshold",
        icon="mdi:solar-power",
        native_min_value=0,
        native_max_value=20000,
        native_step=100,
        native_unit_of_measurement="W",
        entity_category=EntityCategory.CONFIG,
        conf_key=CONF_GENERATION_COOL_THRESHOLD,
        default=DEFAULT_GENERATION_COOL_THRESHOLD,
        object_id=f"{DOMAIN}_cool_generation_threshold",
    ),
    NumberDescription(
        key="generation_dry_threshold",
        name="Dry Generation Threshold",
        icon="mdi:solar-power-variant",
        native_min_value=0,
        native_max_value=20000,
        native_step=100,
        native_unit_of_measurement="W",
        entity_category=EntityCategory.CONFIG,
        conf_key=CONF_GENERATION_DRY_THRESHOLD,
        default=DEFAULT_GENERATION_DRY_THRESHOLD,
        object_id=f"{DOMAIN}_dry_generation_threshold",
    ),
    NumberDescription(
        key="humidity_threshold",
        name="Humidity Threshold",
        icon="mdi:water-percent-alert",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        entity_category=EntityCategory.CONFIG,
        conf_key=CONF_HUMIDITY_THRESHOLD,
        default=DEFAULT_HUMIDITY_THRESHOLD,
        object_id=f"{DOMAIN}_humidity_threshold",
    ),
)


class HomeRulesNumberEntity(HomeRulesEntity, NumberEntity):
    entity_description: NumberDescription
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: HomeRulesConfigEntry,
        coordinator: HomeRulesCoordinator,
        description: NumberDescription,
    ) -> None:
        super().__init__(
            entry,
            coordinator,
            unique_id_suffix=description.key,
            object_id=description.object_id or f"{DOMAIN}_{description.key}",
        )
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return self.coordinator.get_parameter(self.entity_description.conf_key, self.entity_description.default)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_parameter(self.entity_description.conf_key, value)


async def async_setup_sensor_entry(hass: HomeAssistant, entry: HCE, add_entities: AEC) -> None:
    add_entities(HomeRulesSensor(entry, entry.runtime_data, description) for description in SENSORS)


async def async_setup_binary_sensor_entry(hass: HomeAssistant, entry: HCE, add_entities: AEC) -> None:
    add_entities(HomeRulesBinarySensor(entry, entry.runtime_data, description) for description in BINARY_SENSORS)


async def async_setup_select_entry(hass: HomeAssistant, entry: HCE, add_entities: AEC) -> None:
    add_entities([HomeRulesModeSelect(entry, entry.runtime_data)])


async def async_setup_switch_entry(hass: HomeAssistant, entry: HCE, add_entities: AEC) -> None:
    add_entities([HomeRulesCoolingEnabledSwitch(entry, entry.runtime_data)])


async def async_setup_button_entry(hass: HomeAssistant, entry: HCE, add_entities: AEC) -> None:
    add_entities([HomeRulesEvaluateButton(entry, entry.runtime_data)])


async def async_setup_number_entry(hass: HomeAssistant, entry: HCE, add_entities: AEC) -> None:
    add_entities(HomeRulesNumberEntity(entry, entry.runtime_data, description) for description in NUMBERS)
