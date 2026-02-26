from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import const as c
from .coordinator import HomeRulesCoordinator

_LEGACY_SUFFIXES = (
    "enabled aggressive_cooling dry_run notifications_enabled "
    "generation_cool_threshold generation_dry_threshold timer_countdown current"
).split()
_TARGET_MINOR_VERSION = 2


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = dict(entry.data)
    options = dict(entry.options)
    changed = False
    if data.pop(c.LEGACY_CONF_TIMER_ENTITY_ID, None) is not None:
        changed = True
    if options.pop(c.LEGACY_CONF_TIMER_ENTITY_ID, None) is not None:
        changed = True
    if entry.minor_version < _TARGET_MINOR_VERSION or changed:
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            minor_version=_TARGET_MINOR_VERSION,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HomeRulesCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    registry = er.async_get(hass)
    legacy = {f"{entry.entry_id}_{s}" for s in _LEGACY_SUFFIXES}
    for e in er.async_entries_for_config_entry(registry, entry.entry_id):
        if e.unique_id in legacy:
            registry.async_remove(e.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, c.PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if (coordinator := getattr(entry, "runtime_data", None)) is not None:
        await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, c.PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
