"""Decision-engine parity tests for Home Rules."""

from __future__ import annotations

from custom_components.home_rules.rules import (
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    RuleParameters,
    adjust,
    apply_adjustment,
    current_state,
)

TEST_PARAMS = RuleParameters(
    generation_cool_threshold=5500,
    generation_dry_threshold=3500,
    temperature_threshold=24,
    humidity_threshold=65,
    grid_usage_delay=2,
    reactivate_delay=2,
    temperature_cool=23,
)


def default_input(**overrides):
    data = {
        "aircon_mode": AirconMode.OFF,
        "timer": False,
        "have_solar": True,
        "generation": 0.0,
        "grid_usage": 0.0,
        "auto": False,
        "aggressive_cooling": False,
        "temperature": TEST_PARAMS.temperature_threshold,
        "humidity": TEST_PARAMS.humidity_threshold,
        "enabled": True,
        "cooling_enabled": True,
    }
    data.update(overrides)
    return HomeInput(**data)


def test_adjust_disabled_state():
    state = CachedState()
    home = default_input(enabled=False, grid_usage=0.1, aircon_mode=AirconMode.COOL, auto=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DISABLED


def test_adjust_disabled_resets_tolerated():
    state = CachedState(tolerated=5)
    assert adjust(TEST_PARAMS, default_input(enabled=False), state) is HomeOutput.DISABLED
    assert state.tolerated == 0


def test_adjust_disabled_last_disabled_returns_no_change():
    state = CachedState(last=HomeOutput.DISABLED)
    assert adjust(TEST_PARAMS, default_input(enabled=False), state) is HomeOutput.NO_CHANGE


def test_off_no_solar_wont_start():
    state = CachedState()
    home = default_input(have_solar=False, generation=TEST_PARAMS.generation_dry_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_off_can_auto_cool():
    state = CachedState()
    home = default_input(generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_off_prefers_dry_if_humid():
    state = CachedState()
    home = default_input(
        generation=TEST_PARAMS.generation_cool_threshold,
        humidity=TEST_PARAMS.humidity_threshold + 1,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_off_aggressive_ignores_humidity_for_cool():
    state = CachedState()
    home = default_input(
        aggressive_cooling=True,
        generation=TEST_PARAMS.generation_cool_threshold,
        humidity=TEST_PARAMS.humidity_threshold + 10,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_off_can_auto_dry():
    state = CachedState()
    home = default_input(generation=TEST_PARAMS.generation_dry_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_off_aggressive_does_not_switch_to_dry():
    state = CachedState()
    home = default_input(aggressive_cooling=True, generation=TEST_PARAMS.generation_dry_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_off_insufficient_generation():
    state = CachedState()
    home = default_input(generation=TEST_PARAMS.generation_dry_threshold - 1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_off_too_cool_for_activation():
    state = CachedState()
    home = default_input(temperature=TEST_PARAMS.temperature_threshold - 0.1, generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_reactivation_delay_blocks_start():
    state = CachedState(reactivate_delay=2)
    home = default_input(temperature=TEST_PARAMS.temperature_threshold, generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.reactivate_delay == 1
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.reactivate_delay == 0
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_stale_auto_signal_when_off_returns_off():
    state = CachedState(tolerated=5)
    home = default_input(auto=True, temperature=TEST_PARAMS.temperature_threshold - 0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.OFF
    assert state.tolerated == 0


def test_off_cooling_disabled():
    state = CachedState()
    home = default_input(cooling_enabled=False, generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_auto_cool_no_grid_usage_no_change_and_reset_tolerated():
    state = CachedState(tolerated=1)
    home = default_input(generation=TEST_PARAMS.generation_cool_threshold, aircon_mode=AirconMode.COOL, auto=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.tolerated == 0


def test_auto_cool_grid_usage_can_reduce_to_dry():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.COOL,
        grid_usage=0.1,
        generation=TEST_PARAMS.generation_dry_threshold,
        auto=True,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_auto_cool_grid_usage_tolerates_then_off():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.COOL,
        grid_usage=0.1,
        generation=TEST_PARAMS.generation_dry_threshold - 1,
        auto=True,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.tolerated == 1
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.OFF
    assert state.tolerated == 0
    assert state.reactivate_delay == TEST_PARAMS.reactivate_delay


def test_auto_cool_no_solar_tolerates_then_off():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, have_solar=False, generation=TEST_PARAMS.generation_cool_threshold, auto=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.OFF


def test_auto_cool_power_free_but_between_thresholds_downgrade_to_dry():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, auto=True, generation=TEST_PARAMS.generation_dry_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_auto_dry_upgrade_to_cool_when_generation_allows_and_not_humid():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.DRY,
        generation=TEST_PARAMS.generation_cool_threshold,
        humidity=TEST_PARAMS.humidity_threshold,
        auto=True,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_auto_dry_stays_dry_when_humid():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.DRY,
        generation=TEST_PARAMS.generation_cool_threshold,
        humidity=TEST_PARAMS.humidity_threshold + 1,
        auto=True,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_manual_cool_grid_usage_sets_timer():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.TIMER


def test_manual_cool_grid_usage_with_timer_active_no_change():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1, timer=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_unknown_mode_returns_no_change():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.UNKNOWN, auto=True, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_timer_finishes_returns_reset():
    state = CachedState(last=HomeOutput.TIMER, tolerated=5)
    home = default_input(timer=False)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.RESET
    assert state.tolerated == 0


def test_current_state_mapping():
    assert current_state(default_input(enabled=False)) is HomeOutput.DISABLED
    assert current_state(default_input()) is HomeOutput.OFF
    assert current_state(default_input(timer=True, aircon_mode=AirconMode.COOL)) is HomeOutput.TIMER
    assert current_state(default_input(aircon_mode=AirconMode.COOL)) is HomeOutput.COOL
    assert current_state(default_input(aircon_mode=AirconMode.DRY)) is HomeOutput.DRY
    assert current_state(default_input(aircon_mode=AirconMode.HEAT_COOL)) is HomeOutput.COOL
    assert current_state(default_input(aircon_mode=AirconMode.UNKNOWN)) is HomeOutput.OFF


def test_apply_adjustment_behavior():
    session = CachedState(last=HomeOutput.DISABLED, failed_to_change=1)
    assert apply_adjustment(session, HomeOutput.DISABLED, HomeOutput.NO_CHANGE)
    assert session.last is HomeOutput.DISABLED
    assert session.failed_to_change == 0

    session = CachedState(last=HomeOutput.DISABLED)
    assert apply_adjustment(session, HomeOutput.OFF, HomeOutput.RESET)
    assert session.last is HomeOutput.OFF

    session = CachedState(last=None, failed_to_change=1)
    assert apply_adjustment(session, HomeOutput.COOL, HomeOutput.COOL)
    assert session.last is HomeOutput.COOL

    session = CachedState(last=HomeOutput.COOL, failed_to_change=1)
    assert apply_adjustment(session, HomeOutput.COOL, HomeOutput.DRY)
    assert session.last is HomeOutput.DRY

    session = CachedState(last=HomeOutput.COOL, failed_to_change=2)
    assert apply_adjustment(session, HomeOutput.OFF, HomeOutput.COOL)
    assert not apply_adjustment(session, HomeOutput.OFF, HomeOutput.COOL)
