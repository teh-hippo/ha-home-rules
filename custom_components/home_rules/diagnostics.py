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
            "aggressive_cooling": coordinator.control_mode is c.ControlMode.BOOST_COOLING,
            "dry_run": coordinator.control_mode is c.ControlMode.MONITOR,
        },
        "session": dict(coordinator._last_record),
        "recent_evaluations": list(coordinator._recent),
    }
