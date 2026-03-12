"""Comprehensive tests for the pure rules engine (rules.py).

No Home Assistant dependencies — every branch of _evaluate_target_mode,
current_state, _idle_reason, adjust, and apply_adjustment is covered.
"""

from __future__ import annotations

from custom_components.home_rules.rules import (
    ALLOWED_FAILURES,
    R_ALREADY_COOLING,
    R_ALREADY_DRYING,
    R_AUTO_IDLE,
    R_BELOW_COOL_SETPOINT,
    R_BELOW_THRESHOLD,
    R_BOOST_COOLING,
    R_BOOST_GRID_TOLERATED,
    R_BOOST_SOLAR,
    R_COOLING_DISABLED,
    R_DISABLED,
    R_GRID_TOLERATED,
    R_GRID_TOO_HIGH,
    R_INSUFFICIENT_SOLAR,
    R_MANUAL,
    R_NO_CHANGE,
    R_NO_SOLAR,
    R_REACTIVATE_WAIT,
    R_SOLAR_COOL,
    R_SOLAR_DRY,
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
    generation_boost_threshold=500,
    temperature_threshold=24,
    humidity_threshold=65,
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
        humidity=TEST_PARAMS.humidity_threshold,
        auto=False,
        aggressive_cooling=False,
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

    def test_b1_boost_not_cool(self):
        """Boost + gen>=boost_threshold + not COOL -> COOL, R_BOOST_SOLAR, actionable."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, aircon_mode=AirconMode.OFF),
        )
        assert r == TargetResult(OUT.COOL, R_BOOST_SOLAR, True)

    def test_b2_boost_already_cool(self):
        """Boost + gen>=boost_threshold + already COOL -> None, R_BOOST_COOLING, not actionable."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, aircon_mode=AirconMode.COOL),
        )
        assert r == TargetResult(None, R_BOOST_COOLING, False)

    def test_c1_solar_cool_not_cool(self):
        """gen>=cool + humid<=thresh + not COOL -> COOL, R_SOLAR_COOL, actionable."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=5500, humidity=65, aircon_mode=AirconMode.OFF),
        )
        assert r == TargetResult(OUT.COOL, R_SOLAR_COOL, True)

    def test_c2_solar_cool_already_cool(self):
        """gen>=cool + humid<=thresh + already COOL -> None, R_ALREADY_COOLING."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=5500, humidity=65, aircon_mode=AirconMode.COOL),
        )
        assert r == TargetResult(None, R_ALREADY_COOLING, False)

    def test_d1_solar_dry_not_dry(self):
        """gen>=dry + not DRY -> DRY, R_SOLAR_DRY, actionable."""
        r = _evaluate_target_mode(TEST_PARAMS, home(generation=3500, aircon_mode=AirconMode.OFF))
        assert r == TargetResult(OUT.DRY, R_SOLAR_DRY, True)

    def test_d2_solar_dry_already_dry(self):
        """gen>=dry + already DRY -> None, R_ALREADY_DRYING, not actionable."""
        r = _evaluate_target_mode(TEST_PARAMS, home(generation=3500, aircon_mode=AirconMode.DRY))
        assert r == TargetResult(None, R_ALREADY_DRYING, False)

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
        """humidity exactly == threshold (<= check) -> COOL allowed."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=6000, humidity=65, aircon_mode=AirconMode.OFF),
        )
        assert r.output is OUT.COOL

    def test_boundary_humidity_above_threshold_forces_dry(self):
        """humidity == threshold+1 -> DRY instead of COOL."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(generation=6000, humidity=66, aircon_mode=AirconMode.OFF),
        )
        assert r.output is OUT.DRY
        assert r.reason == R_SOLAR_DRY

    def test_boost_ignores_humidity(self):
        """Boost + gen>=boost_threshold + high humidity -> still COOL."""
        r = _evaluate_target_mode(
            TEST_PARAMS,
            home(
                aggressive_cooling=True,
                generation=500,
                humidity=99,
                aircon_mode=AirconMode.OFF,
            ),
        )
        assert r == TargetResult(OUT.COOL, R_BOOST_SOLAR, True)

    def test_boost_with_zero_gen_falls_to_solar_logic(self):
        """Boost + gen==0 -> falls through to solar logic (insufficient)."""
        r = _evaluate_target_mode(TEST_PARAMS, home(aggressive_cooling=True, generation=0))
        assert r == TargetResult(None, R_INSUFFICIENT_SOLAR, False)

    def test_boost_below_threshold_falls_to_solar_logic(self):
        """Boost + gen<boost_threshold -> falls through to solar logic."""
        r = _evaluate_target_mode(TEST_PARAMS, home(aggressive_cooling=True, generation=499))
        assert r == TargetResult(None, R_INSUFFICIENT_SOLAR, False)


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

    def test_fan_only_fallback_to_cool(self):
        assert current_state(home(aircon_mode=AirconMode.FAN_ONLY)) is OUT.COOL

    def test_heat_fallback_to_cool(self):
        assert current_state(home(aircon_mode=AirconMode.HEAT)) is OUT.COOL

    def test_heat_cool_fallback_to_cool(self):
        assert current_state(home(aircon_mode=AirconMode.HEAT_COOL)) is OUT.COOL

    def test_auto_fallback_to_cool(self):
        assert current_state(home(aircon_mode=AirconMode.AUTO)) is OUT.COOL


