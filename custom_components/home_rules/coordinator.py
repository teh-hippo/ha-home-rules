# fmt: off
# ruff: noqa: E501, E701, E702

import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from typing import Any
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, State
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import PowerConverter, TemperatureConverter

from . import const as c
from .rules import (
    AdjustResult,
    AirconMode,
    CachedState,
    HomeInput,
    HomeOutput,
    ManualCoolingBehaviour,
    RuleParameters,
    adjust,
    apply_adjustment,
    current_state,
)

_HOME_RECORD_FIELDS = ("generation", "grid_usage", "temperature", "temperature_available", "humidity", "have_solar", "auto", "aircon_mode", "before_afternoon", "battery_discharge")
_SESSION_RECORD_FIELDS = ("tolerated", "reactivate_delay")
_CLEAR_ISSUES = (c.ISSUE_RUNTIME, c.ISSUE_ENTITY_MISSING, c.ISSUE_INVALID_UNIT, c.ISSUE_ENTITY_UNAVAILABLE)


@dataclass
class CoordinatorData:
    mode: HomeOutput = HomeOutput.OFF; adjustment: HomeOutput = HomeOutput.NO_CHANGE; decision: str = ""; solar_available: bool = False; auto_mode: bool = False; timer_finishes_at: datetime | None = None; last_evaluated: str | None = None; last_changed: str | None = None


