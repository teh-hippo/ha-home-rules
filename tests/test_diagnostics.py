"""Diagnostics tests for Home Rules."""

from __future__ import annotations


async def test_diagnostics_contains_expected_sections(hass, loaded_entry) -> None:
    """Diagnostics output should include key sections for config and runtime state."""
    from custom_components.home_rules.const import CONF_CLIMATE_ENTITY_ID
    from custom_components.home_rules.diagnostics import async_get_config_entry_diagnostics

    diagnostics = await async_get_config_entry_diagnostics(hass, loaded_entry)

    assert set(diagnostics) == {"config", "options", "controls", "policy", "session", "recent_evaluations"}
    assert diagnostics["controls"]["mode"] == "monitor"
    assert diagnostics["controls"]["dry_mode_enabled"] is True
    assert diagnostics["controls"]["only_cool_when_home"] is False
    assert diagnostics["controls"]["allow_away_battery_cooling"] is False
    assert diagnostics["controls"]["afternoon_cooling_enabled"] is False
    assert diagnostics["controls"]["stop_at_comfort_temperature"] is False
    assert diagnostics["controls"]["automatic_target_notifications"] is True
    assert diagnostics["policy"]["dry_mode_humidity_cutoff"] == 65.0
    assert diagnostics["policy"]["battery_full_threshold"] == 100.0
    assert diagnostics["policy"]["battery_reserve_threshold"] == 80.0
    assert diagnostics["policy"]["afternoon_energy_budget"] == 6.1
    assert diagnostics["policy"]["afternoon_battery_reserve"] == 40.0
    assert diagnostics["policy"]["afternoon_ready_by"] == "17:00:00"
    assert isinstance(diagnostics["recent_evaluations"], list)
    assert diagnostics["config"][CONF_CLIMATE_ENTITY_ID] != loaded_entry.data[CONF_CLIMATE_ENTITY_ID]
