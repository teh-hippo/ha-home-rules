"""Coordinator HVAC mode regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_execute_adjustment_sets_explicit_hvac_mode(hass) -> None:
    """Ensure we never rely on set_temperature(hvac_mode=...) to change HVAC mode."""

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
    coordinator.controls.dry_run = False

    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def record_service_call(call) -> None:
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("climate", "set_hvac_mode", record_service_call)
    hass.services.async_register("climate", "set_temperature", record_service_call)

    await coordinator._execute_adjustment(HomeOutput.COOL)

    assert calls == [
        ("climate", "set_hvac_mode", {"entity_id": "climate.test", "hvac_mode": "cool"}),
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.test", "temperature": coordinator.parameters.temperature_cool},
        ),
    ]
