"""Coordinator HVAC mode regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_execute_adjustment_sets_explicit_hvac_mode(hass, coord_factory) -> None:
    """Verify set_hvac_mode is called explicitly before set_temperature in solar cooling mode."""
    from custom_components.home_rules.const import ControlMode

    calls: list[tuple[str, str, dict[str, Any]]] = []

    async def record_service_call(call) -> None:
        calls.append((call.domain, call.service, dict(call.data)))

    hass.services.async_register("climate", "set_hvac_mode", record_service_call)
    hass.services.async_register("climate", "set_temperature", record_service_call)

    # Register services before any solar cooling evaluation runs.
    coordinator = await coord_factory()  # monitor mode by default, high generation
    await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)  # triggers solar cooling evaluation → COOL

    assert calls == [
        ("climate", "set_hvac_mode", {"entity_id": "climate.test", "hvac_mode": "cool"}),
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.test", "temperature": coordinator.parameters.temperature_cool},
        ),
    ]
