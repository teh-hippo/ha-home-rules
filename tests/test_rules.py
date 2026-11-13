"""Comprehensive tests for the pure rules engine (rules.py).

No Home Assistant dependencies — every branch of _evaluate_target_mode,
current_state, _idle_reason, adjust, and apply_adjustment is covered.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.home_rules.rules import (
    ALLOWED_FAILURES,
    R_ALREADY_COOLING,
    R_ALREADY_DRYING,
    R_AUTO_IDLE,
    R_BELOW_COOL_SETPOINT,
    R_BELOW_THRESHOLD,
    R_COOLING_DISABLED,
    R_DISABLED,
    R_DRY_DISABLED,
    R_GRID_TOLERATED,
    R_GRID_TOO_HIGH,
    R_HUMIDITY_TOO_LOW,
    R_INSUFFICIENT_SOLAR,
    R_INVALID_TEMPERATURE_RANGE,
    R_MANUAL,
    R_NO_CHANGE,
    R_NO_SOLAR,
    R_PAID_POWER,
    R_REACTIVATE_WAIT,
    R_RUN_ON_EXPIRED,
    R_SOLAR_COOL,
    R_SOLAR_DRY,
    R_TARGET_REACHED,
    R_TEMPERATURE_UNAVAILABLE,
    R_TIMER_EXPIRED,
    R_UNKNOWN_MODE,
    AdjustResult,
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    RuleParameters,
    TargetResult,
    _evaluate_target_mode,
    _idle_reason,
    adjust,
    apply_adjustment,
    current_state,
)

OUT = HomeOutput

TEST_PARAMS = RuleParameters(
    generation_cool_threshold=5500,
    generation_dry_threshold=3500,
    temperature_threshold=24,
    dry_mode_humidity_cutoff=65,
    dry_mode_enabled=True,
    grid_usage_delay=2,
    reactivate_delay=2,
    temperature_cool=22,
)


def home(**overrides) -> HomeInput:
    defaults = dict(
        aircon_mode=AirconMode.OFF,
        have_solar=True,
        generation=0.0,
        grid_usage=0.0,
        timer=False,
        temperature=TEST_PARAMS.temperature_threshold,
        humidity=TEST_PARAMS.dry_mode_humidity_cutoff,
        auto=False,
        allow_paid_power=False,
        enabled=True,
        cooling_enabled=True,
    )
    defaults.update(overrides)
    return HomeInput(**defaults)


# ---------------------------------------------------------------------------
# _evaluate_target_mode — all 8 return paths + boundary conditions
# ---------------------------------------------------------------------------


class TestEvaluateTargetMode:
    def test_a_no_solar(self):
        """No have_solar -> None, R_NO_SOLAR, actionable."""
        r = _evaluate_target_mode(TEST_PARAMS, home(have_solar=False))
        assert r == TargetResult(None, R_NO_SOLAR, True)

    def test_c1_solar_cool_not_cool(self):
        """gen>=cool + not COOL -> COOL, R_SOLAR_COOL, actionable."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=5500, humidity=65, aircon_mode=AirconMode.OFF),
        )
        assert r == TargetResult(OUT.COOL, R_SOLAR_COOL, True)

    def test_c2_solar_cool_already_cool(self):
        """gen>=cool + already COOL -> None, R_ALREADY_COOLING."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=5500, humidity=65, aircon_mode=AirconMode.COOL),
        )
        assert r == TargetResult(None, R_ALREADY_COOLING, False)

    def test_d1_solar_dry_not_dry(self):
        """gen>=dry + not DRY -> DRY, R_SOLAR_DRY, actionable."""
        r = _evaluate_target_mode(TEST_PARAMS, home(generation=3500, humidity=66, aircon_mode=AirconMode.OFF))
        assert r == TargetResult(OUT.DRY, R_SOLAR_DRY, True)

    def test_d2_solar_dry_already_dry(self):
        """gen>=dry + already DRY -> None, R_ALREADY_DRYING, not actionable."""
        r = _evaluate_target_mode(TEST_PARAMS, home(generation=3500, humidity=66, aircon_mode=AirconMode.DRY))
        assert r == TargetResult(None, R_ALREADY_DRYING, False)

    def test_d3_solar_dry_disabled(self):
        r = _evaluate_target_mode(
            RuleParameters(**{**TEST_PARAMS.__dict__, "dry_mode_enabled": False}),
            home(generation=3500, humidity=66, aircon_mode=AirconMode.OFF),
        )
        assert r == TargetResult(None, R_DRY_DISABLED, True)

    def test_d4_solar_dry_low_humidity(self):
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=3500, humidity=64, aircon_mode=AirconMode.OFF),
        )
        assert r == TargetResult(None, R_HUMIDITY_TOO_LOW, True)

    def test_e_insufficient_solar(self):
        """gen<dry -> None, R_INSUFFICIENT_SOLAR, not actionable."""
        r = _evaluate_target_mode(TEST_PARAMS, home(generation=3499))
        assert r == TargetResult(None, R_INSUFFICIENT_SOLAR, False)

    # --- Boundary conditions ---

    def test_boundary_gen_exactly_cool_threshold(self):
        """gen exactly == cool_threshold -> COOL (>= check)."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=5500, humidity=60, aircon_mode=AirconMode.OFF),
        )
        assert r.output is OUT.COOL
        assert r.reason == R_SOLAR_COOL

    def test_boundary_gen_exactly_dry_threshold(self):
        """gen exactly == dry_threshold -> DRY (>= check)."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=3500, humidity=66, aircon_mode=AirconMode.OFF),
        )
        assert r.output is OUT.DRY
        assert r.reason == R_SOLAR_DRY

    def test_boundary_humidity_at_threshold_allows_cool(self):
        """humidity exactly == cutoff does not block COOL."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=6000, humidity=65, aircon_mode=AirconMode.OFF),
        )
        assert r.output is OUT.COOL

    def test_boundary_humidity_above_cutoff_still_allows_cool(self):
        """High humidity should not block COOL when solar can support it."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=6000, humidity=66, aircon_mode=AirconMode.OFF),
        )
        assert r.output is OUT.COOL
        assert r.reason == R_SOLAR_COOL


# ---------------------------------------------------------------------------
# current_state — all aircon modes
# ---------------------------------------------------------------------------


class TestCurrentState:
    def test_disabled(self):
        assert current_state(home(enabled=False)) is OUT.DISABLED

    def test_timer_not_off(self):
        assert current_state(home(timer=True, aircon_mode=AirconMode.COOL)) is OUT.TIMER

    def test_timer_but_off_ignored(self):
        """enabled=True + timer=True + OFF -> OFF (timer ignored when off)."""
        assert current_state(home(timer=True, aircon_mode=AirconMode.OFF)) is OUT.OFF

    def test_cool(self):
        assert current_state(home(aircon_mode=AirconMode.COOL)) is OUT.COOL

    def test_dry(self):
        assert current_state(home(aircon_mode=AirconMode.DRY)) is OUT.DRY

    def test_off(self):
        assert current_state(home(aircon_mode=AirconMode.OFF)) is OUT.OFF

    def test_unknown(self):
        assert current_state(home(aircon_mode=AirconMode.UNKNOWN)) is OUT.OFF

    def test_fan_only_maps_to_on(self):
        assert current_state(home(aircon_mode=AirconMode.FAN_ONLY)) is OUT.ON

    def test_heat_maps_to_on(self):
        assert current_state(home(aircon_mode=AirconMode.HEAT)) is OUT.ON

    def test_heat_cool_maps_to_on(self):
        assert current_state(home(aircon_mode=AirconMode.HEAT_COOL)) is OUT.ON

    def test_auto_maps_to_on(self):
        assert current_state(home(aircon_mode=AirconMode.AUTO)) is OUT.ON


# ---------------------------------------------------------------------------
# _idle_reason — priority order
# ---------------------------------------------------------------------------


class TestIdleReason:
    def test_cooling_disabled_highest_priority(self):
        """cooling_enabled=False wins even if other conditions match."""
        r = _idle_reason(
            TEST_PARAMS,
            home(cooling_enabled=False, pre_cooling=True, allow_paid_power=True, temperature=20),
            "activation",
            "default",
        )
        assert r == R_COOLING_DISABLED

    def test_precooling_uses_lower_temperature_target(self):
        r = _idle_reason(
            TEST_PARAMS,
            home(pre_cooling=True, allow_paid_power=True, temperature=20),
            "activation",
            "default",
        )
        assert r == R_BELOW_COOL_SETPOINT

    def test_boost_below_cool_setpoint(self):
        """aggressive + temp <= cool_setpoint -> R_BELOW_COOL_SETPOINT."""
        r = _idle_reason(
            TEST_PARAMS,
            home(allow_paid_power=True, temperature=21),
            None,
            "default",
        )
        assert r == R_BELOW_COOL_SETPOINT

    def test_boost_at_cool_setpoint_boundary(self):
        """temperature == cool_setpoint (<= check) -> R_BELOW_COOL_SETPOINT."""
        r = _idle_reason(
            TEST_PARAMS,
            home(allow_paid_power=True, temperature=22),
            None,
            "default",
        )
        assert r == R_BELOW_COOL_SETPOINT

    def test_below_threshold(self):
        """temp < threshold -> R_BELOW_THRESHOLD."""
        r = _idle_reason(TEST_PARAMS, home(temperature=23.9), None, "default")
        assert r == R_BELOW_THRESHOLD

    def test_activation_returned_when_present(self):
        r = _idle_reason(TEST_PARAMS, home(temperature=24), R_SOLAR_COOL, "default")
        assert r == R_SOLAR_COOL

    def test_default_fallback_when_no_activation(self):
        r = _idle_reason(TEST_PARAMS, home(temperature=24), None, R_AUTO_IDLE)
        assert r == R_AUTO_IDLE

    def test_activation_none_uses_default(self):
        r = _idle_reason(TEST_PARAMS, home(temperature=24), None, R_NO_CHANGE)
        assert r == R_NO_CHANGE


# ---------------------------------------------------------------------------
# adjust — Disabled
# ---------------------------------------------------------------------------


class TestAdjustDisabled:
    def test_first_disable(self):
        """enabled=False, last=None -> DISABLED."""
        state = CachedState()
        r = adjust(TEST_PARAMS, home(enabled=False), state)
        assert r == AdjustResult(OUT.DISABLED, R_DISABLED)

    def test_already_disabled_no_change(self):
        """last=DISABLED + enabled=False -> NO_CHANGE."""
        state = CachedState(last=OUT.DISABLED)
        r = adjust(TEST_PARAMS, home(enabled=False), state)
        assert r == AdjustResult(OUT.NO_CHANGE, R_DISABLED)

    def test_transition_from_other_to_disabled(self):
        """last=COOL + enabled=False -> DISABLED."""
        state = CachedState(last=OUT.COOL)
        r = adjust(TEST_PARAMS, home(enabled=False), state)
        assert r == AdjustResult(OUT.DISABLED, R_DISABLED)

    def test_disabled_resets_tolerated(self):
        state = CachedState(tolerated=5)
        adjust(TEST_PARAMS, home(enabled=False), state)
        assert state.tolerated == 0


# ---------------------------------------------------------------------------
# adjust — Unknown aircon mode
# ---------------------------------------------------------------------------


class TestAdjustUnknown:
    def test_unknown_mode_no_change(self):
        state = CachedState()
        r = adjust(TEST_PARAMS, home(aircon_mode=AirconMode.UNKNOWN), state)
        assert r == AdjustResult(OUT.NO_CHANGE, R_UNKNOWN_MODE)


# ---------------------------------------------------------------------------
# adjust — Reactivation delay
# ---------------------------------------------------------------------------


class TestAdjustReactivateDelay:
    def test_extra_evaluations_do_not_shorten_cooldown(self):
        state = CachedState(reactivate_at=120)
        for now in (0, 0, 1, 10, 119.9):
            assert adjust(TEST_PARAMS, home(generation=6000, now=now), state) == AdjustResult(
                OUT.NO_CHANGE, R_REACTIVATE_WAIT
            )
            assert state.reactivate_at == 120
        assert adjust(TEST_PARAMS, home(generation=6000, now=120), state).output is OUT.COOL

    def test_cooldown_does_not_block_manual_run_or_timer_expiry(self):
        state = CachedState(reactivate_at=120, last=OUT.TIMER)
        running = home(aircon_mode=AirconMode.COOL, auto=False, timer=True)
        assert adjust(TEST_PARAMS, running, state).output is OUT.NO_CHANGE
        assert adjust(TEST_PARAMS, replace(running, timer=False), state).output is OUT.OFF


# ---------------------------------------------------------------------------
# adjust — Aircon OFF, Solar activation
# ---------------------------------------------------------------------------


class TestAdjustOffSolar:
    def test_cool_activation(self):
        """gen>=cool + temp>=threshold -> COOL."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=5500, humidity=65, temperature=24, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_SOLAR_COOL)

    @pytest.mark.parametrize("temperature", [21, 23.9, 24])
    @pytest.mark.parametrize("generation,mode,reason", [(6000, OUT.COOL, R_SOLAR_COOL), (3500, OUT.DRY, R_SOLAR_DRY)])
    def test_precooling_respects_normal_start_temperature(self, temperature, generation, mode, reason):
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=generation, humidity=65, temperature=temperature, pre_cooling=True, auto=True),
            state,
        )
        expected = AdjustResult(mode, reason) if temperature >= 24 else AdjustResult(OUT.OFF, R_BELOW_THRESHOLD)
        assert r == expected

    def test_high_humidity_does_not_block_cool(self):
        """High humidity should not force DRY when COOL solar is available."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=6000, humidity=66, temperature=24, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_SOLAR_COOL)

    def test_dry_activation_gen_above_dry(self):
        """gen>=dry + temp>=threshold -> DRY."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=3500, humidity=66, temperature=24, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.DRY, R_SOLAR_DRY)

    def test_dry_disabled_leaves_auto_idle(self):
        state = CachedState()
        params = RuleParameters(**{**TEST_PARAMS.__dict__, "dry_mode_enabled": False})
        r = adjust(params, home(generation=3500, humidity=66, temperature=24, auto=True), state)
        assert r == AdjustResult(OUT.OFF, R_DRY_DISABLED)

    def test_low_humidity_blocks_dry_activation(self):
        state = CachedState()
        r = adjust(TEST_PARAMS, home(generation=3500, humidity=64, temperature=24, auto=True), state)
        assert r == AdjustResult(OUT.OFF, R_HUMIDITY_TOO_LOW)

    def test_insufficient_solar_no_change(self):
        """gen<dry, auto=False -> NO_CHANGE."""
        state = CachedState()
        r = adjust(TEST_PARAMS, home(generation=2000, temperature=24), state)
        assert r.output is OUT.NO_CHANGE

    def test_no_solar_no_change(self):
        """No solar, auto=False -> NO_CHANGE, R_NO_SOLAR (actionable idle)."""
        state = CachedState()
        r = adjust(TEST_PARAMS, home(have_solar=False, temperature=24), state)
        assert r.output is OUT.NO_CHANGE
        assert r.reason == R_NO_SOLAR

    def test_below_threshold_no_activation(self):
        """temp<threshold -> OFF (auto), reason R_BELOW_THRESHOLD."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=6000, temperature=23, auto=True),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_BELOW_THRESHOLD

    def test_cooling_disabled(self):
        """cooling_enabled=False -> OFF (auto), reason R_COOLING_DISABLED."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=6000, temperature=24, cooling_enabled=False, auto=True),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_COOLING_DISABLED

    def test_auto_insufficient_off_with_idle_reason(self):
        """auto=True + insufficient solar -> OFF, R_AUTO_IDLE."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=1000, temperature=24, auto=True),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_AUTO_IDLE

    def test_manual_last_timer_no_timer_reset(self):
        """auto=False + last=TIMER + no timer -> RESET, R_TIMER_EXPIRED."""
        state = CachedState(last=OUT.TIMER)
        r = adjust(TEST_PARAMS, home(auto=False, timer=False), state)
        assert r == AdjustResult(OUT.RESET, R_TIMER_EXPIRED)

    def test_manual_last_timer_still_active_no_change(self):
        """auto=False + last=TIMER + timer=True -> NO_CHANGE (falls through)."""
        state = CachedState(last=OUT.TIMER)
        r = adjust(TEST_PARAMS, home(auto=False, timer=True), state)
        assert r.output is OUT.NO_CHANGE

    def test_manual_no_conditions_no_change(self):
        """auto=False + no activation conditions -> NO_CHANGE, R_NO_CHANGE."""
        state = CachedState()
        r = adjust(TEST_PARAMS, home(auto=False, generation=2000, temperature=24), state)
        assert r.output is OUT.NO_CHANGE
        assert r.reason == R_NO_CHANGE

    def test_off_resets_tolerated(self):
        state = CachedState(tolerated=5)
        adjust(TEST_PARAMS, home(generation=1000, auto=True), state)
        assert state.tolerated == 0


# ---------------------------------------------------------------------------
# adjust — Paid-power policy cannot authorise fresh starts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("generation", "grid", "discharge"),
    [(0, 0, 0), (1, 0, 0), (500, 0, 0), (6000, 500, 0), (6000, 0, 300)],
)
def test_run_on_policy_never_starts_on_paid_power(generation, grid, discharge):
    state = CachedState(solar_run_eligible=True, solar_lost_at=0)
    result = adjust(
        TEST_PARAMS,
        home(
            allow_paid_power=True,
            generation=generation,
            have_solar=generation > 0,
            grid_usage=grid,
            battery_discharge=discharge,
        ),
        state,
    )
    assert result.output is OUT.NO_CHANGE
    assert not state.solar_run_eligible
    assert state.solar_lost_at is None


# ---------------------------------------------------------------------------
# adjust — Aircon ON, grid draw, auto mode (solar)
# ---------------------------------------------------------------------------


class TestAdjustOnGridAutoSolar:
    def test_already_cool_gen_above_cool_falls_to_tolerance(self):
        """Already COOL + gen>=cool + grid>0 -> tolerance (target is None)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=5500,
                humidity=60,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r.output is OUT.NO_CHANGE
        assert r.reason == R_GRID_TOLERATED
        assert state.tolerated == 1

    def test_already_cool_gen_insufficient_tolerance_then_off(self):
        """Already COOL + gen<dry + grid>0 -> tolerance cycles then OFF."""
        state = CachedState()
        h = home(
            aircon_mode=AirconMode.COOL,
            generation=2000,
            grid_usage=100,
            auto=True,
        )
        r1 = adjust(TEST_PARAMS, h, state)
        assert r1 == AdjustResult(OUT.NO_CHANGE, R_GRID_TOLERATED)
        assert state.tolerated == 1

        r2 = adjust(TEST_PARAMS, h, state)
        assert r2 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)
        assert state.tolerated == 0
        assert state.reactivate_at == TEST_PARAMS.reactivate_delay * 60

    def test_dry_upgrade_to_cool_on_grid(self):
        """DRY + gen>=cool + humid<=thresh + grid>0 -> upgrade to COOL immediately."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.DRY,
                generation=6000,
                humidity=60,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_SOLAR_COOL)
        assert state.tolerated == 1

    def test_tolerance_counter_below_delay(self):
        """Tolerance counter < delay -> NO_CHANGE R_GRID_TOLERATED."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=2000,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r.reason == R_GRID_TOLERATED
        assert state.tolerated == 1

    def test_tolerance_exceeded_off(self):
        """Tolerance counter >= delay -> OFF R_GRID_TOO_HIGH."""
        state = CachedState(tolerated=1)
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=2000,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)
        assert state.reactivate_at == TEST_PARAMS.reactivate_delay * 60


