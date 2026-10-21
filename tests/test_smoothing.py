"""Smoothing tests."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_smoothed_fields_present_in_evaluation_record(coord_factory) -> None:
    """Each evaluation record should contain raw and smoothed generation fields."""
    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("manual")

    record = coordinator._last_record
    for key in ("raw_generation", "smoothed_generation"):
        assert key in record, f"Missing key: {key}"


async def test_window_1_gives_identical_results(coord_factory) -> None:
    """With smoothing_window=1, smoothed generation should equal raw generation."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW

    coordinator = await coord_factory(options={CONF_SMOOTHING_WINDOW: 1})
    await coordinator.async_run_evaluation("manual")

    record = coordinator._last_record
    assert record["smoothed_generation"] == record["raw_generation"]


async def test_smoothing_dampens_transient_spike(hass, coord_factory) -> None:
    """A single bad reading in a window of good ones should be smoothed out."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW

    coordinator = await coord_factory(
        generation="6000",
        grid="0",
        options={CONF_SMOOTHING_WINDOW: 3},
    )

    # First eval: generation=6000, grid=0 → COOL
    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record["adjustment"] == "Cool"

    # Second eval: generation=6000, grid=0 → no change (already COOL)
    hass.states.async_set("sensor.generation", "6000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    # Third eval: spike — generation drops to 0, grid appears
    hass.states.async_set("sensor.generation", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "500", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    record = coordinator._last_record
    assert record["raw_generation"] == 0.0
    assert record["smoothed_generation"] > 0.0  # averaged with previous good readings


async def test_default_eval_interval_changed(coord_factory) -> None:
    """Default eval interval should now be 180 seconds (3 min)."""
    from custom_components.home_rules.const import DEFAULT_EVAL_INTERVAL

    assert DEFAULT_EVAL_INTERVAL == 180


async def test_default_smoothing_window_is_five() -> None:
    """Default smoothing window should be 5 evaluations."""
    from custom_components.home_rules.const import DEFAULT_SMOOTHING_WINDOW

    assert DEFAULT_SMOOTHING_WINDOW == 5
