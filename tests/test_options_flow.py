"""Options flow tests for Home Rules."""

from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType

pytest.importorskip("pytest_homeassistant_custom_component")


def _valid_options_input() -> dict[str, str | int | float]:
    from custom_components.home_rules.const import (
        CONF_AIRCON_TIMER_DURATION,
        CONF_CLIMATE_ENTITY_ID,
        CONF_EVAL_INTERVAL,
        CONF_GENERATION_COOL_THRESHOLD,
        CONF_GENERATION_DRY_THRESHOLD,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_GRID_USAGE_DELAY,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_INVERTER_ENTITY_ID,
        CONF_REACTIVATE_DELAY,
        CONF_TEMPERATURE_ENTITY_ID,
        DEFAULT_AIRCON_TIMER_DURATION,
        DEFAULT_EVAL_INTERVAL,
        DEFAULT_GENERATION_COOL_THRESHOLD,
        DEFAULT_GENERATION_DRY_THRESHOLD,
        DEFAULT_GRID_USAGE_DELAY,
        DEFAULT_REACTIVATE_DELAY,
    )

    return {
        CONF_CLIMATE_ENTITY_ID: "climate.test",
        CONF_INVERTER_ENTITY_ID: "sensor.inverter",
        CONF_GENERATION_ENTITY_ID: "sensor.generation",
        CONF_GRID_ENTITY_ID: "sensor.grid",
        CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
        CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        CONF_AIRCON_TIMER_DURATION: DEFAULT_AIRCON_TIMER_DURATION,
        CONF_EVAL_INTERVAL: DEFAULT_EVAL_INTERVAL,
        CONF_GENERATION_COOL_THRESHOLD: DEFAULT_GENERATION_COOL_THRESHOLD,
        CONF_GENERATION_DRY_THRESHOLD: DEFAULT_GENERATION_DRY_THRESHOLD,
        CONF_GRID_USAGE_DELAY: DEFAULT_GRID_USAGE_DELAY,
        CONF_REACTIVATE_DELAY: DEFAULT_REACTIVATE_DELAY,
    }


async def test_options_flow_updates_values_and_accepts_notify_service(hass, mock_entry) -> None:
    """Options flow should accept valid inputs and persist selected notify service."""
    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE

    async def _notify_service(call) -> None:
        return None

    hass.services.async_register("notify", "mobile_app_test", _notify_service)
    hass.states.async_set("sensor.inverter", "online")

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    user_input = _valid_options_input()
    user_input[CONF_NOTIFICATION_SERVICE] = "notify.mobile_app_test"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NOTIFICATION_SERVICE] == "notify.mobile_app_test"


async def test_options_flow_validates_entities(hass, mock_entry) -> None:
    """Options flow should return entity_not_found for missing entities."""
    from custom_components.home_rules.const import CONF_CLIMATE_ENTITY_ID

    hass.states.async_set("sensor.inverter", "online")
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input[CONF_CLIMATE_ENTITY_ID] = "climate.missing"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}
