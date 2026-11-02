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
    assert coordinator._last_record["dry_run"] is True  # safety default
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
    assert coordinator._last_record["dry_run"] is False


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


async def test_async_set_control_disables_dry_mode(coord_factory) -> None:
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="3500", humidity="70")
    await coordinator.async_set_control("dry_mode_enabled", False)

    assert coordinator.dry_mode_enabled is False
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == "Dry mode disabled"


async def test_afternoon_cooling_gates_before_start_hour(coord_factory, monkeypatch) -> None:
    from datetime import UTC, datetime

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="6000", temperature="26")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: datetime(2026, 3, 15, 13, 59, tzinfo=UTC))
    await coordinator.async_set_control("afternoon_cooling", True)

    assert coordinator.afternoon_cooling is True
    assert (coordinator.data.adjustment, coordinator._last_record["reason"]) == (
        HomeOutput.NO_CHANGE,
        "Before afternoon cooling time",
    )

    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: datetime(2026, 3, 15, 14, 0, tzinfo=UTC))
    await coordinator.async_run_evaluation("test")
    assert coordinator.data.adjustment is HomeOutput.COOL


@pytest.mark.parametrize("start_hour", [None, 16])
async def test_boost_only_applies_in_afternoon(hass, coord_factory, monkeypatch, start_hour) -> None:
    from datetime import datetime

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import CONF_AFTERNOON_COOLING_HOUR, CONF_TEMPERATURE_COOL, ControlMode
    from custom_components.home_rules.rules import HomeOutput

    cooling_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    off_calls = async_mock_service(hass, "climate", "turn_off")
    options = {CONF_TEMPERATURE_COOL: 21}
    if start_hour is not None:
        options[CONF_AFTERNOON_COOLING_HOUR] = start_hour
    coordinator = await coord_factory(generation="1134", temperature="21.2", humidity="71", options=options)
    now = datetime.fromisoformat("2026-11-03T08:04:00+11:00")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: now)
    await coordinator.async_set_mode(ControlMode.BOOST_COOLING)

    morning = coordinator.data
    assert morning.adjustment is HomeOutput.NO_CHANGE
    assert not cooling_calls

    now = now.replace(hour=(start_hour or 14) - 1, minute=59)
    await coordinator.async_run_evaluation("poll")
    before_start = coordinator.data
    assert before_start.adjustment is HomeOutput.NO_CHANGE
    assert not cooling_calls

    now = now.replace(hour=start_hour or 14, minute=0)
    await coordinator.async_run_evaluation("poll")
    afternoon = coordinator.data
    assert afternoon.adjustment is HomeOutput.COOL
    assert coordinator._last_record["reason"] == "Boost solar available"
    assert len(cooling_calls) == 1

    hass.states.async_set("climate.test", "cool")
    hass.states.async_set("sensor.grid", "1000", {"unit_of_measurement": "W"})
    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record["reason"] == "Boost grid tolerated"

    now = now.replace(day=4, hour=8)
    await coordinator.async_run_evaluation("poll")
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.OFF
    assert coordinator._last_record["reason"] == "Grid usage too high"
    assert len(off_calls) == 1
    assert coordinator.control_mode is ControlMode.BOOST_COOLING


@pytest.mark.parametrize(
    ("generation", "temperature", "adjustment", "reason"),
    [
        ("6000", "23", "No Change", "Temperature below threshold"),
        ("1134", "25", "No Change", "No change"),
        ("6000", "25", "Cool", "Solar above cool threshold"),
    ],
)
async def test_boost_uses_normal_solar_rules_in_morning(
    hass, coord_factory, monkeypatch, generation, temperature, adjustment, reason
) -> None:
    from datetime import datetime

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import ControlMode

    cooling_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: datetime.fromisoformat("2026-11-03T08:04:00+11:00"))
    coordinator = await coord_factory(generation=generation, temperature=temperature)
    await coordinator.async_set_mode(ControlMode.BOOST_COOLING)

    assert coordinator.data.adjustment == adjustment
    assert coordinator._last_record["reason"] == reason
    assert len(cooling_calls) == (1 if adjustment == "Cool" else 0)


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
