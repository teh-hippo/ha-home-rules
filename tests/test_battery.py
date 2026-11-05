"""Battery and forecast guard tests."""

from __future__ import annotations

import pytest

from custom_components.home_rules.rules import (
    R_BATTERY_ENGAGED,
    R_BATTERY_LOW,
    R_COOL_ON_BATTERY,
    R_FORECAST_LOW,
    R_GRID_TOLERATED,
    R_SOLAR_COOL,
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    RuleParameters,
    adjust,
)

PARAMS = RuleParameters(5500, 3500, 500, 24, 65, True, 2, 2, 22)


def _home(mode: AirconMode, **kw) -> HomeInput:
    base = dict(
        aircon_mode=mode, have_solar=True, generation=6000, grid_usage=0, timer=False, temperature=26, humidity=50,
        auto=mode is not AirconMode.OFF, aggressive_cooling=False, enabled=True, cooling_enabled=True,
    )  # fmt: skip
    return HomeInput(**{**base, **kw})


def test_battery_low_blocks_start() -> None:
    assert adjust(PARAMS, _home(AirconMode.OFF), CachedState()).reason == R_SOLAR_COOL
    result = adjust(PARAMS, _home(AirconMode.OFF, battery_low=True, auto=False), CachedState())
    assert result.output is HomeOutput.NO_CHANGE and result.reason == R_BATTERY_LOW


def test_forecast_low_blocks_start() -> None:
    result = adjust(PARAMS, _home(AirconMode.OFF, forecast_low=True, auto=False), CachedState())
    assert result.output is HomeOutput.NO_CHANGE and result.reason == R_FORECAST_LOW


def test_battery_low_shuts_off_running_aircon_after_tolerance() -> None:
    state = CachedState()
    home = _home(AirconMode.COOL, battery_low=True)
    assert adjust(PARAMS, home, state).reason == R_GRID_TOLERATED
    result = adjust(PARAMS, home, state)
    assert result.output is HomeOutput.OFF and result.reason == R_BATTERY_LOW and state.reactivate_delay == 2


@pytest.mark.parametrize(
    ("soc", "climate", "expected"),
    [("60", "off", True), ("65", "off", False), ("60", "cool", False), ("55", "cool", True), ("59", "cool", False)],
)
async def test_battery_low_hysteresis(coord_factory, hass, soc: str, climate: str, expected: bool) -> None:
    pytest.importorskip("pytest_homeassistant_custom_component")
    from custom_components.home_rules.const import CONF_BATTERY_MIN_SOC, CONF_BATTERY_SOC_ENTITY_ID

    hass.states.async_set("sensor.soc", soc)
    coordinator = await coord_factory(climate=climate, options={CONF_BATTERY_SOC_ENTITY_ID: "sensor.soc"})
    coordinator._parameters[CONF_BATTERY_MIN_SOC] = 62.0
    home, _ = coordinator._build_home_input()
    assert home.battery_low is expected


async def test_battery_discharge_reported_separately_from_grid(coord_factory, hass) -> None:
    pytest.importorskip("pytest_homeassistant_custom_component")
    from custom_components.home_rules.const import CONF_BATTERY_POWER_ENTITY_ID

    hass.states.async_set("sensor.batt", "1100", {"unit_of_measurement": "W"})
    coordinator = await coord_factory(options={CONF_BATTERY_POWER_ENTITY_ID: "sensor.batt"})
    home, _ = coordinator._build_home_input()
    assert home.grid_usage == 0.0 and home.battery_discharge == 1000.0  # 1100 W less the 100 W default tolerance


async def test_forecast_low_from_kwh_sensor(coord_factory, hass) -> None:
    pytest.importorskip("pytest_homeassistant_custom_component")
    from custom_components.home_rules.const import CONF_FORECAST_ENTITY_ID, CONF_FORECAST_MIN_KWH

    hass.states.async_set("sensor.fc", "9000", {"unit_of_measurement": "Wh"})
    coordinator = await coord_factory(options={CONF_FORECAST_ENTITY_ID: "sensor.fc"})
    coordinator._parameters[CONF_FORECAST_MIN_KWH] = 10.0
    home, _ = coordinator._build_home_input()
    assert home.forecast_kwh == 9.0 and home.forecast_low is True


def test_solar_cooling_stops_when_battery_engaged() -> None:
    state = CachedState()
    result = adjust(PARAMS, _home(AirconMode.COOL, battery_discharge=300), state)
    assert result.output is HomeOutput.OFF and result.reason == R_BATTERY_ENGAGED and state.reactivate_delay == 2


def test_solar_cooling_does_not_start_while_battery_engaged() -> None:
    result = adjust(PARAMS, _home(AirconMode.OFF, battery_discharge=300, auto=False), CachedState())
    assert result.output is HomeOutput.NO_CHANGE and result.reason == R_BATTERY_ENGAGED


def test_boost_keeps_cooling_on_battery_while_house_hot() -> None:
    home = _home(AirconMode.COOL, aggressive_cooling=True, generation=1000, battery_discharge=800)
    result = adjust(PARAMS, home, CachedState())
    assert result.output is not HomeOutput.OFF


def test_boost_stops_on_battery_once_cool_enough() -> None:
    home = _home(AirconMode.COOL, aggressive_cooling=True, temperature=22, battery_discharge=800)
    result = adjust(PARAMS, home, CachedState())
    assert result.output is HomeOutput.OFF and result.reason == R_COOL_ON_BATTERY


def test_boost_stops_on_battery_low() -> None:
    state = CachedState()
    home = _home(AirconMode.COOL, aggressive_cooling=True, battery_discharge=800, battery_low=True)
    adjust(PARAMS, home, state)
    assert adjust(PARAMS, home, state).output is HomeOutput.OFF
