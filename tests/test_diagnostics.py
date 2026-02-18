"""Diagnostics tests for Home Rules."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_diagnostics_contains_expected_sections(hass, loaded_entry) -> None:
    """Diagnostics output should include key sections for config and runtime state."""
    from custom_components.home_rules.diagnostics import async_get_config_entry_diagnostics

    diagnostics = await async_get_config_entry_diagnostics(hass, loaded_entry)

    assert set(diagnostics) == {"config", "options", "controls", "session", "recent_evaluations"}
    assert diagnostics["controls"]["mode"] == "Dry Run"
    assert isinstance(diagnostics["recent_evaluations"], list)
