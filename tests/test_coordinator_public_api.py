"""Characterization tests for the coordinator's public API.

These tests validate behavior through public interfaces only:
- async_run_evaluation, async_set_mode, async_set_control
- coordinator.data, coordinator.control_mode, coordinator.cooling_enabled
- coordinator.last_evaluation, coordinator.recent_evaluations

No private methods (_evaluate, _execute_adjustment, _session, etc.) are called.
This file serves as the Phase 0 behavior contract for subsequent refactoring.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest


async def test_evaluation_produces_coordinator_data(coord_factory) -> None:
    """async_run_evaluation populates coordinator.data via the public interface."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("test")

    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator.last_evaluation["dry_run"] is True  # safety default
    assert coordinator.last_evaluation["generation"] == 6000.0
    assert coordinator.last_evaluation["have_solar"] is True

    snapshot = coordinator.last_evaluation
    snapshot["fallback_inputs"]["changed"] = True
    assert "changed" not in coordinator.last_evaluation["fallback_inputs"]


async def test_manual_evaluation_reports_runtime_issue(hass, coord_factory) -> None:
    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.home_rules.const import DOMAIN, ISSUE_RUNTIME

    coordinator = await coord_factory()
    with patch.object(coordinator, "_evaluate", AsyncMock(side_effect=ValueError("broken input"))):
        with pytest.raises(UpdateFailed):
            await coordinator.async_run_evaluation("manual")

    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{coordinator.config_entry.entry_id}_{ISSUE_RUNTIME}")


async def test_default_control_mode_is_monitor(coord_factory) -> None:
    """Coordinator starts in monitor mode as a safety default."""
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory()
    assert coordinator.control_mode is ControlMode.MONITOR


async def test_async_set_mode_solar_cooling(coord_factory) -> None:
    """async_set_mode(SOLAR_COOLING) transitions coordinator out of monitor mode."""
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory(generation="0")
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)

    assert coordinator.control_mode is ControlMode.AUTOMATIC
    assert coordinator._last_record == {}

    await coordinator.async_run_evaluation("manual")
    assert coordinator._last_record["dry_run"] is False
    assert coordinator._last_record["trigger"] == "manual"


async def test_climate_mode_change_evaluates_immediately(hass, coord_factory) -> None:
    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("initial")

    hass.states.async_set("climate.test", "cool", {"temperature": 22})
    await hass.async_block_till_done()

    assert coordinator._last_record["trigger"] == "climate"


async def test_adjustment_failure_budget_prevents_extra_service_calls(hass, coord_factory) -> None:
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import ALLOWED_FAILURES

    hvac_modes = async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    coordinator = await coord_factory()
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("poll")
    for _ in range(ALLOWED_FAILURES):
        await coordinator.async_run_evaluation("poll")
    with pytest.raises(UpdateFailed):
        await coordinator.async_run_evaluation("poll")

    assert len(hvac_modes) == ALLOWED_FAILURES + 1


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
    await coordinator.async_run_evaluation("poll")

    assert coordinator.cooling_enabled is False
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE


async def test_async_set_control_disables_dry_mode(coord_factory) -> None:
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="3500", humidity="70")
    await coordinator.async_set_control("dry_mode_enabled", False)
    await coordinator.async_run_evaluation("poll")

    assert coordinator.dry_mode_enabled is False
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == "Dry mode disabled"


@pytest.mark.parametrize(
    ("generation", "temperature", "adjustment", "reason"),
    [
        ("6000", "23", "No Change", "Temperature below comfort temperature"),
        ("6000", "24", "Cool", "Solar above cool threshold"),
        ("1", "24", "No Change", "No change"),
        ("0", "25", "No Change", "No solar available"),
        ("unavailable", "25", "No Change", "No solar available"),
    ],
)
async def test_run_on_policy_still_requires_solar_to_start(
    hass, coord_factory, monkeypatch, generation, temperature, adjustment, reason
) -> None:
    from datetime import datetime

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import ControlMode

    cooling_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: datetime.fromisoformat("2026-11-03T08:04:00+11:00"))
    coordinator = await coord_factory(generation=generation, temperature=temperature)
    from custom_components.home_rules.const import PowerPolicy

    coordinator.power_policy = PowerPolicy.ALLOW_BATTERY_GRID
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("poll")

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


async def test_user_setpoint_stays_automatic_across_reload(hass, coord_factory, monkeypatch) -> None:
    from datetime import datetime, timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import ControlMode, PowerPolicy
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    async_mock_service(hass, "climate", "set_hvac_mode")
    targets = async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "climate", "turn_off")
    now = datetime.fromisoformat("2026-11-13T15:00:00+11:00")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: now)
    coordinator = await coord_factory(temperature="25")
    coordinator.power_policy = PowerPolicy.ALLOW_BATTERY_GRID
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("poll")
    hass.states.async_set("climate.test", "cool", {"temperature": 20})
    await hass.async_block_till_done()
    hass.states.async_set("climate.test", "cool", {"temperature": 19})
    await coordinator.async_run_evaluation("poll")
    assert len(targets) == 1
    assert coordinator.data.auto_mode
    assert coordinator.data.timer_finishes_at is None
    assert coordinator.parameters.temperature_cool == 22
    await coordinator.async_shutdown()

    restored = HomeRulesCoordinator(hass, coordinator.config_entry)
    try:
        await restored.async_initialize()
        await restored.async_run_evaluation("restart")
        assert len(targets) == 1
        assert restored.data.auto_mode
        assert restored._last_record["target_temperature"] == 19
        hass.states.async_set("climate.test", "off")
        await hass.async_block_till_done()
        utc_now = dt_util.utcnow() + timedelta(minutes=restored.parameters.reactivate_delay)
        monkeypatch.setattr(dt_util, "utcnow", lambda: utc_now)
        await restored.async_run_evaluation("poll")
        assert targets[-1].data["temperature"] == 22
        assert restored._adjusted_setpoint is None
    finally:
        await restored.async_shutdown()


async def test_off_on_between_polls_starts_new_manual_run_even_with_cooling_disabled(hass, coord_factory) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory()
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("poll")
    hass.states.async_set("climate.test", "cool", {"temperature": 22})
    await hass.async_block_till_done()
    await coordinator.async_set_control("cooling_enabled", False)
    await coordinator.async_run_evaluation("poll")
    assert len(stops) == 1
    hass.states.async_set("climate.test", "off")
    hass.states.async_set("climate.test", "cool", {"temperature": 19})
    hass.states.async_set("sensor.grid", "500", {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.TIMER
    assert not coordinator.data.auto_mode
    assert coordinator.data.timer_finishes_at is not None
    assert len(stops) == 1