# ---------------------------------------------------------------------------
# adjust — Aircon ON, grid draw, auto mode (boost)
# ---------------------------------------------------------------------------


class TestSolarRunOn:
    @pytest.mark.parametrize("mode", [AirconMode.COOL, AirconMode.DRY])
    @pytest.mark.parametrize("minutes", [15, 60])
    def test_solar_started_run_keeps_its_mode_until_fixed_deadline(self, mode, minutes):
        params = replace(TEST_PARAMS, solar_run_on_minutes=minutes)
        state = CachedState()
        start = home(allow_paid_power=True, generation=6000 if mode is AirconMode.COOL else 4000, now=100)
        assert adjust(params, start, state).output is (OUT.COOL if mode is AirconMode.COOL else OUT.DRY)
        running = replace(start, aircon_mode=mode, auto=True, have_solar=False, generation=0, grid_usage=500, now=200)
        deadline = 200 + params.grid_usage_delay * params.evaluation_interval + minutes * 60
        for now in (200, 201, deadline - 0.1):
            assert adjust(params, replace(running, now=now), state) == AdjustResult(OUT.NO_CHANGE, R_PAID_POWER)
            assert state.solar_lost_at == 200
        assert adjust(params, replace(running, now=deadline), state) == AdjustResult(OUT.OFF, R_RUN_ON_EXPIRED)
        assert state.reactivate_at == deadline + params.reactivate_delay * 60
        assert not state.solar_run_eligible

    def test_unqualified_automatic_run_cannot_gain_an_allowance_overnight(self):
        state = CachedState()
        running = home(aircon_mode=AirconMode.COOL, auto=True, allow_paid_power=True, have_solar=False, grid_usage=500)
        assert adjust(TEST_PARAMS, running, state).reason == R_GRID_TOLERATED
        assert adjust(TEST_PARAMS, running, state).output is OUT.OFF

    def test_sustained_solar_recovery_is_required_to_reset_allowance(self):
        state = CachedState(solar_run_eligible=True)
        running = home(aircon_mode=AirconMode.COOL, auto=True, allow_paid_power=True, generation=100, grid_usage=500)
        adjust(TEST_PARAMS, running, state)
        recovered = replace(running, generation=6000, grid_usage=0, now=100)
        adjust(TEST_PARAMS, recovered, state)
        adjust(TEST_PARAMS, replace(running, now=101), state)
        assert state.solar_lost_at == 0
        assert state.solar_recovered_at is None

        adjust(TEST_PARAMS, replace(recovered, now=200), state)
        adjust(
            TEST_PARAMS,
            replace(recovered, now=200 + TEST_PARAMS.grid_usage_delay * TEST_PARAMS.evaluation_interval),
            state,
        )
        assert state.solar_lost_at is None
        adjust(TEST_PARAMS, replace(running, now=1000), state)
        assert state.solar_lost_at == 1000

    def test_zero_allowance_uses_solar_only_tolerance(self):
        params = replace(TEST_PARAMS, solar_run_on_minutes=0)
        running = home(aircon_mode=AirconMode.COOL, auto=True, allow_paid_power=True, have_solar=False)
        state = CachedState(solar_run_eligible=True)
        assert adjust(params, running, state).reason == R_GRID_TOLERATED
        assert adjust(params, running, state).output is OUT.OFF

    def test_manual_run_uses_its_timer_instead_of_solar_allowance(self):
        state = CachedState(solar_run_eligible=True)
        running = home(aircon_mode=AirconMode.COOL, allow_paid_power=True, have_solar=False)
        assert adjust(TEST_PARAMS, running, state) == AdjustResult(OUT.TIMER, R_MANUAL)
        assert not state.solar_run_eligible


