"""Entity registration and basic state assertions for Home Rules."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_entities_register_on_setup(hass, loaded_entry) -> None:
    """All platform entities should be created when the config entry is set up."""
    entity_ids = [
        "sensor.home_rules_mode",
        "sensor.home_rules_current_state",
        "sensor.home_rules_action",
        "sensor.home_rules_decision",
        "sensor.home_rules_last_evaluated",
        "sensor.home_rules_last_changed",
        "sensor.home_rules_timer_countdown",
        "binary_sensor.home_rules_solar_available",
        "binary_sensor.home_rules_auto_mode",
        "select.home_rules_control_mode",
        "switch.home_rules_cooling_enabled",
        "button.home_rules_evaluate_now",
    ]

    for entity_id in entity_ids:
        assert hass.states.get(entity_id) is not None

    assert hass.states.get("select.home_rules_control_mode").state == "Monitor"
    assert hass.states.get("switch.home_rules_cooling_enabled").state == "on"
