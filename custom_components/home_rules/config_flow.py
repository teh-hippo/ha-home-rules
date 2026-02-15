"""Config flow for Home Rules."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

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

_HOME_RULES_PREFIXES = (
    "switch.home_rules_",
    "select.home_rules_",
    "sensor.home_rules_",
    "binary_sensor.home_rules_",
    "button.home_rules_",
)

_VALID_POWER_UNITS = {"", "w", "kw", "mw", "watt", "watts", "kilowatt", "kilowatts"}

_DOMAIN_CHECKS: dict[str, tuple[str, str]] = {
    CONF_TIMER_ENTITY_ID: ("timer.", "invalid_timer_entity"),
    CONF_CLIMATE_ENTITY_ID: ("climate.", "invalid_climate_entity"),
}

_SENSOR_KEYS = {
    CONF_GENERATION_ENTITY_ID,
    CONF_GRID_ENTITY_ID,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_HUMIDITY_ENTITY_ID,
}


def _validate_entities(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    *,
    required_keys: list[str],
    allow_inverter: bool = False,
    check_domains: bool = True,
) -> dict[str, str]:
    """Validate entity selections shared by config and options flows."""
    errors: dict[str, str] = {}
    for key in required_keys:
        entity_id = str(user_input[key])
        state = hass.states.get(entity_id)
        if state is None:
            return {"base": "entity_not_found"}
        if entity_id.startswith(_HOME_RULES_PREFIXES):
            return {"base": "invalid_entity_selection"}

        if key in (CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID):
            unit = str(state.attributes.get("unit_of_measurement", "")).lower()
            if unit not in _VALID_POWER_UNITS:
                return {"base": "invalid_power_unit"}

        if check_domains:
            domain_check = _DOMAIN_CHECKS.get(key)
            if domain_check and not entity_id.startswith(domain_check[0]):
                return {"base": domain_check[1]}

            if key in _SENSOR_KEYS and not entity_id.startswith("sensor."):
                return {"base": "invalid_sensor_entity"}

    if allow_inverter:
        inverter_entity = str(user_input.get(CONF_INVERTER_ENTITY_ID, "")).strip()
        if inverter_entity:
            state = hass.states.get(inverter_entity)
            if state is None:
                return {"base": "entity_not_found"}
            if inverter_entity.startswith(_HOME_RULES_PREFIXES):
                return {"base": "invalid_entity_selection"}
            if not inverter_entity.startswith(("sensor.", "binary_sensor.")):
                return {"base": "invalid_inverter_entity"}

    return errors


class HomeRulesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

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
            errors = _validate_entities(
                self.hass, user_input, required_keys=[CONF_CLIMATE_ENTITY_ID, CONF_TIMER_ENTITY_ID]
            )
            if not errors:
                self._data.update(user_input)
                return await self.async_step_solar()

        return self.async_show_form(step_id="user", data_schema=self._step_user_schema(), errors=errors)

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure solar inputs."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(
                self.hass,
                user_input,
                required_keys=[CONF_GENERATION_ENTITY_ID, CONF_GRID_ENTITY_ID],
                allow_inverter=True,
            )
            if not errors:
                self._data.update(user_input)
                return await self.async_step_comfort()

        return self.async_show_form(step_id="solar", data_schema=self._step_solar_schema(), errors=errors)

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Configure comfort inputs and complete setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(
                self.hass, user_input, required_keys=[CONF_TEMPERATURE_ENTITY_ID, CONF_HUMIDITY_ENTITY_ID]
            )
            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(
                    title="Home Rules",
                    data=self._data,
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

        return self.async_show_form(
            step_id="comfort",
            data_schema=self._step_comfort_schema(),
            errors=errors,
        )

    def _step_user_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_CLIMATE_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Required(CONF_TIMER_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="timer")
                ),
            }
        )

    def _step_solar_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Optional(CONF_INVERTER_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])
                ),
                vol.Required(CONF_GENERATION_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Required(CONF_GRID_ENTITY_ID): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
            }
        )

    def _step_comfort_schema(self) -> vol.Schema:
        return vol.Schema(
            {
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
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_entities(
                self.hass,
                user_input,
                required_keys=[
                    CONF_CLIMATE_ENTITY_ID,
                    CONF_TIMER_ENTITY_ID,
                    CONF_GENERATION_ENTITY_ID,
                    CONF_GRID_ENTITY_ID,
                    CONF_TEMPERATURE_ENTITY_ID,
                    CONF_HUMIDITY_ENTITY_ID,
                ],
                allow_inverter=True,
            )
            if not errors:
                data = dict(self._config_entry.options)
                data.update(user_input)
                return self.async_create_entry(data=data)

        current = self._config_entry.options
        notify_services = self._notify_service_options()
        notify_options: list[SelectOptionDict] = [{"label": "Disabled", "value": ""}]
        notify_options.extend({"label": service, "value": service} for service in notify_services)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLIMATE_ENTITY_ID,
                        default=current.get(
                            CONF_CLIMATE_ENTITY_ID,
                            self._config_entry.data.get(CONF_CLIMATE_ENTITY_ID),
                        ),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
                    vol.Required(
                        CONF_TIMER_ENTITY_ID,
                        default=current.get(CONF_TIMER_ENTITY_ID, self._config_entry.data.get(CONF_TIMER_ENTITY_ID)),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="timer")),
                    vol.Optional(
                        CONF_INVERTER_ENTITY_ID,
                        default=current.get(
                            CONF_INVERTER_ENTITY_ID,
                            self._config_entry.data.get(CONF_INVERTER_ENTITY_ID, ""),
                        ),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor", "binary_sensor"])),
                    vol.Required(
                        CONF_GENERATION_ENTITY_ID,
                        default=current.get(
                            CONF_GENERATION_ENTITY_ID,
                            self._config_entry.data.get(CONF_GENERATION_ENTITY_ID),
                        ),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power")),
                    vol.Required(
                        CONF_GRID_ENTITY_ID,
                        default=current.get(CONF_GRID_ENTITY_ID, self._config_entry.data.get(CONF_GRID_ENTITY_ID)),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power")),
                    vol.Required(
                        CONF_TEMPERATURE_ENTITY_ID,
                        default=current.get(
                            CONF_TEMPERATURE_ENTITY_ID,
                            self._config_entry.data.get(CONF_TEMPERATURE_ENTITY_ID),
                        ),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                    ),
                    vol.Required(
                        CONF_HUMIDITY_ENTITY_ID,
                        default=current.get(
                            CONF_HUMIDITY_ENTITY_ID,
                            self._config_entry.data.get(CONF_HUMIDITY_ENTITY_ID),
                        ),
                    ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="humidity")),
                    vol.Required(
                        CONF_EVAL_INTERVAL,
                        default=current.get(CONF_EVAL_INTERVAL, DEFAULT_EVAL_INTERVAL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60,
                            max=3600,
                            step=60,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_GENERATION_COOL_THRESHOLD,
                        default=current.get(CONF_GENERATION_COOL_THRESHOLD, DEFAULT_GENERATION_COOL_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=20000,
                            step=100,
                            unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_GENERATION_DRY_THRESHOLD,
                        default=current.get(CONF_GENERATION_DRY_THRESHOLD, DEFAULT_GENERATION_DRY_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=20000,
                            step=100,
                            unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_HUMIDITY_THRESHOLD,
                        default=current.get(CONF_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=100,
                            step=1,
                            unit_of_measurement="%",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_TEMPERATURE_THRESHOLD,
                        default=current.get(CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=40,
                            step=0.5,
                            unit_of_measurement="C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_TEMPERATURE_COOL,
                        default=current.get(CONF_TEMPERATURE_COOL, DEFAULT_TEMPERATURE_COOL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=40,
                            step=0.5,
                            unit_of_measurement="C",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_GRID_USAGE_DELAY,
                        default=current.get(CONF_GRID_USAGE_DELAY, DEFAULT_GRID_USAGE_DELAY),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=5,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_REACTIVATE_DELAY,
                        default=current.get(CONF_REACTIVATE_DELAY, DEFAULT_REACTIVATE_DELAY),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=5,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_NOTIFICATION_SERVICE,
                        default=current.get(CONF_NOTIFICATION_SERVICE, ""),
                    ): selector.SelectSelector(selector.SelectSelectorConfig(options=notify_options)),
                }
            ),
            errors=errors,
        )