# ---------------------------------------------------------------------------
# adjust — Aircon ON, grid draw, manual mode
# ---------------------------------------------------------------------------


class TestAdjustOnGridManual:
    def test_timer_active_no_change(self):
        """Manual + timer active -> NO_CHANGE."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                grid_usage=100,
                timer=True,
                auto=False,
            ),
            state,
        )
        assert r == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)

    def test_timer_expired_off(self):
        """last=TIMER + timer expired -> OFF R_TIMER_EXPIRED."""
        state = CachedState(last=OUT.TIMER)
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                grid_usage=100,
                timer=False,
                auto=False,
            ),
            state,
        )
        assert r == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)

    def test_no_timer_starts_timer(self):
        """No timer -> TIMER R_MANUAL."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                grid_usage=100,
                timer=False,
                auto=False,
            ),
            state,
        )
        assert r == AdjustResult(OUT.TIMER, R_MANUAL)

    def test_fan_only_with_grid_starts_timer(self):
        """FAN_ONLY + grid -> TIMER R_MANUAL."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.FAN_ONLY, grid_usage=100, auto=False),
            state,
        )
        assert r == AdjustResult(OUT.TIMER, R_MANUAL)


# ---------------------------------------------------------------------------
# adjust — Aircon ON, free solar
# ---------------------------------------------------------------------------


class TestAdjustOnFreeSolar:
    def test_auto_target_available_applies(self):
        """Auto + target available -> apply target (DRY upgrades to COOL)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.DRY,
                generation=6000,
                humidity=60,
                grid_usage=0,
                auto=True,
            ),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_SOLAR_COOL)
        assert state.tolerated == 0

    def test_auto_no_target_no_change(self):
        """Auto + no target (already cooling) -> NO_CHANGE."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=6000,
                humidity=60,
                grid_usage=0,
                auto=True,
            ),
            state,
        )
        assert r.output is OUT.NO_CHANGE
        assert r.reason == R_NO_CHANGE

    def test_manual_no_change(self):
        """Not auto -> NO_CHANGE R_NO_CHANGE."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=6000,
                humidity=60,
                grid_usage=0,
                auto=False,
            ),
            state,
        )
        assert r == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)

    def test_free_solar_resets_tolerated(self):
        """Auto free solar path resets tolerated counter."""
        state = CachedState(tolerated=5)
        adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=6000,
                humidity=60,
                grid_usage=0,
                auto=True,
            ),
            state,
        )
        assert state.tolerated == 0


