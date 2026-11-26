"""Control persistence and legacy-mode tests."""

from __future__ import annotations

import pytest


async def test_power_and_target_controls_persist_across_reload(hass, loaded_entry) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.home_rules_power_policy", "option": "allow_battery_grid"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.home_rules_stop_at_comfort_temperature"}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.home_rules_automatic_target_notifications"}, blocking=True
    )

    assert await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("select.home_rules_power_policy").state == "allow_battery_grid"
    assert hass.states.get("switch.home_rules_stop_at_comfort_temperature").state == "on"
    assert hass.states.get("switch.home_rules_automatic_target_notifications").state == "off"


@pytest.mark.parametrize(
    ("legacy_mode", "policy"), [("solar_cooling", "solar_only"), ("boost_cooling", "allow_battery_grid")]
)
async def test_legacy_modes_migrate(coord_factory, legacy_mode, policy) -> None:
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory(temperature="19")
    await coordinator._store.async_save({"controls": {"mode": legacy_mode}, "parameters": {"temperature_cool": 21}})
    await coordinator.async_shutdown()
    await coordinator.async_initialize()
    await coordinator.async_run_evaluation("restart")

    assert coordinator.control_mode is ControlMode.AUTOMATIC
    assert coordinator.power_policy.value == policy
    assert coordinator.parameters.temperature_cool == 21
    stored = await coordinator._store.async_load()
    assert stored["controls"]["mode"] == "automatic"
    assert stored["controls"]["power_policy"] == policy


@pytest.mark.parametrize(("behaviour", "stop"), [("timer", False), ("ask", False), ("stop", True)])
async def test_legacy_target_behaviour_migrates_to_independent_controls(coord_factory, behaviour, stop) -> None:
    from custom_components.home_rules.const import (
        CONF_AUTOMATIC_TARGET_NOTIFICATIONS,
        CONF_MANUAL_COOLING_BEHAVIOUR,
        CONF_STOP_AT_COMFORT_TEMPERATURE,
    )

    coordinator = await coord_factory(options={CONF_MANUAL_COOLING_BEHAVIOUR: behaviour})
    assert coordinator.stop_at_comfort_temperature is stop
    assert coordinator.automatic_target_notifications
    await coordinator.async_set_control(CONF_STOP_AT_COMFORT_TEMPERATURE, not stop)
    await coordinator.async_set_control(CONF_AUTOMATIC_TARGET_NOTIFICATIONS, False)
    await coordinator.async_shutdown()
    await coordinator.async_initialize()
    assert coordinator.stop_at_comfort_temperature is not stop
    assert not coordinator.automatic_target_notifications
