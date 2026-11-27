"""Options flow tests for Home Rules."""

from __future__ import annotations

from homeassistant.data_entry_flow import FlowResultType


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
        CONF_REACTIVATE_DELAY_MINUTES,
        CONF_SOLAR_RUN_ON_MINUTES,
        CONF_TEMPERATURE_ENTITY_ID,
        DEFAULT_AIRCON_TIMER_DURATION,
        DEFAULT_EVAL_INTERVAL,
        DEFAULT_GENERATION_COOL_THRESHOLD,
        DEFAULT_GENERATION_DRY_THRESHOLD,
        DEFAULT_GRID_USAGE_DELAY,
        DEFAULT_REACTIVATE_DELAY_MINUTES,
        DEFAULT_SOLAR_RUN_ON_MINUTES,
    )

    return {
        CONF_CLIMATE_ENTITY_ID: "climate.test",
        CONF_GENERATION_ENTITY_ID: "sensor.generation",
        CONF_GRID_ENTITY_ID: "sensor.grid",
        CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
        CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        CONF_AIRCON_TIMER_DURATION: DEFAULT_AIRCON_TIMER_DURATION,
        CONF_EVAL_INTERVAL: DEFAULT_EVAL_INTERVAL,
        CONF_GENERATION_COOL_THRESHOLD: DEFAULT_GENERATION_COOL_THRESHOLD,
        CONF_GENERATION_DRY_THRESHOLD: DEFAULT_GENERATION_DRY_THRESHOLD,
        CONF_GRID_USAGE_DELAY: DEFAULT_GRID_USAGE_DELAY,
        CONF_REACTIVATE_DELAY_MINUTES: DEFAULT_REACTIVATE_DELAY_MINUTES,
        CONF_SOLAR_RUN_ON_MINUTES: DEFAULT_SOLAR_RUN_ON_MINUTES,
    }


async def test_options_flow_updates_values_and_accepts_notify_service(hass, mock_entry) -> None:
    """Options flow should accept valid inputs and persist selected notify service."""
    from custom_components.home_rules.const import (
        CONF_NOTIFICATION_SERVICE,
        CONF_REACTIVATE_DELAY_MINUTES,
        CONF_SOLAR_RUN_ON_MINUTES,
    )

    async def _notify_service(call) -> None:
        return None

    hass.services.async_register("notify", "mobile_app_test", _notify_service)

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    user_input = _valid_options_input()
    user_input[CONF_NOTIFICATION_SERVICE] = "notify.mobile_app_test"
    user_input[CONF_REACTIVATE_DELAY_MINUTES] = 12.5
    user_input[CONF_SOLAR_RUN_ON_MINUTES] = 37
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NOTIFICATION_SERVICE] == "notify.mobile_app_test"
    assert result["data"][CONF_REACTIVATE_DELAY_MINUTES] == 12.5
    assert result["data"][CONF_SOLAR_RUN_ON_MINUTES] == 37


async def test_options_flow_preserves_temporarily_missing_notify_service(hass, mock_entry) -> None:
    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE

    service = "notify.mobile_app_temporarily_missing"
    hass.config_entries.async_update_entry(mock_entry, options={CONF_NOTIFICATION_SERVICE: service})
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input[CONF_NOTIFICATION_SERVICE] = service
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_NOTIFICATION_SERVICE] == service


async def test_options_flow_accepts_percentage_battery_sensor(hass, mock_entry) -> None:
    from custom_components.home_rules.const import CONF_BATTERY_SOC_ENTITY_ID

    hass.states.async_set("sensor.battery_soc", "100", {"unit_of_measurement": "%"})
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input[CONF_BATTERY_SOC_ENTITY_ID] = "sensor.battery_soc"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BATTERY_SOC_ENTITY_ID] == "sensor.battery_soc"


async def test_options_flow_rejects_non_percentage_battery_sensor(hass, mock_entry) -> None:
    from custom_components.home_rules.const import CONF_BATTERY_SOC_ENTITY_ID

    hass.states.async_set("sensor.battery_soc", "100", {"unit_of_measurement": "V"})
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input[CONF_BATTERY_SOC_ENTITY_ID] = "sensor.battery_soc"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_percentage_unit"}


async def test_options_flow_accepts_person_for_comfort_occupancy(hass, mock_entry) -> None:
    from custom_components.home_rules.const import CONF_OCCUPANCY_ENTITY_ID

    hass.states.async_set("person.camille", "not_home")
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input[CONF_OCCUPANCY_ENTITY_ID] = "person.camille"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OCCUPANCY_ENTITY_ID] == "person.camille"


async def test_options_flow_accepts_afternoon_forecast_and_deadline(hass, mock_entry) -> None:
    from custom_components.home_rules.const import (
        CONF_AFTERNOON_BATTERY_RESERVE,
        CONF_AFTERNOON_ENERGY_BUDGET,
        CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID,
        CONF_AFTERNOON_READY_BY,
    )

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input.update(
        {
            CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID: "forecast-entry",
            CONF_AFTERNOON_READY_BY: "17:30:00",
            CONF_AFTERNOON_ENERGY_BUDGET: 6.5,
            CONF_AFTERNOON_BATTERY_RESERVE: 45,
        }
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID] == "forecast-entry"
    assert result["data"][CONF_AFTERNOON_READY_BY] == "17:30:00"
    assert result["data"][CONF_AFTERNOON_ENERGY_BUDGET] == 6.5
    assert result["data"][CONF_AFTERNOON_BATTERY_RESERVE] == 45


async def test_options_flow_validates_entities(hass, mock_entry) -> None:
    """Options flow should return entity_not_found for missing entities."""
    from custom_components.home_rules.const import CONF_CLIMATE_ENTITY_ID

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    user_input = _valid_options_input()
    user_input[CONF_CLIMATE_ENTITY_ID] = "climate.missing"
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_found"}


async def test_target_behaviour_is_no_longer_an_options_selector(hass, mock_entry) -> None:
    from custom_components.home_rules.const import CONF_MANUAL_COOLING_BEHAVIOUR

    hass.config_entries.async_update_entry(mock_entry, options={CONF_MANUAL_COOLING_BEHAVIOUR: "ask"})
    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    assert CONF_MANUAL_COOLING_BEHAVIOUR not in {str(key) for key in result["data_schema"].schema}
    result = await hass.config_entries.options.async_configure(result["flow_id"], _valid_options_input())

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_MANUAL_COOLING_BEHAVIOUR not in result["data"]
