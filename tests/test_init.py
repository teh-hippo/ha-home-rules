"""Integration lifecycle tests for Home Rules."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_setup_and_unload_entry(hass, mock_entry) -> None:
    """Config entry should set up and unload cleanly through HA lifecycle APIs."""
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state == ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state == ConfigEntryState.NOT_LOADED


@pytest.mark.parametrize("forecast", ["0", "invalid"])
async def test_setup_removes_retired_controls(hass, mock_entry, hass_storage, forecast) -> None:
    from homeassistant.helpers import entity_registry as er

    from custom_components.home_rules.const import CONF_TEMPERATURE_COOL, DOMAIN, RETIRED_CONFIG_KEYS, STORAGE_VERSION
    from custom_components.home_rules.rules import HomeOutput

    hass.states.async_set("sensor.forecast", forecast, {"unit_of_measurement": "kWh"})
    hass.config_entries.async_update_entry(
        mock_entry,
        data={**mock_entry.data, "forecast_entity_id": "sensor.forecast", "battery_soc_entity_id": "sensor.missing"},
        options={
            "forecast_entity_id": "sensor.forecast",
            "forecast_min_kwh": 10,
            "battery_min_soc": 99,
            "battery_soc_entity_id": "sensor.missing",
            "generation_boost_threshold": 500,
            CONF_TEMPERATURE_COOL: 20,
        },
    )
    storage_key = f"{DOMAIN}_{mock_entry.entry_id}"
    hass_storage[storage_key] = {
        "version": STORAGE_VERSION,
        "data": {"parameters": {"forecast_min_kwh": 20, "battery_min_soc": 99, CONF_TEMPERATURE_COOL: 21}},
    }
    registry = er.async_get(hass)
    retired = [
        registry.async_get_or_create(
            "number",
            DOMAIN,
            f"{mock_entry.entry_id}_{key}",
            config_entry=mock_entry,
            suggested_object_id=f"hallway_home_rules_{name}",
        )
        for key, name in (
            ("forecast_min_kwh", "forecast_minimum_remaining"),
            ("battery_min_soc", "battery_minimum_charge"),
        )
    ]

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    for entity in retired:
        assert registry.async_get(entity.entity_id) is None
        assert hass.states.get(entity.entity_id) is None
    assert not RETIRED_CONFIG_KEYS.intersection(mock_entry.data)
    assert mock_entry.options == {CONF_TEMPERATURE_COOL: 20}
    assert hass_storage[storage_key]["data"]["parameters"] == {CONF_TEMPERATURE_COOL: 21}
    assert hass.states.get("number.home_rules_cool_setpoint").state == "21.0"
    coordinator = mock_entry.runtime_data
    assert coordinator.data.adjustment is HomeOutput.COOL
    assert not {"forecast_low", "forecast_kwh", "battery_low", "battery_soc"}.intersection(coordinator._last_record)

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert all(registry.async_get(entity.entity_id) is None for entity in retired)


async def test_options_update_triggers_reload(hass, loaded_entry) -> None:
    """Updating options should invoke the registered config entry reload listener."""
    with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as mock_reload:
        hass.config_entries.async_update_entry(loaded_entry, options={"eval_interval": 120})
        await hass.async_block_till_done()

    mock_reload.assert_awaited_once_with(loaded_entry.entry_id)


async def test_boost_restores_automatic_run_without_solar(hass, mock_entry, hass_storage) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import DOMAIN, STORAGE_VERSION, ControlMode, PowerPolicy
    from custom_components.home_rules.rules import R_MAINTAIN_TARGET, HomeOutput

    stops = async_mock_service(hass, "climate", "turn_off")
    hass.states.async_set("climate.test", "cool")
    hass.states.async_set("sensor.generation", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "1200", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.temperature", "23", {"unit_of_measurement": "°C"})
    hass_storage[f"{DOMAIN}_{mock_entry.entry_id}"] = {
        "version": STORAGE_VERSION,
        "data": {"controls": {"mode": "boost_cooling"}, "auto_mode": True, "session": {"last": "Cool"}},
    }

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_entry.runtime_data
    assert coordinator._last_record["reason"] == R_MAINTAIN_TARGET
    assert coordinator.control_mode is ControlMode.AUTOMATIC
    assert coordinator.power_policy is PowerPolicy.ALLOW_BATTERY_GRID
    assert coordinator.data.auto_mode
    assert not stops

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = mock_entry.runtime_data
    hass.states.async_set("sensor.temperature", "22", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
    assert coordinator._last_record["reason"] == R_MAINTAIN_TARGET
    assert not stops


async def test_setup_retry_for_unavailable_required_entity_does_not_create_runtime_issue(hass, mock_entry) -> None:
    """Unavailable required entities during startup should retry setup without runtime repair issues."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.home_rules.const import DOMAIN, ISSUE_RUNTIME

    hass.states.async_set("climate.test", "unavailable")
    assert await hass.config_entries.async_setup(mock_entry.entry_id) is False
    await hass.async_block_till_done()
    assert mock_entry.state == ConfigEntryState.SETUP_RETRY

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"{mock_entry.entry_id}_{ISSUE_RUNTIME}") is None
