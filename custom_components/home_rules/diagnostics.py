"""Diagnostics for Home Rules."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

REDACT_KEYS: set[str] = set()


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "config": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": dict(entry.options),
        "controls": {
            "enabled": coordinator.controls.enabled,
            "cooling_enabled": coordinator.controls.cooling_enabled,
            "aggressive_cooling": coordinator.controls.aggressive_cooling,
            "dry_run": coordinator.controls.dry_run,
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
