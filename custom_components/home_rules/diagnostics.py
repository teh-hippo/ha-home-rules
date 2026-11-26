from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import const as c

_REDACT_KEYS = {
    c.CONF_BATTERY_POWER_ENTITY_ID,
    c.CONF_BATTERY_SOC_ENTITY_ID,
    c.CONF_CLIMATE_ENTITY_ID,
    c.CONF_GENERATION_ENTITY_ID,
    c.CONF_GRID_ENTITY_ID,
    c.CONF_HUMIDITY_ENTITY_ID,
    c.CONF_NOTIFICATION_SERVICE,
    c.CONF_OCCUPANCY_ENTITY_ID,
    c.CONF_TEMPERATURE_ENTITY_ID,
}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "config": async_redact_data(dict(entry.data), _REDACT_KEYS),
        "options": async_redact_data(dict(entry.options), _REDACT_KEYS),
        "controls": {
            "mode": coordinator.control_mode.value,
            "enabled": coordinator.control_mode is not c.ControlMode.DISABLED,
            "cooling_enabled": coordinator.cooling_enabled,
            "dry_mode_enabled": coordinator.dry_mode_enabled,
            "only_cool_when_home": coordinator.only_cool_when_home,
            "allow_away_battery_cooling": coordinator.allow_away_battery_cooling,
            "stop_at_comfort_temperature": coordinator.stop_at_comfort_temperature,
            "automatic_target_notifications": coordinator.automatic_target_notifications,
            "power_policy": coordinator.power_policy.value,
            "dry_run": coordinator.control_mode is c.ControlMode.MONITOR,
        },
        "policy": {
            "dry_mode_humidity_cutoff": c.DRY_MODE_HUMIDITY_CUTOFF,
            "temperature_cool": coordinator.parameters.temperature_cool,
            "battery_full_threshold": coordinator.parameters.battery_full_threshold,
            "battery_reserve_threshold": coordinator.parameters.battery_reserve_threshold,
            "reactivate_delay_minutes": coordinator.parameters.reactivate_delay,
            "solar_run_on_minutes": coordinator.parameters.solar_run_on_minutes,
        },
        "session": coordinator.last_evaluation,
        "recent_evaluations": coordinator.recent_evaluations,
    }
