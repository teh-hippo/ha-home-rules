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


async def test_high_humidity_yields_dry_not_cool(coord_factory) -> None:
    """Humidity above threshold with high solar → DRY, not COOL."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(humidity="70")  # above 65% threshold
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.DRY
    assert coordinator._last_record["humidity"] == pytest.approx(70.0)


async def test_kw_generation_normalised_to_watts(hass, coord_factory) -> None:
    """Generation sensor reporting in kW is normalised to W before decisioning."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()
    # Override unit to kW: 6 kW = 6000 W → still above the 5500 W cool threshold
    hass.states.async_set("sensor.generation", "6", {"unit_of_measurement": "kW"})
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record["generation"] == pytest.approx(6000.0)


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
    from custom_components.home_rules.rules import HomeOutput

    # Simulate session that was in TIMER state, timer is still active in HA.
    coordinator = await coord_factory(
        climate="cool",
        timer="active",
        timer_attributes={"remaining": "0:02:00"},
        generation="0",  # No solar — reason the timer was running
    )
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

    # Timer has expired (idle), aircon is off — timer finished while HA was down.
    coordinator = await coord_factory(
        climate="off",
        timer="idle",
        generation="0",
    )
    # Simulate stale stored state: session said TIMER but reality is now OFF.
    coordinator._session.last = HomeOutput.TIMER
    coordinator._initialized = False  # Reset so startup sync runs again.

    await coordinator.async_run_evaluation("restart")

    # Startup sync should have resolved TIMER → OFF (live state).
    assert coordinator._session.last is HomeOutput.OFF


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
