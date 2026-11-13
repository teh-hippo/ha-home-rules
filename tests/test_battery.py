"""Battery guard tests."""

from __future__ import annotations

import pytest

from custom_components.home_rules.rules import (
    R_BATTERY_ENGAGED,
    R_BATTERY_TOLERATED,
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
        auto=mode is not AirconMode.OFF, allow_paid_power=False, enabled=True, cooling_enabled=True,
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
def test_solar_cooling_stops_when_battery_engaged(mode: AirconMode) -> None:
    state = CachedState()
    result = adjust(PARAMS, _home(mode, battery_discharge=300), state)
    assert result.output is HomeOutput.NO_CHANGE and result.reason == R_BATTERY_TOLERATED
    result = adjust(PARAMS, _home(mode, battery_discharge=300), state)
    assert result.output is HomeOutput.OFF and result.reason == R_BATTERY_ENGAGED and state.reactivate_at == 120


async def test_manual_battery_run_preserves_active_timer(coord_factory, hass) -> None:
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
    deadline = dt_util.utcnow() + timedelta(minutes=2)
    coordinator._aircon_timer_finishes_at = deadline
    coordinator._schedule_timer_expiry()

    await coordinator.async_set_mode(ControlMode.AUTOMATIC)

    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._auto_mode is False
    assert not turned_off
    assert coordinator.data.timer_finishes_at == deadline
    assert coordinator._timer_expiry_handle is not None


def test_solar_cooling_does_not_start_while_battery_engaged() -> None:
    result = adjust(PARAMS, _home(AirconMode.OFF, battery_discharge=300, auto=False), CachedState())
    assert result.output is HomeOutput.NO_CHANGE and result.reason == R_BATTERY_ENGAGED


@pytest.mark.parametrize("auto", [False, True])
def test_boost_keeps_cooling_on_battery_while_house_hot(auto: bool) -> None:
    home = _home(AirconMode.COOL, auto=auto, allow_paid_power=True, generation=1000, battery_discharge=800)
    result = adjust(PARAMS, home, CachedState())
    assert result.output is not HomeOutput.OFF


def test_paid_power_maintains_target_on_battery() -> None:
    home = _home(AirconMode.COOL, allow_paid_power=True, temperature=22, battery_discharge=800)
    result = adjust(PARAMS, home, CachedState())
    assert result.output is HomeOutput.NO_CHANGE


def test_precooling_still_stops_on_sustained_battery_use_and_resets_after_recovery() -> None:
    state = CachedState()
    run = _home(AirconMode.COOL, pre_cooling=True, temperature=20, battery_discharge=300)
    assert adjust(PARAMS, run, state).reason == R_BATTERY_TOLERATED
    run.battery_discharge = 0
    assert adjust(PARAMS, run, state).output is HomeOutput.NO_CHANGE
    assert state.tolerated == 0
    run.battery_discharge = 300
    assert adjust(PARAMS, run, state).reason == R_BATTERY_TOLERATED
    assert adjust(PARAMS, run, state).output is HomeOutput.OFF