# ---------------------------------------------------------------------------
# apply_adjustment
# ---------------------------------------------------------------------------


class TestApplyAdjustment:
    def test_no_change_resets_counter(self):
        session = CachedState(failed_to_change=5)
        result = apply_adjustment(session, OUT.COOL, OUT.NO_CHANGE)
        assert result is True
        assert session.failed_to_change == 0

    def test_no_change_preserves_last(self):
        session = CachedState(last=OUT.COOL, failed_to_change=3)
        apply_adjustment(session, OUT.DRY, OUT.NO_CHANGE)
        assert session.last is OUT.COOL

    def test_reset_sets_last_to_current(self):
        session = CachedState(last=OUT.OFF, failed_to_change=3)
        result = apply_adjustment(session, OUT.COOL, OUT.RESET)
        assert result is True
        assert session.last is OUT.COOL
        assert session.failed_to_change == 0

    def test_reset_from_none(self):
        session = CachedState(last=None)
        result = apply_adjustment(session, OUT.COOL, OUT.RESET)
        assert result is True
        assert session.last is OUT.COOL

    def test_new_adjustment_sets_last(self):
        """last != adjustment -> set last, reset counter, return True."""
        session = CachedState(last=OUT.OFF)
        result = apply_adjustment(session, OUT.COOL, OUT.COOL)
        assert result is True
        assert session.last is OUT.COOL
        assert session.failed_to_change == 0

    def test_new_adjustment_from_none(self):
        """last=None -> set last, return True."""
        session = CachedState(last=None)
        result = apply_adjustment(session, OUT.OFF, OUT.COOL)
        assert result is True
        assert session.last is OUT.COOL

    def test_same_adjustment_increments_failure(self):
        session = CachedState(last=OUT.COOL, failed_to_change=0)
        result = apply_adjustment(session, OUT.OFF, OUT.COOL)
        assert result is True
        assert session.failed_to_change == 1

    def test_at_allowed_failures_returns_true(self):
        session = CachedState(last=OUT.COOL, failed_to_change=ALLOWED_FAILURES - 1)
        result = apply_adjustment(session, OUT.OFF, OUT.COOL)
        assert result is True
        assert session.failed_to_change == ALLOWED_FAILURES

    def test_above_allowed_failures_returns_false(self):
        session = CachedState(last=OUT.COOL, failed_to_change=ALLOWED_FAILURES)
        result = apply_adjustment(session, OUT.OFF, OUT.COOL)
        assert result is False
        assert session.failed_to_change == ALLOWED_FAILURES + 1

    def test_different_adjustment_resets_counter(self):
        """Switching to a different adjustment resets the failure counter."""
        session = CachedState(last=OUT.COOL, failed_to_change=5)
        result = apply_adjustment(session, OUT.OFF, OUT.DRY)
        assert result is True
        assert session.last is OUT.DRY
        assert session.failed_to_change == 0


