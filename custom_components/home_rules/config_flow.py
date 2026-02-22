# fmt: off
# ruff: noqa: E501, E701, E702

from typing import Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.selector import SelectOptionDict

from . import const as c

_PLATFORMS = ("switch", "select", "sensor", "binary_sensor", "button", "number")
_HOME_RULES_PREFIXES = tuple(f"{platform}.{c.DOMAIN}_" for platform in _PLATFORMS)
_POWER_KEYS = {c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID}


def _entity_selector(domain: str | list[str], device_class: str | None = None) -> selector.EntitySelector: return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain) if device_class is None else selector.EntitySelectorConfig(domain=domain, device_class=device_class))
def _number_selector(min_val: float, max_val: float, step: float, unit: str | None = None) -> selector.NumberSelector:
    return selector.NumberSelector(selector.NumberSelectorConfig(min=min_val, max=max_val, step=step, mode=selector.NumberSelectorMode.BOX) if unit is None else selector.NumberSelectorConfig(min=min_val, max=max_val, step=step, mode=selector.NumberSelectorMode.BOX, unit_of_measurement=unit))


_ENTITY_SELECTORS = {c.CONF_CLIMATE_ENTITY_ID: _entity_selector("climate"), c.CONF_INVERTER_ENTITY_ID: _entity_selector(["sensor", "binary_sensor"]), c.CONF_GENERATION_ENTITY_ID: _entity_selector("sensor", "power"), c.CONF_GRID_ENTITY_ID: _entity_selector("sensor", "power"), c.CONF_TEMPERATURE_ENTITY_ID: _entity_selector("sensor", "temperature"), c.CONF_HUMIDITY_ENTITY_ID: _entity_selector("sensor", "humidity")}
_NUMBER_FIELDS = ((c.CONF_AIRCON_TIMER_DURATION, c.DEFAULT_AIRCON_TIMER_DURATION, _number_selector(1, 180, 1, "min")), (c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL, _number_selector(60, 3600, 60, "s")), (c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD, _number_selector(0, 20000, 100, "W")), (c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD, _number_selector(0, 20000, 100, "W")), (c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY, _number_selector(0, 5, 1)), (c.CONF_REACTIVATE_DELAY, c.DEFAULT_REACTIVATE_DELAY, _number_selector(0, 5, 1)))
_OPTIONS_ENTITY_FIELDS: tuple[tuple[type, str], ...] = ((vol.Required, c.CONF_CLIMATE_ENTITY_ID), (vol.Optional, c.CONF_INVERTER_ENTITY_ID), (vol.Required, c.CONF_GENERATION_ENTITY_ID), (vol.Required, c.CONF_GRID_ENTITY_ID), (vol.Required, c.CONF_TEMPERATURE_ENTITY_ID), (vol.Required, c.CONF_HUMIDITY_ENTITY_ID))
_OPTIONS_REQUIRED = [key for marker, key in _OPTIONS_ENTITY_FIELDS if marker is vol.Required]


def _schema(required: tuple[str, ...], optional: tuple[str, ...] = ()) -> vol.Schema:
    fields: dict[Any, Any] = {vol.Optional(key): _ENTITY_SELECTORS[key] for key in optional}; fields.update({vol.Required(key): _ENTITY_SELECTORS[key] for key in required}); return vol.Schema(fields)


def _validate_entities(
    hass: HomeAssistant,
    user_input: dict[str, Any],
    required_keys: list[str],
    allow_inverter: bool = False,
    check_domains: bool = True,
) -> dict[str, str]:
    for key in required_keys:
        entity_id = str(user_input[key])
        if not (state := hass.states.get(entity_id)): return {"base": "entity_not_found"}
        if entity_id.startswith(_HOME_RULES_PREFIXES): return {"base": "invalid_entity_selection"}
        if key in _POWER_KEYS:
            try: UnitOfPower(str(state.attributes.get("unit_of_measurement", "")).strip())
            except ValueError: return {"base": "invalid_power_unit"}
        if check_domains and key == c.CONF_CLIMATE_ENTITY_ID and not entity_id.startswith("climate."): return {"base": "invalid_climate_entity"}
        if check_domains and key != c.CONF_CLIMATE_ENTITY_ID and not entity_id.startswith("sensor."): return {"base": "invalid_sensor_entity"}
    if not allow_inverter: return {}
    inverter = str(user_input.get(c.CONF_INVERTER_ENTITY_ID, "")).strip()
    if not inverter: return {}
    if not hass.states.get(inverter): return {"base": "entity_not_found"}
    if inverter.startswith(_HOME_RULES_PREFIXES): return {"base": "invalid_entity_selection"}
    return {} if inverter.startswith(("sensor.", "binary_sensor.")) else {"base": "invalid_inverter_entity"}


class HomeRulesConfigFlow(ConfigFlow, domain=c.DOMAIN):
    VERSION = 1

    def __init__(self) -> None: self._data: dict[str, Any] = {}
    @staticmethod
    def async_get_options_flow(_config_entry: ConfigEntry) -> "HomeRulesOptionsFlow": return HomeRulesOptionsFlow()

    async def _step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        required: tuple[str, ...],
        optional: tuple[str, ...] = (),
        *,
        next_step: str | None = None,
        **validate_kw: Any,
    ) -> ConfigFlowResult:
        errors = _validate_entities(self.hass, user_input, list(required), **validate_kw) if user_input else {}
        if not user_input or errors: return self.async_show_form(step_id=step_id, data_schema=_schema(required, optional), errors=errors)
        self._data.update(user_input)
        return await getattr(self, f"async_step_{next_step}")() if next_step else self.async_create_entry(title="Home Rules", data=self._data, options=c.DEFAULT_OPTIONS)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(c.DOMAIN); self._abort_if_unique_id_configured(); return await self._step("user", user_input, (c.CONF_CLIMATE_ENTITY_ID,), next_step="solar")

    async def async_step_solar(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step("solar", user_input, (c.CONF_GENERATION_ENTITY_ID, c.CONF_GRID_ENTITY_ID), optional=(c.CONF_INVERTER_ENTITY_ID,), next_step="comfort", allow_inverter=True)

    async def async_step_comfort(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step("comfort", user_input, (c.CONF_TEMPERATURE_ENTITY_ID, c.CONF_HUMIDITY_ENTITY_ID))


class HomeRulesOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors = _validate_entities(self.hass, user_input, _OPTIONS_REQUIRED, allow_inverter=True) if user_input else {}
        if user_input and not errors: return self.async_create_entry(data={**self.config_entry.options, **user_input})
        cur = self.config_entry.options
        notify_options = cast(list[SelectOptionDict], [{"label": "Disabled", "value": ""}] + [{"label": f"notify.{name}", "value": f"notify.{name}"} for name in sorted(self.hass.services.async_services_for_domain("notify"))])
        schema: dict[Any, Any] = {marker(key, default=cur.get(key, self.config_entry.data.get(key, ""))): _ENTITY_SELECTORS[key] for marker, key in _OPTIONS_ENTITY_FIELDS}
        schema.update({vol.Required(key, default=cur.get(key, default)): sel for key, default, sel in _NUMBER_FIELDS})
        schema[vol.Optional(c.CONF_NOTIFICATION_SERVICE, default=cur.get(c.CONF_NOTIFICATION_SERVICE, ""))] = selector.SelectSelector(selector.SelectSelectorConfig(options=notify_options))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)
