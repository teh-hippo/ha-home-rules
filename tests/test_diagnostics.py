"""Diagnostics tests for Home Rules."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_diagnostics_contains_expected_sections(hass, loaded_entry) -> None:
    """Diagnostics output should include key sections for config and runtime state."""
    from custom_components.home_rules.diagnostics import async_get_config_entry_diagnostics

    diagnostics = await async_get_config_entry_diagnostics(hass, loaded_entry)

    assert set(diagnostics) == {"config", "options", "controls", "policy", "session", "recent_evaluations"}
    assert diagnostics["controls"]["mode"] == "monitor"
    assert diagnostics["controls"]["dry_mode_enabled"] is True
    assert diagnostics["policy"]["dry_mode_humidity_cutoff"] == 65.0
    assert isinstance(diagnostics["recent_evaluations"], list)