# ---------------------------------------------------------------------------
# Lifecycle scenarios
# ---------------------------------------------------------------------------


class TestLifecycleScenarios:
    def test_morning_ramp_off_dry_cool(self):
        """OFF -> DRY -> COOL as generation increases."""
        state = CachedState()

        # Low generation -> no activation
        r1 = adjust(TEST_PARAMS, home(generation=2000, temperature=24, auto=True), state)
        assert r1.output is OUT.OFF

        # Generation rises above dry threshold -> DRY
        r2 = adjust(TEST_PARAMS, home(generation=3500, temperature=24, auto=True), state)
        assert r2 == AdjustResult(OUT.DRY, R_SOLAR_DRY)

        # Aircon now DRY; generation rises above cool threshold -> COOL
        r3 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.DRY,
                generation=5500,
                humidity=60,
                temperature=24,
                auto=True,
            ),
            state,
        )
        assert r3 == AdjustResult(OUT.COOL, R_SOLAR_COOL)

    def test_cloud_passing_tolerance_then_recovery(self):
        """COOL + grid spike -> tolerance -> grid clears -> continue COOL."""
        state = CachedState()

        # COOL with free solar
        r1 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=6000,
                humidity=60,
                auto=True,
            ),
            state,
        )
        assert r1.output is OUT.NO_CHANGE

        # Cloud: gen drops, grid spike
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=2000,
                grid_usage=500,
                auto=True,
            ),
            state,
        )
        assert r2.reason == R_GRID_TOLERATED
        assert state.tolerated == 1

        # Grid clears before tolerance expires -> continue
        r3 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=6000,
                humidity=60,
                grid_usage=0,
                auto=True,
            ),
            state,
        )
        assert r3.output is OUT.NO_CHANGE
        assert state.tolerated == 0  # reset by free solar path

    def test_evening_fade_cool_dry_off(self):
        """COOL -> DRY -> OFF as generation decreases."""
        state = CachedState()

        # COOL, gen drops below cool but above dry + grid appears -> downgrade to DRY
        r1 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=4000,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r1 == AdjustResult(OUT.DRY, R_SOLAR_DRY)

        # A mode change cannot reset the paid-power allowance.
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.DRY,
                generation=2000,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r2 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)

    def test_boost_lifecycle(self):
        """Boost starts on solar, finishes without it, then stays off below the start threshold."""
        state = CachedState()

        # Activate boost
        r1 = adjust(
            TEST_PARAMS,
            home(allow_paid_power=True, generation=6000, temperature=24, auto=True),
            state,
        )
        assert r1 == AdjustResult(OUT.COOL, R_SOLAR_COOL)

        # Grid appears, boost tolerates
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=True,
                generation=500,
                grid_usage=500,
                temperature=23,
                auto=True,
            ),
            state,
        )
        assert r2 == AdjustResult(OUT.NO_CHANGE, R_PAID_POWER)
        assert state.tolerated == 0

        # Solar disappears, but the automatic run finishes its cooling goal.
        r3 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=True,
                have_solar=False,
                generation=0,
                grid_usage=500,
                temperature=23,
                auto=True,
            ),
            state,
        )
        assert r3.reason == R_PAID_POWER
        assert state.tolerated == 0

        r4 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=True,
                have_solar=False,
                generation=0,
                grid_usage=500,
                temperature=22,
                auto=True,
            ),
            state,
        )
        assert r4 == AdjustResult(OUT.NO_CHANGE, R_PAID_POWER)
        assert adjust(TEST_PARAMS, home(allow_paid_power=True, temperature=23), state).reason == R_BELOW_THRESHOLD

    def test_boost_low_solar_does_not_cycle_on_grid(self):
        state = CachedState(solar_run_eligible=True)
        h = home(
            aircon_mode=AirconMode.COOL,
            allow_paid_power=True,
            generation=117,
            grid_usage=556,
            auto=True,
        )
        r1 = adjust(TEST_PARAMS, h, state)
        assert r1 == AdjustResult(OUT.NO_CHANGE, R_PAID_POWER)

        r2 = adjust(TEST_PARAMS, h, state)
        assert r2 == AdjustResult(OUT.NO_CHANGE, R_PAID_POWER)

    def test_mode_switch_solar_to_boost_tolerates_grid(self):
        """Solar COOL -> boost enabled -> grid appears -> boost tolerates."""
        state = CachedState()

        # Solar COOL, free solar
        r1 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=6000,
                humidity=60,
                auto=True,
            ),
            state,
        )
        assert r1.output is OUT.NO_CHANGE

        # Boost enabled, grid appears, gen drops but > 0
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=True,
                generation=500,
                grid_usage=200,
                auto=True,
            ),
            state,
        )
        assert r2 == AdjustResult(OUT.NO_CHANGE, R_PAID_POWER)

    def test_mode_switch_boost_to_solar_grid_tolerance_off(self):
        """Boost COOL -> boost disabled -> grid appears -> tolerance -> OFF."""
        state = CachedState(solar_run_eligible=True)

        # Boost COOL with grid tolerated
        r1 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=True,
                generation=500,
                grid_usage=200,
                auto=True,
            ),
            state,
        )
        assert r1.reason == R_PAID_POWER

        # Boost disabled, grid still present, gen insufficient
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=False,
                generation=2000,
                grid_usage=200,
                auto=True,
            ),
            state,
        )
        assert r2.reason == R_GRID_TOLERATED
        assert state.tolerated == 1

        r3 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                allow_paid_power=False,
                generation=2000,
                grid_usage=200,
                auto=True,
            ),
            state,
        )
        assert r3 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)


