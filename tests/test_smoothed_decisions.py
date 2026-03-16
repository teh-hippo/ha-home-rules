"""Tests for smoothed-generation decision making.

The primary adjust() call uses smoothed generation to dampen threshold
oscillation (e.g. COOL→DRY→COOL bouncing when solar fluctuates around 5500W).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_smoothed_gen_prevents_transient_activation(hass, coord_factory) -> None:
    """A single-poll generation spike shouldn't activate from OFF."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(
        generation="1000",
        grid="0",
        humidity="70",
        options={CONF_SMOOTHING_WINDOW: 3},
    )

    # Seed low solar
    await coordinator.async_run_evaluation("poll")
    hass.states.async_set("sensor.generation", "1000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    # Raw spikes to 4000 (above dry=3500) but smoothed=(1000+1000+4000)/3=2000
    hass.states.async_set("sensor.generation", "4000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    # Smoothed generation is below dry threshold → no activation
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["raw_generation"] == 4000.0
    assert coordinator._last_record["smoothed_generation"] < 3500


async def test_sustained_generation_activates_normally(hass, coord_factory) -> None:
    """Steady generation above threshold should activate without delay."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(
        generation="4000",
        grid="0",
        humidity="70",
        options={CONF_SMOOTHING_WINDOW: 3},
    )

    # All readings at 4000W — smoothed = 4000 → above dry threshold
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.DRY


async def test_oscillation_dampened_at_cool_threshold(hass, coord_factory) -> None:
    """COOL→DRY→COOL oscillation when solar fluctuates around cool threshold."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW

    coordinator = await coord_factory(
        generation="6000",
        grid="0",
        humidity="40",
        options={CONF_SMOOTHING_WINDOW: 3},
    )

    # Establish COOL mode with consistent high solar
    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record["adjustment"] == "Cool"
    hass.states.async_set("climate.test", "cool")
    hass.states.async_set("sensor.generation", "6000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    # Generation dips below cool threshold (5500) for one poll.
    # Raw=5000 but smoothed=(6000+6000+5000)/3=5667 → still above cool.
    hass.states.async_set("sensor.generation", "5000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    # Should stay in COOL (smoothed is above threshold), no downgrade to DRY
    assert coordinator._last_record["adjustment"] == "No Change"
    assert coordinator._last_record["smoothed_generation"] > 5500


async def test_shadow_shows_raw_alternative(hass, coord_factory) -> None:
    """Shadow run uses raw values and decision_differs shows when smoothing matters."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW

    coordinator = await coord_factory(
        generation="1000",
        grid="0",
        humidity="70",
        options={CONF_SMOOTHING_WINDOW: 3},
    )

    await coordinator.async_run_evaluation("poll")
    hass.states.async_set("sensor.generation", "1000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    # Spike: raw says DRY (4000>3500), smoothed says NO (avg 2000<3500)
    hass.states.async_set("sensor.generation", "4000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    record = coordinator._last_record
    assert record["adjustment"] == "No Change"  # actual (smoothed) decision
    assert record["smoothed_adjustment"] == "Dry"  # raw alternative
    assert record["decision_differs"] is True
