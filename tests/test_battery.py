"""Battery guard tests."""

from __future__ import annotations

import pytest

from custom_components.home_rules.rules import (
    R_BATTERY_ENGAGED,
    R_COOL_ON_BATTERY,
    R_TARGET_REACHED,
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    RuleParameters,
    adjust,
)

PARAMS = RuleParameters(5500, 3500, 24, 65, True, 2, 2, 22)


def _home(mode: AirconMode, **kw) -> HomeInput:
    base = dict(
        aircon_mode=mode, have_solar=True, generation=6000, grid_usage=0, timer=False, temperature=26, humidity=50,
        auto=mode is not AirconMode.OFF, aggressive_cooling=False, enabled=True, cooling_enabled=True,
    )  # fmt: skip
    return HomeInput(**{**base, **kw})


async def test_battery_discharge_reported_separately_from_grid(coord_factory, hass) -> None:
    pytest.importorskip("pytest_homeassistant_custom_component")
    from custom_components.home_rules.const import CONF_BATTERY_POWER_ENTITY_ID

    hass.states.async_set("sensor.batt", "1100", {"unit_of_measurement": "W"})
    coordinator = await coord_factory(options={CONF_BATTERY_POWER_ENTITY_ID: "sensor.batt"})
    home, _ = coordinator._build_home_input()
    assert home.grid_usage == 0.0 and home.battery_discharge == 1000.0  # 1100 W less the 100 W default tolerance


@pytest.mark.parametrize("mode", [AirconMode.COOL, AirconMode.DRY])
@pytest.mark.parametrize("auto", [False, True])
def test_solar_cooling_stops_when_battery_engaged(mode: AirconMode, auto: bool) -> None:
    state = CachedState()
    result = adjust(PARAMS, _home(mode, auto=auto, battery_discharge=300), state)
    assert result.output is HomeOutput.OFF and result.reason == R_BATTERY_ENGAGED and state.reactivate_delay == 2


async def test_manual_battery_stop_cancels_active_timer(coord_factory, hass) -> None:
    pytest.importorskip("pytest_homeassistant_custom_component")
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.const import CONF_BATTERY_POWER_ENTITY_ID, ControlMode

    turned_off: list[str] = []

    async def record(call) -> None:
        turned_off.append(call.data["entity_id"])

    hass.services.async_register("climate", "turn_off", record)
    hass.states.async_set("sensor.batt", "1627", {"unit_of_measurement": "W"})
    coordinator = await coord_factory(
        climate="cool",
        generation="4317",
        temperature="22.1",
        humidity="56",
        options={CONF_BATTERY_POWER_ENTITY_ID: "sensor.batt"},
    )
    coordinator._session.last = HomeOutput.TIMER
    coordinator._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(minutes=2)
    coordinator._schedule_timer_expiry()

    await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)

    assert coordinator.data.adjustment is HomeOutput.OFF
    assert coordinator._last_record["reason"] == R_BATTERY_ENGAGED
    assert coordinator._auto_mode is False
    assert turned_off == ["climate.test"]
    assert coordinator.data.timer_finishes_at is None
    assert coordinator._aircon_timer_finishes_at is None
    assert coordinator._timer_expiry_handle is None


def test_solar_cooling_does_not_start_while_battery_engaged() -> None:
    result = adjust(PARAMS, _home(AirconMode.OFF, battery_discharge=300, auto=False), CachedState())
    assert result.output is HomeOutput.NO_CHANGE and result.reason == R_BATTERY_ENGAGED


@pytest.mark.parametrize("auto", [False, True])
def test_boost_keeps_cooling_on_battery_while_house_hot(auto: bool) -> None:
    home = _home(AirconMode.COOL, auto=auto, aggressive_cooling=True, generation=1000, battery_discharge=800)
    result = adjust(PARAMS, home, CachedState())
    assert result.output is not HomeOutput.OFF


@pytest.mark.parametrize("auto", [False, True])
def test_boost_stops_on_battery_once_cool_enough(auto: bool) -> None:
    home = _home(AirconMode.COOL, auto=auto, aggressive_cooling=True, temperature=22, battery_discharge=800)
    result = adjust(PARAMS, home, CachedState())
    assert result.output is HomeOutput.OFF
    assert result.reason == (R_TARGET_REACHED if auto else R_COOL_ON_BATTERY)
