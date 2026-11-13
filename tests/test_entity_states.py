"""Entity registration and basic state assertions for Home Rules."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_entities_register_on_setup(hass, loaded_entry) -> None:
    """All platform entities should be created when the config entry is set up."""
    entity_ids = [
        "sensor.home_rules_mode",
        "sensor.home_rules_action",
        "sensor.home_rules_decision",
        "sensor.home_rules_last_evaluated",
        "sensor.home_rules_last_changed",
        "sensor.home_rules_timer_countdown",
        "binary_sensor.home_rules_solar_available",
        "binary_sensor.home_rules_auto_mode",
        "select.home_rules_control_mode",
        "select.home_rules_power_policy",
        "switch.home_rules_cooling_enabled",
        "switch.home_rules_dry_mode_enabled",
        "switch.home_rules_afternoon_cooling",
        "button.home_rules_evaluate_now",
        "time.home_rules_pre_cooling_start",
        "time.home_rules_pre_cooling_finish",
    ]

    for entity_id in entity_ids:
        assert hass.states.get(entity_id) is not None
    assert hass.states.get("sensor.home_rules_current_state") is None

    assert hass.states.get("select.home_rules_control_mode").state == "monitor"
    assert hass.states.get("select.home_rules_power_policy").state == "solar_only"
    assert hass.states.get("time.home_rules_pre_cooling_start").state == "14:00:00"
    assert hass.states.get("time.home_rules_pre_cooling_finish").state == "17:00:00"
    assert hass.states.get("switch.home_rules_cooling_enabled").state == "on"
    assert hass.states.get("switch.home_rules_dry_mode_enabled").state == "on"
    assert hass.states.get("switch.home_rules_afternoon_cooling").state == "off"


async def test_all_entities_use_translation_key_not_name(hass, loaded_entry) -> None:
    """All entity descriptions must use translation_key and not hardcoded name/icon."""
    from custom_components.home_rules.entities import BINARY_SENSORS, NUMBERS, SENSORS, SWITCHES

    for desc in (*SENSORS, *BINARY_SENSORS, *SWITCHES, *NUMBERS):
        assert desc.translation_key, f"{desc.key} missing translation_key"
        assert not isinstance(desc.name, str), f"{desc.key} should not set name (use translation_key)"
        assert desc.icon is None, f"{desc.key} should not set icon (use icons.json)"


async def test_renamed_labels_preserve_registered_entity_ids(hass, mock_entry) -> None:
    from homeassistant.helpers import entity_registry as er

    from custom_components.home_rules.const import DOMAIN

    registry = er.async_get(hass)
    for domain, key, object_id in (
        ("number", "temperature_cool", "my_cooling_target"),
        ("switch", "afternoon_cooling", "my_afternoon_switch"),
    ):
        registry.async_get_or_create(
            domain,
            DOMAIN,
            f"{mock_entry.entry_id}_{key}",
            config_entry=mock_entry,
            suggested_object_id=object_id,
        )

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.my_cooling_target") is not None
    assert hass.states.get("switch.my_afternoon_switch") is not None
