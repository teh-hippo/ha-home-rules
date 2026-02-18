"""Config flow tests for Home Rules."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

pytest.importorskip("pytest_homeassistant_custom_component")


def _seed_valid_states(hass: HomeAssistant) -> None:
    hass.states.async_set("climate.ac", "off")
    hass.states.async_set("timer.sleep", "idle")
    hass.states.async_set("sensor.solar_generation", "6000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid_usage", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.temp", "25", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.humidity", "40", {"unit_of_measurement": "%"})


async def _start_user_flow(hass: HomeAssistant) -> ConfigFlowResult:
    from custom_components.home_rules.const import DOMAIN

    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )


async def _move_to_solar_step(hass: HomeAssistant) -> ConfigFlowResult:
    from custom_components.home_rules.const import CONF_CLIMATE_ENTITY_ID, CONF_TIMER_ENTITY_ID

    _seed_valid_states(hass)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_CLIMATE_ENTITY_ID: "climate.ac",
            CONF_TIMER_ENTITY_ID: "timer.sleep",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "solar"
    return result


async def _move_to_comfort_step(hass: HomeAssistant) -> ConfigFlowResult:
    from custom_components.home_rules.const import CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID

    result = await _move_to_solar_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_GENERATION_ENTITY_ID: "sensor.solar_generation",
            CONF_GRID_ENTITY_ID: "sensor.grid_usage",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "comfort"
    return result


async def test_config_flow_happy_path_creates_entry(hass) -> None:
    """The full user -> solar -> comfort flow should create an entry with defaults."""
    from custom_components.home_rules.const import (
        CONF_CLIMATE_ENTITY_ID,
        CONF_EVAL_INTERVAL,
        CONF_GENERATION_COOL_THRESHOLD,
        CONF_GENERATION_DRY_THRESHOLD,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_GRID_USAGE_DELAY,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_HUMIDITY_THRESHOLD,
        CONF_REACTIVATE_DELAY,
        CONF_TEMPERATURE_COOL,
        CONF_TEMPERATURE_ENTITY_ID,
        CONF_TEMPERATURE_THRESHOLD,
        CONF_TIMER_ENTITY_ID,
        DEFAULT_EVAL_INTERVAL,
        DEFAULT_GENERATION_COOL_THRESHOLD,
        DEFAULT_GENERATION_DRY_THRESHOLD,
        DEFAULT_GRID_USAGE_DELAY,
        DEFAULT_HUMIDITY_THRESHOLD,
        DEFAULT_REACTIVATE_DELAY,
        DEFAULT_TEMPERATURE_COOL,
        DEFAULT_TEMPERATURE_THRESHOLD,
    )

    result = await _move_to_comfort_step(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_TEMPERATURE_ENTITY_ID: "sensor.temp",
            CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Rules"
    assert result["data"] == {
        CONF_CLIMATE_ENTITY_ID: "climate.ac",
        CONF_TIMER_ENTITY_ID: "timer.sleep",
        CONF_GENERATION_ENTITY_ID: "sensor.solar_generation",
        CONF_GRID_ENTITY_ID: "sensor.grid_usage",
        CONF_TEMPERATURE_ENTITY_ID: "sensor.temp",
        CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
    }
    assert result["options"] == {
        CONF_EVAL_INTERVAL: DEFAULT_EVAL_INTERVAL,
        CONF_GENERATION_COOL_THRESHOLD: DEFAULT_GENERATION_COOL_THRESHOLD,
        CONF_GENERATION_DRY_THRESHOLD: DEFAULT_GENERATION_DRY_THRESHOLD,
        CONF_HUMIDITY_THRESHOLD: DEFAULT_HUMIDITY_THRESHOLD,
        CONF_TEMPERATURE_THRESHOLD: DEFAULT_TEMPERATURE_THRESHOLD,
        CONF_TEMPERATURE_COOL: DEFAULT_TEMPERATURE_COOL,
        CONF_GRID_USAGE_DELAY: DEFAULT_GRID_USAGE_DELAY,
        CONF_REACTIVATE_DELAY: DEFAULT_REACTIVATE_DELAY,
    }


async def test_config_flow_rejects_missing_entities(hass) -> None:
    """Missing selected entities should return entity_not_found."""
    from custom_components.home_rules.const import CONF_CLIMATE_ENTITY_ID, CONF_TIMER_ENTITY_ID

    hass.states.async_set("timer.sleep", "idle")
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_CLIMATE_ENTITY_ID: "climate.missing",
            CONF_TIMER_ENTITY_ID: "timer.sleep",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}


async def test_config_flow_rejects_invalid_power_unit(hass) -> None:
    """Solar step should reject unsupported power units."""
    from custom_components.home_rules.const import (
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
    )

    result = await _move_to_solar_step(hass)
    hass.states.async_set("sensor.bad_power", "1", {"unit_of_measurement": "kWh"})
    invalid_power = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_GENERATION_ENTITY_ID: "sensor.bad_power",
            CONF_GRID_ENTITY_ID: "sensor.grid_usage",
        },
    )
    assert invalid_power["errors"] == {"base": "invalid_power_unit"}


async def test_config_flow_aborts_when_already_configured(hass) -> None:
    """Single entry integration should abort additional user flows."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.home_rules.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={})
    entry.add_to_hass(hass)

    result = await _start_user_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] in {"already_configured", "single_instance_allowed"}


