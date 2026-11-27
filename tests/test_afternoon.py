"""Afternoon forecast and central-cooling policy tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import SupportsResponse

from custom_components.home_rules.rules import (
    R_AFTERNOON_COOLING,
    R_AFTERNOON_FORECAST_UNAVAILABLE,
    R_AFTERNOON_NO_RECOVERY,
    R_AFTERNOON_OCCUPANCY,
    R_AFTERNOON_POWER_UNAVAILABLE,
    R_AFTERNOON_RESERVE,
    R_AFTERNOON_TARGET,
    R_AFTERNOON_WAITING,
    R_AFTERNOON_WINDOW_CLOSED,
    R_BATTERY_ENGAGED,
    R_BATTERY_TOLERATED,
    R_GRID_TOO_HIGH,
    R_NO_ONE_HOME,
    R_SOLAR_COOL,
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    RuleParameters,
    adjust,
)


def _params(**changes: object) -> RuleParameters:
    values = {
        "generation_cool_threshold": 5500,
        "generation_dry_threshold": 3500,
        "temperature_threshold": 24,
        "dry_mode_humidity_cutoff": 65,
        "dry_mode_enabled": True,
        "grid_usage_delay": 2,
        "reactivate_delay": 6,
        "temperature_cool": 22,
    }
    return RuleParameters(**(values | changes))


def _home(**changes: object) -> HomeInput:
    values = {
        "aircon_mode": AirconMode.OFF,
        "have_solar": False,
        "generation": 0,
        "grid_usage": 0,
        "timer": False,
        "temperature": 25,
        "humidity": 40,
        "auto": True,
        "allow_paid_power": False,
        "enabled": True,
        "cooling_enabled": True,
        "afternoon_enabled": True,
        "afternoon_planning": True,
        "afternoon_window_open": True,
        "afternoon_start_allowed": True,
        "afternoon_forecast_available": True,
        "someone_home": True,
        "only_cool_when_home": True,
        "battery_soc": 60,
        "generation_available": True,
        "grid_available": True,
        "battery_power_available": True,
    }
    return HomeInput(**(values | changes))


def test_afternoon_disabled_preserves_normal_solar_start() -> None:
    result = adjust(
        _params(),
        _home(
            afternoon_enabled=False,
            afternoon_planning=False,
            have_solar=True,
            generation=6000,
        ),
        CachedState(),
    )

    assert result.output is HomeOutput.COOL
    assert result.reason == R_SOLAR_COOL


@pytest.mark.parametrize("forecast_available", [True, False])
def test_waiting_for_afternoon_window_blocks_early_start(forecast_available: bool) -> None:
    result = adjust(
        _params(),
        _home(
            have_solar=True,
            generation=6000,
            afternoon_window_open=False,
            afternoon_forecast_available=forecast_available,
        ),
        CachedState(),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == (R_AFTERNOON_WAITING if forecast_available else R_AFTERNOON_FORECAST_UNAVAILABLE)


def test_away_low_battery_blocks_afternoon_start() -> None:
    result = adjust(
        _params(),
        _home(
            have_solar=True,
            generation=6000,
            someone_home=False,
            battery_soc=99,
            allow_away_battery_cooling=True,
        ),
        CachedState(),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_NO_ONE_HOME


def test_away_full_battery_can_start_only_on_live_surplus() -> None:
    state = CachedState()
    result = adjust(
        _params(),
        _home(
            have_solar=True,
            generation=6000,
            someone_home=False,
            battery_soc=100,
            allow_away_battery_cooling=True,
        ),
        state,
    )

    assert result.output is HomeOutput.COOL
    assert state.battery_run_authorized
    assert not state.afternoon_run_authorized

    running = _home(
        aircon_mode=AirconMode.COOL,
        have_solar=True,
        generation=6000,
        someone_home=False,
        battery_soc=99,
        allow_away_battery_cooling=True,
    )
    assert adjust(_params(), running, state).output is HomeOutput.NO_CHANGE


def test_away_exception_remains_explicit_during_planning() -> None:
    result = adjust(
        _params(),
        _home(
            have_solar=True,
            generation=6000,
            someone_home=False,
            battery_soc=100,
            allow_away_battery_cooling=False,
        ),
        CachedState(),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_NO_ONE_HOME


@pytest.mark.parametrize(
    "missing",
    ["generation_available", "grid_available", "battery_power_available"],
)
def test_missing_live_power_blocks_afternoon_start(missing: str) -> None:
    result = adjust(
        _params(),
        _home(**{missing: False}),
        CachedState(),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_AFTERNOON_POWER_UNAVAILABLE


def test_existing_top_up_stops_when_live_power_disappears() -> None:
    result = adjust(
        _params(),
        _home(
            aircon_mode=AirconMode.COOL,
            battery_power_available=False,
        ),
        CachedState(
            last=HomeOutput.COOL,
            afternoon_run_authorized=True,
            afternoon_battery_run=True,
        ),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_AFTERNOON_POWER_UNAVAILABLE


def test_home_allows_battery_top_up_above_reserve() -> None:
    state = CachedState()
    result = adjust(_params(), _home(), state)

    assert result.output is HomeOutput.COOL
    assert result.reason == R_AFTERNOON_COOLING
    assert state.afternoon_run_authorized
    assert state.afternoon_battery_run
    assert adjust(_params(), _home(battery_discharge=500), CachedState()).reason == R_AFTERNOON_COOLING
    assert (
        adjust(
            _params(),
            _home(have_solar=True, generation=6000, battery_discharge=500),
            CachedState(),
        ).reason
        == R_AFTERNOON_COOLING
    )

    running = _home(
        aircon_mode=AirconMode.COOL,
        battery_discharge=500,
        afternoon_forecast_recovery=False,
    )
    continued = adjust(_params(), running, state)
    assert continued.output is HomeOutput.NO_CHANGE
    assert continued.reason == R_AFTERNOON_COOLING


def test_home_below_reserve_cannot_start_battery_top_up() -> None:
    result = adjust(_params(), _home(battery_soc=39.9), CachedState())

    assert result.output is HomeOutput.OFF
    assert result.reason == R_AFTERNOON_RESERVE


def test_top_up_does_not_start_at_its_stop_temperature() -> None:
    result = adjust(_params(), _home(temperature=24), CachedState())

    assert result.output is HomeOutput.OFF
    assert result.reason != R_AFTERNOON_COOLING


def test_temporary_battery_dip_requires_forecast_recovery() -> None:
    state = CachedState(last=HomeOutput.COOL, afternoon_run_authorized=True)
    running = _home(
        aircon_mode=AirconMode.COOL,
        battery_discharge=500,
        afternoon_forecast_recovery=False,
    )

    result = adjust(_params(), running, state)

    assert result.output is HomeOutput.OFF
    assert result.reason == R_AFTERNOON_NO_RECOVERY


def test_recovery_dip_cannot_exceed_paid_power_tolerance() -> None:
    state = CachedState(last=HomeOutput.COOL, afternoon_run_authorized=True)
    running = _home(
        aircon_mode=AirconMode.COOL,
        battery_discharge=500,
        afternoon_forecast_recovery=True,
    )

    first = adjust(_params(), running, state)
    second = adjust(_params(), running, state)

    assert first.output is HomeOutput.NO_CHANGE
    assert first.reason == R_BATTERY_TOLERATED
    assert second.output is HomeOutput.OFF
    assert second.reason == R_BATTERY_ENGAGED
    assert state.afternoon_battery_run is False


def test_explicit_away_battery_run_uses_legacy_reserve_policy() -> None:
    state = CachedState(
        last=HomeOutput.COOL,
        battery_run_authorized=True,
        afternoon_run_authorized=True,
    )
    result = adjust(
        _params(),
        _home(
            aircon_mode=AirconMode.COOL,
            someone_home=False,
            battery_soc=99,
            battery_discharge=500,
            allow_away_battery_cooling=True,
            afternoon_forecast_recovery=False,
        ),
        state,
    )

    assert result.output is HomeOutput.NO_CHANGE
    assert result.reason == "Battery-authorised cooling"


def test_afternoon_dry_conversion_fails_closed_on_missing_live_power() -> None:
    result = adjust(
        _params(dry_mode_enabled=False),
        _home(
            aircon_mode=AirconMode.DRY,
            have_solar=True,
            generation=6000,
            grid_available=False,
        ),
        CachedState(last=HomeOutput.DRY, afternoon_run_authorized=True),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_AFTERNOON_POWER_UNAVAILABLE


def test_waiting_dry_run_fails_closed_before_mode_conversion() -> None:
    result = adjust(
        _params(dry_mode_enabled=False),
        _home(
            aircon_mode=AirconMode.DRY,
            have_solar=True,
            generation=6000,
            afternoon_window_open=False,
            afternoon_start_allowed=False,
            grid_available=False,
        ),
        CachedState(last=HomeOutput.DRY),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_AFTERNOON_POWER_UNAVAILABLE


@pytest.mark.parametrize(
    ("forecast_available", "window_open", "reason"),
    [
        (False, True, R_AFTERNOON_FORECAST_UNAVAILABLE),
        (True, False, R_AFTERNOON_WINDOW_CLOSED),
    ],
)
def test_battery_run_stops_when_forecast_window_is_invalidated(
    forecast_available: bool, window_open: bool, reason: str
) -> None:
    result = adjust(
        _params(),
        _home(
            aircon_mode=AirconMode.COOL,
            afternoon_forecast_available=forecast_available,
            afternoon_window_open=window_open,
        ),
        CachedState(
            last=HomeOutput.COOL,
            afternoon_run_authorized=True,
            afternoon_battery_run=True,
        ),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == reason


def test_afternoon_grid_import_stops_immediately() -> None:
    result = adjust(
        _params(),
        _home(
            aircon_mode=AirconMode.COOL,
            grid_usage=100,
            afternoon_forecast_recovery=True,
        ),
        CachedState(last=HomeOutput.COOL, afternoon_run_authorized=True),
    )

    assert result.output is HomeOutput.OFF
    assert result.reason == R_GRID_TOO_HIGH


def test_battery_run_stops_at_reserve_or_24_degrees() -> None:
    state = CachedState(
        last=HomeOutput.COOL,
        afternoon_run_authorized=True,
        afternoon_battery_run=True,
    )
    reserve = adjust(_params(), _home(aircon_mode=AirconMode.COOL, battery_soc=39), state)
    assert reserve.output is HomeOutput.OFF
    assert reserve.reason == R_AFTERNOON_RESERVE

    state = CachedState(
        last=HomeOutput.COOL,
        afternoon_run_authorized=True,
        afternoon_battery_run=True,
    )
    target = adjust(_params(), _home(aircon_mode=AirconMode.COOL, temperature=24), state)
    assert target.output is HomeOutput.OFF
    assert target.reason == R_AFTERNOON_TARGET


def test_battery_run_stops_if_camille_leaves_or_window_closes() -> None:
    state = CachedState(
        last=HomeOutput.COOL,
        afternoon_run_authorized=True,
        afternoon_battery_run=True,
    )
    departed = adjust(
        _params(),
        _home(aircon_mode=AirconMode.COOL, someone_home=False),
        state,
    )
    assert departed.reason == R_AFTERNOON_OCCUPANCY

    state = CachedState(
        last=HomeOutput.COOL,
        afternoon_run_authorized=True,
        afternoon_battery_run=True,
    )
    closed = adjust(
        _params(),
        _home(aircon_mode=AirconMode.COOL, afternoon_planning=False),
        state,
    )
    assert closed.output is HomeOutput.OFF
    assert closed.reason == R_AFTERNOON_WINDOW_CLOSED


def test_forecast_parser_uses_period_energy() -> None:
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    periods = HomeRulesCoordinator._forecast_periods(
        {
            "wh_period": {
                "2026-11-27T15:00:00+11:00": 5500,
                "2026-11-27T16:00:00+11:00": 1000,
                "2026-11-27T17:00:00+11:00": 0,
            }
        }
    )

    assert periods == [
        (
            datetime(2026, 11, 27, 15, tzinfo=timezone(timedelta(hours=11))),
            datetime(2026, 11, 27, 16, tzinfo=timezone(timedelta(hours=11))),
            5.5,
        ),
        (
            datetime(2026, 11, 27, 16, tzinfo=timezone(timedelta(hours=11))),
            datetime(2026, 11, 27, 17, tzinfo=timezone(timedelta(hours=11))),
            1.0,
        ),
        (
            datetime(2026, 11, 27, 17, tzinfo=timezone(timedelta(hours=11))),
            datetime(2026, 11, 27, 18, tzinfo=timezone(timedelta(hours=11))),
            0.0,
        ),
    ]


def test_latest_window_is_latest_complete_window() -> None:
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    tz = timezone(timedelta(hours=11))
    periods = [
        (datetime(2026, 11, 27, 14, tzinfo=tz), datetime(2026, 11, 27, 15, tzinfo=tz), 7.0),
        (datetime(2026, 11, 27, 15, tzinfo=tz), datetime(2026, 11, 27, 16, tzinfo=tz), 2.0),
        (datetime(2026, 11, 27, 16, tzinfo=tz), datetime(2026, 11, 27, 17, tzinfo=tz), 6.5),
    ]

    window = HomeRulesCoordinator._latest_afternoon_window(
        datetime(2026, 11, 27, 14, tzinfo=tz),
        datetime(2026, 11, 27, 17, tzinfo=tz),
        periods,
        6.1,
    )

    assert window is not None
    assert window[0].hour == 16
    assert window[1].hour == 17
    assert window[2] == 6.5

    partial = HomeRulesCoordinator._latest_afternoon_window(
        datetime(2026, 11, 27, 14, 1, tzinfo=tz),
        datetime(2026, 11, 27, 17, tzinfo=tz),
        periods,
        6.1,
    )
    assert partial is not None
    assert partial[0].hour == 16

    no_full_window = HomeRulesCoordinator._latest_afternoon_window(
        datetime(2026, 11, 27, 16, 45, tzinfo=tz),
        datetime(2026, 11, 27, 17, tzinfo=tz),
        periods,
        6.1,
    )
    assert no_full_window is None


@pytest.mark.asyncio
async def test_coordinator_reads_cached_forecast_response(hass, coord_factory, freezer) -> None:
    from custom_components.home_rules.const import (
        CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID,
        CONF_AFTERNOON_READY_BY,
    )

    calls: list[str] = []

    async def get_forecast(call) -> dict[str, dict[str, float]]:
        calls.append(call.data["config_entry"])
        return {
            "watts": {
                "2026-11-27T15:00:00+00:00": 2000,
                "2026-11-27T16:00:00+00:00": 6500,
            },
            "wh_period": {
                "2026-11-27T15:00:00+00:00": 2000,
                "2026-11-27T16:00:00+00:00": 6500,
            },
        }

    hass.services.async_register(
        "forecast_solar",
        "get_forecast",
        get_forecast,
        supports_response=SupportsResponse.ONLY,
    )
    from homeassistant.util import dt as dt_util

    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    freezer.move_to("2026-11-27 16:00:00+00:00")
    coordinator = await coord_factory(
        options={
            CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID: "forecast-entry",
            CONF_AFTERNOON_READY_BY: "17:00:00",
        }
    )
    coordinator.afternoon_cooling_enabled = True

    context = await coordinator._afternoon_context(coordinator.parameters)

    assert calls == ["forecast-entry"]
    assert context.planning
    assert context.window_open
    assert context.forecast_recovery
    assert context.window_energy == 6.5
    assert context.window_start == "2026-11-27T16:00:00+00:00"


@pytest.mark.asyncio
async def test_selected_window_tolerates_one_poll_of_jitter(hass, coord_factory, freezer) -> None:
    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.const import CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID

    async def get_forecast(call) -> dict[str, dict[str, float]]:
        return {
            "watts": {"2026-11-27T16:00:00+00:00": 6500},
            "wh_period": {"2026-11-27T16:00:00+00:00": 6500},
        }

    hass.services.async_register(
        "forecast_solar",
        "get_forecast",
        get_forecast,
        supports_response=SupportsResponse.ONLY,
    )
    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    freezer.move_to("2026-11-27 15:59:59+00:00")
    coordinator = await coord_factory(options={CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID: "forecast-entry"})
    coordinator.afternoon_cooling_enabled = True

    planned = await coordinator._afternoon_context(coordinator.parameters)
    assert planned.window_start == "2026-11-27T16:00:00+00:00"
    assert not planned.window_open

    freezer.move_to("2026-11-27 16:00:30+00:00")
    opened = await coordinator._afternoon_context(coordinator.parameters)

    assert opened.window_open
    assert opened.start_allowed


@pytest.mark.asyncio
async def test_monitor_records_battery_top_up_without_climate_call(hass, coord_factory, freezer) -> None:
    from custom_components.home_rules.const import (
        CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID,
        CONF_AFTERNOON_READY_BY,
        CONF_BATTERY_POWER_ENTITY_ID,
        CONF_BATTERY_SOC_ENTITY_ID,
        CONF_OCCUPANCY_ENTITY_ID,
    )

    async def get_forecast(call) -> dict[str, dict[str, float]]:
        return {
            "watts": {"2026-11-27T16:00:00+00:00": 6500},
            "wh_period": {"2026-11-27T16:00:00+00:00": 6500},
        }

    hass.services.async_register(
        "forecast_solar",
        "get_forecast",
        get_forecast,
        supports_response=SupportsResponse.ONLY,
    )
    from homeassistant.util import dt as dt_util

    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    hass.states.async_set("sensor.battery", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("person.camille", "home")
    freezer.move_to("2026-11-27 16:00:00+00:00")
    coordinator = await coord_factory(
        generation="0",
        options={
            CONF_BATTERY_POWER_ENTITY_ID: "sensor.battery",
            CONF_BATTERY_SOC_ENTITY_ID: "sensor.battery_soc",
            CONF_OCCUPANCY_ENTITY_ID: "person.camille",
            CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID: "forecast-entry",
            CONF_AFTERNOON_READY_BY: "17:00:00",
        },
    )
    coordinator.afternoon_cooling_enabled = True

    await coordinator.async_run_evaluation()

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator.last_evaluation["dry_run"] is True
    assert coordinator.last_evaluation["target_temperature"] == 24
    assert coordinator.last_evaluation["afternoon_forecast_recovery"] is True


@pytest.mark.asyncio
async def test_battery_top_up_preserves_adjusted_target(hass, coord_factory, freezer) -> None:
    from custom_components.home_rules.const import (
        CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID,
        CONF_BATTERY_POWER_ENTITY_ID,
        CONF_BATTERY_SOC_ENTITY_ID,
        CONF_OCCUPANCY_ENTITY_ID,
        ControlMode,
    )

    async def get_forecast(call) -> dict[str, dict[str, float]]:
        return {
            "watts": {"2026-11-27T16:00:00+00:00": 6500},
            "wh_period": {"2026-11-27T16:00:00+00:00": 6500},
        }

    hass.services.async_register(
        "forecast_solar",
        "get_forecast",
        get_forecast,
        supports_response=SupportsResponse.ONLY,
    )
    targets: list[float] = []

    async def set_temperature(call) -> None:
        targets.append(call.data["temperature"])

    async def set_hvac_mode(call) -> None:
        return None

    hass.services.async_register("climate", "set_temperature", set_temperature)
    hass.services.async_register("climate", "set_hvac_mode", set_hvac_mode)
    hass.states.async_set("sensor.battery", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.battery_soc", "60", {"unit_of_measurement": "%"})
    hass.states.async_set("person.camille", "home")
    from homeassistant.util import dt as dt_util

    dt_util.set_default_time_zone(ZoneInfo("UTC"))
    freezer.move_to("2026-11-27 16:00:00+00:00")
    coordinator = await coord_factory(
        climate="cool",
        generation="0",
        options={
            CONF_BATTERY_POWER_ENTITY_ID: "sensor.battery",
            CONF_BATTERY_SOC_ENTITY_ID: "sensor.battery_soc",
            CONF_OCCUPANCY_ENTITY_ID: "person.camille",
            CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID: "forecast-entry",
        },
    )
    coordinator.afternoon_cooling_enabled = True
    coordinator.only_cool_when_home = True
    coordinator._auto_mode = True
    hass.states.async_set("climate.test", "cool", {"temperature": 22})
    await hass.async_block_till_done()
    coordinator._adjusted_setpoint = 26
    coordinator._session.last = HomeOutput.COOL
    coordinator._session.afternoon_run_authorized = True
    coordinator._session.afternoon_battery_run = True
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)

    await coordinator.async_run_evaluation()

    assert targets == [26], coordinator.last_evaluation