# ---------------------------------------------------------------------------
# _idle_reason — priority order
# ---------------------------------------------------------------------------


class TestIdleReason:
    def test_cooling_disabled_highest_priority(self):
        """cooling_enabled=False wins even if other conditions match."""
        r = _idle_reason(
            TEST_PARAMS,
            home(cooling_enabled=False, aggressive_cooling=True, temperature=20),
            "activation",
            "default",
        )
        assert r == R_COOLING_DISABLED

    def test_boost_below_cool_setpoint(self):
        """aggressive + temp <= cool_setpoint -> R_BELOW_COOL_SETPOINT."""
        r = _idle_reason(
            TEST_PARAMS,
            home(aggressive_cooling=True, temperature=21),
            None,
            "default",
        )
        assert r == R_BELOW_COOL_SETPOINT

    def test_boost_at_cool_setpoint_boundary(self):
        """temperature == cool_setpoint (<= check) -> R_BELOW_COOL_SETPOINT."""
        r = _idle_reason(
            TEST_PARAMS,
            home(aggressive_cooling=True, temperature=22),
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
    def test_delay_2_decrements_to_1(self):
        state = CachedState(reactivate_delay=2)
        r = adjust(TEST_PARAMS, home(), state)
        assert r == AdjustResult(OUT.NO_CHANGE, R_REACTIVATE_WAIT)
        assert state.reactivate_delay == 1

    def test_delay_1_decrements_to_0(self):
        state = CachedState(reactivate_delay=1)
        r = adjust(TEST_PARAMS, home(), state)
        assert r == AdjustResult(OUT.NO_CHANGE, R_REACTIVATE_WAIT)
        assert state.reactivate_delay == 0

    def test_delay_0_proceeds_normally(self):
        """delay=0 -> normal evaluation (not intercepted)."""
        state = CachedState(reactivate_delay=0)
        r = adjust(TEST_PARAMS, home(), state)
        assert r.reason != R_REACTIVATE_WAIT


# ---------------------------------------------------------------------------
# adjust — Aircon OFF, Solar activation
# ---------------------------------------------------------------------------


class TestAdjustOffSolar:
    def test_cool_activation(self):
        """gen>=cool + humid<=thresh + temp>=threshold -> COOL."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=5500, humidity=65, temperature=24, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_SOLAR_COOL)

    def test_dry_activation_humidity_gate(self):
        """gen>=cool but humid>thresh -> DRY (humidity prevents COOL)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=6000, humidity=66, temperature=24, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.DRY, R_SOLAR_DRY)

    def test_dry_activation_gen_above_dry(self):
        """gen>=dry + temp>=threshold -> DRY."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(generation=3500, temperature=24, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.DRY, R_SOLAR_DRY)

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
# adjust — Aircon OFF, Boost activation
# ---------------------------------------------------------------------------


class TestAdjustOffBoost:
    def test_boost_activation(self):
        """Boost + solar + gen>=boost_threshold + temp>cool_setpoint -> COOL."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, temperature=22.1, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_BOOST_SOLAR)

    def test_boost_temp_at_setpoint_no_activation(self):
        """Boost + temp==cool_setpoint -> OFF (> is strict for boost)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, temperature=22, auto=True),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_BELOW_COOL_SETPOINT

    def test_boost_zero_gen_no_activation(self):
        """Boost + gen==0 -> OFF (insufficient solar, auto idle)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=0, temperature=24, auto=True),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_AUTO_IDLE

    def test_boost_no_solar_no_activation(self):
        """Boost + no solar -> OFF, R_NO_SOLAR (actionable via idle)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aggressive_cooling=True,
                have_solar=False,
                temperature=24,
                auto=True,
            ),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_NO_SOLAR

    def test_boost_cooling_disabled(self):
        """Boost + cooling_disabled -> OFF, R_COOLING_DISABLED."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aggressive_cooling=True,
                generation=500,
                temperature=23,
                cooling_enabled=False,
                auto=True,
            ),
            state,
        )
        assert r.output is OUT.OFF
        assert r.reason == R_COOLING_DISABLED

    def test_boost_activates_below_threshold(self):
        """Boost + temp between cool_setpoint and temp_threshold -> COOL.

        Boost uses a lower bar (> cool_setpoint) instead of >= threshold.
        """
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, temperature=23, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_BOOST_SOLAR)

    def test_boost_below_threshold_no_activation(self):
        """Boost + gen<boost_threshold -> NO_CHANGE (insufficient solar)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=499, temperature=23, auto=False),
            state,
        )
        assert r.output is OUT.NO_CHANGE

    def test_boost_at_threshold_activates(self):
        """Boost + gen==boost_threshold -> COOL (>= boundary)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, temperature=23, auto=True),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_BOOST_SOLAR)


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
        assert state.reactivate_delay == 2

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
        assert state.tolerated == 0

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
        assert state.reactivate_delay == TEST_PARAMS.reactivate_delay