# ---------------------------------------------------------------------------
# Reason string coverage — verify exact R_* constant per path
# ---------------------------------------------------------------------------


class TestReasonConstants:
    def test_r_no_solar(self):
        r = adjust(TEST_PARAMS, home(have_solar=False, auto=True), CachedState())
        assert r.reason == R_NO_SOLAR

    def test_r_solar_cool(self):
        r = adjust(
            TEST_PARAMS,
            home(generation=6000, humidity=60, temperature=24, auto=True),
            CachedState(),
        )
        assert r.reason == R_SOLAR_COOL

    def test_r_solar_dry(self):
        r = adjust(
            TEST_PARAMS,
            home(generation=3500, temperature=24, auto=True),
            CachedState(),
        )
        assert r.reason == R_SOLAR_DRY

    def test_r_grid_tolerated(self):
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=2000,
                grid_usage=100,
                auto=True,
            ),
            CachedState(),
        )
        assert r.reason == R_GRID_TOLERATED

    def test_r_grid_too_high(self):
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                generation=2000,
                grid_usage=100,
                auto=True,
            ),
            CachedState(tolerated=1),
        )
        assert r.reason == R_GRID_TOO_HIGH

    def test_r_reactivate_wait(self):
        r = adjust(TEST_PARAMS, home(), CachedState(reactivate_at=120))
        assert r.reason == R_REACTIVATE_WAIT

    def test_r_disabled(self):
        r = adjust(TEST_PARAMS, home(enabled=False), CachedState())
        assert r.reason == R_DISABLED

    def test_r_unknown_mode(self):
        r = adjust(TEST_PARAMS, home(aircon_mode=AirconMode.UNKNOWN), CachedState())
        assert r.reason == R_UNKNOWN_MODE

    def test_r_timer_expired(self):
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                grid_usage=100,
                timer=False,
                auto=False,
            ),
            CachedState(last=OUT.TIMER),
        )
        assert r.reason == R_TIMER_EXPIRED

    def test_r_manual(self):
        r = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.COOL, grid_usage=100, auto=False),
            CachedState(),
        )
        assert r.reason == R_MANUAL

    def test_r_auto_idle(self):
        r = adjust(
            TEST_PARAMS,
            home(generation=1000, temperature=24, auto=True),
            CachedState(),
        )
        assert r.reason == R_AUTO_IDLE

    def test_r_no_change(self):
        r = adjust(
            TEST_PARAMS,
            home(generation=1000, temperature=24, auto=False),
            CachedState(),
        )
        assert r.reason == R_NO_CHANGE

    def test_r_cooling_disabled(self):
        r = adjust(
            TEST_PARAMS,
            home(cooling_enabled=False, temperature=24, auto=True),
            CachedState(),
        )
        assert r.reason == R_COOLING_DISABLED

    def test_r_below_cool_setpoint(self):
        r = adjust(
            TEST_PARAMS,
            home(allow_paid_power=True, generation=500, temperature=22, auto=True),
            CachedState(),
        )
        assert r.reason == R_BELOW_COOL_SETPOINT

    def test_r_below_threshold(self):
        r = adjust(
            TEST_PARAMS,
            home(generation=6000, temperature=23, auto=True),
            CachedState(),
        )
        assert r.reason == R_BELOW_THRESHOLD


