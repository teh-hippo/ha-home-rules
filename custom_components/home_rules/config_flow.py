from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from . import const as c

_HOME_RULES_PREFIXES = tuple(
    f"{platform}.{c.DOMAIN}_" for platform in ("switch", "select", "sensor", "binary_sensor", "button", "number")
)
_VALID_POWER_UNITS = {"", "w", "kw", "mw", "watt", "watts", "kilowatt", "kilowatts"}
_SENSOR_KEYS = {
    c.CONF_GENERATION_ENTITY_ID,
    c.CONF_GRID_ENTITY_ID,
    c.CONF_TEMPERATURE_ENTITY_ID,
    c.CONF_HUMIDITY_ENTITY_ID,
}
_DOMAIN_CHECKS = {
    c.CONF_TIMER_ENTITY_ID: ("timer.", "invalid_timer_entity"),
    c.CONF_CLIMATE_ENTITY_ID: ("climate.", "invalid_climate_entity"),
}
_DEFAULT_OPTIONS = {
    c.CONF_EVAL_INTERVAL: c.DEFAULT_EVAL_INTERVAL,
    c.CONF_GENERATION_COOL_THRESHOLD: c.DEFAULT_GENERATION_COOL_THRESHOLD,
    c.CONF_GENERATION_DRY_THRESHOLD: c.DEFAULT_GENERATION_DRY_THRESHOLD,
    c.CONF_HUMIDITY_THRESHOLD: c.DEFAULT_HUMIDITY_THRESHOLD,
    c.CONF_TEMPERATURE_THRESHOLD: c.DEFAULT_TEMPERATURE_THRESHOLD,
    c.CONF_TEMPERATURE_COOL: c.DEFAULT_TEMPERATURE_COOL,
    c.CONF_GRID_USAGE_DELAY: c.DEFAULT_GRID_USAGE_DELAY,
    c.CONF_REACTIVATE_DELAY: c.DEFAULT_REACTIVATE_DELAY,
}


def _entity_selector(domain: str | list[str], device_class: str | None = None) -> selector.EntitySelector:
    config = (
        selector.EntitySelectorConfig(domain=domain)
        if device_class is None
        else selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    )
    return selector.EntitySelector(config)


