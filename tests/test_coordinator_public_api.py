"""Characterization tests for the coordinator's public API.

These tests validate behavior through public interfaces only:
- async_run_evaluation, async_set_mode, async_set_control
- coordinator.data, coordinator.control_mode, coordinator.cooling_enabled

No private methods (_evaluate, _execute_adjustment, _session, etc.) are called.
This file serves as the Phase 0 behavior contract for subsequent refactoring.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_evaluation_produces_coordinator_data(coord_factory) -> None:
    """async_run_evaluation populates coordinator.data via the public interface."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator.data.dry_run is True  # safety default
    assert coordinator._last_record["generation"] == 6000.0
    assert coordinator._last_record["have_solar"] is True


async def test_default_control_mode_is_monitor(coord_factory) -> None:
    """Coordinator starts in monitor mode as a safety default."""
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory()
    assert coordinator.control_mode is ControlMode.MONITOR


async def test_async_set_mode_solar_cooling(coord_factory) -> None:
    """async_set_mode(SOLAR_COOLING) transitions coordinator out of monitor mode."""
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory(generation="0")
    await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)

    assert coordinator.control_mode is ControlMode.SOLAR_COOLING
    assert coordinator.data.dry_run is False


async def test_async_set_mode_disabled(coord_factory) -> None:
    """async_set_mode(DISABLED) disables the coordinator."""
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory()
    await coordinator.async_set_mode(ControlMode.DISABLED)

    assert coordinator.control_mode is ControlMode.DISABLED


async def test_async_set_control_disables_cooling(coord_factory) -> None:
    """async_set_control disables cooling and re-evaluates; no COOL adjustment is made."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()
    await coordinator.async_set_control("cooling_enabled", False)

    assert coordinator.cooling_enabled is False
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE


async def test_evaluation_fires_ha_event(hass, coord_factory) -> None:
    """Each evaluation fires an EVENT_EVALUATION event on the HA event bus."""
    from custom_components.home_rules.const import EVENT_EVALUATION

    events: list[Any] = []
    hass.bus.async_listen(EVENT_EVALUATION, lambda e: events.append(e))

    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("characterization")
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["trigger"] == "characterization"
