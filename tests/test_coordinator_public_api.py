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
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)

    assert coordinator.control_mode is ControlMode.AUTOMATIC
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


async def test_afternoon_precooling_does_not_block_normal_morning_cooling(coord_factory, monkeypatch) -> None:
    from datetime import UTC, datetime

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(generation="6000", temperature="26")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: datetime(2026, 3, 15, 13, 59, tzinfo=UTC))
    await coordinator.async_set_control("afternoon_cooling", True)

    assert coordinator.afternoon_cooling is True
    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record.get("pre_cooling") is False

    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: datetime(2026, 3, 15, 14, 0, tzinfo=UTC))
    await coordinator.async_run_evaluation("test")
    assert coordinator.data.adjustment is HomeOutput.COOL
    assert coordinator._last_record.get("pre_cooling") is True
    assert coordinator._last_record["target_temperature"] == 20


@pytest.mark.parametrize("policy", ["solar_only", "allow_battery_grid"])
async def test_precooling_window_sets_and_maintains_target_then_returns_to_comfort(
    hass, coord_factory, monkeypatch, policy
) -> None:
    from datetime import datetime

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import ControlMode, PowerPolicy
    from custom_components.home_rules.rules import HomeOutput

    cooling_calls = async_mock_service(hass, "climate", "set_hvac_mode")
    temperature_calls = async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(generation="6000", temperature="23")
    coordinator.stop_at_comfort_temperature = True
    coordinator.power_policy = PowerPolicy(policy)
    now = datetime.fromisoformat("2026-11-03T13:59:00+11:00")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: now)
    await coordinator.async_set_control("afternoon_cooling", True)
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)

    morning = coordinator.data
    assert morning.adjustment is HomeOutput.NO_CHANGE
    assert not cooling_calls

    now = now.replace(hour=14, minute=0)
    await coordinator.async_run_evaluation("poll")
    afternoon = coordinator.data
    assert afternoon.adjustment is HomeOutput.COOL
    assert len(cooling_calls) == 1
    assert temperature_calls[-1].data["temperature"] == 20
    assert coordinator._last_record.get("pre_cooling") is True

    hass.states.async_set("climate.test", "cool", {"temperature": 20})
    hass.states.async_set("sensor.temperature", "20", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert not stops

    now = now.replace(hour=17)
    hass.states.async_set("sensor.temperature", "23", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    assert coordinator._last_record.get("pre_cooling") is False
    assert temperature_calls[-1].data["temperature"] == 22

    hass.states.async_set("sensor.temperature", "21", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    assert len(stops) == 1
    assert coordinator.control_mode is ControlMode.AUTOMATIC


@pytest.mark.parametrize(
    ("generation", "temperature", "adjustment", "reason"),
    [
        ("6000", "23", "No Change", "Temperature below threshold"),
        ("1", "24", "Cool", "Battery and grid power permitted"),
        ("0", "25", "Cool", "Battery and grid power permitted"),
        ("unavailable", "25", "Cool", "Battery and grid power permitted"),
    ],
)
async def test_boost_works_in_morning_with_any_solar(
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
    from custom_components.home_rules.const import PowerPolicy

    coordinator.power_policy = PowerPolicy.ALLOW_BATTERY_GRID
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)

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


async def test_user_setpoint_stays_automatic_across_window_and_reload(hass, coord_factory, monkeypatch) -> None:
    from datetime import datetime

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import ControlMode, PowerPolicy
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    async_mock_service(hass, "climate", "set_hvac_mode")
    targets = async_mock_service(hass, "climate", "set_temperature")
    async_mock_service(hass, "climate", "turn_off")
    now = datetime.fromisoformat("2026-11-13T15:00:00+11:00")
    monkeypatch.setattr(dt_util, "now", lambda *a, **kw: now)
    coordinator = await coord_factory(temperature="25")
    coordinator.afternoon_cooling = True
    coordinator.power_policy = PowerPolicy.ALLOW_BATTERY_GRID
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    hass.states.async_set("climate.test", "cool", {"temperature": 20})
    await hass.async_block_till_done()
    hass.states.async_set("climate.test", "cool", {"temperature": 19})
    await coordinator.async_run_evaluation("poll")
    assert len(targets) == 1
    assert coordinator.data.auto_mode
    assert coordinator.data.timer_finishes_at is None
    assert coordinator.parameters.temperature_cool == 22
    assert coordinator.parameters.temperature_precool == 20
    await coordinator.async_shutdown()

    restored = HomeRulesCoordinator(hass, coordinator.config_entry)
    try:
        await restored.async_initialize()
        now = now.replace(hour=17)
        await restored.async_run_evaluation("restart")
        assert len(targets) == 1
        assert restored.data.auto_mode
        assert restored._last_record["target_temperature"] == 19
        hass.states.async_set("climate.test", "off")
        await hass.async_block_till_done()
        await restored.async_run_evaluation("poll")
        assert targets[-1].data["temperature"] == 22
        assert restored._adjusted_setpoint is None
    finally:
        await restored.async_shutdown()


async def test_off_on_between_polls_starts_new_manual_run_even_with_cooling_disabled(hass, coord_factory) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    async_mock_service(hass, "climate", "set_hvac_mode")
    async_mock_service(hass, "climate", "set_temperature")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory()
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    hass.states.async_set("climate.test", "cool", {"temperature": 22})
    await hass.async_block_till_done()
    await coordinator.async_set_control("cooling_enabled", False)
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