def _number_selector(
    min_value: float, max_value: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    config = (
        selector.NumberSelectorConfig(min=min_value, max=max_value, step=step, mode=selector.NumberSelectorMode.BOX)
        if unit is None
        else selector.NumberSelectorConfig(
            min=min_value,
            max=max_value,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )
    return selector.NumberSelector(config)


_ENTITY_SELECTORS = {
    c.CONF_CLIMATE_ENTITY_ID: _entity_selector("climate"),
    c.CONF_TIMER_ENTITY_ID: _entity_selector("timer"),
    c.CONF_INVERTER_ENTITY_ID: _entity_selector(["sensor", "binary_sensor"]),
    c.CONF_GENERATION_ENTITY_ID: _entity_selector("sensor", "power"),
    c.CONF_GRID_ENTITY_ID: _entity_selector("sensor", "power"),
    c.CONF_TEMPERATURE_ENTITY_ID: _entity_selector("sensor", "temperature"),
    c.CONF_HUMIDITY_ENTITY_ID: _entity_selector("sensor", "humidity"),
}

_NUMBER_FIELDS = (
    (c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL, _number_selector(60, 3600, 60, "s")),
    (c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD, _number_selector(0, 20000, 100, "W")),
    (c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD, _number_selector(0, 20000, 100, "W")),
    (c.CONF_HUMIDITY_THRESHOLD, c.DEFAULT_HUMIDITY_THRESHOLD, _number_selector(0, 100, 1, "%")),
    (c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD, _number_selector(0, 40, 0.5, "C")),
    (c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL, _number_selector(0, 40, 0.5, "C")),
    (c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY, _number_selector(0, 5, 1)),
    (c.CONF_REACTIVATE_DELAY, c.DEFAULT_REACTIVATE_DELAY, _number_selector(0, 5, 1)),
)


def _schema(required: tuple[str, ...], optional: tuple[str, ...] = ()) -> vol.Schema:
    schema: dict[Any, Any] = {vol.Optional(key): _ENTITY_SELECTORS[key] for key in optional}
    schema.update({vol.Required(key): _ENTITY_SELECTORS[key] for key in required})
    return vol.Schema(schema)


def _option_default(config_entry: ConfigEntry, current: Mapping[str, Any], key: str, fallback: Any = "") -> Any:
    return current.get(key, config_entry.data.get(key, fallback))


def _validate_entities(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    *,
    required_keys: list[str],
    allow_inverter: bool = False,
    check_domains: bool = True,
) -> dict[str, str]:
    for key in required_keys:
        entity_id = str(user_input[key])
        state = hass.states.get(entity_id)
        if state is None:
            return {"base": "entity_not_found"}
        if entity_id.startswith(_HOME_RULES_PREFIXES):
            return {"base": "invalid_entity_selection"}
        if key in (c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID):
            unit = str(state.attributes.get("unit_of_measurement", "")).lower()
            if unit not in _VALID_POWER_UNITS:
                return {"base": "invalid_power_unit"}
        if check_domains:
            if (domain_check := _DOMAIN_CHECKS.get(key)) and not entity_id.startswith(domain_check[0]):
                return {"base": domain_check[1]}
            if key in _SENSOR_KEYS and not entity_id.startswith("sensor."):
                return {"base": "invalid_sensor_entity"}

    if not allow_inverter:
        return {}
    inverter_entity = str(user_input.get(c.CONF_INVERTER_ENTITY_ID, "")).strip()
    if not inverter_entity:
        return {}
    if hass.states.get(inverter_entity) is None:
        return {"base": "entity_not_found"}
    if inverter_entity.startswith(_HOME_RULES_PREFIXES):
        return {"base": "invalid_entity_selection"}
    if not inverter_entity.startswith(("sensor.", "binary_sensor.")):
        return {"base": "invalid_inverter_entity"}
    return {}


class HomeRulesConfigFlow(ConfigFlow, domain=c.DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(_config_entry: ConfigEntry) -> "HomeRulesOptionsFlow":
        return HomeRulesOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(c.DOMAIN)
        self._abort_if_unique_id_configured()
        errors = (
            _validate_entities(self.hass, user_input, required_keys=[c.CONF_CLIMATE_ENTITY_ID, c.CONF_TIMER_ENTITY_ID])
            if user_input
            else {}
        )
        if user_input and not errors:
            self._data.update(user_input)
            return await self.async_step_solar()
        return self.async_show_form(
            step_id="user", data_schema=_schema((c.CONF_CLIMATE_ENTITY_ID, c.CONF_TIMER_ENTITY_ID)), errors=errors
        )

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = (
            _validate_entities(
                self.hass,
                user_input,
                required_keys=[c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID],
                allow_inverter=True,
            )
            if user_input
            else {}
        )
        if user_input and not errors:
            self._data.update(user_input)
            return await self.async_step_comfort()
        return self.async_show_form(
            step_id="solar",
            data_schema=_schema(
                (c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID), optional=(c.CONF_INVERTER_ENTITY_ID,)
            ),
            errors=errors,
        )

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = (
            _validate_entities(
                self.hass, user_input, required_keys=[c.CONF_TEMPERATURE_ENTITY_ID, c.CONF_HUMIDITY_ENTITY_ID]
            )
            if user_input
            else {}
        )
        if user_input and not errors:
            self._data.update(user_input)
            return self.async_create_entry(title="Home Rules", data=self._data, options=_DEFAULT_OPTIONS)
        return self.async_show_form(
            step_id="comfort",
            data_schema=_schema((c.CONF_TEMPERATURE_ENTITY_ID, c.CONF_HUMIDITY_ENTITY_ID)),
            errors=errors,
        )


class HomeRulesOptionsFlow(OptionsFlow):
    def _notify_service_options(self) -> list[str]:
        return [f"notify.{name}" for name in sorted(self.hass.services.async_services_for_domain("notify"))]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        required = [
            c.CONF_CLIMATE_ENTITY_ID,
            c.CONF_TIMER_ENTITY_ID,
            c.CONF_GENERATION_ENTITY_ID,
            c.CONF_GRID_ENTITY_ID,
            c.CONF_TEMPERATURE_ENTITY_ID,
            c.CONF_HUMIDITY_ENTITY_ID,
        ]
        errors = (
            _validate_entities(self.hass, user_input, required_keys=required, allow_inverter=True) if user_input else {}
        )
        if user_input and not errors:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})

        current = self.config_entry.options
        notify_options: list[SelectOptionDict] = [{"label": "Disabled", "value": ""}]
        notify_options.extend({"label": service, "value": service} for service in self._notify_service_options())

        data_schema: dict[Any, Any] = {}
        for marker, key in (
            (vol.Required, c.CONF_CLIMATE_ENTITY_ID),
            (vol.Required, c.CONF_TIMER_ENTITY_ID),
            (vol.Optional, c.CONF_INVERTER_ENTITY_ID),
            (vol.Required, c.CONF_GENERATION_ENTITY_ID),
            (vol.Required, c.CONF_GRID_ENTITY_ID),
            (vol.Required, c.CONF_TEMPERATURE_ENTITY_ID),
            (vol.Required, c.CONF_HUMIDITY_ENTITY_ID),
        ):
            data_schema[marker(key, default=_option_default(self.config_entry, current, key))] = _ENTITY_SELECTORS[key]
        for key, default, number_selector in _NUMBER_FIELDS:
            data_schema[vol.Required(key, default=current.get(key, default))] = number_selector
        data_schema[vol.Optional(c.CONF_NOTIFICATION_SERVICE, default=current.get(c.CONF_NOTIFICATION_SERVICE, ""))] = (
            selector.SelectSelector(selector.SelectSelectorConfig(options=notify_options))
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(data_schema), errors=errors)
