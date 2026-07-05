"""End-to-end scenario tests for the coordinator pipeline.

These tests trace full scenarios through the coordinator public API:
  HA entity state → input gateway (normalization) → decision engine → coordinator.data

They complement the decision-engine unit tests in test_rules.py by verifying
that the coordinator correctly normalises inputs before passing them to rules.

No private methods are called.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_no_solar_generation_yields_no_change(coord_factory) -> None:
    """Zero generation → solar unavailable → no action taken."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="0")
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator.data.solar_available is False


async def test_high_humidity_still_yields_cool_when_solar_allows(coord_factory) -> None:
    """Humidity above the DRY cutoff should not block COOL at the cool threshold."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(humidity="70")  # above 65% threshold
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record["humidity"] == pytest.approx(70.0)


async def test_dry_band_with_high_humidity_yields_dry(coord_factory) -> None:
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="3500", humidity="70")
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.DRY


async def test_kw_generation_normalised_to_watts(hass, coord_factory) -> None:
    """Generation sensor reporting in lowercase kw is normalised to W before decisioning."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()
    # Override unit to lowercase kw: 6 kW = 6000 W → still above the 5500 W cool threshold
    hass.states.async_set("sensor.generation", "6", {"unit_of_measurement": "kw"})
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record["generation"] == pytest.approx(6000.0)


async def test_inverter_on_line_treated_as_online(coord_factory) -> None:
    """Hyphenated inverter state (e.g. 'on-line') is treated as online/available."""
    coordinator = await coord_factory(inverter="on-line")
    await coordinator.async_run_evaluation("test")

    assert coordinator._last_record["have_solar"] is True
    assert coordinator.data.solar_available is True


async def test_fahrenheit_temperature_normalised_to_celsius(hass, coord_factory) -> None:
    """Temperature sensor reporting in °F is normalised to °C before decisioning."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()
    # 77°F = 25°C, which is above the 24°C threshold → hot enough to activate
    hass.states.async_set("sensor.temperature", "77", {"unit_of_measurement": "°F"})
    await coordinator.async_run_evaluation("test")

    # 25°C, 40% humidity, 6000W → COOL
    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record["temperature"] == pytest.approx(25.0, abs=0.1)


async def test_cool_threshold_boundary_activates_cooling(coord_factory) -> None:
    """Generation exactly at cool threshold (5500W) activates COOL."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="5500")
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.COOL


async def test_below_dry_threshold_no_change(coord_factory) -> None:
    """Generation below dry threshold (3500W) → no action, even when hot."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="3499", temperature="28")
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE


async def test_restart_timer_still_active_preserves_timer_state(coord_factory) -> None:
    """After restart with timer still running, session state is preserved as TIMER."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.rules import HomeOutput

    # Simulate session that was in TIMER state, with integration-owned timer still active.
    coordinator = await coord_factory(
        climate="cool",
        generation="0",  # No solar — reason the timer was running
    )
    coordinator._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(minutes=2)
    # Bootstrap stored state as if we had previously been in TIMER mode.
    coordinator._session.last = HomeOutput.TIMER
    coordinator._initialized = False  # Reset so startup sync runs again.

    await coordinator.async_run_evaluation("restart")

    # Timer is still active → session.last should remain TIMER.
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._session.last is HomeOutput.TIMER


async def test_restart_with_stale_timer_state_syncs_to_live(hass, coord_factory) -> None:
    """After restart, if stored state was TIMER but timer has expired, sync to live."""
    from custom_components.home_rules.rules import HomeOutput

    # Timer has expired, aircon is off — timer finished while HA was down.
    coordinator = await coord_factory(
        climate="off",
        generation="0",
    )
    # Simulate stale stored state: session said TIMER but reality is now OFF.
    coordinator._session.last = HomeOutput.TIMER
    coordinator._initialized = False  # Reset so startup sync runs again.

    await coordinator.async_run_evaluation("restart")

    # Startup sync should have resolved TIMER → OFF (live state).
    assert coordinator._session.last is HomeOutput.OFF


async def test_timer_expiry_callback_triggers_immediate_evaluation(hass, coord_factory) -> None:
    import asyncio
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(climate="cool", grid="100")
    coordinator._initialized = True
    coordinator._session.last = HomeOutput.TIMER
    coordinator._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(milliseconds=20)
    coordinator._schedule_timer_expiry()

    await asyncio.sleep(0.1)
    await hass.async_block_till_done()

    assert coordinator._last_record["trigger"] == "timer_expired"
    assert coordinator.data.adjustment is HomeOutput.OFF
    await coordinator.async_shutdown()


async def test_restart_first_eval_uses_live_state_when_no_stored_session(coord_factory) -> None:
    """First eval with no stored session initialises session.last from live entity state."""
    # High solar, hot, aircon is already cooling.
    coordinator = await coord_factory(climate="cool", generation="6000", temperature="27")
    # session.last starts as None (no stored state).
    coordinator._session.last = None
    coordinator._initialized = False

    await coordinator.async_run_evaluation("startup")

    # Session must be initialised from live state, not left as None.
    assert coordinator._session.last is not None


async def test_online_inverter_without_generation_telemetry_is_not_solar(coord_factory) -> None:
    """An inverter stuck 'on-line' with no generation telemetry (asleep at night) is not solar.

    Regression: a stale online status previously masked the sleeping inverter, so a manually
    run aircon was treated as running on free solar and never capped by the overnight timer.
    """
    coordinator = await coord_factory(inverter="on-line", generation="unknown", grid="unknown", climate="heat")
    await coordinator.async_run_evaluation("poll")

    assert coordinator._last_record["have_solar"] is False
    assert coordinator.data.solar_available is False


