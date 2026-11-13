from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import const as c


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "config": async_redact_data(dict(entry.data), set()),
        "options": async_redact_data(dict(entry.options), set()),
        "controls": {
            "mode": coordinator.control_mode.value,
            "enabled": coordinator.control_mode is not c.ControlMode.DISABLED,
            "cooling_enabled": coordinator.cooling_enabled,
            "dry_mode_enabled": coordinator.dry_mode_enabled,
            "afternoon_cooling": coordinator.afternoon_cooling,
            "stop_at_comfort_temperature": coordinator.stop_at_comfort_temperature,
            "automatic_target_notifications": coordinator.automatic_target_notifications,
            "power_policy": coordinator.power_policy.value,
            "pre_cooling_start": coordinator.pre_cooling_start.isoformat(),
            "pre_cooling_finish": coordinator.pre_cooling_finish.isoformat(),
            "dry_run": coordinator.control_mode is c.ControlMode.MONITOR,
        },
        "policy": {
            "dry_mode_humidity_cutoff": c.DRY_MODE_HUMIDITY_CUTOFF,
            "temperature_cool": coordinator.parameters.temperature_cool,
            "temperature_precool": coordinator.parameters.temperature_precool,
        },
        "session": dict(coordinator._last_record),
        "recent_evaluations": list(coordinator._recent),
    }
