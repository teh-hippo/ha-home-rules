from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from . import const as c

_HOME_RULES_PREFIXES = tuple(
    f"{platform}.{c.DOMAIN}_" for platform in ("switch", "select", "sensor", "binary_sensor", "button", "number")
)
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
    c.CONF_GRID_USAGE_DELAY: c.DEFAULT_GRID_USAGE_DELAY,
    c.CONF_REACTIVATE_DELAY: c.DEFAULT_REACTIVATE_DELAY,
}


def _entity_selector(domain: str | list[str], device_class: str | None = None) -> selector.EntitySelector:
    cfg = selector.EntitySelectorConfig(domain=domain)
    if device_class:
        cfg = selector.EntitySelectorConfig(domain=domain, device_class=device_class)
    return selector.EntitySelector(cfg)


def _number_selector(min_val: float, max_val: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    mode = selector.NumberSelectorMode.BOX
    cfg = (
        selector.NumberSelectorConfig(min=min_val, max=max_val, step=step, mode=mode)
        if unit is None
        else selector.NumberSelectorConfig(min=min_val, max=max_val, step=step, unit_of_measurement=unit, mode=mode)
    )
    return selector.NumberSelector(cfg)


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
        eid = str(user_input[key])
        if not (state := hass.states.get(eid)):
            return {"base": "entity_not_found"}
        if eid.startswith(_HOME_RULES_PREFIXES):
            return {"base": "invalid_entity_selection"}
        if key in (c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID):
            try:
                UnitOfPower(str(state.attributes.get("unit_of_measurement", "")).strip())
            except ValueError:
                return {"base": "invalid_power_unit"}
        if check_domains and (dc := _DOMAIN_CHECKS.get(key)) and not eid.startswith(dc[0]):
            return {"base": dc[1]}
        if check_domains and key in _SENSOR_KEYS and not eid.startswith("sensor."):
            return {"base": "invalid_sensor_entity"}
    if not allow_inverter:
        return {}
    inv = str(user_input.get(c.CONF_INVERTER_ENTITY_ID, "")).strip()
    if not inv:
        return {}
    if not hass.states.get(inv):
        return {"base": "entity_not_found"}
    if inv.startswith(_HOME_RULES_PREFIXES):
        return {"base": "invalid_entity_selection"}
    return {"base": "invalid_inverter_entity"} if not inv.startswith(("sensor.", "binary_sensor.")) else {}


class HomeRulesConfigFlow(ConfigFlow, domain=c.DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    def async_get_options_flow(_config_entry: ConfigEntry) -> "HomeRulesOptionsFlow":
        return HomeRulesOptionsFlow()

    async def _config_step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        required: tuple[str, ...],
        optional: tuple[str, ...] = (),
        **validate_kw: Any,
    ) -> ConfigFlowResult:
        errors = (
            _validate_entities(self.hass, user_input, required_keys=list(required), **validate_kw) if user_input else {}
        )
        if user_input and not errors:
            self._data.update(user_input)
            if step_id == "user":
                return await self.async_step_solar()
            if step_id == "solar":
                return await self.async_step_comfort()
            return self.async_create_entry(title="Home Rules", data=self._data, options=_DEFAULT_OPTIONS)
        return self.async_show_form(step_id=step_id, data_schema=_schema(required, optional), errors=errors)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(c.DOMAIN)
        self._abort_if_unique_id_configured()
        return await self._config_step("user", user_input, (c.CONF_CLIMATE_ENTITY_ID, c.CONF_TIMER_ENTITY_ID))

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._config_step(
            "solar",
            user_input,
            (c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID),
            optional=(c.CONF_INVERTER_ENTITY_ID,),
            allow_inverter=True,
        )

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._config_step("comfort", user_input, (c.CONF_TEMPERATURE_ENTITY_ID, c.CONF_HUMIDITY_ENTITY_ID))


_OPTIONS_ENTITY_FIELDS: tuple[tuple[type, str], ...] = (
    (vol.Required, c.CONF_CLIMATE_ENTITY_ID),
    (vol.Required, c.CONF_TIMER_ENTITY_ID),
    (vol.Optional, c.CONF_INVERTER_ENTITY_ID),
    (vol.Required, c.CONF_GENERATION_ENTITY_ID),
    (vol.Required, c.CONF_GRID_ENTITY_ID),
    (vol.Required, c.CONF_TEMPERATURE_ENTITY_ID),
    (vol.Required, c.CONF_HUMIDITY_ENTITY_ID),
)
_OPTIONS_REQUIRED = [k for _, k in _OPTIONS_ENTITY_FIELDS if _ is vol.Required]


class HomeRulesOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = (
            _validate_entities(self.hass, user_input, required_keys=_OPTIONS_REQUIRED, allow_inverter=True)
            if user_input
            else {}
        )
        if user_input and not errors:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})

        cur = self.config_entry.options
        notify_options: list[SelectOptionDict] = [{"label": "Disabled", "value": ""}]
        notify_options.extend(
            {"label": f"notify.{n}", "value": f"notify.{n}"}
            for n in sorted(self.hass.services.async_services_for_domain("notify"))
        )
        schema: dict[Any, Any] = {}
        for marker, key in _OPTIONS_ENTITY_FIELDS:
            schema[marker(key, default=_option_default(self.config_entry, cur, key))] = _ENTITY_SELECTORS[key]
        for key, default, sel in _NUMBER_FIELDS:
            schema[vol.Required(key, default=cur.get(key, default))] = sel
        schema[vol.Optional(c.CONF_NOTIFICATION_SERVICE, default=cur.get(c.CONF_NOTIFICATION_SERVICE, ""))] = (
            selector.SelectSelector(selector.SelectSelectorConfig(options=notify_options))
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)
