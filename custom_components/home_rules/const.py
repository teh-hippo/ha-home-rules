from collections.abc import Mapping
from enum import StrEnum
from logging import Logger, getLogger
from typing import Any

from homeassistant.const import Platform as Plat

LOGGER: Logger = getLogger(__package__)
DOMAIN = "home_rules"


class ControlMode(StrEnum):
    DISABLED = "disabled"
    MONITOR = "monitor"
    AUTOMATIC = "automatic"


class PowerPolicy(StrEnum):
    SOLAR_ONLY = "solar_only"
    ALLOW_BATTERY_GRID = "allow_battery_grid"


PLATFORMS: list[Plat] = [Plat.SWITCH, Plat.SELECT, Plat.SENSOR, Plat.BINARY_SENSOR, Plat.BUTTON, Plat.NUMBER]

CONF_CLIMATE_ENTITY_ID = "climate_entity_id"
CONF_GENERATION_ENTITY_ID = "generation_entity_id"
CONF_GRID_ENTITY_ID, CONF_TEMPERATURE_ENTITY_ID = "grid_entity_id", "temperature_entity_id"
CONF_HUMIDITY_ENTITY_ID, CONF_GENERATION_COOL_THRESHOLD = "humidity_entity_id", "generation_cool_threshold"
CONF_GENERATION_DRY_THRESHOLD = "generation_dry_threshold"
CONF_DRY_MODE_ENABLED = "dry_mode_enabled"
CONF_POWER_POLICY = "power_policy"
CONF_TEMPERATURE_THRESHOLD = "temperature_threshold"
CONF_GRID_USAGE_DELAY = "grid_usage_delay"
CONF_REACTIVATE_DELAY, CONF_TEMPERATURE_COOL = "reactivate_delay", "temperature_cool"
CONF_REACTIVATE_DELAY_MINUTES = "reactivate_delay_minutes"
CONF_SOLAR_RUN_ON_MINUTES = "solar_run_on_minutes"
CONF_EVAL_INTERVAL, CONF_AIRCON_TIMER_DURATION = "eval_interval", "aircon_timer_duration"
CONF_NOTIFICATION_SERVICE, CONF_SMOOTHING_WINDOW = "notification_service", "smoothing_window"
CONF_MANUAL_COOLING_BEHAVIOUR = "manual_cooling_behaviour"
CONF_STOP_AT_COMFORT_TEMPERATURE = "stop_at_comfort_temperature"
CONF_AUTOMATIC_TARGET_NOTIFICATIONS = "automatic_target_notifications"
CONF_GRID_INVERT = "grid_invert"
CONF_BATTERY_POWER_ENTITY_ID = "battery_power_entity_id"
CONF_BATTERY_INVERT = "battery_invert"
OPTIONAL_ENTITY_KEYS = (CONF_BATTERY_POWER_ENTITY_ID,)
BATTERY_DISCHARGE_TOLERANCE = 100.0
RETIRED_CONFIG_KEYS = frozenset(
    {
        "forecast_entity_id",
        "forecast_min_kwh",
        "battery_min_soc",
        "battery_soc_entity_id",
        "generation_boost_threshold",
        "afternoon_cooling",
        "afternoon_cooling_hour",
        "pre_cooling_start",
        "pre_cooling_finish",
        "temperature_precool",
        "tariff_entity_id",
        "peak_tariff",
        "battery_discharge_tolerance",
        CONF_REACTIVATE_DELAY,
    }
)

DEFAULT_GENERATION_COOL_THRESHOLD, DEFAULT_GENERATION_DRY_THRESHOLD = 5500.0, 3500.0
DEFAULT_TEMPERATURE_THRESHOLD, DRY_MODE_HUMIDITY_CUTOFF = 24.0, 65.0
DEFAULT_GRID_USAGE_DELAY, DEFAULT_REACTIVATE_DELAY = 2, 2
DEFAULT_TEMPERATURE_COOL, DEFAULT_EVAL_INTERVAL, DEFAULT_AIRCON_TIMER_DURATION = 22.0, 180, 60
DEFAULT_REACTIVATE_DELAY_MINUTES = DEFAULT_REACTIVATE_DELAY * DEFAULT_EVAL_INTERVAL / 60
DEFAULT_SOLAR_RUN_ON_MINUTES = 60
DEFAULT_SMOOTHING_WINDOW = 5

MAX_RECENT_EVALUATIONS, STORAGE_VERSION = 50, 1
EVENT_EVALUATION = "home_rules_evaluation"
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
ISSUE_RUNTIME, ISSUE_ENTITY_MISSING, ISSUE_ENTITY_UNAVAILABLE = "runtime_error", "entity_missing", "entity_unavailable"
ISSUE_INVALID_UNIT, ISSUE_NOTIFICATION_SERVICE = "invalid_unit", "notification_service"


def reactivation_delay_minutes(options: Mapping[str, Any]) -> float:
    if CONF_REACTIVATE_DELAY_MINUTES in options:
        return float(options[CONF_REACTIVATE_DELAY_MINUTES])
    return (
        float(options.get(CONF_REACTIVATE_DELAY, DEFAULT_REACTIVATE_DELAY))
        * float(options.get(CONF_EVAL_INTERVAL, DEFAULT_EVAL_INTERVAL))
        / 60
    )
