# fmt: off
# ruff: noqa: E501, E701, E702

import asyncio
from collections import deque
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
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
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
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
    RuleParameters,
    adjust,
    apply_adjustment,
    current_state,
)

_HOME_RECORD_FIELDS = ("generation", "grid_usage", "temperature", "temperature_available", "humidity", "humidity_available", "have_solar", "auto", "aircon_mode", "battery_discharge", "battery_soc", "someone_home", "afternoon_enabled", "afternoon_planning", "afternoon_window_open", "afternoon_start_allowed", "afternoon_forecast_available", "afternoon_forecast_recovery", "afternoon_window_start", "afternoon_window_end", "afternoon_window_energy", "generation_available", "grid_available", "battery_power_available")
_SESSION_RECORD_FIELDS = ("tolerated", "reactivate_at", "solar_run_eligible", "solar_lost_at", "solar_recovered_at", "battery_run_authorized", "afternoon_run_authorized", "afternoon_battery_run", "afternoon_window_start", "afternoon_window_end", "afternoon_window_energy")
_CLEAR_ISSUES = (c.ISSUE_RUNTIME, c.ISSUE_ENTITY_MISSING, c.ISSUE_INVALID_UNIT, c.ISSUE_ENTITY_UNAVAILABLE)


@dataclass
class CoordinatorData:
    mode: HomeOutput = HomeOutput.OFF; adjustment: HomeOutput = HomeOutput.NO_CHANGE; decision: str = ""; solar_available: bool = False; auto_mode: bool = False; timer_finishes_at: datetime | None = None; last_evaluated: str | None = None; last_changed: str | None = None


@dataclass
class AfternoonContext:
    planning: bool = False
    window_open: bool = False
    forecast_available: bool = True
    forecast_recovery: bool = False
    window_start: str | None = None
    window_end: str | None = None
    window_energy: float = 0.0
    start_allowed: bool = False