# ---------------------------------------------------------------------------
# adjust — Aircon ON, grid draw, auto mode (boost)
# ---------------------------------------------------------------------------


class TestAdjustOnGridAutoBoost:
    def test_boost_cool_grid_tolerated(self):
        """Boost + COOL + solar + gen>=boost_threshold + grid>0 -> NO_CHANGE R_BOOST_GRID_TOLERATED."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=500,
                grid_usage=500,
                auto=True,
            ),
            state,
        )
        assert r == AdjustResult(OUT.NO_CHANGE, R_BOOST_GRID_TOLERATED)
        assert state.tolerated == 0

    def test_boost_dry_upgrade_to_cool(self):
        """Boost + DRY + solar + gen>=boost_threshold + grid>0 -> COOL (upgrade via target)."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.DRY,
                aggressive_cooling=True,
                generation=500,
                grid_usage=500,
                auto=True,
            ),
            state,
        )
        assert r == AdjustResult(OUT.COOL, R_BOOST_SOLAR)

    def test_boost_zero_gen_tolerance_then_off(self):
        """Boost + gen==0 -> tolerance then OFF (boost needs gen>=threshold)."""
        state = CachedState()
        h = home(
            aircon_mode=AirconMode.COOL,
            aggressive_cooling=True,
            generation=0,
            grid_usage=100,
            auto=True,
        )
        r1 = adjust(TEST_PARAMS, h, state)
        assert r1.reason == R_GRID_TOLERATED

        r2 = adjust(TEST_PARAMS, h, state)
        assert r2 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)

    def test_boost_no_solar_tolerance_then_off(self):
        """Boost + no solar -> tolerance then OFF."""
        state = CachedState()
        h = home(
            aircon_mode=AirconMode.COOL,
            aggressive_cooling=True,
            have_solar=False,
            grid_usage=100,
            auto=True,
        )
        r1 = adjust(TEST_PARAMS, h, state)
        assert r1.reason == R_GRID_TOLERATED

        r2 = adjust(TEST_PARAMS, h, state)
        assert r2 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)

    def test_boost_grid_tolerated_resets_counter(self):
        """Boost grid tolerated resets tolerance counter."""
        state = CachedState(tolerated=5)
        adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=500,
                grid_usage=500,
                auto=True,
            ),
            state,
        )
        assert state.tolerated == 0

    def test_boost_above_threshold_tolerates_grid(self):
        """Boost + gen>=boost_threshold + grid -> R_BOOST_GRID_TOLERATED."""
        state = CachedState()
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=500,
                grid_usage=300,
                auto=True,
            ),
            state,
        )
        assert r == AdjustResult(OUT.NO_CHANGE, R_BOOST_GRID_TOLERATED)


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

        # DRY, gen drops below dry -> tolerance cycle -> OFF
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
        assert r2.reason == R_GRID_TOLERATED

        r3 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.DRY,
                generation=2000,
                grid_usage=100,
                auto=True,
            ),
            state,
        )
        assert r3 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)

    def test_boost_lifecycle(self):
        """OFF -> COOL(boost) -> grid tolerated -> solar lost -> tolerance -> OFF."""
        state = CachedState()

        # Activate boost
        r1 = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, temperature=23, auto=True),
            state,
        )
        assert r1 == AdjustResult(OUT.COOL, R_BOOST_SOLAR)

        # Grid appears, boost tolerates
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=500,
                grid_usage=500,
                temperature=23,
                auto=True,
            ),
            state,
        )
        assert r2 == AdjustResult(OUT.NO_CHANGE, R_BOOST_GRID_TOLERATED)
        assert state.tolerated == 0

        # Solar lost (gen=0), grid still present -> tolerance
        r3 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=0,
                grid_usage=500,
                temperature=23,
                auto=True,
            ),
            state,
        )
        assert r3.reason == R_GRID_TOLERATED
        assert state.tolerated == 1

        # Second tick -> OFF
        r4 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=0,
                grid_usage=500,
                temperature=23,
                auto=True,
            ),
            state,
        )
        assert r4 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)

    def test_boost_cycling_regression(self):
        """gen=117W, grid=556W should fall through to normal tolerance with new threshold.

        With generation_boost_threshold=500, gen=117 is below the threshold
        so boost grid tolerance does NOT apply. Normal tolerance kicks in.
        """
        state = CachedState()
        h = home(
            aircon_mode=AirconMode.COOL,
            aggressive_cooling=True,
            generation=117,
            grid_usage=556,
            auto=True,
        )
        r1 = adjust(TEST_PARAMS, h, state)
        assert r1 == AdjustResult(OUT.NO_CHANGE, R_GRID_TOLERATED)

        r2 = adjust(TEST_PARAMS, h, state)
        assert r2 == AdjustResult(OUT.OFF, R_GRID_TOO_HIGH)

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
                aggressive_cooling=True,
                generation=500,
                grid_usage=200,
                auto=True,
            ),
            state,
        )
        assert r2 == AdjustResult(OUT.NO_CHANGE, R_BOOST_GRID_TOLERATED)

    def test_mode_switch_boost_to_solar_grid_tolerance_off(self):
        """Boost COOL -> boost disabled -> grid appears -> tolerance -> OFF."""
        state = CachedState()

        # Boost COOL with grid tolerated
        r1 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=500,
                grid_usage=200,
                auto=True,
            ),
            state,
        )
        assert r1.reason == R_BOOST_GRID_TOLERATED

        # Boost disabled, grid still present, gen insufficient
        r2 = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=False,
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
                aggressive_cooling=False,
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

    def test_r_boost_solar(self):
        r = adjust(
            TEST_PARAMS,
            home(aggressive_cooling=True, generation=500, temperature=23, auto=True),
            CachedState(),
        )
        assert r.reason == R_BOOST_SOLAR

    def test_r_boost_grid_tolerated(self):
        r = adjust(
            TEST_PARAMS,
            home(
                aircon_mode=AirconMode.COOL,
                aggressive_cooling=True,
                generation=500,
                grid_usage=100,
                auto=True,
            ),
            CachedState(),
        )
        assert r.reason == R_BOOST_GRID_TOLERATED

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
        r = adjust(TEST_PARAMS, home(), CachedState(reactivate_delay=1))
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
            home(aggressive_cooling=True, generation=500, temperature=22, auto=True),
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