@pytest.mark.parametrize(
    ("mode", "boost", "generation", "grid", "discharge", "temperature"),
    [
        (AirconMode.COOL, False, 6000, 0, 0, 22),
        (AirconMode.DRY, False, 6000, 0, 0, 21),
    ],
)
def test_automatic_target_stop_precedes_power_and_mode_changes(mode, boost, generation, grid, discharge, temperature):
    state = CachedState(tolerated=1, reactivate_at=60)
    result = adjust(
        replace(TEST_PARAMS, stop_at_comfort_temperature=True),
        home(
            aircon_mode=mode,
            auto=True,
            allow_paid_power=boost,
            have_solar=generation > 0,
            generation=generation,
            grid_usage=grid,
            battery_discharge=discharge,
            temperature=temperature,
        ),
        state,
    )
    assert result == AdjustResult(OUT.OFF, R_TARGET_REACHED)
    assert state.tolerated == 0
    assert state.reactivate_at == TEST_PARAMS.reactivate_delay * 60


@pytest.mark.parametrize("boost", [False, True])
def test_manual_free_solar_run_is_not_stopped_at_temperature_target(boost):
    result = adjust(
        TEST_PARAMS,
        home(aircon_mode=AirconMode.COOL, generation=6000, temperature=21, allow_paid_power=boost),
        CachedState(),
    )
    assert result.output is OUT.NO_CHANGE


@pytest.mark.parametrize("start", [21, 22, float("nan"), float("inf")])
def test_invalid_temperature_range_blocks_automatic_starts(start):
    params = replace(TEST_PARAMS, temperature_threshold=start)
    result = adjust(params, home(generation=6000, temperature=26), CachedState())
    assert result == AdjustResult(OUT.NO_CHANGE, R_INVALID_TEMPERATURE_RANGE)


def test_unavailable_temperature_prevents_start_and_mode_upgrade():
    result = adjust(TEST_PARAMS, home(generation=6000, temperature=26, temperature_available=False), CachedState())
    assert result == AdjustResult(OUT.NO_CHANGE, R_TEMPERATURE_UNAVAILABLE)
    result = adjust(
        TEST_PARAMS,
        home(aircon_mode=AirconMode.DRY, auto=True, allow_paid_power=True, temperature=20, temperature_available=False),
        CachedState(),
    )
    assert result == AdjustResult(OUT.NO_CHANGE, R_TEMPERATURE_UNAVAILABLE)


def test_solar_only_does_not_start_while_importing():
    result = adjust(TEST_PARAMS, home(generation=6000, grid_usage=500), CachedState())
    assert result == AdjustResult(OUT.NO_CHANGE, R_GRID_TOO_HIGH)


class TestAdjustManualFreeSolar:
    """Free solar allows uncapped manual cooling, but cannot override an existing timer cap."""

    def test_free_solar_manual_stays_uncapped(self):
        r = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.COOL, have_solar=True, generation=6000, auto=False),
            CachedState(last=OUT.COOL),
        )
        assert r == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)

    def test_free_solar_manual_stops_when_timer_expires(self):
        r = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.COOL, have_solar=True, generation=6000, auto=False),
            CachedState(last=OUT.TIMER),
        )
        assert r == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)


@pytest.mark.parametrize("mode", [AirconMode.COOL, AirconMode.DRY])
@pytest.mark.parametrize("boost", [False, True])
@pytest.mark.parametrize("stop_at_target", [False, True])
def test_manual_timer_target_behaviour_overrides_battery_guard(mode, boost, stop_at_target):
    params = replace(TEST_PARAMS, stop_at_comfort_temperature=stop_at_target)
    state = CachedState(last=OUT.TIMER, reactivate_at=120)
    result = adjust(
        params,
        home(
            aircon_mode=mode,
            auto=False,
            allow_paid_power=boost,
            timer=True,
            have_solar=False,
            battery_discharge=800,
            temperature=22,
        ),
        state,
    )
    expected = OUT.OFF if stop_at_target else OUT.NO_CHANGE
    assert result.output is expected
    assert result.reason == (R_TARGET_REACHED if expected is OUT.OFF else R_NO_CHANGE)


def test_manual_stop_at_target_requires_available_temperature():
    params = replace(TEST_PARAMS, stop_at_comfort_temperature=True)
    result = adjust(
        params,
        home(aircon_mode=AirconMode.COOL, timer=True, temperature=20, temperature_available=False),
        CachedState(last=OUT.TIMER),
    )
    assert result == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("mode", [AirconMode.COOL, AirconMode.DRY])
def test_disabling_cooling_stops_only_automatic_runs(auto, mode):
    result = adjust(
        TEST_PARAMS,
        home(aircon_mode=mode, auto=auto, cooling_enabled=False, generation=6000),
        CachedState(),
    )
    assert result.output is (OUT.OFF if auto else OUT.NO_CHANGE)
    if auto:
        assert result.reason == R_COOLING_DISABLED