class HomeRulesCoordinator(DataUpdateCoordinator[CoordinatorData]):
    config_entry: ConfigEntry
    _FALLBACK_DEFAULTS = {"generation": "0", "grid": "0"}
    _recent: deque[dict[str, Any]]
    _last_record: dict[str, Any]
    _last_changed: str | None
    _fallback_inputs: dict[str, str]

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass, self.config_entry = hass, config_entry; self._lock, self._session = asyncio.Lock(), CachedState(); self.control_mode, self.cooling_enabled, self.dry_mode_enabled = c.ControlMode.MONITOR, True, True
        self.only_cool_when_home, self.allow_away_battery_cooling = False, False
        self.afternoon_cooling_enabled = False
        self.power_policy = c.PowerPolicy.SOLAR_ONLY
        self.stop_at_comfort_temperature, self.automatic_target_notifications = False, True
        self._parameters: dict[str, float] = {}; self._auto_mode = self._initialized = self._first_refresh_done = False; self._recent, self._last_changed, self._last_record, self._fallback_inputs = deque(maxlen=c.MAX_RECENT_EVALUATIONS), None, {}, {}; self._aircon_timer_finishes_at: datetime | None = None
        self._target_notified = False; self._target_prompt_id: str | None = None; self._notification_unsub: CALLBACK_TYPE | None = None
        self._climate_unsub: CALLBACK_TYPE | None = None; self._climate_write_in_progress = False
        self._automatic_setpoint: float | None = None; self._adjusted_setpoint: float | None = None; self._observed_setpoint: float | None = None
        self._store = Store[dict[str, Any]](hass, c.STORAGE_VERSION, f"{c.DOMAIN}_{config_entry.entry_id}")
        interval = timedelta(seconds=int(config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))); name = f"{c.DOMAIN} ({config_entry.entry_id})"
        super().__init__(hass, c.LOGGER, name=name, update_interval=interval, always_update=True, config_entry=config_entry); self.data = CoordinatorData()

    def get_parameter(self, key: str, default: float) -> float: return float(self._parameters.get(key, self.config_entry.options.get(key, default)))
    @property
    def last_evaluation(self) -> dict[str, Any]: return deepcopy(self._last_record)
    @property
    def recent_evaluations(self) -> list[dict[str, Any]]: return deepcopy(list(self._recent))
    @property
    def occupancy_entity_id(self) -> str: return str(self.config_entry.options.get(c.CONF_OCCUPANCY_ENTITY_ID, c.HOME_ZONE_ENTITY_ID)).strip() or c.HOME_ZONE_ENTITY_ID

    async def async_set_parameter(self, key: str, value: float) -> None:
        if key in (c.CONF_TEMPERATURE_THRESHOLD, c.CONF_TEMPERATURE_COOL):
            candidate = replace(self.parameters, temperature_threshold=value) if key == c.CONF_TEMPERATURE_THRESHOLD else replace(self.parameters, temperature_cool=value)
            if not candidate.temperature_range_valid: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_temperature_range")
        if key in (c.CONF_BATTERY_FULL_THRESHOLD, c.CONF_BATTERY_RESERVE_THRESHOLD):
            candidate = replace(self.parameters, battery_full_threshold=value) if key == c.CONF_BATTERY_FULL_THRESHOLD else replace(self.parameters, battery_reserve_threshold=value)
            if not candidate.battery_range_valid: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_battery_range")
        if key in (c.CONF_AFTERNOON_ENERGY_BUDGET, c.CONF_AFTERNOON_BATTERY_RESERVE):
            candidate = replace(self.parameters, afternoon_energy_budget=value) if key == c.CONF_AFTERNOON_ENERGY_BUDGET else replace(self.parameters, afternoon_battery_reserve=value)
            if not candidate.afternoon_range_valid: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_afternoon_range")
        self._parameters[key] = value; await self._save_state()

    @property
    def parameters(self) -> RuleParameters:
        g, o = self.get_parameter, self.config_entry.options
        return RuleParameters(g(c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD), g(c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD), g(c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD), c.DRY_MODE_HUMIDITY_CUTOFF, self.dry_mode_enabled, int(o.get(c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY)), float(o.get(c.CONF_REACTIVATE_DELAY_MINUTES, c.DEFAULT_REACTIVATE_DELAY_MINUTES)), g(c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL), self.stop_at_comfort_temperature, solar_run_on_minutes=float(o.get(c.CONF_SOLAR_RUN_ON_MINUTES, c.DEFAULT_SOLAR_RUN_ON_MINUTES)), evaluation_interval=float(o.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL)), battery_full_threshold=g(c.CONF_BATTERY_FULL_THRESHOLD, c.DEFAULT_BATTERY_FULL_THRESHOLD), battery_reserve_threshold=g(c.CONF_BATTERY_RESERVE_THRESHOLD, c.DEFAULT_BATTERY_RESERVE_THRESHOLD), afternoon_energy_budget=g(c.CONF_AFTERNOON_ENERGY_BUDGET, c.DEFAULT_AFTERNOON_ENERGY_BUDGET), afternoon_battery_reserve=g(c.CONF_AFTERNOON_BATTERY_RESERVE, c.DEFAULT_AFTERNOON_BATTERY_RESERVE))

    async def async_set_mode(self, mode: c.ControlMode) -> None: self.control_mode = mode; await self._save_state()
    async def async_set_power_policy(self, policy: c.PowerPolicy) -> None: self.power_policy = policy; self._session.tolerated = 0; await self._save_state()

    async def async_initialize(self) -> None:
        stored = await self._store.async_load() or {}
        controls, session = stored.get("controls", {}), stored.get("session", {})
        mode = str(controls.get("mode", c.ControlMode.MONITOR))
        with suppress(ValueError): self.control_mode = c.ControlMode.AUTOMATIC if mode in {"solar_cooling", "boost_cooling"} else c.ControlMode(mode)
        with suppress(ValueError): self.power_policy = c.PowerPolicy(controls.get(c.CONF_POWER_POLICY, c.PowerPolicy.ALLOW_BATTERY_GRID if mode == "boost_cooling" else c.PowerPolicy.SOLAR_ONLY))
        self.cooling_enabled, self.dry_mode_enabled = bool(controls.get("cooling_enabled", True)), bool(controls.get(c.CONF_DRY_MODE_ENABLED, True))
        self.only_cool_when_home = bool(controls.get(c.CONF_ONLY_COOL_WHEN_HOME, False))
        self.allow_away_battery_cooling = bool(controls.get(c.CONF_ALLOW_AWAY_BATTERY_COOLING, False))
        self.afternoon_cooling_enabled = bool(controls.get(c.CONF_AFTERNOON_COOLING_ENABLED, False))
        self.stop_at_comfort_temperature = bool(controls.get(c.CONF_STOP_AT_COMFORT_TEMPERATURE, self.config_entry.options.get(c.CONF_MANUAL_COOLING_BEHAVIOUR) == "stop"))
        self.automatic_target_notifications = bool(controls.get(c.CONF_AUTOMATIC_TARGET_NOTIFICATIONS, True))
        last = session.get("last")
        legacy_delay = float(session.get("reactivate_delay", 0)) * float(self.config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))
        self._session = CachedState(reactivate_at=float(session.get("reactivate_at", dt_util.utcnow().timestamp() + legacy_delay if legacy_delay else 0)), tolerated=int(session.get("tolerated", 0)), last=HomeOutput(last) if last else None, failed_to_change=int(session.get("failed_to_change", 0)), solar_run_eligible=bool(session.get("solar_run_eligible", False)), solar_lost_at=session.get("solar_lost_at"), solar_recovered_at=session.get("solar_recovered_at"), battery_run_authorized=bool(session.get("battery_run_authorized", False)), afternoon_run_authorized=bool(session.get("afternoon_run_authorized", False)), afternoon_battery_run=bool(session.get("afternoon_battery_run", False)), afternoon_window_start=session.get("afternoon_window_start"), afternoon_window_end=session.get("afternoon_window_end"), afternoon_window_energy=float(session.get("afternoon_window_energy", 0.0)))
        self._auto_mode, self._last_changed = bool(stored.get("auto_mode", False)), stored.get("last_changed")
        self._recent = deque(stored.get("recent_evaluations", []), maxlen=c.MAX_RECENT_EVALUATIONS)
        self._aircon_timer_finishes_at = dt_util.parse_datetime(str(v)) if (v := stored.get("aircon_timer_finishes_at")) else None
        self._target_notified, self._target_prompt_id = bool(stored.get("target_notified", stored.get("timer_target_notified", False))), stored.get("target_prompt_id", stored.get("timer_prompt_id"))
        last_target = self._recent[0].get("target_temperature") if self._recent and self._auto_mode else None
        self._automatic_setpoint = self._valid_setpoint(stored.get("automatic_setpoint", last_target))
        self._adjusted_setpoint = self._valid_setpoint(stored.get("adjusted_setpoint"))
        self._parameters = {}
        for k, v in stored.get("parameters", {}).items():
            if k not in c.PERSISTED_PARAMETER_KEYS: continue
            with suppress(TypeError, ValueError): self._parameters[str(k)] = float(v)
        if self._notification_unsub is None:
            self._notification_unsub = self.hass.bus.async_listen(c.EVENT_NOTIFICATION_ACTION, self._async_handle_notification_action)
            self.config_entry.async_on_unload(self._unsubscribe_notifications)
        if self._climate_unsub is None:
            self._climate_unsub = async_track_state_change_event(self.hass, [self._entity_id(c.CONF_CLIMATE_ENTITY_ID)], self._async_handle_climate_change)
            self.config_entry.async_on_unload(self._unsubscribe_climate)

    async def async_set_control(self, key: str, value: bool) -> None: setattr(self, key, value); await self._save_state()
    async def async_shutdown(self) -> None: self._unsubscribe_notifications(); self._unsubscribe_climate()
    def _unsubscribe_climate(self) -> None:
        if self._climate_unsub is not None: self._climate_unsub(); self._climate_unsub = None
    @staticmethod
    def _valid_setpoint(value: object) -> float | None:
        return float(value) if isinstance(value, (int, float)) and isfinite(value) else None

    def _reset_target_tracking(self) -> None:
        self._target_notified, self._target_prompt_id = False, None
        self._automatic_setpoint = self._adjusted_setpoint = self._observed_setpoint = None

    @callback
    def _async_handle_climate_change(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None: return
        if new.state == AirconMode.OFF:
            was_running = self._auto_mode or self._session.last in (HomeOutput.COOL, HomeOutput.DRY, HomeOutput.ON, HomeOutput.TIMER) or (old is not None and old.state not in (AirconMode.OFF, STATE_UNKNOWN, STATE_UNAVAILABLE))
            self._auto_mode = False; self._reset_target_tracking(); self._clear_aircon_timer(); self._session.last = HomeOutput.OFF
            self._session.clear_power_run()
            if was_running:
                self._session.record_stop(dt_util.utcnow().timestamp(), self.parameters.reactivate_delay)
        elif self._auto_mode and new.state in (AirconMode.COOL, AirconMode.DRY):
            target = self._valid_setpoint(new.attributes.get("temperature"))
            if not self._climate_write_in_progress and old is not None and old.attributes.get("temperature") != target and target is not None and target != self._automatic_setpoint: self._adjusted_setpoint = target
            if not self._climate_write_in_progress or target == self._automatic_setpoint: self._observed_setpoint = target
        elif new.state in (AirconMode.AUTO, AirconMode.HEAT, AirconMode.HEAT_COOL, AirconMode.FAN_ONLY):
            self._auto_mode = False; self._reset_target_tracking()
    async def async_run_evaluation(self, trigger: str = "manual") -> None: self.async_set_updated_data(await self._evaluate_with_error_handling(trigger))

    async def _async_update_data(self) -> CoordinatorData:
        return await self._evaluate_with_error_handling("poll")

    async def _evaluate_with_error_handling(self, trigger: str, *, notification_action: str | None = None) -> CoordinatorData:
        try: return await self._evaluate(trigger, notification_action=notification_action)
        except ConfigEntryNotReady as err: raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            self._create_issue(c.ISSUE_RUNTIME, {"error": str(err)})
            raise UpdateFailed(translation_domain=c.DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}) from err

    async def _evaluate(self, trigger: str, *, notification_action: str | None = None) -> CoordinatorData:
        async with self._lock:
            if notification_action is not None and notification_action not in self._target_notification_actions(): return self.data
            now = dt_util.utcnow().isoformat(); self._fallback_inputs = {}; self._clear_issue(c.ISSUE_ENTITY_UNAVAILABLE); home, _ = self._build_home_input(); params = self.parameters; afternoon = await self._afternoon_context(params); home = replace(home, afternoon_planning=afternoon.planning, afternoon_window_open=afternoon.window_open, afternoon_start_allowed=afternoon.start_allowed, afternoon_forecast_available=afternoon.forecast_available, afternoon_forecast_recovery=afternoon.forecast_recovery, afternoon_window_start=afternoon.window_start, afternoon_window_end=afternoon.window_end, afternoon_window_energy=afternoon.window_energy)
            if notification_action is not None and (home.auto or home.aircon_mode not in (AirconMode.COOL, AirconMode.DRY) or self.control_mode in (c.ControlMode.DISABLED, c.ControlMode.MONITOR) or params.stop_at_comfort_temperature or (self._session.last is HomeOutput.TIMER and not home.timer)): notification_action = None
            if home.timer and home.aircon_mode is AirconMode.OFF: self._clear_aircon_timer(); home = replace(home, timer=False)
            if notification_action is not None and notification_action.endswith("_five"):
                finishes = dt_util.utcnow() + timedelta(minutes=5)
                self._aircon_timer_finishes_at = min(self._aircon_timer_finishes_at or finishes, finishes)
                home = replace(home, timer=True); self._session.last = HomeOutput.TIMER
            current = current_state(home); smoothed_gen = self._smoothed_generation(home.generation); decision_home = replace(home, generation=smoothed_gen)
            if not self._initialized: self._initialized = True; self._sync_on_startup(current, home)
            elif self._session.last is None: self._session.last = current
            if notification_action is not None and notification_action.endswith("_off"):
                self._session.record_stop(home.now, params.reactivate_delay)
                result = AdjustResult(HomeOutput.OFF, "Turned off from notification")
            else: result = adjust(params, decision_home, self._session)
            adjustment, reason = result.output, result.reason; target_temperature = self._adjusted_setpoint if home.auto and self._adjusted_setpoint is not None else params.temperature_threshold if self._session.afternoon_battery_run else params.temperature_cool
            previous = self._session.last; applied = apply_adjustment(self._session, current, adjustment); is_monitor = self.control_mode is c.ControlMode.MONITOR
            if is_monitor: self._session.failed_to_change, applied = 0, True
            if not applied: raise HomeAssistantError("failed to apply adjustment")
            await self._execute_adjustment(adjustment, target_temperature)
            if adjustment is HomeOutput.NO_CHANGE and home.auto and home.enabled and home.temperature_available and home.aircon_mode in (AirconMode.COOL, AirconMode.DRY) and self.control_mode is c.ControlMode.AUTOMATIC:
                climate = self._state(c.CONF_CLIMATE_ENTITY_ID, "climate")
                if climate.attributes.get("temperature") is not None and climate.attributes["temperature"] != target_temperature: await self._set_climate_target(target_temperature)
            timer = self._active_aircon_timer()
            if notification_action is not None: self._target_prompt_id = None
            if previous is not None and previous != self._session.last and adjustment is not HomeOutput.RESET: self._last_changed = now; await self._maybe_notify(previous, current, adjustment)
            await self._maybe_notify_target(home, adjustment)
            mode = self._session.last or current
            record = {"time": now, "trigger": trigger, "current": current.value, "adjustment": adjustment.value, "mode": mode.value, "reason": reason, "dry_run": is_monitor, "control_mode": self.control_mode.value, "power_policy": self.power_policy.value, "target_temperature": target_temperature, "adjusted_setpoint": self._adjusted_setpoint, "stop_at_comfort_temperature": params.stop_at_comfort_temperature, "automatic_target_notifications": self.automatic_target_notifications, "raw_generation": home.generation, "smoothed_generation": round(smoothed_gen, 1), "fallback_inputs": dict(self._fallback_inputs), "reactivate_delay_remaining": max(0.0, self._session.reactivate_at - home.now), "solar_run_on_deadline": self._session.solar_run_on_deadline(params)} | {k: getattr(home, k) for k in _HOME_RECORD_FIELDS} | {k: getattr(self._session, k) for k in _SESSION_RECORD_FIELDS}
            record["parameters"] = asdict(params)
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

    def _target_notification_actions(self) -> dict[str, str]:
        if self._target_prompt_id is None: return {}
        prefix = f"{c.DOMAIN}_{self.config_entry.entry_id}_{self._target_prompt_id}"
        return {f"{prefix}_off": "Turn off", f"{prefix}_keep": "Keep running", f"{prefix}_five": "5 mins"}

    async def _maybe_notify_target(self, home: HomeInput, adjustment: HomeOutput) -> None:
        if self._target_notified or home.aircon_mode not in (AirconMode.COOL, AirconMode.DRY): return
        if self.control_mode in (c.ControlMode.DISABLED, c.ControlMode.MONITOR): return
        if home.auto and not self.automatic_target_notifications: return
        if not home.temperature_available or home.temperature is None or home.temperature > self.parameters.temperature_cool: return
        data: dict[str, Any] = {"title": "Aircon target reached", "message": f"Room: {home.temperature:g}°C. Target: {self.parameters.temperature_cool:g}°C."}
        if not home.auto and adjustment is not HomeOutput.OFF:
            self._target_prompt_id = uuid4().hex
            data["message"] += " Turn cooling off? No response leaves the timer unchanged." if home.timer else " Turn cooling off? No response leaves cooling unchanged."
            data["data"] = {"actions": [{"action": action, "title": title} for action, title in self._target_notification_actions().items()]}
        self._target_notified = await self._send_notification(data)
        if not self._target_notified: self._target_prompt_id = None

    async def _async_handle_notification_action(self, event: Event[dict[str, Any]]) -> None:
        action = event.data.get("action")
        if not isinstance(action, str) or action not in self._target_notification_actions(): return
        self.async_set_updated_data(await self._evaluate_with_error_handling("notification_action", notification_action=action))

    def _unsubscribe_notifications(self) -> None:
        if self._notification_unsub is not None: self._notification_unsub(); self._notification_unsub = None

    def _smoothed_generation(self, raw_gen: float) -> float:
        window = max(1, int(self.config_entry.options.get(c.CONF_SMOOTHING_WINDOW, c.DEFAULT_SMOOTHING_WINDOW)))
        if window <= 1 or not self._recent: return raw_gen
        vals: list[float] = [r.get("raw_generation", r.get("generation", 0.0)) for r in list(self._recent)[:window - 1]] + [raw_gen]
        return sum(vals) / len(vals)

    async def _afternoon_context(self, params: RuleParameters) -> AfternoonContext:
        context = AfternoonContext()
        if not self.afternoon_cooling_enabled: return context
        local_now = dt_util.now()
        try: ready_by = time.fromisoformat(str(self.config_entry.options.get(c.CONF_AFTERNOON_READY_BY, c.DEFAULT_AFTERNOON_READY_BY)))
        except ValueError: ready_by = time.fromisoformat(c.DEFAULT_AFTERNOON_READY_BY)
        start = local_now.replace(hour=c.AFTERNOON_PLANNING_START_HOUR, minute=0, second=0, microsecond=0)
        deadline = datetime.combine(local_now.date(), ready_by, local_now.tzinfo)
        if local_now < start or local_now >= deadline: return context
        context.planning = True
        config_entry_id = str(self.config_entry.options.get(c.CONF_AFTERNOON_FORECAST_CONFIG_ENTRY_ID, "")).strip()
        if not config_entry_id:
            self._fallback_inputs["afternoon_forecast"] = "missing_configuration"
            context.forecast_available = False
            return context
        try:
            response = await self.hass.services.async_call("forecast_solar", "get_forecast", {"config_entry": config_entry_id, "start": start.isoformat(), "end": deadline.isoformat(), "resolution": "raw"}, blocking=True, return_response=True)
        except (HomeAssistantError, TimeoutError) as err:
            c.LOGGER.warning("Afternoon forecast unavailable: %s", err)
            self._fallback_inputs["afternoon_forecast"] = "service_error"
            context.forecast_available = False
            return context
        periods = self._forecast_periods(response)
        if not periods:
            self._fallback_inputs["afternoon_forecast"] = "no_periods"
            context.forecast_available = False
            return context
        tolerance_end = local_now + timedelta(seconds=max(1, params.grid_usage_delay) * params.evaluation_interval)
        context.forecast_recovery = any(period_start < tolerance_end and period_end > local_now and wh * 1000 / max(1 / 3600, (period_end - period_start).total_seconds() / 3600) >= params.generation_cool_threshold for period_start, period_end, wh in periods)
        window = self._latest_afternoon_window(local_now, deadline, periods, params.afternoon_energy_budget)
        if window is None and self._session.afternoon_window_start:
            selected_start = dt_util.parse_datetime(self._session.afternoon_window_start)
            if selected_start is not None and selected_start < local_now:
                retained = self._window_energy(selected_start, selected_start + timedelta(hours=1), periods)
                if retained is not None and retained >= params.afternoon_energy_budget and local_now < selected_start + timedelta(hours=1):
                    window = selected_start, selected_start + timedelta(hours=1), retained
        if window is None: return context
        window_start, window_end, energy = window
        context.window_open = window_start <= local_now < window_end
        context.start_allowed = context.window_open and local_now <= window_start + timedelta(seconds=params.evaluation_interval)
        context.window_start, context.window_end, context.window_energy = window_start.isoformat(), window_end.isoformat(), round(energy, 3)
        self._session.afternoon_window_start = context.window_start; self._session.afternoon_window_end = context.window_end; self._session.afternoon_window_energy = context.window_energy
        return context

    @staticmethod
    def _forecast_periods(response: object) -> list[tuple[datetime, datetime, float]]:
        if not isinstance(response, Mapping) or not isinstance(series := response.get("wh_period"), Mapping): return []
        raw: list[tuple[datetime, float]] = []
        for timestamp, value in series.items():
            parsed = dt_util.parse_datetime(str(timestamp))
            if parsed is None or not isinstance(value, (int, float)): continue
            energy = float(value) / 1000
            if isfinite(energy) and energy >= 0: raw.append((parsed, energy))
        raw.sort(key=lambda item: item[0])
        if not raw: return []
        periods: list[tuple[datetime, datetime, float]] = []
        default_duration = raw[1][0] - raw[0][0] if len(raw) > 1 else timedelta(hours=1)
        for index, (period_start, energy) in enumerate(raw):
            period_end = raw[index + 1][0] if index + 1 < len(raw) else period_start + (raw[index][0] - raw[index - 1][0] if index else default_duration)
            if period_end > period_start: periods.append((period_start, period_end, energy))
        return periods

    @staticmethod
    def _latest_afternoon_window(now: datetime, deadline: datetime, periods: list[tuple[datetime, datetime, float]], budget: float) -> tuple[datetime, datetime, float] | None:
        candidates = sorted({period_start for period_start, _, _ in periods if period_start >= now and period_start + timedelta(hours=1) <= deadline}, reverse=True)
        for window_start in candidates:
            window_end = window_start + timedelta(hours=1)
            cursor, coverage, energy = window_start, timedelta(), 0.0
            for period_start, period_end, period_energy in periods:
                if period_end <= cursor or period_start >= window_end: continue
                if period_start > cursor: break
                overlap_start, overlap_end = max(cursor, period_start), min(window_end, period_end)
                if overlap_end <= overlap_start: continue
                fraction = (overlap_end - overlap_start) / (period_end - period_start)
                coverage += overlap_end - overlap_start; energy += period_energy * fraction; cursor = overlap_end
            if coverage >= timedelta(hours=1) and energy >= budget:
                return window_start, window_end, energy
        return None

    @staticmethod
    def _window_energy(window_start: datetime, window_end: datetime, periods: list[tuple[datetime, datetime, float]]) -> float | None:
        cursor, energy = window_start, 0.0
        for period_start, period_end, period_energy in periods:
            if period_end <= cursor or period_start >= window_end: continue
            if period_start > cursor: return None
            overlap_start, overlap_end = max(cursor, period_start), min(window_end, period_end)
            fraction = (overlap_end - overlap_start) / (period_end - period_start)
            energy += period_energy * fraction
            cursor = overlap_end
        return energy if cursor >= window_end else None

    def _entity_id(self, key: str) -> str:
        return str(self.config_entry.options.get(key, self.config_entry.data.get(key, ""))).strip() or str(self.config_entry.data[key])

    def _state(self, conf_key: str, label: str, *, allow_unavailable: bool = False) -> State: return self._get_state(self._entity_id(conf_key), label, allow_unavailable=allow_unavailable)

    def _build_home_input(self) -> tuple[HomeInput, datetime | None]:
        timer = self._active_aircon_timer(); climate = self._state(c.CONF_CLIMATE_ENTITY_ID, "climate")
        gen = self._state(c.CONF_GENERATION_ENTITY_ID, "generation", allow_unavailable=True); grid = self._state(c.CONF_GRID_ENTITY_ID, "grid", allow_unavailable=True); temp = self._state(c.CONF_TEMPERATURE_ENTITY_ID, "temperature", allow_unavailable=True); hum = self._state(c.CONF_HUMIDITY_ENTITY_ID, "humidity", allow_unavailable=True)
        discharge = self._optional_power(c.CONF_BATTERY_POWER_ENTITY_ID, "battery_power", invert=bool(self.config_entry.options.get(c.CONF_BATTERY_INVERT, False)))
        gen_live = "generation" not in self._fallback_inputs; grid_live = "grid" not in self._fallback_inputs  # a fallback means the sensor is unknown/unavailable (e.g. inverter asleep)
        battery_power_live = bool(self.config_entry.options.get(c.CONF_BATTERY_POWER_ENTITY_ID, self.config_entry.data.get(c.CONF_BATTERY_POWER_ENTITY_ID, ""))) and "battery_power" not in self._fallback_inputs
        generation = self._normalized_power(gen, "generation") if gen_live else 0.0; grid_usage = self._normalized_power(grid, "grid", invert=bool(self.config_entry.options.get(c.CONF_GRID_INVERT, False))) if grid_live else 0.0  # normalise only live readings; a stale fallback stays 0
        have_solar = gen_live and generation > 0.0
        battery_discharge = max(0.0, (discharge or 0.0) - c.BATTERY_DISCHARGE_TOLERANCE)  # a battery covering the load hides the draw from the grid meter: pass it to the rules separately from grid usage
        someone_home: bool | None = None
        if self.only_cool_when_home or self.afternoon_cooling_enabled:
            occupancy = self.hass.states.get(self.occupancy_entity_id)
            if occupancy is None or str(occupancy.state).lower() in {STATE_UNKNOWN, STATE_UNAVAILABLE}:
                self._fallback_inputs["occupancy"] = "missing" if occupancy is None else str(occupancy.state).lower()
            else:
                raw = str(occupancy.state).lower()
                if self.occupancy_entity_id.startswith("zone."):
                    with suppress(TypeError, ValueError): someone_home = float(raw) > 0
                    if someone_home is None: self._fallback_inputs["occupancy"] = "invalid"
                else:
                    someone_home = raw == "home"
        battery_soc: float | None = None
        if (self.only_cool_when_home and self.allow_away_battery_cooling) or self._session.battery_run_authorized or self.afternoon_cooling_enabled:
            soc = self._optional_state(c.CONF_BATTERY_SOC_ENTITY_ID, "battery_state_of_charge")
            if soc is not None:
                with suppress(TypeError, ValueError):
                    candidate = self._state_to_float(soc, "battery state of charge")
                    if isfinite(candidate) and 0 <= candidate <= 100: battery_soc = candidate
                if battery_soc is None: self._fallback_inputs["battery_state_of_charge"] = "invalid"
        mode = AirconMode.UNKNOWN
        with suppress(ValueError): mode = AirconMode(str(climate.state).lower().strip())
        if mode not in (AirconMode.COOL, AirconMode.DRY): self._auto_mode = False; self._reset_target_tracking()
        elif self._auto_mode:
            target = self._valid_setpoint(climate.attributes.get("temperature"))
            if target is not None and self._automatic_setpoint is not None and target != self._automatic_setpoint and (not self._initialized or (self._observed_setpoint is not None and target != self._observed_setpoint)): self._adjusted_setpoint = target
            self._observed_setpoint = target
        aggressive = self.power_policy is c.PowerPolicy.ALLOW_BATTERY_GRID; enabled = self.control_mode is not c.ControlMode.DISABLED
        raw_temperature = self._normalized_temperature(temp) if "temperature" not in self._fallback_inputs else None; temperature_available = raw_temperature is not None and isfinite(raw_temperature)
        raw_humidity = self._state_to_float(hum, "humidity") if "humidity" not in self._fallback_inputs else None; humidity_available = raw_humidity is not None and isfinite(raw_humidity)
        return HomeInput(mode, have_solar, generation, grid_usage, timer is not None, raw_temperature if temperature_available else None, raw_humidity if humidity_available else None, self._auto_mode, aggressive, enabled, self.cooling_enabled, battery_discharge, temperature_available, humidity_available, now=dt_util.utcnow().timestamp(), someone_home=someone_home, only_cool_when_home=self.only_cool_when_home, battery_soc=battery_soc, allow_away_battery_cooling=self.allow_away_battery_cooling, afternoon_enabled=self.afternoon_cooling_enabled, generation_available=gen_live, grid_available=grid_live, battery_power_available=battery_power_live), timer

    def _sync_on_startup(self, current: HomeOutput, home: HomeInput) -> None:
        if home.aircon_mode is AirconMode.OFF and self._session.last in (HomeOutput.COOL, HomeOutput.DRY, HomeOutput.ON, HomeOutput.TIMER) and self._session.reactivate_at <= home.now:
            self._session.record_stop(home.now, self.parameters.reactivate_delay)
        if self._session.last is None: self._session.last = current
        elif home.timer and self._session.last is HomeOutput.TIMER:         return
        elif self._session.last is HomeOutput.TIMER and home.aircon_mode is not AirconMode.OFF: return  # cap elapsed while down but aircon still on: keep TIMER so adjust() issues OFF, don't re-arm
        elif self._session.last != current: c.LOGGER.info("Startup sync: restoring from %s to live state %s", self._session.last.value, current.value); self._session.last = current

    async def _call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try: await self.hass.services.async_call(domain, service, data, blocking=True)
        except ServiceValidationError as err: raise HomeAssistantError(f"service call failed: {err}") from err

    async def _set_climate_target(self, target_temperature: float, mode: str | None = None) -> None:
        climate = self._entity_id(c.CONF_CLIMATE_ENTITY_ID); self._automatic_setpoint = target_temperature
        state = self.hass.states.get(climate)
        self._observed_setpoint = self._valid_setpoint(state.attributes.get("temperature")) if state is not None else None
        self._climate_write_in_progress = True
        try:
            if mode is not None: await self._call_service("climate", "set_hvac_mode", {"entity_id": climate, "hvac_mode": mode})
            await self._call_service("climate", "set_temperature", {"entity_id": climate, "temperature": target_temperature})
        finally:
            self._climate_write_in_progress = False
            state = self.hass.states.get(climate)
            if state is not None and self._valid_setpoint(state.attributes.get("temperature")) == target_temperature: self._observed_setpoint = target_temperature

    async def _execute_adjustment(self, adjustment: HomeOutput, target_temperature: float) -> None:
        if adjustment in (HomeOutput.NO_CHANGE, HomeOutput.RESET, HomeOutput.DISABLED): return
        if self.control_mode is c.ControlMode.MONITOR: c.LOGGER.info("MONITOR: would apply adjustment %s", adjustment.value)
        else:
            climate = str(self._entity_id(c.CONF_CLIMATE_ENTITY_ID))
            if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
                await self._set_climate_target(target_temperature, adjustment.value.lower())
            elif adjustment is HomeOutput.OFF: await self._call_service("climate", "turn_off", {"entity_id": climate})
        if adjustment is HomeOutput.TIMER:
            self._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(minutes=max(1, int(self.config_entry.options.get(c.CONF_AIRCON_TIMER_DURATION, c.DEFAULT_AIRCON_TIMER_DURATION))))
        elif adjustment in (HomeOutput.COOL, HomeOutput.DRY) or (adjustment is HomeOutput.OFF and self.control_mode is not c.ControlMode.MONITOR):
            self._clear_aircon_timer()
        if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
            if not self._auto_mode: self._target_notified, self._target_prompt_id = False, None
            self._auto_mode = True
        elif adjustment is HomeOutput.OFF and self.control_mode is not c.ControlMode.MONITOR: self._auto_mode = False

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
        return state

    @staticmethod
    def _state_to_float(state: State, label: str) -> float:
        try: return float(state.state)
        except ValueError as err: raise ValueError(f"invalid numeric {label}: {state.state}") from err

    def _active_aircon_timer(self) -> datetime | None:
        if self._aircon_timer_finishes_at and self._aircon_timer_finishes_at <= dt_util.utcnow(): self._clear_aircon_timer()
        return self._aircon_timer_finishes_at

    def _clear_aircon_timer(self) -> None:
        self._aircon_timer_finishes_at = None; self._target_prompt_id = None

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
        history_size = max(1, int(self.config_entry.options.get(c.CONF_SMOOTHING_WINDOW, c.DEFAULT_SMOOTHING_WINDOW)))
        await self._store.async_save({"controls": {"mode": self.control_mode.value, c.CONF_POWER_POLICY: self.power_policy.value, "cooling_enabled": self.cooling_enabled, c.CONF_DRY_MODE_ENABLED: self.dry_mode_enabled, c.CONF_ONLY_COOL_WHEN_HOME: self.only_cool_when_home, c.CONF_ALLOW_AWAY_BATTERY_COOLING: self.allow_away_battery_cooling, c.CONF_AFTERNOON_COOLING_ENABLED: self.afternoon_cooling_enabled, c.CONF_STOP_AT_COMFORT_TEMPERATURE: self.stop_at_comfort_temperature, c.CONF_AUTOMATIC_TARGET_NOTIFICATIONS: self.automatic_target_notifications}, "session": session, "auto_mode": self._auto_mode, "last_changed": self._last_changed, "recent_evaluations": list(self._recent)[:history_size], "aircon_timer_finishes_at": self._aircon_timer_finishes_at and self._aircon_timer_finishes_at.isoformat(), "target_notified": self._target_notified, "target_prompt_id": self._target_prompt_id, "automatic_setpoint": self._automatic_setpoint, "adjusted_setpoint": self._adjusted_setpoint, "parameters": dict(self._parameters)})

    def _create_issue(self, issue: str, placeholders: dict[str, str]) -> None:
        ir.async_create_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}", is_fixable=False, is_persistent=False, severity=ir.IssueSeverity.ERROR, translation_key=issue, translation_placeholders=placeholders)

    def _clear_issue(self, issue: str) -> None: ir.async_delete_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}")


type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]