async def test_online_inverter_without_telemetry_arms_overnight_timer(coord_factory) -> None:
    """With no live solar telemetry, a manually run aircon is capped by the overnight timer."""
    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(inverter="on-line", generation="unknown", grid="unknown", climate="heat")
    await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)

    assert coordinator._last_record["have_solar"] is False
    assert coordinator.data.adjustment is HomeOutput.TIMER
    assert coordinator._aircon_timer_finishes_at is not None
    await coordinator.async_shutdown()


async def test_live_zero_generation_with_stuck_online_inverter_caps_manual_run(coord_factory) -> None:
    """H2: a live 0 W reading (not 'unknown') with a stuck-online inverter is confirmed no-solar.

    have_solar must be False (requires generation > 0) and solar_unknown False, so a manual run
    enters the timer branch and is capped, so the original overnight bug cannot recur via a real 0.
    """
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(inverter="on-line", generation="0", grid="0", climate="heat")
    await coordinator.async_run_evaluation("poll")

    assert coordinator._last_record["have_solar"] is False
    assert coordinator._last_record["solar_unknown"] is False
    assert coordinator.data.adjustment is HomeOutput.TIMER


async def test_auto_cooling_holds_on_unknown_generation(coord_factory) -> None:
    """H1: an active auto-cooling run holds (does not shut off) when solar telemetry is missing."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(inverter="on-line", generation="unknown", grid="unknown", climate="cool")
    coordinator._auto_mode = True
    coordinator._session.last = HomeOutput.COOL
    coordinator._initialized = True  # skip startup sync so the simulated auto run persists

    await coordinator.async_run_evaluation("poll")

    assert coordinator._last_record["solar_unknown"] is True
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator.data.reason == "Solar telemetry unavailable"


async def test_auto_cooling_shuts_off_on_measured_grid_despite_unknown_solar(coord_factory) -> None:
    """H1 boundary: a real measured grid import still shuts an auto run off (not held)."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(inverter="on-line", generation="unknown", grid="200", climate="cool")
    coordinator._auto_mode = True
    coordinator._session.last = HomeOutput.COOL
    coordinator._initialized = True

    await coordinator.async_run_evaluation("poll")  # tolerated=1
    await coordinator.async_run_evaluation("poll")  # tolerated=grid_usage_delay -> OFF

    assert coordinator.data.adjustment is HomeOutput.OFF
    assert coordinator.data.reason == "Grid usage too high"


async def test_restart_with_expired_timer_and_aircon_on_turns_off(coord_factory) -> None:
    """M1: HA down when the cap elapsed, aircon still heating -> restart issues OFF, not a re-arm."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(climate="heat", generation="unknown", grid="unknown")
    coordinator._session.last = HomeOutput.TIMER
    coordinator._aircon_timer_finishes_at = None  # elapsed while HA was down
    coordinator._initialized = False  # startup sync runs

    await coordinator.async_run_evaluation("restart")

    assert coordinator.data.adjustment is HomeOutput.OFF  # cap issues OFF instead of re-arming a fresh timer
    assert coordinator.data.reason == "Timer expired"


async def test_offline_inverter_is_confirmed_no_solar_not_unknown(coord_factory) -> None:
    """An offline inverter is confirmed no-solar (not 'unknown'): an auto run shuts off, is not held."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(inverter="off-line", generation="unknown", grid="unknown", climate="cool")
    coordinator._auto_mode = True
    coordinator._session.last = HomeOutput.COOL
    coordinator._initialized = True

    await coordinator.async_run_evaluation("poll")  # tolerated=1
    assert coordinator._last_record["solar_unknown"] is False
    assert coordinator.data.reason == "Grid usage tolerated"

    await coordinator.async_run_evaluation("poll")  # tolerated=grid_usage_delay -> OFF
    assert coordinator.data.adjustment is HomeOutput.OFF


async def test_free_solar_reset_of_stale_timer_does_not_notify(coord_factory) -> None:
    """Clearing a stale expired cap under genuine free solar is internal: no notify, no last_changed bump."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(inverter="on-line", generation="6000", grid="0", climate="cool")
    coordinator._session.last = HomeOutput.TIMER
    coordinator._aircon_timer_finishes_at = None  # cap elapsed
    coordinator._initialized = True
    coordinator._last_changed = "sentinel"

    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.RESET
    assert coordinator._session.last is HomeOutput.COOL  # stale TIMER cleared to live state
    assert coordinator._last_changed == "sentinel"  # RESET is internal, so no spurious mode-change notification


async def test_restart_with_stored_elapsed_timer_issues_off_without_rescheduling(coord_factory) -> None:
    """M1/hardening: a cap that elapsed while HA was down issues OFF via the first eval and does not
    schedule a second, racing expiry callback that could re-arm."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(climate="heat", generation="unknown", grid="unknown")
    coordinator._session.last = HomeOutput.TIMER
    coordinator._aircon_timer_finishes_at = dt_util.utcnow() - timedelta(minutes=5)  # elapsed while HA was down
    coordinator._schedule_timer_expiry()  # as async_initialize would on restart

    assert coordinator._timer_expiry_handle is None  # an already-elapsed cap must not schedule a racing callback

    coordinator._initialized = False  # startup sync runs on the first evaluation
    await coordinator.async_run_evaluation("restart")

    assert coordinator.data.adjustment is HomeOutput.OFF
    assert coordinator._aircon_timer_finishes_at is None
