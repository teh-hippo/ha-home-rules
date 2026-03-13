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


async def test_required_entity_unavailable_during_startup_is_wrapped_without_runtime_issue(hass, coord_factory) -> None:
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.home_rules.const import DOMAIN, ISSUE_RUNTIME

    coordinator = await coord_factory(climate="unavailable")
    with pytest.raises(UpdateFailed, match="Required entity not yet available: climate.test"):
        await coordinator._async_update_data()

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"{coordinator.config_entry.entry_id}_{ISSUE_RUNTIME}") is None


async def test_unavailable_temperature_uses_below_threshold_default(coord_factory) -> None:
    """Unavailable temperature defaults to threshold-0.1°C so cooling is not triggered."""
    from custom_components.home_rules.rules import HomeOutput

    # High generation but temperature unknown: fallback keeps temp below threshold.
    coordinator = await coord_factory(temperature="unavailable")
    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["temperature"] < coordinator.parameters.temperature_threshold


async def test_unavailable_humidity_biases_away_from_dry(coord_factory) -> None:
    """Unavailable humidity falls below the DRY cutoff so COOL can still be chosen."""
    from custom_components.home_rules.rules import HomeOutput

    # High generation should still allow COOL, and mid generation should avoid DRY.
    coordinator = await coord_factory(humidity="unavailable")
    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record["humidity"] < coordinator.parameters.dry_mode_humidity_cutoff

    coordinator = await coord_factory(generation="3500", humidity="unavailable")
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator.data.reason == "Humidity too low for dry mode"
