"""Regression tests for unavailable input entities."""

from __future__ import annotations

import pytest


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


async def test_unavailable_temperature_is_not_synthesised(coord_factory) -> None:
    """Unavailable temperature remains unavailable rather than becoming a plausible value."""
    from custom_components.home_rules.rules import HomeOutput

    # High generation but temperature unknown: fallback keeps temperature below the comfort boundary.
    coordinator = await coord_factory(temperature="unavailable")
    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["temperature"] is None
    assert coordinator._last_record["temperature_available"] is False


async def test_unavailable_humidity_is_not_synthesised(coord_factory) -> None:
    """Unavailable humidity remains unavailable and only blocks decisions that need it."""
    from custom_components.home_rules.rules import R_HUMIDITY_UNAVAILABLE, HomeOutput

    # High generation should still allow COOL, and mid generation should avoid DRY.
    coordinator = await coord_factory(humidity="unavailable")
    await coordinator.async_run_evaluation("poll")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record["humidity"] is None

    coordinator = await coord_factory(generation="3500", humidity="unavailable")
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == R_HUMIDITY_UNAVAILABLE


@pytest.mark.parametrize("temperature", ["unknown", "unavailable", "nan"])
async def test_missing_temperature_does_not_stop_boost_at_synthetic_target(
    hass, coord_factory, freezer, temperature
) -> None:
    from datetime import timedelta

    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import CONF_TEMPERATURE_COOL, CONF_TEMPERATURE_THRESHOLD, ControlMode
    from custom_components.home_rules.rules import R_TEMPERATURE_UNAVAILABLE, HomeOutput

    async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(
        temperature="25", options={CONF_TEMPERATURE_THRESHOLD: 24, CONF_TEMPERATURE_COOL: 23.95}
    )
    from custom_components.home_rules.const import PowerPolicy

    coordinator.power_policy = PowerPolicy.ALLOW_BATTERY_GRID
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("initial")
    hass.states.async_set("climate.test", "cool")
    hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == R_TEMPERATURE_UNAVAILABLE
    assert not stops

    hass.states.async_set("climate.test", "off")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=coordinator.parameters.reactivate_delay))
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == R_TEMPERATURE_UNAVAILABLE
