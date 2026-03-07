"""Smoothing shadow-mode tests."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_smoothed_fields_present_in_evaluation_record(coord_factory) -> None:
    """Each evaluation record should contain raw and smoothed fields."""
    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("manual")

    record = coordinator._last_record
    expected = (
        "raw_generation",
        "raw_grid_usage",
        "smoothed_generation",
        "smoothed_grid_usage",
        "smoothed_adjustment",
        "smoothed_reason",
        "decision_differs",
    )
    for key in expected:
        assert key in record, f"Missing key: {key}"


async def test_window_1_gives_identical_results(coord_factory) -> None:
    """With smoothing_window=1, smoothed values should equal raw values."""
    from custom_components.home_rules.const import CONF_SMOOTHING_WINDOW

    coordinator = await coord_factory(options={CONF_SMOOTHING_WINDOW: 1})
    await coordinator.async_run_evaluation("manual")

    record = coordinator._last_record
    assert record["smoothed_generation"] == record["raw_generation"]
    assert record["smoothed_grid_usage"] == record["raw_grid_usage"]
    assert record["decision_differs"] is False


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
    # Raw would say "Grid usage too high" after tolerance,
    # but smoothed should still show decent generation
    hass.states.async_set("sensor.generation", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "500", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")

    record = coordinator._last_record
    assert record["raw_generation"] == 0.0
    assert record["smoothed_generation"] > 0.0  # averaged with previous good readings


async def test_smoothing_disagrees_count(coord_factory) -> None:
    """The smoothing_disagrees field should count disagreements in recent history."""
    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("manual")
    assert coordinator.data.smoothing_disagrees == 0


async def test_default_eval_interval_changed(coord_factory) -> None:
    """Default eval interval should now be 180 seconds (3 min)."""
    from custom_components.home_rules.const import DEFAULT_EVAL_INTERVAL

    assert DEFAULT_EVAL_INTERVAL == 180


async def test_default_smoothing_window_is_five() -> None:
    """Default smoothing window should be 5 evaluations."""
    from custom_components.home_rules.const import DEFAULT_SMOOTHING_WINDOW

    assert DEFAULT_SMOOTHING_WINDOW == 5
