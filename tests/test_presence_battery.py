"""Occupancy and battery-authorised cooling tests."""

from __future__ import annotations


async def test_full_battery_starts_away_cooling_on_next_poll(hass, coord_factory) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import (
        CONF_BATTERY_SOC_ENTITY_ID,
        ControlMode,
    )
    from custom_components.home_rules.rules import HomeOutput

    hass.states.async_set("zone.home", "0")
    hass.states.async_set("sensor.battery_soc", "99", {"unit_of_measurement": "%"})
    starts = async_mock_service(hass, "climate", "set_hvac_mode")
    targets = async_mock_service(hass, "climate", "set_temperature")
    coordinator = await coord_factory(
        generation="0",
        temperature="29",
        options={CONF_BATTERY_SOC_ENTITY_ID: "sensor.battery_soc"},
    )
    coordinator.only_cool_when_home = True
    coordinator.allow_away_battery_cooling = True
    coordinator.control_mode = ControlMode.AUTOMATIC

    await coordinator.async_run_evaluation("initial")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert not starts

    hass.states.async_set("sensor.battery_soc", "100", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert coordinator._last_record["trigger"] == "initial"
    assert not starts

    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record["trigger"] == "poll"
    assert coordinator.data.adjustment.value == HomeOutput.COOL.value
    assert starts[-1].data["hvac_mode"] == "cool"
    assert targets[-1].data["temperature"] == 22
    assert coordinator._session.battery_run_authorized


async def test_departure_is_applied_on_next_evaluation(hass, coord_factory) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import (
        CONF_BATTERY_SOC_ENTITY_ID,
        ControlMode,
    )
    from custom_components.home_rules.rules import HomeOutput

    hass.states.async_set("zone.home", "1")
    hass.states.async_set("sensor.battery_soc", "79", {"unit_of_measurement": "%"})
    async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(
        generation="6000",
        temperature="29",
        options={CONF_BATTERY_SOC_ENTITY_ID: "sensor.battery_soc"},
    )
    coordinator.only_cool_when_home = True
    coordinator.allow_away_battery_cooling = True
    coordinator.control_mode = ControlMode.AUTOMATIC
    await coordinator.async_run_evaluation("initial")
    assert coordinator.data.adjustment.value == HomeOutput.COOL.value

    hass.states.async_set("climate.test", "cool", {"temperature": 22})
    await hass.async_block_till_done()
    hass.states.async_set("zone.home", "0")
    await hass.async_block_till_done()
    assert coordinator._last_record["trigger"] == "climate"
    assert not stops

    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record["trigger"] == "poll"
    assert coordinator.data.adjustment.value == HomeOutput.OFF.value
    assert len(stops) == 1


async def test_selected_person_controls_home_comfort_independently_of_zone(hass, coord_factory) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import (
        CONF_BATTERY_SOC_ENTITY_ID,
        CONF_OCCUPANCY_ENTITY_ID,
        ControlMode,
    )
    from custom_components.home_rules.rules import R_NO_ONE_HOME, HomeOutput

    hass.states.async_set("zone.home", "1")
    hass.states.async_set("person.camille", "not_home")
    hass.states.async_set("sensor.battery_soc", "66", {"unit_of_measurement": "%"})
    starts = async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(
        options={
            CONF_OCCUPANCY_ENTITY_ID: "person.camille",
            CONF_BATTERY_SOC_ENTITY_ID: "sensor.battery_soc",
        },
    )
    coordinator.only_cool_when_home = True
    coordinator.allow_away_battery_cooling = True
    coordinator.control_mode = ControlMode.AUTOMATIC

    await coordinator.async_run_evaluation("initial")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == R_NO_ONE_HOME
    assert not starts

    hass.states.async_set("person.camille", "home")
    await hass.async_block_till_done()
    assert coordinator._last_record["trigger"] == "initial"
    assert not starts

    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record["trigger"] == "poll"
    assert coordinator.data.adjustment.value == HomeOutput.COOL.value
    assert len(starts) == 1

    hass.states.async_set("climate.test", "cool", {"temperature": 22})
    await hass.async_block_till_done()
    hass.states.async_set("person.camille", "not_home")
    await hass.async_block_till_done()
    assert len(stops) == 0

    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment.value == HomeOutput.OFF.value
    assert coordinator._last_record["reason"] == R_NO_ONE_HOME
    assert len(stops) == 1


async def test_policy_controls_persist_and_unavailable_occupancy_fails_closed(coord_factory) -> None:
    from custom_components.home_rules.const import CONF_ONLY_COOL_WHEN_HOME
    from custom_components.home_rules.rules import R_OCCUPANCY_UNAVAILABLE

    coordinator = await coord_factory(temperature="29")
    await coordinator.async_set_control(CONF_ONLY_COOL_WHEN_HOME, True)
    await coordinator.async_run_evaluation("poll")
    assert coordinator.only_cool_when_home
    assert coordinator._last_record["reason"] == R_OCCUPANCY_UNAVAILABLE

    await coordinator.async_shutdown()
    await coordinator.async_initialize()
    assert coordinator.only_cool_when_home
