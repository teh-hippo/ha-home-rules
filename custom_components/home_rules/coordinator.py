# fmt: off
# ruff: noqa: E501, E701, E702

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter, TemperatureConverter

from . import const as c
from .rules import (
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    RuleParameters,
    adjust,
    apply_adjustment,
    current_state,
)

_HOME_RECORD_FIELDS = ("generation", "grid_usage", "temperature", "humidity", "have_solar", "auto")
_SESSION_RECORD_FIELDS = ("tolerated", "reactivate_delay")
_CLEAR_ISSUES = (c.ISSUE_RUNTIME, c.ISSUE_ENTITY_MISSING, c.ISSUE_INVALID_UNIT, c.ISSUE_ENTITY_UNAVAILABLE)


@dataclass
class CoordinatorData:
    mode: HomeOutput = HomeOutput.OFF; current: HomeOutput = HomeOutput.OFF; adjustment: HomeOutput = HomeOutput.NO_CHANGE; decision: str = ""; reason: str = ""; solar_available: bool = False; auto_mode: bool = False; dry_run: bool = False; timer_finishes_at: datetime | None = None; last_evaluated: str | None = None; last_changed: str | None = None


class HomeRulesCoordinator(DataUpdateCoordinator[CoordinatorData]):
    config_entry: ConfigEntry
    _LEGACY_MODES: dict[str, str] = {"Disabled": "disabled", "Dry Run": "monitor", "Live": "solar_cooling", "Aggressive": "boost_cooling"}
    _FALLBACK_DEFAULTS = {"generation": "0", "grid": "0", "inverter": "offline"}
    _recent: deque[dict[str, Any]]
    _last_record: dict[str, Any]
    _last_changed: str | None

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass, self.config_entry = hass, config_entry; self._lock, self._session = asyncio.Lock(), CachedState(); self.control_mode, self.cooling_enabled = c.ControlMode.MONITOR, True
        self._parameters: dict[str, float] = {}; self._auto_mode = self._initialized = self._first_refresh_done = False; self._recent, self._last_changed, self._last_record = deque(maxlen=c.MAX_RECENT_EVALUATIONS), None, {}; self._aircon_timer_finishes_at: datetime | None = None
        self._store = Store[dict[str, Any]](hass, c.STORAGE_VERSION, f"{c.DOMAIN}_{config_entry.entry_id}")
        interval = timedelta(seconds=int(config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))); name = f"{c.DOMAIN} ({config_entry.entry_id})"
        super().__init__(hass, c.LOGGER, name=name, update_interval=interval, always_update=True, config_entry=config_entry); self.data = CoordinatorData()

    def get_parameter(self, key: str, default: float) -> float: return float(self._parameters.get(key, self.config_entry.options.get(key, default)))
    async def async_set_parameter(self, key: str, value: float) -> None: self._parameters[key] = value; await self._save_state(); await self.async_run_evaluation("parameter")

    @property
    def parameters(self) -> RuleParameters:
        g, o = self.get_parameter, self.config_entry.options
        return RuleParameters(g(c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD), g(c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD), g(c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD), g(c.CONF_HUMIDITY_THRESHOLD, c.DEFAULT_HUMIDITY_THRESHOLD), int(o.get(c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY)), int(o.get(c.CONF_REACTIVATE_DELAY, c.DEFAULT_REACTIVATE_DELAY)), g(c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL))

    async def async_set_mode(self, mode: c.ControlMode) -> None: self.control_mode = mode; await self._save_state(); await self.async_run_evaluation("control_mode")

    def _control_mode_from_storage(self, controls: dict[str, Any]) -> c.ControlMode:
        if (mode_raw := controls.get("mode")) is not None:
            mapped = self._LEGACY_MODES.get(str(mode_raw), str(mode_raw))
            with suppress(ValueError): return c.ControlMode(mapped)
        if not controls.get("enabled", True): return c.ControlMode.DISABLED
        if controls.get("dry_run", True): return c.ControlMode.MONITOR
        return c.ControlMode.BOOST_COOLING if controls.get("aggressive_cooling", False) else c.ControlMode.SOLAR_COOLING

    async def async_initialize(self) -> None:
        stored = await self._store.async_load()
        if not stored: return
        controls, session = stored.get("controls", {}), stored.get("session", {})
        self.control_mode, self.cooling_enabled = self._control_mode_from_storage(controls), bool(controls.get("cooling_enabled", True))
        last = session.get("last"); last = HomeOutput.NO_CHANGE.value if last == "NoChange" else last
        self._session = CachedState(reactivate_delay=int(session.get("reactivate_delay", 0)), tolerated=int(session.get("tolerated", 0)), last=HomeOutput(last) if last else None, failed_to_change=int(session.get("failed_to_change", 0)))
        self._auto_mode, self._last_changed = bool(stored.get("auto_mode", False)), stored.get("last_changed")
        self._recent = deque(stored.get("recent_evaluations", []), maxlen=c.MAX_RECENT_EVALUATIONS)
        self._aircon_timer_finishes_at = dt_util.parse_datetime(str(v)) if (v := stored.get("aircon_timer_finishes_at")) else None
        self._parameters = {}
        for k, v in stored.get("parameters", {}).items():
            with suppress(TypeError, ValueError): self._parameters[str(k)] = float(v)

    async def async_set_control(self, key: str, value: bool) -> None: setattr(self, key, value); await self._save_state(); await self.async_run_evaluation("control")
    async def async_run_evaluation(self, trigger: str = "manual") -> None: self.async_set_updated_data(await self._evaluate(trigger))

    async def _async_update_data(self) -> CoordinatorData:
        try: return await self._evaluate("poll")
        except ConfigEntryNotReady: raise
        except Exception as err:  # noqa: BLE001
            self._create_issue(c.ISSUE_RUNTIME, {"error": str(err)})
            raise UpdateFailed(translation_domain=c.DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}) from err

    async def _evaluate(self, trigger: str) -> CoordinatorData:
        async with self._lock:
            now = dt_util.utcnow().isoformat(); self._clear_issue(c.ISSUE_ENTITY_UNAVAILABLE); home, evaluated_timer = self._build_home_input(); current = current_state(home)
            if not self._initialized: self._initialized = True; self._sync_on_startup(current, home)
            elif self._session.last is None: self._session.last = current
            result = adjust(self.parameters, home, self._session); adjustment, reason = result.output, result.reason; await self._execute_adjustment(adjustment); timer = self._active_aircon_timer() if adjustment is HomeOutput.TIMER else evaluated_timer
            previous = self._session.last; applied = apply_adjustment(self._session, current, adjustment); is_monitor = self.control_mode is c.ControlMode.MONITOR
            if is_monitor: self._session.failed_to_change, applied = 0, True
            if not applied: raise HomeAssistantError("failed to apply adjustment")
            if previous is not None and previous != self._session.last: self._last_changed = now; await self._maybe_notify(previous, current, adjustment)
            mode = self._session.last or current
            record = {"time": now, "trigger": trigger, "current": current.value, "adjustment": adjustment.value, "mode": mode.value, "reason": reason, "dry_run": is_monitor, "control_mode": self.control_mode.value} | {k: getattr(home, k) for k in _HOME_RECORD_FIELDS} | {k: getattr(self._session, k) for k in _SESSION_RECORD_FIELDS}
            self._last_record = record; self._recent.appendleft(record); await self._save_state(); self.hass.bus.async_fire(c.EVENT_EVALUATION, record)
            for issue in _CLEAR_ISSUES: self._clear_issue(issue)
            self._first_refresh_done = True
            return CoordinatorData(mode=mode, current=current, adjustment=adjustment, decision=f"{mode.value} - {reason}", reason=reason, solar_available=home.have_solar and home.generation > 0.0, auto_mode=self._auto_mode, dry_run=is_monitor, timer_finishes_at=timer, last_evaluated=now, last_changed=self._last_changed)

    async def _maybe_notify(self, previous: HomeOutput, current: HomeOutput, adjustment: HomeOutput) -> None:
        service = str(self.config_entry.options.get(c.CONF_NOTIFICATION_SERVICE, "")).strip()
        if not service: self._clear_issue(c.ISSUE_NOTIFICATION_SERVICE); return
        domain, name = service.split(".", 1) if "." in service else ("notify", service)
        if not self.hass.services.has_service(domain, name): self._create_issue(c.ISSUE_NOTIFICATION_SERVICE, {"service": service}); return
        self._clear_issue(c.ISSUE_NOTIFICATION_SERVICE)
        msg = f"Mode changed: {previous.value} -> {(self._session.last or current).value} (current={current.value}, action={adjustment.value})"
        try: await self.hass.services.async_call(domain, name, {"title": "Home Rules", "message": msg}, blocking=False)
        except ServiceValidationError: self._create_issue(c.ISSUE_NOTIFICATION_SERVICE, {"service": service})

    def _entity_id(self, key: str, *, optional: bool = False) -> str | None:
        value = str(self.config_entry.options.get(key, self.config_entry.data.get(key, ""))).strip()
        return (value or None) if optional else value or str(self.config_entry.data[key])

    def _state(self, conf_key: str, label: str, *, allow_unavailable: bool = False) -> State: return self._get_state(str(self._entity_id(conf_key)), label, allow_unavailable=allow_unavailable)

    def _build_home_input(self) -> tuple[HomeInput, datetime | None]:
        timer = self._active_aircon_timer(); climate = self._state(c.CONF_CLIMATE_ENTITY_ID, "climate")
        inv_id = self._entity_id(c.CONF_INVERTER_ENTITY_ID, optional=True); inv = self._get_state(inv_id, "inverter", allow_unavailable=True) if inv_id else None
        gen = self._state(c.CONF_GENERATION_ENTITY_ID, "generation", allow_unavailable=True); grid = self._state(c.CONF_GRID_ENTITY_ID, "grid", allow_unavailable=True); temp = self._state(c.CONF_TEMPERATURE_ENTITY_ID, "temperature", allow_unavailable=True); hum = self._state(c.CONF_HUMIDITY_ENTITY_ID, "humidity", allow_unavailable=True)
        have_solar = str(inv.state).lower() in {"on", "true", "1", "online"} if inv else not inv_id
        mode = AirconMode.UNKNOWN
        with suppress(ValueError): mode = AirconMode(str(climate.state).lower().strip())
        aggressive = self.control_mode is c.ControlMode.BOOST_COOLING; enabled = self.control_mode is not c.ControlMode.DISABLED
        generation = self._normalized_power(gen, "generation") if have_solar else 0.0; grid_usage = self._normalized_power(grid, "grid") if have_solar else 0.0
        return HomeInput(mode, have_solar, generation, grid_usage, timer is not None, self._normalized_temperature(temp), self._state_to_float(hum, "humidity"), self._auto_mode, aggressive, enabled, self.cooling_enabled), timer

    def _sync_on_startup(self, current: HomeOutput, home: HomeInput) -> None:
        if self._session.last is None: self._session.last = current
        elif home.timer and self._session.last is HomeOutput.TIMER: return
        elif self._session.last != current: c.LOGGER.info("Startup sync: restoring from %s to live state %s", self._session.last.value, current.value); self._session.last = current

    async def _call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try: await self.hass.services.async_call(domain, service, data, blocking=True)
        except ServiceValidationError as err: raise HomeAssistantError(f"service call failed: {err}") from err

    async def _execute_adjustment(self, adjustment: HomeOutput) -> None:
        if adjustment in (HomeOutput.NO_CHANGE, HomeOutput.RESET, HomeOutput.DISABLED): return
        if self.control_mode is c.ControlMode.MONITOR: c.LOGGER.info("MONITOR: would apply adjustment %s", adjustment.value)
        else:
            climate = str(self._entity_id(c.CONF_CLIMATE_ENTITY_ID))
            if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
                for service, data in (("set_hvac_mode", {"entity_id": climate, "hvac_mode": adjustment.value.lower()}), ("set_temperature", {"entity_id": climate, "temperature": self.parameters.temperature_cool})): await self._call_service("climate", service, data)
            elif adjustment is HomeOutput.OFF: await self._call_service("climate", "turn_off", {"entity_id": climate})
            elif adjustment is HomeOutput.TIMER: self._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(minutes=max(1, int(self.config_entry.options.get(c.CONF_AIRCON_TIMER_DURATION, c.DEFAULT_AIRCON_TIMER_DURATION))))
        if adjustment in (HomeOutput.COOL, HomeOutput.DRY): self._auto_mode = True
        elif adjustment is HomeOutput.OFF: self._auto_mode = False

    def _get_state(self, entity_id: str, label: str, *, allow_unavailable: bool = False) -> State:
        state = self.hass.states.get(entity_id)
        if state is None:
            if not allow_unavailable and not self._first_refresh_done: raise ConfigEntryNotReady(f"Required entity not yet available: {entity_id}")
            self._create_issue(c.ISSUE_ENTITY_MISSING, {"entity_id": entity_id, "label": label}); raise ValueError(f"missing entity: {entity_id}")
        raw = str(state.state).lower()
        if raw not in {"unknown", "unavailable"}: return state
        if not allow_unavailable:
            if not self._first_refresh_done: raise ConfigEntryNotReady(f"Required entity not yet available: {entity_id}")
            self._create_issue(c.ISSUE_ENTITY_UNAVAILABLE, {"entity_id": entity_id, "label": label}); raise ValueError(f"entity unavailable: {entity_id}")
        if label in self._FALLBACK_DEFAULTS: return State(entity_id, self._FALLBACK_DEFAULTS[label], state.attributes)
        if label == "temperature": return State(entity_id, str(self.parameters.temperature_threshold - 0.1), state.attributes)
        if label == "humidity": return State(entity_id, str(self.parameters.humidity_threshold + 1.0), state.attributes)
        return state

    @staticmethod
    def _state_to_float(state: State, label: str) -> float:
        try: return float(state.state)
        except ValueError as err: raise ValueError(f"invalid numeric {label}: {state.state}") from err

    def _active_aircon_timer(self) -> datetime | None:
        if self._aircon_timer_finishes_at and self._aircon_timer_finishes_at <= dt_util.utcnow(): self._aircon_timer_finishes_at = None
        return self._aircon_timer_finishes_at

    def _normalized_power(self, state: State, label: str) -> float:
        value = self._state_to_float(state, label); unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip()
        try: return max(0.0, PowerConverter.convert(value, UnitOfPower(unit), UnitOfPower.WATT))
        except ValueError:
            self._create_issue(c.ISSUE_INVALID_UNIT, {"entity_id": state.entity_id, "unit": unit or "(none)"}); raise ValueError(f"unsupported power unit for {state.entity_id}: {unit}") from None

    def _normalized_temperature(self, state: State) -> float:
        value = self._state_to_float(state, "temperature"); unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip().upper()
        if unit in {"", "°C", "C"}: return value
        if unit in {"°F", "F"}: return TemperatureConverter.convert(value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS)
        raise ValueError(f"unsupported temperature unit: {unit}")

    async def _save_state(self) -> None:
        session = asdict(self._session); session["last"] = self._session.last.value if self._session.last else None
        await self._store.async_save({"controls": {"mode": self.control_mode.value, "cooling_enabled": self.cooling_enabled}, "session": session, "auto_mode": self._auto_mode, "last_changed": self._last_changed, "recent_evaluations": list(self._recent), "aircon_timer_finishes_at": self._aircon_timer_finishes_at and self._aircon_timer_finishes_at.isoformat(), "parameters": dict(self._parameters)})

    def _create_issue(self, issue: str, placeholders: dict[str, str]) -> None:
        ir.async_create_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}", is_fixable=False, is_persistent=False, severity=ir.IssueSeverity.ERROR, translation_key=issue, translation_placeholders=placeholders)

    def _clear_issue(self, issue: str) -> None: ir.async_delete_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}")


type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]
