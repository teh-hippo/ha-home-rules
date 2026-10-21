from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import const as c
from .coordinator import HomeRulesCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
