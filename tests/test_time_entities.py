"""Pre-cooling window controls and tariff-driven evaluations."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_time_and_power_controls_persist_across_reload(hass, loaded_entry) -> None:
    for entity_id, value in (
        ("time.home_rules_pre_cooling_start", "13:30:00"),
        ("time.home_rules_pre_cooling_finish", "17:30:00"),
    ):
        await hass.services.async_call("time", "set_value", {"entity_id": entity_id, "time": value}, blocking=True)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.home_rules_power_policy", "option": "allow_battery_grid"},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.home_rules_temperature_precool", "value": 21},
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

    assert hass.states.get("time.home_rules_pre_cooling_start").state == "13:30:00"
    assert hass.states.get("time.home_rules_pre_cooling_finish").state == "17:30:00"
    assert hass.states.get("select.home_rules_power_policy").state == "allow_battery_grid"
    assert hass.states.get("number.home_rules_temperature_precool").state == "21.0"
    assert hass.states.get("switch.home_rules_stop_at_comfort_temperature").state == "on"
    assert hass.states.get("switch.home_rules_automatic_target_notifications").state == "off"


@pytest.mark.parametrize(
    ("entity_id", "value"),
    [("time.home_rules_pre_cooling_start", "17:00:00"), ("time.home_rules_pre_cooling_finish", "13:00:00")],
)
async def test_invalid_window_preserves_saved_controls(hass, loaded_entry, entity_id, value) -> None:
    from homeassistant.exceptions import ServiceValidationError

    coordinator = loaded_entry.runtime_data
    before = await coordinator._store.async_load()
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call("time", "set_value", {"entity_id": entity_id, "time": value}, blocking=True)

    assert error.value.translation_key == "invalid_precooling_window"
    assert await coordinator._store.async_load() == before


@pytest.mark.parametrize(("zone", "offset"), [("UTC", "+00:00"), ("Australia/Sydney", "+11:00")])
async def test_window_boundaries_evaluate_without_waiting_for_poll(hass, coord_factory, freezer, zone, offset) -> None:
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    await hass.config.async_update(time_zone=zone)
    freezer.move_to(f"2026-11-13T13:59:00{offset}")
    starts = async_mock_service(hass, "climate", "set_hvac_mode")
    targets = async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(temperature="23")
    coordinator.stop_at_comfort_temperature = True
    await coordinator.async_set_control("afternoon_cooling", True)
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    assert not starts

    freezer.move_to(f"2026-11-13T14:00:00{offset}")
    hass.states.async_set("sensor.temperature", "24", {"unit_of_measurement": "°C"})
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(starts) == 1
    assert targets[-1].data["temperature"] == 20
    assert coordinator._last_record["trigger"] == "pre_cooling_boundary"

    hass.states.async_set("climate.test", "cool", {"temperature": 20})
    hass.states.async_set("sensor.temperature", "21", {"unit_of_measurement": "°C"})
    freezer.move_to(f"2026-11-13T17:00:00{offset}")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert len(stops) == 1
    assert coordinator.data.adjustment is HomeOutput.OFF
    assert coordinator._last_record["trigger"] == "pre_cooling_boundary"
    assert coordinator._last_record["pre_cooling"] is False

    hass.states.async_set("climate.test", "off")
    freezer.move_to(f"2026-11-13T21:00:00{offset}")
    await coordinator.async_run_evaluation("poll")
    assert len(starts) == 1
    assert coordinator._last_record["target_temperature"] == 22


@pytest.mark.parametrize("tariff", ["peak", "unavailable", "unknown"])
async def test_tariff_change_immediately_ends_precooling(hass, coord_factory, freezer, tariff) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import CONF_TARIFF_ENTITY_ID, ControlMode

    await hass.config.async_update(time_zone="UTC")
    freezer.move_to("2026-11-13T15:00:00+00:00")
    hass.states.async_set("select.tariff", "offpeak")
    async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(temperature="23", options={CONF_TARIFF_ENTITY_ID: "select.tariff"})
    coordinator.stop_at_comfort_temperature = True
    await coordinator.async_set_control("afternoon_cooling", True)
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    assert coordinator._last_record.get("pre_cooling") is True

    hass.states.async_set("climate.test", "cool", {"temperature": 20})
    hass.states.async_set("sensor.temperature", "21", {"unit_of_measurement": "°C"})
    hass.states.async_set("select.tariff", tariff)
    await hass.async_block_till_done()

    assert coordinator._last_record["trigger"] == "tariff"
    assert coordinator._last_record.get("pre_cooling") is False
    assert len(stops) == 1


@pytest.mark.parametrize(
    ("legacy_mode", "policy"), [("solar_cooling", "solar_only"), ("boost_cooling", "allow_battery_grid")]
)
async def test_legacy_modes_and_afternoon_hour_migrate(coord_factory, legacy_mode, policy) -> None:
    from datetime import time

    from custom_components.home_rules.const import CONF_AFTERNOON_COOLING_HOUR, ControlMode

    coordinator = await coord_factory(temperature="19", options={CONF_AFTERNOON_COOLING_HOUR: 16})
    await coordinator._store.async_save(
        {"controls": {"mode": legacy_mode, "afternoon_cooling": True}, "parameters": {"temperature_cool": 21}}
    )
    await coordinator.async_shutdown()
    await coordinator.async_initialize()
    await coordinator.async_run_evaluation("restart")

    assert coordinator.control_mode is ControlMode.AUTOMATIC
    assert coordinator.power_policy.value == policy
    assert coordinator.afternoon_cooling
    assert coordinator.pre_cooling_start == time(16)
    assert coordinator.pre_cooling_finish == time(17)
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