def test_validate_entities_covers_all_custom_errors(hass) -> None:
    """_validate_entities should return expected custom error codes."""
    from custom_components.home_rules.config_flow import _validate_entities
    from custom_components.home_rules.const import (
        CONF_CLIMATE_ENTITY_ID,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_INVERTER_ENTITY_ID,
        CONF_TEMPERATURE_ENTITY_ID,
        CONF_TIMER_ENTITY_ID,
    )

    hass.states.async_set("climate.ok", "off")
    hass.states.async_set("timer.ok", "idle")
    hass.states.async_set("sensor.ok", "1", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.home_rules_mode", "off", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.bad_power", "1", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.temp", "25", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.humidity", "40", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.not_timer", "idle")
    hass.states.async_set("sensor.not_climate", "off")
    hass.states.async_set("climate.not_inverter", "off")
    hass.states.async_set("timer.not_sensor", "idle")

    assert _validate_entities(
        hass,
        {CONF_CLIMATE_ENTITY_ID: "sensor.not_climate", CONF_TIMER_ENTITY_ID: "timer.ok"},
        required_keys=[CONF_CLIMATE_ENTITY_ID, CONF_TIMER_ENTITY_ID],
    ) == {"base": "invalid_climate_entity"}

    assert _validate_entities(
        hass,
        {CONF_CLIMATE_ENTITY_ID: "climate.ok", CONF_TIMER_ENTITY_ID: "sensor.not_timer"},
        required_keys=[CONF_CLIMATE_ENTITY_ID, CONF_TIMER_ENTITY_ID],
    ) == {"base": "invalid_timer_entity"}

    assert _validate_entities(
        hass,
        {CONF_GENERATION_ENTITY_ID: "sensor.home_rules_mode", CONF_GRID_ENTITY_ID: "sensor.ok"},
        required_keys=[CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID],
    ) == {"base": "invalid_entity_selection"}

    assert _validate_entities(
        hass,
        {CONF_GENERATION_ENTITY_ID: "sensor.bad_power", CONF_GRID_ENTITY_ID: "sensor.ok"},
        required_keys=[CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID],
    ) == {"base": "invalid_power_unit"}

    assert _validate_entities(
        hass,
        {
            CONF_GENERATION_ENTITY_ID: "sensor.ok",
            CONF_GRID_ENTITY_ID: "sensor.ok",
            CONF_INVERTER_ENTITY_ID: "climate.not_inverter",
        },
        required_keys=[CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID],
        allow_inverter=True,
    ) == {"base": "invalid_inverter_entity"}

    assert _validate_entities(
        hass,
        {CONF_TEMPERATURE_ENTITY_ID: "timer.not_sensor", CONF_HUMIDITY_ENTITY_ID: "sensor.humidity"},
        required_keys=[CONF_TEMPERATURE_ENTITY_ID, CONF_HUMIDITY_ENTITY_ID],
    ) == {"base": "invalid_sensor_entity"}