class HomeRulesCoordinator(DataUpdateCoordinator[CoordinatorData]):
    config_entry: ConfigEntry
    _FALLBACK_DEFAULTS = {"generation": "0", "grid": "0"}
    _recent: deque[dict[str, Any]]
    _last_record: dict[str, Any]
    _last_changed: str | None
    _fallback_inputs: dict[str, str]

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass, self.config_entry = hass, config_entry; self._lock, self._session = asyncio.Lock(), CachedState(); self.control_mode, self.cooling_enabled, self.dry_mode_enabled, self.afternoon_cooling = c.ControlMode.MONITOR, True, True, False
        self._parameters: dict[str, float] = {}; self._auto_mode = self._initialized = self._first_refresh_done = False; self._recent, self._last_changed, self._last_record, self._fallback_inputs = deque(maxlen=c.MAX_RECENT_EVALUATIONS), None, {}, {}; self._aircon_timer_finishes_at: datetime | None = None; self._timer_expiry_handle: asyncio.TimerHandle | None = None
        self._timer_target_notified = False; self._timer_prompt_id: str | None = None; self._notification_unsub: CALLBACK_TYPE | None = None
        self._store = Store[dict[str, Any]](hass, c.STORAGE_VERSION, f"{c.DOMAIN}_{config_entry.entry_id}")
        interval = timedelta(seconds=int(config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))); name = f"{c.DOMAIN} ({config_entry.entry_id})"
        super().__init__(hass, c.LOGGER, name=name, update_interval=interval, always_update=True, config_entry=config_entry); self.data = CoordinatorData()

    def get_parameter(self, key: str, default: float) -> float: return float(self._parameters.get(key, self.config_entry.options.get(key, default)))
    async def async_set_parameter(self, key: str, value: float) -> None:
        if key in (c.CONF_TEMPERATURE_THRESHOLD, c.CONF_TEMPERATURE_COOL):
            candidate = replace(self.parameters, temperature_threshold=value) if key == c.CONF_TEMPERATURE_THRESHOLD else replace(self.parameters, temperature_cool=value)
            if not candidate.temperature_range_valid: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_temperature_range")
        self._parameters[key] = value; await self._save_state(); await self.async_run_evaluation("parameter")

    @property
    def parameters(self) -> RuleParameters:
        g, o = self.get_parameter, self.config_entry.options
        return RuleParameters(g(c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD), g(c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD), g(c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD), c.DRY_MODE_HUMIDITY_CUTOFF, self.dry_mode_enabled, int(o.get(c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY)), int(o.get(c.CONF_REACTIVATE_DELAY, c.DEFAULT_REACTIVATE_DELAY)), g(c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL), ManualCoolingBehaviour(o.get(c.CONF_MANUAL_COOLING_BEHAVIOUR, ManualCoolingBehaviour.ASK)))

    async def async_set_mode(self, mode: c.ControlMode) -> None: self.control_mode = mode; await self._save_state(); await self.async_run_evaluation("control_mode")

    async def async_initialize(self) -> None:
        stored = await self._store.async_load() or {}
        controls, session = stored.get("controls", {}), stored.get("session", {})
        with suppress(ValueError): self.control_mode = c.ControlMode(str(controls.get("mode", c.ControlMode.MONITOR)))
        self.cooling_enabled, self.dry_mode_enabled, self.afternoon_cooling = bool(controls.get("cooling_enabled", True)), bool(controls.get(c.CONF_DRY_MODE_ENABLED, True)), bool(controls.get(c.CONF_AFTERNOON_COOLING, False))
        last = session.get("last")
        self._session = CachedState(reactivate_delay=int(session.get("reactivate_delay", 0)), tolerated=int(session.get("tolerated", 0)), last=HomeOutput(last) if last else None, failed_to_change=int(session.get("failed_to_change", 0)))
        self._auto_mode, self._last_changed = bool(stored.get("auto_mode", False)), stored.get("last_changed")
        self._recent = deque(stored.get("recent_evaluations", []), maxlen=c.MAX_RECENT_EVALUATIONS)
        self._aircon_timer_finishes_at = dt_util.parse_datetime(str(v)) if (v := stored.get("aircon_timer_finishes_at")) else None
        self._timer_target_notified, self._timer_prompt_id = bool(stored.get("timer_target_notified", False)), stored.get("timer_prompt_id")
        self._parameters = {}
        for k, v in stored.get("parameters", {}).items():
            if k in c.RETIRED_CONFIG_KEYS: continue
            with suppress(TypeError, ValueError): self._parameters[str(k)] = float(v)
        self._schedule_timer_expiry()
        if self._notification_unsub is None:
            self._notification_unsub = self.hass.bus.async_listen(c.EVENT_NOTIFICATION_ACTION, self._async_handle_notification_action)
            self.config_entry.async_on_unload(self._unsubscribe_notifications)

    async def async_set_control(self, key: str, value: bool) -> None: setattr(self, key, value); await self._save_state(); await self.async_run_evaluation("control")
    async def async_shutdown(self) -> None: self._cancel_timer_expiry(); self._unsubscribe_notifications()
    async def async_run_evaluation(self, trigger: str = "manual") -> None: self.async_set_updated_data(await self._evaluate(trigger))

    async def _async_update_data(self) -> CoordinatorData:
        try: return await self._evaluate("poll")
        except ConfigEntryNotReady as err: raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            self._create_issue(c.ISSUE_RUNTIME, {"error": str(err)})
            raise UpdateFailed(translation_domain=c.DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}) from err

    async def _evaluate(self, trigger: str, *, notification_action: str | None = None) -> CoordinatorData:
        async with self._lock:
            if notification_action is not None and notification_action not in self._timer_notification_actions(): return self.data
            now = dt_util.utcnow().isoformat(); self._fallback_inputs = {}; self._clear_issue(c.ISSUE_ENTITY_UNAVAILABLE); home, _ = self._build_home_input(); params = self.parameters
            if notification_action is not None and (not home.timer or home.auto or home.aircon_mode not in (AirconMode.COOL, AirconMode.DRY) or self.control_mode in (c.ControlMode.DISABLED, c.ControlMode.MONITOR) or params.manual_cooling_behaviour is not ManualCoolingBehaviour.ASK): notification_action = None
            if home.timer and home.aircon_mode is AirconMode.OFF: self._clear_aircon_timer(); home = replace(home, timer=False)
            if notification_action is not None and notification_action.endswith("_five"):
                self._aircon_timer_finishes_at = min(self._aircon_timer_finishes_at or dt_util.utcnow(), dt_util.utcnow() + timedelta(minutes=5)); self._schedule_timer_expiry()
            current = current_state(home); smoothed_gen = self._smoothed_generation(home.generation); decision_home = replace(home, generation=smoothed_gen)
            if not self._initialized: self._initialized = True; self._sync_on_startup(current, home)
            elif self._session.last is None: self._session.last = current
            if notification_action is not None and notification_action.endswith("_off"):
                self._session.tolerated, self._session.reactivate_delay = 0, params.reactivate_delay
                result = AdjustResult(HomeOutput.OFF, "Turned off from notification")
            else: result = adjust(params, decision_home, self._session)
            adjustment, reason = result.output, result.reason; await self._execute_adjustment(adjustment); timer = self._active_aircon_timer()
            if notification_action is not None: self._timer_prompt_id = None
            previous = self._session.last; applied = apply_adjustment(self._session, current, adjustment); is_monitor = self.control_mode is c.ControlMode.MONITOR
            if is_monitor: self._session.failed_to_change, applied = 0, True
            if not applied: raise HomeAssistantError("failed to apply adjustment")
            if previous is not None and previous != self._session.last and adjustment is not HomeOutput.RESET: self._last_changed = now; await self._maybe_notify(previous, current, adjustment)
            await self._maybe_notify_timer_target(home)
            mode = self._session.last or current
            record = {"time": now, "trigger": trigger, "current": current.value, "adjustment": adjustment.value, "mode": mode.value, "reason": reason, "dry_run": is_monitor, "control_mode": self.control_mode.value, "manual_cooling_behaviour": params.manual_cooling_behaviour.value, "raw_generation": home.generation, "smoothed_generation": round(smoothed_gen, 1), "fallback_inputs": dict(self._fallback_inputs)} | {k: getattr(home, k) for k in _HOME_RECORD_FIELDS} | {k: getattr(self._session, k) for k in _SESSION_RECORD_FIELDS}
            self._last_record = record; self._recent.appendleft(record); await self._save_state(); self.hass.bus.async_fire(c.EVENT_EVALUATION, record)
            for issue in _CLEAR_ISSUES: self._clear_issue(issue)
            self._first_refresh_done = True
            return CoordinatorData(mode=mode, adjustment=adjustment, decision=f"{mode.value} - {reason}", solar_available=home.have_solar, auto_mode=self._auto_mode, timer_finishes_at=timer, last_evaluated=now, last_changed=self._last_changed)

    async def _maybe_notify(self, previous: HomeOutput, current: HomeOutput, adjustment: HomeOutput) -> None:
        _emoji = {"Cool": "❄️", "Dry": "💧", "Off": "⏹", "On": "🔛", "Timer": "⏱", "Disabled": "⏸", "Reset": "🔄"}
        new = (self._session.last or current).value; icon = _emoji.get(new, "")
        await self._send_notification({"title": f"{icon} Aircon → {new}", "message": f"Switched from {previous.value} to {new}"})

    async def _send_notification(self, data: dict[str, Any]) -> bool:
        service = str(self.config_entry.options.get(c.CONF_NOTIFICATION_SERVICE, "")).strip()
        if not service: self._clear_issue(c.ISSUE_NOTIFICATION_SERVICE); return False
        domain, name = service.split(".", 1) if "." in service else ("notify", service)
        if not self.hass.services.has_service(domain, name): self._create_issue(c.ISSUE_NOTIFICATION_SERVICE, {"service": service}); return False
        self._clear_issue(c.ISSUE_NOTIFICATION_SERVICE)
        try: await self.hass.services.async_call(domain, name, data, blocking=True)
        except (HomeAssistantError, TimeoutError): self._create_issue(c.ISSUE_NOTIFICATION_SERVICE, {"service": service}); return False
        return True

    def _timer_notification_actions(self) -> dict[str, str]:
        if self._timer_prompt_id is None: return {}
        prefix = f"{c.DOMAIN}_{self.config_entry.entry_id}_{self._timer_prompt_id}"
        return {f"{prefix}_off": "Turn off", f"{prefix}_keep": "Keep running", f"{prefix}_five": "5 mins"}

    async def _maybe_notify_timer_target(self, home: HomeInput) -> None:
        if self._timer_target_notified or self._active_aircon_timer() is None or home.auto or home.aircon_mode not in (AirconMode.COOL, AirconMode.DRY): return
        if self.control_mode in (c.ControlMode.DISABLED, c.ControlMode.MONITOR) or self.parameters.manual_cooling_behaviour is not ManualCoolingBehaviour.ASK: return
        if not home.temperature_available or home.temperature > self.parameters.temperature_cool: return
        self._timer_prompt_id = uuid4().hex
        data = {"title": "Aircon target reached", "message": f"Room: {home.temperature:g}°C. Target: {self.parameters.temperature_cool:g}°C. Turn cooling off? No response leaves the timer unchanged.", "data": {"actions": [{"action": action, "title": title} for action, title in self._timer_notification_actions().items()]}}
        self._timer_target_notified = await self._send_notification(data)
        if not self._timer_target_notified: self._timer_prompt_id = None

    async def _async_handle_notification_action(self, event: Event[dict[str, Any]]) -> None:
        action = event.data.get("action")
        if not isinstance(action, str) or action not in self._timer_notification_actions(): return
        self.async_set_updated_data(await self._evaluate("notification_action", notification_action=action))

    def _unsubscribe_notifications(self) -> None:
        if self._notification_unsub is not None: self._notification_unsub(); self._notification_unsub = None

    def _smoothed_generation(self, raw_gen: float) -> float:
        window = max(1, int(self.config_entry.options.get(c.CONF_SMOOTHING_WINDOW, c.DEFAULT_SMOOTHING_WINDOW)))
        if window <= 1 or not self._recent: return raw_gen
        vals: list[float] = [r.get("raw_generation", r.get("generation", 0.0)) for r in list(self._recent)[:window - 1]] + [raw_gen]
        return sum(vals) / len(vals)

    def _entity_id(self, key: str) -> str:
        return str(self.config_entry.options.get(key, self.config_entry.data.get(key, ""))).strip() or str(self.config_entry.data[key])

    def _state(self, conf_key: str, label: str, *, allow_unavailable: bool = False) -> State: return self._get_state(self._entity_id(conf_key), label, allow_unavailable=allow_unavailable)

    def _build_home_input(self) -> tuple[HomeInput, datetime | None]:
        timer = self._active_aircon_timer(); climate = self._state(c.CONF_CLIMATE_ENTITY_ID, "climate")
        gen = self._state(c.CONF_GENERATION_ENTITY_ID, "generation", allow_unavailable=True); grid = self._state(c.CONF_GRID_ENTITY_ID, "grid", allow_unavailable=True); temp = self._state(c.CONF_TEMPERATURE_ENTITY_ID, "temperature", allow_unavailable=True); hum = self._state(c.CONF_HUMIDITY_ENTITY_ID, "humidity", allow_unavailable=True)
        discharge = self._optional_power(c.CONF_BATTERY_POWER_ENTITY_ID, "battery_power", invert=bool(self.config_entry.options.get(c.CONF_BATTERY_INVERT, False)))
        gen_live = "generation" not in self._fallback_inputs; grid_live = "grid" not in self._fallback_inputs  # a fallback means the sensor is unknown/unavailable (e.g. inverter asleep)
        generation = self._normalized_power(gen, "generation") if gen_live else 0.0; grid_usage = self._normalized_power(grid, "grid", invert=bool(self.config_entry.options.get(c.CONF_GRID_INVERT, False))) if grid_live else 0.0  # normalise only live readings; a stale fallback stays 0
        have_solar = gen_live and generation > 0.0
        battery_discharge = max(0.0, (discharge or 0.0) - self.get_parameter(c.CONF_BATTERY_DISCHARGE_TOLERANCE, c.DEFAULT_BATTERY_DISCHARGE_TOLERANCE))  # a battery covering the load hides the draw from the grid meter: pass it to the rules separately from grid usage
        mode = AirconMode.UNKNOWN
        with suppress(ValueError): mode = AirconMode(str(climate.state).lower().strip())
        if mode not in (AirconMode.COOL, AirconMode.DRY): self._auto_mode = False  # self-heal: only COOL/DRY are home-rules-owned runs; a user-switched mode is external
        before_afternoon = dt_util.now().hour < int(self.config_entry.options.get(c.CONF_AFTERNOON_COOLING_HOUR, c.DEFAULT_AFTERNOON_COOLING_HOUR))
        aggressive = self.control_mode is c.ControlMode.BOOST_COOLING; enabled = self.control_mode is not c.ControlMode.DISABLED
        temperature = self._normalized_temperature(temp); temperature_available = "temperature" not in self._fallback_inputs and isfinite(temperature)
        return HomeInput(mode, have_solar, generation, grid_usage, timer is not None, temperature, self._state_to_float(hum, "humidity"), self._auto_mode, aggressive, enabled, self.cooling_enabled, self.afternoon_cooling and before_afternoon, battery_discharge, temperature_available), timer

    def _sync_on_startup(self, current: HomeOutput, home: HomeInput) -> None:
        if self._session.last is None: self._session.last = current
        elif home.timer and self._session.last is HomeOutput.TIMER: return
        elif self._session.last is HomeOutput.TIMER and home.aircon_mode is not AirconMode.OFF: return  # cap elapsed while down but aircon still on: keep TIMER so adjust() issues OFF, don't re-arm
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
        if adjustment is HomeOutput.TIMER:
            self._timer_target_notified, self._timer_prompt_id = False, None
            self._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(minutes=max(1, int(self.config_entry.options.get(c.CONF_AIRCON_TIMER_DURATION, c.DEFAULT_AIRCON_TIMER_DURATION)))); self._schedule_timer_expiry()
        elif adjustment in (HomeOutput.COOL, HomeOutput.DRY, HomeOutput.OFF):
            self._clear_aircon_timer()
        if adjustment in (HomeOutput.COOL, HomeOutput.DRY): self._auto_mode = True
        elif adjustment is HomeOutput.OFF: self._auto_mode = False

    def _get_state(self, entity_id: str, label: str, *, allow_unavailable: bool = False) -> State:
        state = self.hass.states.get(entity_id)
        if state is None:
            if not allow_unavailable and not self._first_refresh_done: raise ConfigEntryNotReady(f"Required entity not yet available: {entity_id}")
            self._create_issue(c.ISSUE_ENTITY_MISSING, {"entity_id": entity_id, "label": label}); raise ValueError(f"missing entity: {entity_id}")
        raw = str(state.state).lower()
        if raw not in {STATE_UNKNOWN, STATE_UNAVAILABLE}: return state
        if not allow_unavailable:
            if not self._first_refresh_done: raise ConfigEntryNotReady(f"Required entity not yet available: {entity_id}")
            self._create_issue(c.ISSUE_ENTITY_UNAVAILABLE, {"entity_id": entity_id, "label": label}); raise ValueError(f"entity unavailable: {entity_id}")
        self._fallback_inputs[label] = raw
        if label in self._FALLBACK_DEFAULTS: return State(entity_id, self._FALLBACK_DEFAULTS[label], state.attributes)
        if label == "temperature": return State(entity_id, str(self.parameters.temperature_threshold - 0.1), state.attributes)
        if label == "humidity": return State(entity_id, str(c.DRY_MODE_HUMIDITY_CUTOFF - 1.0), state.attributes)
        return state

    @staticmethod
    def _state_to_float(state: State, label: str) -> float:
        try: return float(state.state)
        except ValueError as err: raise ValueError(f"invalid numeric {label}: {state.state}") from err

    def _active_aircon_timer(self) -> datetime | None:
        if self._aircon_timer_finishes_at and self._aircon_timer_finishes_at <= dt_util.utcnow(): self._clear_aircon_timer()
        return self._aircon_timer_finishes_at

    def _clear_aircon_timer(self) -> None:
        self._aircon_timer_finishes_at = None; self._timer_target_notified, self._timer_prompt_id = False, None; self._schedule_timer_expiry()

    def _cancel_timer_expiry(self) -> None:
        if self._timer_expiry_handle is None: return
        self._timer_expiry_handle.cancel(); self._timer_expiry_handle = None

    def _schedule_timer_expiry(self) -> None:
        self._cancel_timer_expiry()
        if self._aircon_timer_finishes_at is None: return
        delay = (self._aircon_timer_finishes_at - dt_util.utcnow()).total_seconds()
        if delay <= 0: return  # already elapsed (e.g. a cap loaded on restart): the imminent evaluation clears it and issues OFF, avoiding a second racing eval that could re-arm
        self._timer_expiry_handle = self.hass.loop.call_later(delay, self._async_handle_timer_expiry)

    def _async_handle_timer_expiry(self) -> None:
        self._timer_expiry_handle = None
        self.hass.async_create_task(self.async_run_evaluation("timer_expired"))

    def _normalized_power(self, state: State, label: str, *, invert: bool = False) -> float:
        value = -self._state_to_float(state, label) if invert else self._state_to_float(state, label); unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip()
        try: return max(0.0, PowerConverter.convert(value, UnitOfPower(unit), UnitOfPower.WATT))
        except ValueError:
            self._create_issue(c.ISSUE_INVALID_UNIT, {"entity_id": state.entity_id, "unit": unit or "(none)"}); raise ValueError(f"unsupported power unit for {state.entity_id}: {unit}") from None

    def _optional_state(self, conf_key: str, label: str) -> State | None:
        entity_id = str(self.config_entry.options.get(conf_key, self.config_entry.data.get(conf_key, ""))).strip()
        if not entity_id: return None
        state = self.hass.states.get(entity_id)
        if state is None or str(state.state).lower() in {STATE_UNKNOWN, STATE_UNAVAILABLE}: self._fallback_inputs[label] = "missing" if state is None else str(state.state).lower(); return None  # optional input: fail open, but record it
        return state

    def _optional_power(self, conf_key: str, label: str, *, invert: bool = False) -> float | None:
        return None if (state := self._optional_state(conf_key, label)) is None else self._normalized_power(state, label, invert=invert)

    def _normalized_temperature(self, state: State) -> float:
        value = self._state_to_float(state, "temperature"); unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip().upper()
        if unit in {"", "°C", "C"}: return value
        if unit in {"°F", "F"}: return TemperatureConverter.convert(value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS)
        raise ValueError(f"unsupported temperature unit: {unit}")

    async def _save_state(self) -> None:
        session = asdict(self._session); session["last"] = self._session.last.value if self._session.last else None
        await self._store.async_save({"controls": {"mode": self.control_mode.value, "cooling_enabled": self.cooling_enabled, c.CONF_DRY_MODE_ENABLED: self.dry_mode_enabled, c.CONF_AFTERNOON_COOLING: self.afternoon_cooling}, "session": session, "auto_mode": self._auto_mode, "last_changed": self._last_changed, "recent_evaluations": list(self._recent), "aircon_timer_finishes_at": self._aircon_timer_finishes_at and self._aircon_timer_finishes_at.isoformat(), "timer_target_notified": self._timer_target_notified, "timer_prompt_id": self._timer_prompt_id, "parameters": dict(self._parameters)})

    def _create_issue(self, issue: str, placeholders: dict[str, str]) -> None:
        ir.async_create_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}", is_fixable=False, is_persistent=False, severity=ir.IssueSeverity.ERROR, translation_key=issue, translation_placeholders=placeholders)

    def _clear_issue(self, issue: str) -> None: ir.async_delete_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}")


type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]
