from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from . import const as c
from .config_flow import HomeRulesConfigFlow
from .coordinator import HomeRulesCoordinator

_LEGACY_REACTIVATE_DELAY = "reactivate_delay"
_RETIRED_CONFIG_KEYS = frozenset(
    {
        "forecast_entity_id",
        "forecast_min_kwh",
        "battery_min_soc",
        "generation_boost_threshold",
        "afternoon_cooling",
        "afternoon_cooling_hour",
        "pre_cooling_start",
        "pre_cooling_finish",
        "temperature_precool",
        "tariff_entity_id",
        "peak_tariff",
        "battery_discharge_tolerance",
        _LEGACY_REACTIVATE_DELAY,
    }
)
_RETIRED_ENTITIES = (
    ("number", "forecast_min_kwh"),
    ("number", "battery_min_soc"),
    ("number", "temperature_precool"),
    ("number", "battery_discharge_tolerance"),
    ("switch", "afternoon_cooling"),
    ("time", "pre_cooling_start"),
    ("time", "pre_cooling_finish"),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = HomeRulesCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, c.PLATFORMS)
    _setup_dehumidifier_tank_issue(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


def _setup_dehumidifier_tank_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    @callback
    def sync_issue() -> None:
        state = hass.states.get(c.DEHUMIDIFIER_TANK_ENTITY_ID)
        if state is None or state.state in ("unknown", "unavailable"):
            return
        if state.state == "on":
            ir.async_create_issue(
                hass,
                c.DOMAIN,
                c.ISSUE_DEHUMIDIFIER_TANK_FULL,
                config_entry_id=entry.entry_id,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key=c.ISSUE_DEHUMIDIFIER_TANK_FULL,
            )
        elif state.state == "off":
            ir.async_delete_issue(hass, c.DOMAIN, c.ISSUE_DEHUMIDIFIER_TANK_FULL)

    @callback
    def handle_state_change(event: Event[EventStateChangedData]) -> None:
        if event.data["new_state"] is not None:
            sync_issue()

    sync_issue()
    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            [c.DEHUMIDIFIER_TANK_ENTITY_ID],
            handle_state_change,
        )
    )


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if entry.version > HomeRulesConfigFlow.VERSION:
        return False
    if entry.version < HomeRulesConfigFlow.VERSION:
        options = {key: value for key, value in entry.options.items() if key not in _RETIRED_CONFIG_KEYS}
        if _LEGACY_REACTIVATE_DELAY in entry.options:
            options[c.CONF_REACTIVATE_DELAY_MINUTES] = (
                float(entry.options[_LEGACY_REACTIVATE_DELAY])
                * float(entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))
                / 60
            )
        registry = er.async_get(hass)
        for platform, key in _RETIRED_ENTITIES:
            if entity_id := registry.async_get_entity_id(platform, c.DOMAIN, f"{entry.entry_id}_{key}"):
                registry.async_remove(entity_id)
        hass.config_entries.async_update_entry(
            entry,
            data={key: value for key, value in entry.data.items() if key not in _RETIRED_CONFIG_KEYS},
            options=options,
            version=HomeRulesConfigFlow.VERSION,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if (coordinator := getattr(entry, "runtime_data", None)) is not None:
        await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, c.PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
