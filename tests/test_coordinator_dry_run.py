"""Coordinator regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_dry_run_does_not_fail_on_repeated_adjustments(hass) -> None:
    """Ensure dry-run doesn't trip the failed_to_change safety counter."""

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.home_rules.const import (
        CONF_CLIMATE_ENTITY_ID,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_TEMPERATURE_ENTITY_ID,
        CONF_TIMER_ENTITY_ID,
        DOMAIN,
    )
    from custom_components.home_rules.coordinator import HomeRulesCoordinator
    from custom_components.home_rules.rules import HomeOutput

    hass.states.async_set("climate.test", "off")
    hass.states.async_set("timer.test", "idle")
    hass.states.async_set("sensor.generation", "6000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.temperature", "25", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.humidity", "40", {"unit_of_measurement": "%"})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CLIMATE_ENTITY_ID: "climate.test",
            CONF_TIMER_ENTITY_ID: "timer.test",
            CONF_GENERATION_ENTITY_ID: "sensor.generation",
            CONF_GRID_ENTITY_ID: "sensor.grid",
            CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
            CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        },
        options={},
    )
    entry.add_to_hass(hass)

    coordinator = HomeRulesCoordinator(hass, entry)
    await coordinator.async_initialize()

    for _ in range(10):
        data = await coordinator._evaluate("poll")
        assert data.adjustment is HomeOutput.COOL
