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
    explain,
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


def test_adjust_disabled_last_anything_returns_disabled():
    state = CachedState(last=HomeOutput.NO_CHANGE)
    assert adjust(TEST_PARAMS, default_input(enabled=False), state) is HomeOutput.DISABLED


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
    home = default_input(
        temperature=TEST_PARAMS.temperature_threshold - 0.1,
        generation=TEST_PARAMS.generation_cool_threshold,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_reactivation_delay_blocks_start():
    state = CachedState(reactivate_delay=2)
    home = default_input(
        temperature=TEST_PARAMS.temperature_threshold,
        generation=TEST_PARAMS.generation_cool_threshold,
    )
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


def test_auto_cool_grid_usage_aggressive_still_allows_dry():
    state = CachedState()
    home = default_input(
        aggressive_cooling=True,
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
    home = default_input(
        aircon_mode=AirconMode.COOL,
        have_solar=False,
        generation=TEST_PARAMS.generation_cool_threshold,
        auto=True,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.OFF


def test_auto_cool_generation_low_but_power_free_no_change():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, auto=True, generation=0.0, grid_usage=0.0)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_auto_cool_power_free_humidity_rises_downgrade_to_dry():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.COOL,
        auto=True,
        generation=TEST_PARAMS.generation_cool_threshold,
        humidity=TEST_PARAMS.humidity_threshold + 1,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_auto_cool_generation_above_cool_threshold_but_grid_usage_turns_on_dry():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.COOL,
        auto=True,
        grid_usage=0.1,
        generation=TEST_PARAMS.generation_cool_threshold,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_auto_cool_power_free_but_between_thresholds_downgrade_to_dry():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, auto=True, generation=TEST_PARAMS.generation_dry_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY


def test_auto_dry_no_grid_usage_no_change():
    state = CachedState()
    home = default_input(
        generation=TEST_PARAMS.generation_cool_threshold - 1,
        aircon_mode=AirconMode.DRY,
        auto=True,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


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


def test_auto_dry_aggressive_upgrades_to_cool_even_if_humid():
    state = CachedState()
    home = default_input(
        aggressive_cooling=True,
        aircon_mode=AirconMode.DRY,
        auto=True,
        generation=TEST_PARAMS.generation_cool_threshold,
        humidity=TEST_PARAMS.humidity_threshold + 1,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_auto_dry_aggressive_will_not_switch_to_dry_when_power_free():
    state = CachedState()
    home = default_input(
        aggressive_cooling=True,
        aircon_mode=AirconMode.DRY,
        auto=True,
        generation=TEST_PARAMS.generation_dry_threshold,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_manual_cool_no_change_if_no_grid_usage():
    state = CachedState()
    home = default_input(generation=TEST_PARAMS.generation_cool_threshold, aircon_mode=AirconMode.COOL)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_manual_cool_grid_usage_sets_timer():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.TIMER


def test_manual_cool_no_solar_sets_timer():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, have_solar=False)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.TIMER


def test_manual_cool_grid_usage_with_timer_active_no_change():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1, timer=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_when_off_and_timer_active_do_not_reset():
    state = CachedState(last=HomeOutput.TIMER)
    home = default_input(timer=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE


def test_scenario_interrupt_automations_from_house():
    state = CachedState()
    home = default_input(generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL
    assert state.tolerated == 0
    assert state.reactivate_delay == 0

    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=1, auto=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.tolerated == 1
    assert state.reactivate_delay == 0


def test_scenario_grid_usage_when_dry_above_dry_threshold_turns_off_after_delay():
    state = CachedState()
    home = default_input(
        aircon_mode=AirconMode.DRY,
        auto=True,
        generation=TEST_PARAMS.generation_dry_threshold,
        grid_usage=0.1,
        humidity=TEST_PARAMS.humidity_threshold - 1,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.tolerated == 1
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.OFF
    assert state.tolerated == 0
    assert state.reactivate_delay == TEST_PARAMS.reactivate_delay


def test_manual_heat_cool_grid_usage_sets_timer():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.HEAT_COOL, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.TIMER


def test_manual_auto_grid_usage_sets_timer():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.AUTO, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.TIMER


def test_auto_heat_cool_with_grid_usage_tolerate_then_turn_off():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.HEAT_COOL, auto=True, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE
    assert state.tolerated == 1
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.OFF
    assert state.tolerated == 0
    assert state.reactivate_delay == TEST_PARAMS.reactivate_delay


def test_scenario_morning_ramp_up_off_to_dry_to_cool():
    state = CachedState()
    home = default_input(generation=TEST_PARAMS.generation_dry_threshold - 1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE

    home = default_input(generation=TEST_PARAMS.generation_dry_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY

    home = default_input(aircon_mode=AirconMode.DRY, auto=True, generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_scenario_cloud_passing_cool_downgrades_then_recovers():
    state = CachedState()
    home = default_input(aircon_mode=AirconMode.COOL, auto=True, generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE

    home = default_input(
        aircon_mode=AirconMode.COOL,
        auto=True,
        generation=TEST_PARAMS.generation_cool_threshold,
        grid_usage=0.1,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY
    assert state.tolerated == 0

    home = default_input(aircon_mode=AirconMode.DRY, auto=True, generation=TEST_PARAMS.generation_cool_threshold)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.COOL


def test_scenario_timer_lifecycle_manual_to_timer_to_reset():
    state = CachedState()

    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.TIMER
    assert apply_adjustment(state, HomeOutput.COOL, HomeOutput.TIMER)

    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1, timer=True)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE

    home = default_input(timer=False)
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.RESET


def test_scenario_aggressive_cooling_deactivates_when_grid_appears():
    state = CachedState()

    home = default_input(
        aggressive_cooling=True,
        aircon_mode=AirconMode.COOL,
        auto=True,
        generation=TEST_PARAMS.generation_cool_threshold,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.NO_CHANGE

    home = default_input(
        aggressive_cooling=True,
        aircon_mode=AirconMode.COOL,
        auto=True,
        generation=TEST_PARAMS.generation_dry_threshold,
        grid_usage=0.1,
    )
    assert adjust(TEST_PARAMS, home, state) is HomeOutput.DRY
    assert state.tolerated == 0


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
    assert current_state(default_input(aircon_mode=AirconMode.AUTO)) is HomeOutput.COOL
    assert current_state(default_input(aircon_mode=AirconMode.HEAT)) is HomeOutput.COOL
    assert current_state(default_input(aircon_mode=AirconMode.FAN_ONLY)) is HomeOutput.COOL
    assert current_state(default_input(aircon_mode=AirconMode.UNKNOWN)) is HomeOutput.OFF
    assert current_state(default_input(timer=True, aircon_mode=AirconMode.OFF)) is HomeOutput.OFF


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


def test_apply_adjustment_fails_after_allowed_failures() -> None:
    session = CachedState(last=HomeOutput.COOL, failed_to_change=2)
    assert apply_adjustment(session, HomeOutput.OFF, HomeOutput.COOL)
    assert session.failed_to_change == 3
    assert not apply_adjustment(session, HomeOutput.OFF, HomeOutput.COOL)
    assert session.failed_to_change == 4


# --- explain() label tests ---


def test_explain_manual_no_timer():
    """Manual mode on grid → reason is just 'Manual'."""
    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1, timer=False)
    assert explain(TEST_PARAMS, home, CachedState()) == "Manual"


def test_explain_manual_timer_active():
    """Manual mode with timer already running → 'No change'."""
    home = default_input(aircon_mode=AirconMode.COOL, grid_usage=0.1, timer=True)
    assert explain(TEST_PARAMS, home, CachedState()) == "No change"


def test_explain_timer_expired():
    """Timer expired while aircon off → 'Timer expired'."""
    home = default_input(timer=False)
    assert explain(TEST_PARAMS, home, CachedState(last=HomeOutput.TIMER)) == "Timer expired"


def test_explain_grid_usage_too_high():
    """Auto mode, grid usage exceeded delay → 'Grid usage too high'."""
    home = default_input(aircon_mode=AirconMode.COOL, auto=True, grid_usage=100.0, generation=0.0)
    state = CachedState(tolerated=TEST_PARAMS.grid_usage_delay - 1)
    assert explain(TEST_PARAMS, home, state) == "Grid usage too high"


def test_explain_grid_usage_tolerated():
    """Auto mode, grid usage within tolerance → 'Grid usage tolerated'."""
    home = default_input(aircon_mode=AirconMode.COOL, auto=True, grid_usage=100.0, generation=0.0)
    assert explain(TEST_PARAMS, home, CachedState(tolerated=0)) == "Grid usage tolerated"


def test_explain_disabled():
    assert explain(TEST_PARAMS, default_input(enabled=False), CachedState()) == "Disabled"


def test_explain_auto_idle():
    home = default_input(auto=True, generation=0.0)
    assert explain(TEST_PARAMS, home, CachedState()) == "Auto idle"
