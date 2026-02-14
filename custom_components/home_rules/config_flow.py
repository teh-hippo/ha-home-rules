"""Config flow for Home Rules."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_EVAL_INTERVAL,
    CONF_GENERATION_COOL_THRESHOLD,
    CONF_GENERATION_DRY_THRESHOLD,
    CONF_GENERATION_ENTITY_ID,
    CONF_GRID_ENTITY_ID,
    CONF_GRID_USAGE_DELAY,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_HUMIDITY_THRESHOLD,
    CONF_INVERTER_ENTITY_ID,
    CONF_NOTIFICATION_SERVICE,
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
    DOMAIN,
)


class HomeRulesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> HomeRulesOptionsFlow:
        """Get options flow handler."""
        return HomeRulesOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle user setup."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate_entities(user_input)
            if not errors:
                return self.async_create_entry(
                    title="Home Rules",
                    data=user_input,
                    options={
                        CONF_EVAL_INTERVAL: DEFAULT_EVAL_INTERVAL,
                        CONF_GENERATION_COOL_THRESHOLD: DEFAULT_GENERATION_COOL_THRESHOLD,
                        CONF_GENERATION_DRY_THRESHOLD: DEFAULT_GENERATION_DRY_THRESHOLD,
                        CONF_HUMIDITY_THRESHOLD: DEFAULT_HUMIDITY_THRESHOLD,
                        CONF_TEMPERATURE_THRESHOLD: DEFAULT_TEMPERATURE_THRESHOLD,
                        CONF_TEMPERATURE_COOL: DEFAULT_TEMPERATURE_COOL,
                        CONF_GRID_USAGE_DELAY: DEFAULT_GRID_USAGE_DELAY,
                        CONF_REACTIVATE_DELAY: DEFAULT_REACTIVATE_DELAY,
                    },
                )

        return self.async_show_form(step_id="user", data_schema=self._step_user_schema(), errors=errors)

    def _validate_entities(self, user_input: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        required = {
            CONF_CLIMATE_ENTITY_ID: "climate",
            CONF_TIMER_ENTITY_ID: "timer",
            CONF_GENERATION_ENTITY_ID: "generation",
            CONF_GRID_ENTITY_ID: "grid",
            CONF_TEMPERATURE_ENTITY_ID: "temperature",
            CONF_HUMIDITY_ENTITY_ID: "humidity",
        }
        for key, _label in required.items():
            entity_id = user_input[key]
            state = self.hass.states.get(entity_id)
            if state is None:
                errors["base"] = "entity_not_found"
                return errors
            if entity_id.startswith(("switch.home_rules_", "sensor.home_rules_", "binary_sensor.home_rules_")):
                errors["base"] = "invalid_entity_selection"
                return errors

            if key in (CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID):
                unit = str(state.attributes.get("unit_of_measurement", "")).lower()
                if unit not in {"", "w", "kw", "mw", "watt", "watts", "kilowatt", "kilowatts"}:
                    errors["base"] = "invalid_power_unit"
                    return errors

            if key == CONF_TIMER_ENTITY_ID and not entity_id.startswith("timer."):
                errors["base"] = "invalid_timer_entity"
                return errors

            if key == CONF_CLIMATE_ENTITY_ID and not entity_id.startswith("climate."):
                errors["base"] = "invalid_climate_entity"
                return errors

            if key == CONF_INVERTER_ENTITY_ID and not entity_id.startswith(("sensor.", "binary_sensor.")):
                errors["base"] = "invalid_inverter_entity"
                return errors

            if key in (
                CONF_GENERATION_ENTITY_ID,
                CONF_GRID_ENTITY_ID,
                CONF_TEMPERATURE_ENTITY_ID,
                CONF_HUMIDITY_ENTITY_ID,
            ):
                if not entity_id.startswith("sensor."):
                    errors["base"] = "invalid_sensor_entity"
                return errors

        inverter_entity = user_input.get(CONF_INVERTER_ENTITY_ID)
        if inverter_entity:
            state = self.hass.states.get(inverter_entity)
            if state is None:
                errors["base"] = "entity_not_found"
                return errors
            if inverter_entity.startswith(("switch.home_rules_", "sensor.home_rules_", "binary_sensor.home_rules_")):
                errors["base"] = "invalid_entity_selection"
                return errors
            if not inverter_entity.startswith(("sensor.", "binary_sensor.")):
                errors["base"] = "invalid_inverter_entity"
                return errors

        return errors

    def _step_user_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_CLIMATE_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_TIMER_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="timer")
                ),
                vol.Optional(CONF_INVERTER_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])
                ),
                vol.Required(CONF_GENERATION_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Required(CONF_GRID_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Required(CONF_TEMPERATURE_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(CONF_HUMIDITY_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
                ),
            }
        )


class HomeRulesOptionsFlow(OptionsFlow):
    """Handle options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    def _notify_service_options(self) -> list[str]:
        services = self.hass.services.async_services().get("notify", {})
        return [f"notify.{name}" for name in sorted(services)]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self._config_entry.options
        notify_options = self._notify_service_options()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EVAL_INTERVAL,
                        default=current.get(CONF_EVAL_INTERVAL, DEFAULT_EVAL_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=60)),
                    vol.Required(
                        CONF_GENERATION_COOL_THRESHOLD,
                        default=current.get(CONF_GENERATION_COOL_THRESHOLD, DEFAULT_GENERATION_COOL_THRESHOLD),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_GENERATION_DRY_THRESHOLD,
                        default=current.get(CONF_GENERATION_DRY_THRESHOLD, DEFAULT_GENERATION_DRY_THRESHOLD),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_HUMIDITY_THRESHOLD,
                        default=current.get(CONF_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_TEMPERATURE_THRESHOLD,
                        default=current.get(CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_TEMPERATURE_COOL,
                        default=current.get(CONF_TEMPERATURE_COOL, DEFAULT_TEMPERATURE_COOL),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_GRID_USAGE_DELAY,
                        default=current.get(CONF_GRID_USAGE_DELAY, DEFAULT_GRID_USAGE_DELAY),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
                    vol.Required(
                        CONF_REACTIVATE_DELAY,
                        default=current.get(CONF_REACTIVATE_DELAY, DEFAULT_REACTIVATE_DELAY),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=5)),
                    vol.Optional(
                        CONF_NOTIFICATION_SERVICE,
                        default=current.get(CONF_NOTIFICATION_SERVICE, ""),
                    ): selector.SelectSelector(selector.SelectSelectorConfig(options=notify_options))
                    if notify_options
                    else str,
                }
            ),
        )
