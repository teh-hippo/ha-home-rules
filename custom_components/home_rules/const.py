"""Constants for Home Rules."""

from __future__ import annotations

from enum import StrEnum
from logging import Logger, getLogger

from homeassistant.const import Platform

LOGGER: Logger = getLogger(__package__)

DOMAIN = "home_rules"


class ControlMode(StrEnum):
    """User-facing operational mode."""

    DISABLED = "Disabled"
    DRY_RUN = "Dry Run"
    LIVE = "Live"
    AGGRESSIVE = "Aggressive"


PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

CONF_CLIMATE_ENTITY_ID = "climate_entity_id"
CONF_TIMER_ENTITY_ID = "timer_entity_id"
CONF_INVERTER_ENTITY_ID = "inverter_entity_id"
CONF_GENERATION_ENTITY_ID = "generation_entity_id"
CONF_GRID_ENTITY_ID = "grid_entity_id"
CONF_TEMPERATURE_ENTITY_ID = "temperature_entity_id"
CONF_HUMIDITY_ENTITY_ID = "humidity_entity_id"

CONF_GENERATION_COOL_THRESHOLD = "generation_cool_threshold"
CONF_GENERATION_DRY_THRESHOLD = "generation_dry_threshold"
CONF_TEMPERATURE_THRESHOLD = "temperature_threshold"
CONF_HUMIDITY_THRESHOLD = "humidity_threshold"
CONF_GRID_USAGE_DELAY = "grid_usage_delay"
CONF_REACTIVATE_DELAY = "reactivate_delay"
CONF_TEMPERATURE_COOL = "temperature_cool"
CONF_EVAL_INTERVAL = "eval_interval"
CONF_NOTIFICATION_SERVICE = "notification_service"

DEFAULT_GENERATION_COOL_THRESHOLD = 5500.0
DEFAULT_GENERATION_DRY_THRESHOLD = 3500.0
DEFAULT_TEMPERATURE_THRESHOLD = 24.0
DEFAULT_HUMIDITY_THRESHOLD = 65.0
DEFAULT_GRID_USAGE_DELAY = 2
DEFAULT_REACTIVATE_DELAY = 2
DEFAULT_TEMPERATURE_COOL = 22.0
DEFAULT_EVAL_INTERVAL = 300

MAX_RECENT_EVALUATIONS = 50

STORAGE_VERSION = 1
STORAGE_KEY_TEMPLATE = f"{DOMAIN}_{{entry_id}}"

EVENT_EVALUATION = "home_rules_evaluation"
ISSUE_RUNTIME = "runtime_error"
ISSUE_ENTITY_MISSING = "entity_missing"
ISSUE_ENTITY_UNAVAILABLE = "entity_unavailable"
ISSUE_INVALID_UNIT = "invalid_unit"
ISSUE_NOTIFICATION_SERVICE = "notification_service"
