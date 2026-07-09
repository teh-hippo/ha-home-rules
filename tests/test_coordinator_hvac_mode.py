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

    coordinator = await coord_factory()
    await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)

    assert calls == [
        ("climate", "set_hvac_mode", {"entity_id": "climate.test", "hvac_mode": "cool"}),
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.test", "temperature": coordinator.parameters.temperature_cool},
        ),
    ]


async def test_stale_auto_mode_self_heals_for_heat(hass, coord_factory) -> None:
    """A stale auto=True (home-rules ran cool, user then switched to HEAT) self-heals to
    auto=False and starts a manual cap instead of flipping the unit back to COOL."""
    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    commanded: list[str] = []

    async def record(call) -> None:
        commanded.append(call.data.get("hvac_mode", call.service))

    hass.services.async_register("climate", "set_hvac_mode", record)
    hass.services.async_register("climate", "set_temperature", record)
    hass.services.async_register("climate", "turn_off", record)

    # Strong free solar + heat: the old engine would have commanded COOL.
    coordinator = await coord_factory(climate="heat", generation="6000", grid="0")
    coordinator._auto_mode = True  # simulate a prior cool cycle that home-rules owned
    await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)

    assert coordinator._auto_mode is False  # self-healed: heat is never home-rules-owned
    assert coordinator.data.adjustment is HomeOutput.TIMER  # capped, not cooled
    assert "cool" not in commanded  # never issued set_hvac_mode: cool on a heat run
