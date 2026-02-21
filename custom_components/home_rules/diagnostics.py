from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import const as c


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "config": async_redact_data(dict(entry.data), set()),
        "options": async_redact_data(dict(entry.options), set()),
        "controls": {
            "mode": coordinator.control_mode.value,
            "enabled": coordinator.control_mode is not c.ControlMode.DISABLED,
            "cooling_enabled": coordinator.controls.cooling_enabled,
            "aggressive_cooling": coordinator.control_mode is c.ControlMode.BOOST_COOLING,
            "dry_run": coordinator.control_mode is c.ControlMode.MONITOR,
        },
        "session": {
            "last_mode": data.mode.value,
            "current": data.current.value,
            "adjustment": data.adjustment.value,
            "solar_available": data.solar_available,
            "solar_generation_w": data.solar_generation_w,
            "grid_usage_w": data.grid_usage_w,
            "auto_mode": data.auto_mode,
            "last_evaluated": data.last_evaluated,
            "last_changed": data.last_changed,
        },
        "recent_evaluations": data.recent_evaluations,
    }
