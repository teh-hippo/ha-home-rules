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

    assert hass.states.get("select.home_rules_control_mode").state == "monitor"
    assert hass.states.get("switch.home_rules_cooling_enabled").state == "on"


async def test_all_entities_use_translation_key_not_name(hass, loaded_entry) -> None:
    """All entity descriptions must use translation_key and not hardcoded name/icon."""
    from custom_components.home_rules.entities import BINARY_SENSORS, NUMBERS, SENSORS

    for desc in (*SENSORS, *BINARY_SENSORS, *NUMBERS):
        assert desc.translation_key, f"{desc.key} missing translation_key"
        assert not isinstance(desc.name, str), f"{desc.key} should not set name (use translation_key)"
        assert desc.icon is None, f"{desc.key} should not set icon (use icons.json)"
