"""Regression tests for unavailable input entities."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_unavailable_generation_does_not_fail_evaluation(hass) -> None:
    from homeassistant.helpers import issue_registry as ir
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

    hass.states.async_set("climate.test", "off")
    hass.states.async_set("timer.test", "idle")
    hass.states.async_set("sensor.generation", "unavailable", {"unit_of_measurement": "W"})
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

    await coordinator._evaluate("poll")

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"{entry.entry_id}_entity_unavailable") is not None
