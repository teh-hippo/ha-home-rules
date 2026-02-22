# fmt: off
# ruff: noqa: E501, E701, E702

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

from . import const as c
from .coordinator import HomeRulesConfigEntry, HomeRulesCoordinator

_DIAG, _CONF, _TS = EntityCategory.DIAGNOSTIC, EntityCategory.CONFIG, SensorDeviceClass.TIMESTAMP
type Entry = HomeRulesConfigEntry
type Coord = HomeRulesCoordinator
_OBJECT_IDS = {"current": f"{c.DOMAIN}_current_state", "adjustment": f"{c.DOMAIN}_action", "timer_finishes_at": f"{c.DOMAIN}_timer_countdown", "temperature_cool": f"{c.DOMAIN}_cool_setpoint"}


def _sensor(key: str, **kwargs: Any) -> SensorEntityDescription: return SensorEntityDescription(key=key, translation_key=key, **kwargs)


SENSORS = (
    _sensor("mode"),
    _sensor("current"),
    _sensor("adjustment"),
    _sensor("decision", entity_category=_DIAG),
    _sensor("last_evaluated", device_class=_TS, entity_category=_DIAG),
    _sensor("last_changed", device_class=_TS, entity_category=_DIAG),
    _sensor("timer_finishes_at", device_class=_TS, entity_category=_DIAG),
)
BINARY_SENSORS = (
    BinarySensorEntityDescription(key="solar_available", translation_key="solar_available", entity_category=_DIAG),
    BinarySensorEntityDescription(key="auto_mode", translation_key="auto_mode", entity_category=_DIAG),
)


class HomeRulesEntity(CoordinatorEntity[HomeRulesCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, entry: Entry, coordinator: Coord, key: str) -> None:
        super().__init__(coordinator); self._attr_unique_id = f"{entry.entry_id}_{key}"; self._attr_suggested_object_id = _OBJECT_IDS.get(key, f"{c.DOMAIN}_{key}"); self._attr_device_info = DeviceInfo(identifiers={(c.DOMAIN, entry.entry_id)}, name="Home Rules")


class HomeRulesSensor(HomeRulesEntity, SensorEntity):
    def __init__(self, entry: Entry, coordinator: Coord, description: SensorEntityDescription) -> None:
        super().__init__(entry, coordinator, description.key); self.entity_description = description

    @property
    def native_value(self) -> str | datetime | None:
        value: object = getattr(self.coordinator.data, self.entity_description.key)
        return str(value.value if hasattr(value, "value") else value) if self.entity_description.device_class != _TS else (None if value is None else value if isinstance(value, datetime) else dt_util.parse_datetime(str(value)))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return None if self.entity_description.key != "decision" else {**dict(self.coordinator._last_record), "recent": list(self.coordinator._recent)[:10]}


class HomeRulesBinarySensor(HomeRulesEntity, BinarySensorEntity):
    def __init__(self, entry: Entry, coordinator: Coord, description: BinarySensorEntityDescription) -> None:
        super().__init__(entry, coordinator, description.key); self.entity_description = description

    @property
    def is_on(self) -> bool: return bool(getattr(self.coordinator.data, self.entity_description.key))


class HomeRulesModeSelect(HomeRulesEntity, SelectEntity):
    _attr_translation_key = "control_mode"
    _attr_options = [mode.value for mode in c.ControlMode]
    _attr_entity_category = _CONF

    def __init__(self, entry: Entry, coordinator: Coord) -> None: super().__init__(entry, coordinator, "control_mode")
    @property
    def current_option(self) -> str: return self.coordinator.control_mode.value
    async def async_select_option(self, option: str) -> None: await self.coordinator.async_set_mode(c.ControlMode(option))


class HomeRulesCoolingEnabledSwitch(HomeRulesEntity, SwitchEntity):
    _attr_translation_key = "cooling_enabled"
    _attr_entity_category = _CONF

    def __init__(self, entry: Entry, coordinator: Coord) -> None: super().__init__(entry, coordinator, "cooling_enabled")
    @property
    def is_on(self) -> bool: return bool(self.coordinator.cooling_enabled)
    async def async_turn_on(self, **kwargs: object) -> None: await self.coordinator.async_set_control("cooling_enabled", True)
    async def async_turn_off(self, **kwargs: object) -> None: await self.coordinator.async_set_control("cooling_enabled", False)


class HomeRulesEvaluateButton(HomeRulesEntity, ButtonEntity):
    _attr_translation_key = "evaluate_now"

    def __init__(self, entry: Entry, coordinator: Coord) -> None: super().__init__(entry, coordinator, "evaluate")
    async def async_press(self) -> None: await self.coordinator.async_run_evaluation("manual")


@dataclass(frozen=True)
class NumberDescription(NumberEntityDescription):
    conf_key: str = ""
    default: float = 0.0


def _num(key: str, min_v: float, max_v: float, step: float, unit: str, conf: str, default: float) -> NumberDescription:
    return NumberDescription(key=key, translation_key=key, native_min_value=min_v, native_max_value=max_v, native_step=step, native_unit_of_measurement=unit, entity_category=_CONF, conf_key=conf, default=default)


NUMBERS = tuple(
    _num(*spec)
    for spec in (
        ("temperature_threshold", 0, 40, 0.5, "°C", c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD),
        ("temperature_cool", 0, 40, 0.5, "°C", c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL),
        ("humidity_threshold", 0, 100, 1, "%", c.CONF_HUMIDITY_THRESHOLD, c.DEFAULT_HUMIDITY_THRESHOLD),
    )
)


class HomeRulesNumberEntity(HomeRulesEntity, NumberEntity):
    entity_description: NumberDescription
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: Entry, coordinator: Coord, description: NumberDescription) -> None:
        super().__init__(entry, coordinator, description.key); self.entity_description = description

    @property
    def native_value(self) -> float: return self.coordinator.get_parameter(self.entity_description.conf_key, self.entity_description.default)
    async def async_set_native_value(self, value: float) -> None: await self.coordinator.async_set_parameter(self.entity_description.conf_key, value)


async def async_setup_sensor_entry(hass: HomeAssistant, entry: Entry, add: AddEntitiesCallback) -> None: add(HomeRulesSensor(entry, entry.runtime_data, description) for description in SENSORS)
async def async_setup_binary_sensor_entry(hass: HomeAssistant, entry: Entry, add: AddEntitiesCallback) -> None: add(HomeRulesBinarySensor(entry, entry.runtime_data, description) for description in BINARY_SENSORS)
async def async_setup_select_entry(hass: HomeAssistant, entry: Entry, add: AddEntitiesCallback) -> None: add([HomeRulesModeSelect(entry, entry.runtime_data)])
async def async_setup_switch_entry(hass: HomeAssistant, entry: Entry, add: AddEntitiesCallback) -> None: add([HomeRulesCoolingEnabledSwitch(entry, entry.runtime_data)])
async def async_setup_button_entry(hass: HomeAssistant, entry: Entry, add: AddEntitiesCallback) -> None: add([HomeRulesEvaluateButton(entry, entry.runtime_data)])
async def async_setup_number_entry(hass: HomeAssistant, entry: Entry, add: AddEntitiesCallback) -> None: add(HomeRulesNumberEntity(entry, entry.runtime_data, description) for description in NUMBERS)
