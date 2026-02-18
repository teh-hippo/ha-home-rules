"""Regression tests for unavailable input entities."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_unavailable_generation_does_not_fail_evaluation(hass, coord_factory) -> None:
    from homeassistant.helpers import issue_registry as ir

    coordinator = await coord_factory(generation="unavailable")
    await coordinator.async_run_evaluation("poll")

    registry = ir.async_get(hass)
    assert registry.async_get_issue("home_rules", f"{coordinator.config_entry.entry_id}_entity_unavailable") is None


async def test_unknown_power_sensors_do_not_raise_repairs_issue(hass, coord_factory) -> None:
    """Unknown is common for power sensors (e.g., solar at night) and should not page users."""
    from homeassistant.helpers import issue_registry as ir

    coordinator = await coord_factory(
        inverter="off-line",
        generation="unknown",
        grid="unknown",
    )
    await coordinator.async_run_evaluation("poll")

    registry = ir.async_get(hass)
    assert registry.async_get_issue("home_rules", f"{coordinator.config_entry.entry_id}_entity_unavailable") is None


async def test_unavailable_temperature_uses_below_threshold_default(coord_factory) -> None:
    """Unavailable temperature defaults to threshold-0.1°C so cooling is not triggered."""
    from custom_components.home_rules.rules import HomeOutput

    # High generation but temperature unknown: fallback keeps temp below threshold.
    coordinator = await coord_factory(temperature="unavailable")
    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator.data.temperature_c < coordinator.parameters.temperature_threshold


async def test_unavailable_humidity_uses_above_threshold_default(coord_factory) -> None:
    """Unavailable humidity defaults to threshold+1% so COOL mode is not chosen (DRY instead)."""
    from custom_components.home_rules.rules import HomeOutput

    # High generation, humidity unknown: fallback exceeds humidity threshold, so DRY not COOL.
    coordinator = await coord_factory(humidity="unavailable")
    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.DRY
    assert coordinator.data.humidity_percent > coordinator.parameters.humidity_threshold
