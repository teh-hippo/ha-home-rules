from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import const as c
from .coordinator import HomeRulesCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HomeRulesCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    registry = er.async_get(hass)
    legacy = {
        f"{entry.entry_id}_{s}"
        for s in (
            "enabled",
            "aggressive_cooling",
            "dry_run",
            "notifications_enabled",
            "generation_cool_threshold",
            "generation_dry_threshold",
        )
    }
    for e in er.async_entries_for_config_entry(registry, entry.entry_id):
        if e.unique_id in legacy:
            registry.async_remove(e.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, c.PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    c.LOGGER.debug("Home Rules set up")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, c.PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
