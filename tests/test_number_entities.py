"""Tests for number entity registration and coordinator parameter overrides."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_number_entities_register_on_setup(hass, loaded_entry) -> None:
    for entity_id in (
        "number.home_rules_temperature_threshold",
        "number.home_rules_cool_setpoint",
        "number.home_rules_cool_generation_threshold",
        "number.home_rules_dry_generation_threshold",
        "number.home_rules_humidity_threshold",
    ):
        assert hass.states.get(entity_id) is not None, f"{entity_id} not found"


async def test_number_entities_show_default_values(hass, loaded_entry) -> None:
    from custom_components.home_rules.const import (
        DEFAULT_GENERATION_COOL_THRESHOLD,
        DEFAULT_GENERATION_DRY_THRESHOLD,
        DEFAULT_HUMIDITY_THRESHOLD,
        DEFAULT_TEMPERATURE_COOL,
        DEFAULT_TEMPERATURE_THRESHOLD,
    )

    assert float(hass.states.get("number.home_rules_temperature_threshold").state) == DEFAULT_TEMPERATURE_THRESHOLD
    assert float(hass.states.get("number.home_rules_cool_setpoint").state) == DEFAULT_TEMPERATURE_COOL
    cool_gen = hass.states.get("number.home_rules_cool_generation_threshold").state
    assert float(cool_gen) == DEFAULT_GENERATION_COOL_THRESHOLD
    dry_gen = hass.states.get("number.home_rules_dry_generation_threshold").state
    assert float(dry_gen) == DEFAULT_GENERATION_DRY_THRESHOLD
    assert float(hass.states.get("number.home_rules_humidity_threshold").state) == DEFAULT_HUMIDITY_THRESHOLD


async def test_set_number_entity_updates_parameter(hass, loaded_entry) -> None:
    from homeassistant.const import ATTR_ENTITY_ID

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.home_rules_temperature_threshold", "value": 26.0},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert float(hass.states.get("number.home_rules_temperature_threshold").state) == 26.0


async def test_get_parameter_falls_back_to_options(coord_factory) -> None:
    from custom_components.home_rules.const import CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD

    coordinator = await coord_factory(options={CONF_TEMPERATURE_THRESHOLD: 27.0})
    assert coordinator.get_parameter(CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD) == 27.0


async def test_get_parameter_override_takes_precedence(coord_factory) -> None:
    from custom_components.home_rules.const import CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD

    coordinator = await coord_factory(options={CONF_TEMPERATURE_THRESHOLD: 27.0})
    await coordinator.async_set_parameter(CONF_TEMPERATURE_THRESHOLD, 30.0)

    assert coordinator.get_parameter(CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD) == 30.0


async def test_parameter_override_affects_evaluation(coord_factory) -> None:
    from custom_components.home_rules.const import CONF_TEMPERATURE_THRESHOLD
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(temperature="25", generation="6000")
    await coordinator.async_run_evaluation("test")
    assert coordinator.data.adjustment is HomeOutput.COOL

    await coordinator.async_set_parameter(CONF_TEMPERATURE_THRESHOLD, 30.0)
    assert coordinator.data.reason == "Temperature below threshold"
