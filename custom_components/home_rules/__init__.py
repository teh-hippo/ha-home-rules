from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import const as c
from .coordinator import HomeRulesCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    retired_keys = c.RETIRED_CONFIG_KEYS
    if retired_keys.intersection(entry.data) or retired_keys.intersection(entry.options):
        options = {key: value for key, value in entry.options.items() if key not in retired_keys}
        if c.CONF_REACTIVATE_DELAY in entry.options:
            options[c.CONF_REACTIVATE_DELAY_MINUTES] = c.reactivation_delay_minutes(entry.options)
        hass.config_entries.async_update_entry(
            entry,
            data={key: value for key, value in entry.data.items() if key not in retired_keys},
            options=options,
        )
    registry = er.async_get(hass)
    for key in ("forecast_min_kwh", "battery_min_soc"):
        if entity_id := registry.async_get_entity_id("number", c.DOMAIN, f"{entry.entry_id}_{key}"):
            registry.async_remove(entity_id)
    coordinator = HomeRulesCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, c.PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if (coordinator := getattr(entry, "runtime_data", None)) is not None:
        await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, c.PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