@pytest.mark.parametrize(
    ("auto", "generation", "paid", "grid", "temperature_available", "expected"),
    [
        (True, 6000, False, 0, True, OUT.COOL),
        (True, 4000, False, 0, True, OUT.OFF),
        (True, 0, True, 500, True, OUT.OFF),
        (True, 6000, False, 500, True, OUT.OFF),
        (True, 6000, False, 0, False, OUT.OFF),
        (False, 4000, False, 0, True, OUT.NO_CHANGE),
    ],
)
def test_disabling_dry_rechecks_cool_eligibility(auto, generation, paid, grid, temperature_available, expected):
    result = adjust(
        replace(TEST_PARAMS, dry_mode_enabled=False),
        home(
            aircon_mode=AirconMode.DRY,
            auto=auto,
            generation=generation,
            have_solar=generation > 0,
            allow_paid_power=paid,
            grid_usage=grid,
            temperature_available=temperature_available,
        ),
        CachedState(),
    )
    assert result.output is expected


@pytest.mark.parametrize(
    ("auto", "paid", "stop", "precool", "expected"),
    [
        (True, False, False, False, OUT.NO_CHANGE),
        (True, False, True, False, OUT.OFF),
        (True, True, True, False, OUT.OFF),
        (False, False, True, False, OUT.OFF),
        (True, True, True, True, OUT.NO_CHANGE),
        (True, False, True, True, OUT.NO_CHANGE),
    ],
)
def test_target_stop_is_independent_of_power_and_preserves_precooling(auto, paid, stop, precool, expected):
    result = adjust(
        replace(TEST_PARAMS, stop_at_comfort_temperature=stop),
        home(
            aircon_mode=AirconMode.COOL,
            auto=auto,
            allow_paid_power=paid,
            pre_cooling=precool,
            generation=6000,
            temperature=20,
        ),
        CachedState(),
    )
    assert result.output is expected


class TestManualOvernightCapLifecycle:
    """End-to-end pure-engine arm -> hold -> expire -> OFF for a manual no-solar run."""

    def test_arm_hold_expire_off(self):
        state = CachedState(last=OUT.OFF)
        armed = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.HEAT, have_solar=False, grid_usage=0.0, timer=False, auto=False),
            state,
        )
        assert armed == AdjustResult(OUT.TIMER, R_MANUAL)
        assert apply_adjustment(state, OUT.COOL, OUT.TIMER) is True  # session.last -> TIMER

        holding = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.HEAT, have_solar=False, grid_usage=0.0, timer=True, auto=False),
            state,
        )
        assert holding == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)

        expired = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.HEAT, have_solar=False, grid_usage=0.0, timer=False, auto=False),
            state,
        )
        assert expired == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)


class TestManualHeatFreeSolarCap:
    """Incident regression: a heat run on FREE solar must still be capped and turned OFF.

    Before the mode-aware fix, a heat run on free solar was never capped (start) and its
    expired cap was cleared with RESET (kept running), so the heater ran all day.
    """

    def _heat(self, **kw) -> HomeInput:
        base = dict(aircon_mode=AirconMode.HEAT, have_solar=True, generation=2016.0, grid_usage=0.0, auto=False)
        base.update(kw)
        return home(**base)

    def test_free_solar_heat_starts_cap(self):
        """Defect A: manual heat on free solar arms the cap (previously NO_CHANGE)."""
        r = adjust(TEST_PARAMS, self._heat(timer=False), CachedState(last=OUT.OFF))
        assert r == AdjustResult(OUT.TIMER, R_MANUAL)

    def test_free_solar_heat_holds_while_capped(self):
        r = adjust(TEST_PARAMS, self._heat(timer=True), CachedState(last=OUT.TIMER))
        assert r == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)

    def test_free_solar_heat_expiry_turns_off(self):
        """The incident: expired cap on free solar turns OFF (previously RESET/keep-running)."""
        r = adjust(TEST_PARAMS, self._heat(timer=False), CachedState(last=OUT.TIMER))
        assert r == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)

    def test_grid_heat_expiry_still_turns_off(self):
        """No regression: expiry on grid draw still turns OFF."""
        r = adjust(TEST_PARAMS, self._heat(grid_usage=300.0, timer=False), CachedState(last=OUT.TIMER))
        assert r == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)

    def test_lifecycle_arm_hold_expire_off_rearm(self):
        """Full user story on free solar: arm -> hold -> expire OFF -> manual on again -> re-arm."""
        state = CachedState(last=OUT.OFF)
        assert adjust(TEST_PARAMS, self._heat(timer=False), state) == AdjustResult(OUT.TIMER, R_MANUAL)
        apply_adjustment(state, OUT.ON, OUT.TIMER)  # session.last -> TIMER
        assert adjust(TEST_PARAMS, self._heat(timer=True), state) == AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)
        assert adjust(TEST_PARAMS, self._heat(timer=False), state) == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)
        apply_adjustment(state, OUT.ON, OUT.OFF)  # session.last -> OFF
        assert adjust(TEST_PARAMS, self._heat(timer=False), state) == AdjustResult(OUT.TIMER, R_MANUAL)

    def test_recorded_free_solar_expiries_turn_off(self):
        """Real generation readings recorded at the free-solar cap expiries (grid=0)."""
        for generation in (2016.0, 5596.0, 1210.0):
            r = adjust(
                TEST_PARAMS,
                self._heat(generation=generation, timer=False),
                CachedState(last=OUT.TIMER),
            )
            assert r == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)


class TestStaleAutoHeat:
    """A stale auto=True (home-rules ran cool, user switched to heat) must not keep a heat run
    alive or flip it back to COOL. The mode-first branch treats any non-cool run as external."""

    def test_stale_auto_heat_expiry_turns_off(self):
        r = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.HEAT, have_solar=True, generation=2016.0, grid_usage=0.0, auto=True),
            CachedState(last=OUT.TIMER),
        )
        assert r == AdjustResult(OUT.OFF, R_TIMER_EXPIRED)

    def test_stale_auto_heat_strong_sun_never_flips_to_cool(self):
        """Generation above the cool threshold must not command COOL on a heat run."""
        r = adjust(
            TEST_PARAMS,
            home(aircon_mode=AirconMode.HEAT, have_solar=True, generation=6000.0, grid_usage=0.0, auto=True),
            CachedState(last=OUT.OFF),
        )
        assert r.output is OUT.TIMER
        assert r.output is not OUT.COOL
