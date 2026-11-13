# fmt: off
# ruff: noqa: E501, E701, E702

import asyncio
from collections import deque
from contextlib import suppress
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
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
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

_HOME_RECORD_FIELDS = ("generation", "grid_usage", "temperature", "temperature_available", "humidity", "have_solar", "auto", "aircon_mode", "pre_cooling", "battery_discharge")
_SESSION_RECORD_FIELDS = ("tolerated", "reactivate_at", "solar_run_eligible", "solar_lost_at", "solar_recovered_at")
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
        self.power_policy = c.PowerPolicy.SOLAR_ONLY; self.pre_cooling_start, self.pre_cooling_finish = c.DEFAULT_PRECOOL_START, c.DEFAULT_PRECOOL_FINISH
        self.stop_at_comfort_temperature, self.automatic_target_notifications = False, True
        self._schedule_unsubs: list[CALLBACK_TYPE] = []; self._tariff_unsub: CALLBACK_TYPE | None = None
        self._parameters: dict[str, float] = {}; self._auto_mode = self._initialized = self._first_refresh_done = False; self._recent, self._last_changed, self._last_record, self._fallback_inputs = deque(maxlen=c.MAX_RECENT_EVALUATIONS), None, {}, {}; self._aircon_timer_finishes_at: datetime | None = None; self._timer_expiry_handle: asyncio.TimerHandle | None = None
        self._target_notified = False; self._target_prompt_id: str | None = None; self._notification_unsub: CALLBACK_TYPE | None = None
        self._climate_unsub: CALLBACK_TYPE | None = None; self._climate_write_in_progress = False
        self._solar_expiry_handle: asyncio.TimerHandle | None = None
        self._automatic_setpoint: float | None = None; self._adjusted_setpoint: float | None = None; self._observed_setpoint: float | None = None
        self._store = Store[dict[str, Any]](hass, c.STORAGE_VERSION, f"{c.DOMAIN}_{config_entry.entry_id}")
        interval = timedelta(seconds=int(config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))); name = f"{c.DOMAIN} ({config_entry.entry_id})"
        super().__init__(hass, c.LOGGER, name=name, update_interval=interval, always_update=True, config_entry=config_entry); self.data = CoordinatorData()

    def get_parameter(self, key: str, default: float) -> float: return float(self._parameters.get(key, self.config_entry.options.get(key, default)))
    async def async_set_parameter(self, key: str, value: float) -> None:
        if key in (c.CONF_TEMPERATURE_THRESHOLD, c.CONF_TEMPERATURE_COOL, c.CONF_TEMPERATURE_PRECOOL):
            candidate = replace(self.parameters, temperature_threshold=value) if key == c.CONF_TEMPERATURE_THRESHOLD else replace(self.parameters, temperature_cool=value) if key == c.CONF_TEMPERATURE_COOL else replace(self.parameters, temperature_precool=value)
            if not candidate.temperature_range_valid: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_temperature_range")
            if key in (c.CONF_TEMPERATURE_COOL, c.CONF_TEMPERATURE_PRECOOL) and not candidate.precooling_range_valid: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_precooling_temperature")
        self._parameters[key] = value; await self._save_state(); await self.async_run_evaluation("parameter")

    @property
    def parameters(self) -> RuleParameters:
        g, o = self.get_parameter, self.config_entry.options
        return RuleParameters(g(c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD), g(c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD), g(c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD), c.DRY_MODE_HUMIDITY_CUTOFF, self.dry_mode_enabled, int(o.get(c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY)), c.reactivation_delay_minutes(o), g(c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL), self.stop_at_comfort_temperature, temperature_precool=g(c.CONF_TEMPERATURE_PRECOOL, c.DEFAULT_TEMPERATURE_PRECOOL), solar_run_on_minutes=float(o.get(c.CONF_SOLAR_RUN_ON_MINUTES, c.DEFAULT_SOLAR_RUN_ON_MINUTES)), evaluation_interval=float(o.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL)))

    async def async_set_mode(self, mode: c.ControlMode) -> None: self.control_mode = mode; await self._save_state(); await self.async_run_evaluation("control_mode")
    async def async_set_power_policy(self, policy: c.PowerPolicy) -> None: self.power_policy = policy; self._session.tolerated = 0; await self._save_state(); await self.async_run_evaluation("power_policy")

    async def async_set_time(self, key: str, value: time) -> None:
        start, finish = (value, self.pre_cooling_finish) if key == c.CONF_PRECOOL_START else (self.pre_cooling_start, value)
        if start >= finish: raise ServiceValidationError(translation_domain=c.DOMAIN, translation_key="invalid_precooling_window")
        setattr(self, key, value); self._schedule_precooling(); await self._save_state(); await self.async_run_evaluation("pre_cooling_time")

    async def async_initialize(self) -> None:
        stored = await self._store.async_load() or {}
        controls, session = stored.get("controls", {}), stored.get("session", {})
        mode = str(controls.get("mode", c.ControlMode.MONITOR))
        with suppress(ValueError): self.control_mode = c.ControlMode.AUTOMATIC if mode in {"solar_cooling", "boost_cooling"} else c.ControlMode(mode)
        with suppress(ValueError): self.power_policy = c.PowerPolicy(controls.get(c.CONF_POWER_POLICY, c.PowerPolicy.ALLOW_BATTERY_GRID if mode == "boost_cooling" else c.PowerPolicy.SOLAR_ONLY))
        self.cooling_enabled, self.dry_mode_enabled, self.afternoon_cooling = bool(controls.get("cooling_enabled", True)), bool(controls.get(c.CONF_DRY_MODE_ENABLED, True)), bool(controls.get(c.CONF_AFTERNOON_COOLING, False))
        self.stop_at_comfort_temperature = bool(controls.get(c.CONF_STOP_AT_COMFORT_TEMPERATURE, self.config_entry.options.get(c.CONF_MANUAL_COOLING_BEHAVIOUR) == "stop"))
        self.automatic_target_notifications = bool(controls.get(c.CONF_AUTOMATIC_TARGET_NOTIFICATIONS, True))
        with suppress(ValueError, TypeError):
            legacy_start = time(int(self.config_entry.options.get(c.CONF_AFTERNOON_COOLING_HOUR, c.DEFAULT_AFTERNOON_COOLING_HOUR)))
            self.pre_cooling_start = time.fromisoformat(str(controls.get(c.CONF_PRECOOL_START, legacy_start)))
            self.pre_cooling_finish = time.fromisoformat(str(controls.get(c.CONF_PRECOOL_FINISH, c.DEFAULT_PRECOOL_FINISH)))
        if self.pre_cooling_start >= self.pre_cooling_finish: self.pre_cooling_start, self.pre_cooling_finish = c.DEFAULT_PRECOOL_START, c.DEFAULT_PRECOOL_FINISH
        last = session.get("last")
        legacy_delay = float(session.get("reactivate_delay", 0)) * float(self.config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))
        self._session = CachedState(reactivate_at=float(session.get("reactivate_at", dt_util.utcnow().timestamp() + legacy_delay if legacy_delay else 0)), tolerated=int(session.get("tolerated", 0)), last=HomeOutput(last) if last else None, failed_to_change=int(session.get("failed_to_change", 0)), solar_run_eligible=bool(session.get("solar_run_eligible", False)), solar_lost_at=session.get("solar_lost_at"), solar_recovered_at=session.get("solar_recovered_at"))
        self._auto_mode, self._last_changed = bool(stored.get("auto_mode", False)), stored.get("last_changed")
        self._recent = deque(stored.get("recent_evaluations", []), maxlen=c.MAX_RECENT_EVALUATIONS)
        self._aircon_timer_finishes_at = dt_util.parse_datetime(str(v)) if (v := stored.get("aircon_timer_finishes_at")) else None
        self._target_notified, self._target_prompt_id = bool(stored.get("target_notified", stored.get("timer_target_notified", False))), stored.get("target_prompt_id", stored.get("timer_prompt_id"))
        last_target = self._recent[0].get("target_temperature") if self._recent and self._auto_mode else None
        self._automatic_setpoint = self._valid_setpoint(stored.get("automatic_setpoint", last_target))
        self._adjusted_setpoint = self._valid_setpoint(stored.get("adjusted_setpoint"))
        self._parameters = {}
        for k, v in stored.get("parameters", {}).items():
            if k in c.RETIRED_CONFIG_KEYS: continue
            with suppress(TypeError, ValueError): self._parameters[str(k)] = float(v)
        self._schedule_timer_expiry()
        self._schedule_precooling()
        if self._tariff_unsub is None and (tariff := str(self.config_entry.options.get(c.CONF_TARIFF_ENTITY_ID, "")).strip()):
            self._tariff_unsub = async_track_state_change_event(self.hass, [tariff], self._async_handle_tariff_change)
        if self._notification_unsub is None:
            self._notification_unsub = self.hass.bus.async_listen(c.EVENT_NOTIFICATION_ACTION, self._async_handle_notification_action)
            self.config_entry.async_on_unload(self._unsubscribe_notifications)
            self.config_entry.async_on_unload(self._unsubscribe_precooling)
        if self._climate_unsub is None:
            self._climate_unsub = async_track_state_change_event(self.hass, [self._entity_id(c.CONF_CLIMATE_ENTITY_ID)], self._async_handle_climate_change)
            self.config_entry.async_on_unload(self._unsubscribe_climate)

    async def async_set_control(self, key: str, value: bool) -> None: setattr(self, key, value); await self._save_state(); await self.async_run_evaluation("control")
    async def async_shutdown(self) -> None: self._cancel_timer_expiry(); self._cancel_solar_expiry(); self._unsubscribe_notifications(); self._unsubscribe_precooling(); self._unsubscribe_climate()
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
            self._auto_mode = False; self._reset_target_tracking(); self._clear_aircon_timer(); self._session.last = None
            self._session.clear_solar_run(); self._cancel_solar_expiry()
            if was_running:
                self._session.record_stop(dt_util.utcnow().timestamp(), self.parameters.reactivate_delay)
                self.hass.async_create_task(self.async_run_evaluation("climate_off"))
        elif self._auto_mode and new.state in (AirconMode.COOL, AirconMode.DRY):
            target = self._valid_setpoint(new.attributes.get("temperature"))
            if not self._climate_write_in_progress and old is not None and old.attributes.get("temperature") != target and target is not None and target != self._automatic_setpoint: self._adjusted_setpoint = target
            if not self._climate_write_in_progress or target == self._automatic_setpoint: self._observed_setpoint = target
        elif new.state in (AirconMode.AUTO, AirconMode.HEAT, AirconMode.HEAT_COOL, AirconMode.FAN_ONLY):
            self._auto_mode = False; self._reset_target_tracking()
    def _unsubscribe_precooling(self) -> None:
        for unsub in self._schedule_unsubs: unsub()
        self._schedule_unsubs.clear()
        if self._tariff_unsub is not None: self._tariff_unsub(); self._tariff_unsub = None
    async def async_run_evaluation(self, trigger: str = "manual") -> None: self.async_set_updated_data(await self._evaluate(trigger))

    def _schedule_precooling(self) -> None:
        for unsub in self._schedule_unsubs: unsub()
        self._schedule_unsubs = [async_track_time_change(self.hass, self._async_handle_precooling_boundary, hour=value.hour, minute=value.minute, second=value.second) for value in (self.pre_cooling_start, self.pre_cooling_finish)]

    @callback
    def _async_handle_precooling_boundary(self, now: datetime) -> None: self.hass.async_create_task(self.async_run_evaluation("pre_cooling_boundary"))
    @callback
    def _async_handle_tariff_change(self, event: Event[EventStateChangedData]) -> None: self.hass.async_create_task(self.async_run_evaluation("tariff"))

    async def _async_update_data(self) -> CoordinatorData:
        try: return await self._evaluate("poll")
        except ConfigEntryNotReady as err: raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001
            self._create_issue(c.ISSUE_RUNTIME, {"error": str(err)})
            raise UpdateFailed(translation_domain=c.DOMAIN, translation_key="update_failed", translation_placeholders={"error": str(err)}) from err

    async def _evaluate(self, trigger: str, *, notification_action: str | None = None) -> CoordinatorData:
        async with self._lock:
            if notification_action is not None and notification_action not in self._target_notification_actions(): return self.data
            now = dt_util.utcnow().isoformat(); self._fallback_inputs = {}; self._clear_issue(c.ISSUE_ENTITY_UNAVAILABLE); home, _ = self._build_home_input(); params = self.parameters
            if notification_action is not None and (home.auto or home.aircon_mode not in (AirconMode.COOL, AirconMode.DRY) or self.control_mode in (c.ControlMode.DISABLED, c.ControlMode.MONITOR) or params.stop_at_comfort_temperature or (self._session.last is HomeOutput.TIMER and not home.timer)): notification_action = None
            if home.timer and home.aircon_mode is AirconMode.OFF: self._clear_aircon_timer(); home = replace(home, timer=False)
            if notification_action is not None and notification_action.endswith("_five"):
                finishes = dt_util.utcnow() + timedelta(minutes=5)
                self._aircon_timer_finishes_at = min(self._aircon_timer_finishes_at or finishes, finishes); self._schedule_timer_expiry()
                home = replace(home, timer=True); self._session.last = HomeOutput.TIMER
            current = current_state(home); smoothed_gen = self._smoothed_generation(home.generation); decision_home = replace(home, generation=smoothed_gen)
            if not self._initialized: self._initialized = True; self._sync_on_startup(current, home)
            elif self._session.last is None: self._session.last = current
            if notification_action is not None and notification_action.endswith("_off"):
                self._session.record_stop(home.now, params.reactivate_delay)
                result = AdjustResult(HomeOutput.OFF, "Turned off from notification")
            else: result = adjust(params, decision_home, self._session)
            adjustment, reason = result.output, result.reason; target_temperature = self._adjusted_setpoint if home.auto and self._adjusted_setpoint is not None else params.cooling_target(home) if home.auto or adjustment in (HomeOutput.COOL, HomeOutput.DRY) else params.temperature_cool
            await self._execute_adjustment(adjustment, target_temperature)
            self._schedule_solar_expiry()
            if adjustment is HomeOutput.NO_CHANGE and home.auto and home.enabled and home.temperature_available and home.aircon_mode in (AirconMode.COOL, AirconMode.DRY) and self.control_mode is c.ControlMode.AUTOMATIC:
                climate = self._state(c.CONF_CLIMATE_ENTITY_ID, "climate")
                if climate.attributes.get("temperature") is not None and climate.attributes["temperature"] != target_temperature: await self._set_climate_target(target_temperature)
            timer = self._active_aircon_timer()
            if notification_action is not None: self._target_prompt_id = None
            previous = self._session.last; applied = apply_adjustment(self._session, current, adjustment); is_monitor = self.control_mode is c.ControlMode.MONITOR
            if is_monitor: self._session.failed_to_change, applied = 0, True
            if not applied: raise HomeAssistantError("failed to apply adjustment")
            if previous is not None and previous != self._session.last and adjustment is not HomeOutput.RESET: self._last_changed = now; await self._maybe_notify(previous, current, adjustment)
            await self._maybe_notify_target(home, adjustment)
            mode = self._session.last or current
            record = {"time": now, "trigger": trigger, "current": current.value, "adjustment": adjustment.value, "mode": mode.value, "reason": reason, "dry_run": is_monitor, "control_mode": self.control_mode.value, "power_policy": self.power_policy.value, "target_temperature": target_temperature, "adjusted_setpoint": self._adjusted_setpoint, "tariff": self._tariff_state(), "stop_at_comfort_temperature": params.stop_at_comfort_temperature, "automatic_target_notifications": self.automatic_target_notifications, "raw_generation": home.generation, "smoothed_generation": round(smoothed_gen, 1), "fallback_inputs": dict(self._fallback_inputs), "reactivate_delay_remaining": max(0.0, self._session.reactivate_at - home.now), "solar_run_on_deadline": self._session.solar_run_on_deadline(params)} | {k: getattr(home, k) for k in _HOME_RECORD_FIELDS} | {k: getattr(self._session, k) for k in _SESSION_RECORD_FIELDS}
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
        if home.auto and (home.pre_cooling or not self.automatic_target_notifications): return
        if not home.temperature_available or home.temperature > self.parameters.temperature_cool: return
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
        if mode not in (AirconMode.COOL, AirconMode.DRY): self._auto_mode = False; self._reset_target_tracking()
        elif self._auto_mode:
            target = self._valid_setpoint(climate.attributes.get("temperature"))
            if target is not None and self._automatic_setpoint is not None and target != self._automatic_setpoint and (not self._initialized or (self._observed_setpoint is not None and target != self._observed_setpoint)): self._adjusted_setpoint = target
            self._observed_setpoint = target
        tariff = self._tariff_state(); now = dt_util.now().time()
        pre_cooling = self.afternoon_cooling and self.parameters.precooling_range_valid and self.pre_cooling_start <= now < self.pre_cooling_finish and (not self.config_entry.options.get(c.CONF_TARIFF_ENTITY_ID) or (tariff is not None and tariff != str(self.config_entry.options.get(c.CONF_PEAK_TARIFF, c.DEFAULT_PEAK_TARIFF))))
        aggressive = self.power_policy is c.PowerPolicy.ALLOW_BATTERY_GRID; enabled = self.control_mode is not c.ControlMode.DISABLED
        temperature = self._normalized_temperature(temp); temperature_available = "temperature" not in self._fallback_inputs and isfinite(temperature)
        return HomeInput(mode, have_solar, generation, grid_usage, timer is not None, temperature, self._state_to_float(hum, "humidity"), self._auto_mode, aggressive, enabled, self.cooling_enabled, pre_cooling, battery_discharge, temperature_available, now=dt_util.utcnow().timestamp()), timer

    def _tariff_state(self) -> str | None:
        return state.state if (state := self._optional_state(c.CONF_TARIFF_ENTITY_ID, "tariff")) is not None else None

    def _sync_on_startup(self, current: HomeOutput, home: HomeInput) -> None:
        if home.aircon_mode is AirconMode.OFF and self._session.last in (HomeOutput.COOL, HomeOutput.DRY, HomeOutput.ON, HomeOutput.TIMER) and self._session.reactivate_at <= home.now:
            self._session.record_stop(home.now, self.parameters.reactivate_delay)
        if self._session.last is None: self._session.last = current
        elif home.timer and self._session.last is HomeOutput.TIMER: return
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
            self._aircon_timer_finishes_at = dt_util.utcnow() + timedelta(minutes=max(1, int(self.config_entry.options.get(c.CONF_AIRCON_TIMER_DURATION, c.DEFAULT_AIRCON_TIMER_DURATION)))); self._schedule_timer_expiry()
        elif adjustment in (HomeOutput.COOL, HomeOutput.DRY, HomeOutput.OFF):
            self._clear_aircon_timer()
        if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
            if not self._auto_mode: self._target_notified, self._target_prompt_id = False, None
            self._auto_mode = True
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
        self._aircon_timer_finishes_at = None; self._target_prompt_id = None; self._schedule_timer_expiry()

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

    def _cancel_solar_expiry(self) -> None:
        if self._solar_expiry_handle is not None: self._solar_expiry_handle.cancel(); self._solar_expiry_handle = None

    def _schedule_solar_expiry(self) -> None:
        self._cancel_solar_expiry()
        if self._session.solar_lost_at is None or not self._session.solar_run_eligible or not self._auto_mode or self.power_policy is not c.PowerPolicy.ALLOW_BATTERY_GRID or self.control_mode is c.ControlMode.DISABLED: return
        params = self.parameters
        deadline = self._session.solar_run_on_deadline(params)
        if deadline is None: return
        delay = deadline - dt_util.utcnow().timestamp()
        if delay > 0: self._solar_expiry_handle = self.hass.loop.call_later(delay, self._async_handle_solar_expiry)

    def _async_handle_solar_expiry(self) -> None:
        self._solar_expiry_handle = None
        self.hass.async_create_task(self.async_run_evaluation("solar_run_on_expired"))

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
        await self._store.async_save({"controls": {"mode": self.control_mode.value, c.CONF_POWER_POLICY: self.power_policy.value, c.CONF_PRECOOL_START: self.pre_cooling_start.isoformat(), c.CONF_PRECOOL_FINISH: self.pre_cooling_finish.isoformat(), "cooling_enabled": self.cooling_enabled, c.CONF_DRY_MODE_ENABLED: self.dry_mode_enabled, c.CONF_AFTERNOON_COOLING: self.afternoon_cooling, c.CONF_STOP_AT_COMFORT_TEMPERATURE: self.stop_at_comfort_temperature, c.CONF_AUTOMATIC_TARGET_NOTIFICATIONS: self.automatic_target_notifications}, "session": session, "auto_mode": self._auto_mode, "last_changed": self._last_changed, "recent_evaluations": list(self._recent), "aircon_timer_finishes_at": self._aircon_timer_finishes_at and self._aircon_timer_finishes_at.isoformat(), "target_notified": self._target_notified, "target_prompt_id": self._target_prompt_id, "automatic_setpoint": self._automatic_setpoint, "adjusted_setpoint": self._adjusted_setpoint, "parameters": dict(self._parameters)})

    def _create_issue(self, issue: str, placeholders: dict[str, str]) -> None:
        ir.async_create_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}", is_fixable=False, is_persistent=False, severity=ir.IssueSeverity.ERROR, translation_key=issue, translation_placeholders=placeholders)

    def _clear_issue(self, issue: str) -> None: ir.async_delete_issue(self.hass, c.DOMAIN, f"{self.config_entry.entry_id}_{issue}")


type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]
