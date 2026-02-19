import asyncio
from collections import deque
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
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
    explain,
)

_POWER_UNITS = {
    "": UnitOfPower.WATT,
    "w": UnitOfPower.WATT,
    "watt": UnitOfPower.WATT,
    "watts": UnitOfPower.WATT,
    "kw": UnitOfPower.KILO_WATT,
    "kilowatt": UnitOfPower.KILO_WATT,
    "kilowatts": UnitOfPower.KILO_WATT,
    "mw": UnitOfPower.MEGA_WATT,
}


@dataclass
class ControlState:
    mode: c.ControlMode = c.ControlMode.DRY_RUN
    cooling_enabled: bool = True


@dataclass
class CoordinatorData:
    mode: HomeOutput = HomeOutput.OFF
    current: HomeOutput = HomeOutput.OFF
    adjustment: HomeOutput = HomeOutput.NO_CHANGE
    decision: str = ""
    reason: str = ""
    solar_available: bool = False
    solar_online: bool = False
    solar_generation_w: float = 0.0
    grid_usage_w: float = 0.0
    temperature_c: float = 0.0
    humidity_percent: float = 0.0
    tolerated: int = 0
    reactivate_delay: int = 0
    auto_mode: bool = False
    dry_run: bool = False
    timer_finishes_at: datetime | None = None
    last_evaluated: str | None = None
    last_changed: str | None = None
    recent_evaluations: list[dict[str, Any]] = field(default_factory=list)


class HomeRulesCoordinator(DataUpdateCoordinator[CoordinatorData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self._lock = asyncio.Lock()
        self._session = CachedState()
        self._controls = ControlState()
        self._auto_mode = False
        self._initialized = False
        self._recent: deque[dict[str, Any]] = deque(maxlen=c.MAX_RECENT_EVALUATIONS)
        self._last_changed: str | None = None
        self._store: Store[dict[str, Any]] = Store(hass, c.STORAGE_VERSION, f"{c.DOMAIN}_{config_entry.entry_id}")
        super().__init__(
            hass,
            c.LOGGER,
            name=f"Home Rules ({config_entry.entry_id})",
            config_entry=config_entry,
            update_interval=timedelta(seconds=self._eval_interval),
            always_update=True,
        )
        self.data = CoordinatorData()

    @property
    def _eval_interval(self) -> int:
        return int(self.config_entry.options.get(c.CONF_EVAL_INTERVAL, c.DEFAULT_EVAL_INTERVAL))

    @property
    def parameters(self) -> RuleParameters:
        options = self.config_entry.options
        return RuleParameters(
            generation_cool_threshold=float(
                options.get(c.CONF_GENERATION_COOL_THRESHOLD, c.DEFAULT_GENERATION_COOL_THRESHOLD)
            ),
            generation_dry_threshold=float(
                options.get(c.CONF_GENERATION_DRY_THRESHOLD, c.DEFAULT_GENERATION_DRY_THRESHOLD)
            ),
            temperature_threshold=float(options.get(c.CONF_TEMPERATURE_THRESHOLD, c.DEFAULT_TEMPERATURE_THRESHOLD)),
            humidity_threshold=float(options.get(c.CONF_HUMIDITY_THRESHOLD, c.DEFAULT_HUMIDITY_THRESHOLD)),
            grid_usage_delay=int(options.get(c.CONF_GRID_USAGE_DELAY, c.DEFAULT_GRID_USAGE_DELAY)),
            reactivate_delay=int(options.get(c.CONF_REACTIVATE_DELAY, c.DEFAULT_REACTIVATE_DELAY)),
            temperature_cool=float(options.get(c.CONF_TEMPERATURE_COOL, c.DEFAULT_TEMPERATURE_COOL)),
        )

    @property
    def controls(self) -> ControlState:
        return self._controls

    def _control_mode_from_storage(self, controls: dict[str, Any]) -> c.ControlMode:
        if (mode_raw := controls.get("mode")) is not None:
            with suppress(ValueError):
                return c.ControlMode(str(mode_raw))
        if not bool(controls.get("enabled", True)):
            return c.ControlMode.DISABLED
        if bool(controls.get("dry_run", True)):
            return c.ControlMode.DRY_RUN
        if bool(controls.get("aggressive_cooling", False)):
            return c.ControlMode.AGGRESSIVE
        return c.ControlMode.LIVE

    async def async_initialize(self) -> None:
        stored = await self._store.async_load()
        if not stored:
            return

        controls = stored.get("controls", {})
        session = stored.get("session", {})
        self._controls = ControlState(
            mode=self._control_mode_from_storage(controls),
            cooling_enabled=bool(controls.get("cooling_enabled", True)),
        )

        last = session.get("last")
        if last == "NoChange":
            last = HomeOutput.NO_CHANGE.value
        self._session = CachedState(
            reactivate_delay=int(session.get("reactivate_delay", 0)),
            tolerated=int(session.get("tolerated", 0)),
            last=HomeOutput(last) if last else None,
            failed_to_change=int(session.get("failed_to_change", 0)),
        )
        self._auto_mode = bool(stored.get("auto_mode", False))
        self._last_changed = stored.get("last_changed")
        self._recent = deque(stored.get("recent_evaluations", []), maxlen=c.MAX_RECENT_EVALUATIONS)

    async def async_set_control(self, key: str, value: bool) -> None:
        setattr(self._controls, key, value)
        await self._save_state()
        await self.async_run_evaluation("control")

    @property
    def control_mode(self) -> c.ControlMode:
        return self._controls.mode

    async def async_set_mode(self, mode: c.ControlMode) -> None:
        self._controls.mode = mode
        await self._save_state()
        await self.async_run_evaluation("control_mode")

    async def async_run_evaluation(self, trigger: str = "manual") -> None:
        self.async_set_updated_data(await self._evaluate(trigger))

    async def _async_update_data(self) -> CoordinatorData:
        try:
            return await self._evaluate("poll")
        except Exception as err:  # noqa: BLE001
            self._create_issue(c.ISSUE_RUNTIME, "runtime_error", {"error": str(err)})
            raise UpdateFailed(
                translation_domain=c.DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _evaluate(self, trigger: str) -> CoordinatorData:
        async with self._lock:
            now = dt_util.utcnow().isoformat()
            self._clear_issue(c.ISSUE_ENTITY_UNAVAILABLE)
            home, timer_finishes_at = self._build_home_input()
            current = current_state(home)

            if not self._initialized:
                self._initialized = True
                self._sync_on_startup(current, home)
            elif self._session.last is None:
                self._session.last = current

            snapshot = CachedState(
                reactivate_delay=self._session.reactivate_delay,
                tolerated=self._session.tolerated,
                last=self._session.last,
                failed_to_change=self._session.failed_to_change,
            )
            reason = explain(self.parameters, home, snapshot)
            adjustment = adjust(self.parameters, home, self._session)
            await self._execute_adjustment(adjustment)

            previous = self._session.last
            applied = apply_adjustment(self._session, current, adjustment)
            if self.control_mode is c.ControlMode.DRY_RUN:
                self._session.failed_to_change = 0
                applied = True
            if not applied:
                raise HomeAssistantError("failed to apply adjustment")

            if previous is not None and previous != self._session.last:
                self._last_changed = now
                await self._maybe_notify(previous, current, adjustment)

            mode = self._session.last or current
            record = {
                "time": now,
                "trigger": trigger,
                "current": current.value,
                "adjustment": adjustment.value,
                "mode": mode.value,
                "reason": reason,
                "generation": home.generation,
                "grid_usage": home.grid_usage,
                "temperature": home.temperature,
                "humidity": home.humidity,
                "have_solar": home.have_solar,
                "auto": home.auto,
                "dry_run": self.control_mode is c.ControlMode.DRY_RUN,
                "tolerated": self._session.tolerated,
                "reactivate_delay": self._session.reactivate_delay,
            }
            self._recent.appendleft(record)
            await self._save_state()
            self.hass.bus.async_fire(c.EVENT_EVALUATION, record)
            for issue in (c.ISSUE_RUNTIME, c.ISSUE_ENTITY_MISSING, c.ISSUE_INVALID_UNIT, c.ISSUE_ENTITY_UNAVAILABLE):
                self._clear_issue(issue)

            return CoordinatorData(
                mode=mode,
                current=current,
                adjustment=adjustment,
                decision=f"{mode.value} - {reason}",
                reason=reason,
                solar_available=home.have_solar and home.generation > 0.0,
                solar_online=home.have_solar,
                solar_generation_w=home.generation,
                grid_usage_w=home.grid_usage,
                temperature_c=home.temperature,
                humidity_percent=home.humidity,
                tolerated=self._session.tolerated,
                reactivate_delay=self._session.reactivate_delay,
                auto_mode=self._auto_mode,
                dry_run=self.control_mode is c.ControlMode.DRY_RUN,
                timer_finishes_at=timer_finishes_at,
                last_evaluated=now,
                last_changed=self._last_changed,
                recent_evaluations=list(self._recent),
            )

    async def _maybe_notify(self, previous: HomeOutput, current: HomeOutput, adjustment: HomeOutput) -> None:
        service = str(self.config_entry.options.get(c.CONF_NOTIFICATION_SERVICE, "")).strip()
        if not service:
            self._clear_issue(c.ISSUE_NOTIFICATION_SERVICE)
            return

        domain, name = ("notify", service)
        if "." in service:
            domain, name = service.split(".", 1)

        if not self.hass.services.has_service(domain, name):
            self._create_issue(c.ISSUE_NOTIFICATION_SERVICE, c.ISSUE_NOTIFICATION_SERVICE, {"service": service})
            return

        self._clear_issue(c.ISSUE_NOTIFICATION_SERVICE)
        message = (
            f"Mode changed: {previous.value} -> {(self._session.last or current).value} "
            f"(current={current.value}, action={adjustment.value}, "
            f"dry_run={self.control_mode is c.ControlMode.DRY_RUN})"
        )
        try:
            await self.hass.services.async_call(
                domain,
                name,
                {"title": "Home Rules", "message": message},
                blocking=False,
            )
        except ServiceValidationError as err:
            self._create_issue(
                c.ISSUE_NOTIFICATION_SERVICE,
                c.ISSUE_NOTIFICATION_SERVICE,
                {"service": f"{service} ({err})"},
            )

    def _entity_id(self, key: str, *, optional: bool = False) -> str | None:
        value = str(self.config_entry.options.get(key, self.config_entry.data.get(key, ""))).strip()
        return (value or None) if optional else value or str(self.config_entry.data[key])

    def _build_home_input(self) -> tuple[HomeInput, datetime | None]:
        climate_state = self._get_state(str(self._entity_id(c.CONF_CLIMATE_ENTITY_ID)), "climate")
        timer_state = self._get_state(str(self._entity_id(c.CONF_TIMER_ENTITY_ID)), "timer")
        inverter_id = self._entity_id(c.CONF_INVERTER_ENTITY_ID, optional=True)
        inverter_state = self._get_state(inverter_id, "inverter", allow_unavailable=True) if inverter_id else None

        generation_state = self._get_state(
            str(self._entity_id(c.CONF_GENERATION_ENTITY_ID)), "generation", allow_unavailable=True
        )
        grid_state = self._get_state(str(self._entity_id(c.CONF_GRID_ENTITY_ID)), "grid", allow_unavailable=True)
        temp_state = self._get_state(
            str(self._entity_id(c.CONF_TEMPERATURE_ENTITY_ID)), "temperature", allow_unavailable=True
        )
        humidity_state = self._get_state(
            str(self._entity_id(c.CONF_HUMIDITY_ENTITY_ID)), "humidity", allow_unavailable=True
        )

        have_solar = self._state_to_bool(inverter_state) if inverter_state else not inverter_id
        generation = self._normalized_power(generation_state, "generation") if have_solar else 0.0
        grid_usage = self._normalized_power(grid_state, "grid") if have_solar else 0.0
        temperature = self._normalized_temperature(temp_state)
        humidity = self._state_to_float(humidity_state, "humidity")
        mode = AirconMode.UNKNOWN
        with suppress(ValueError):
            mode = AirconMode(str(climate_state.state).lower().strip())
        return (
            HomeInput(
                aircon_mode=mode,
                have_solar=have_solar,
                generation=generation,
                grid_usage=grid_usage,
                timer=str(timer_state.state).lower() not in {"idle", "cancelled"},
                temperature=temperature,
                humidity=humidity,
                auto=self._auto_mode,
                aggressive_cooling=self.control_mode is c.ControlMode.AGGRESSIVE,
                enabled=self.control_mode is not c.ControlMode.DISABLED,
                cooling_enabled=self._controls.cooling_enabled,
            ),
            self._timer_finishes_at(timer_state),
        )

    def _sync_on_startup(self, current: HomeOutput, home: HomeInput) -> None:
        if self._session.last is None:
            self._session.last = current
            return
        if home.timer and self._session.last is HomeOutput.TIMER:
            return
        if self._session.last != current:
            c.LOGGER.info("Startup sync: restoring from %s to live state %s", self._session.last.value, current.value)
            self._session.last = current

    def _update_auto_mode(self, adjustment: HomeOutput) -> None:
        if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
            self._auto_mode = True
        elif adjustment is HomeOutput.OFF:
            self._auto_mode = False

    async def _call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except ServiceValidationError as err:
            raise HomeAssistantError(f"service call failed: {err}") from err

    async def _execute_adjustment(self, adjustment: HomeOutput) -> None:
        if adjustment in (HomeOutput.NO_CHANGE, HomeOutput.RESET, HomeOutput.DISABLED):
            return

        climate_entity = str(self._entity_id(c.CONF_CLIMATE_ENTITY_ID))
        timer_entity = str(self._entity_id(c.CONF_TIMER_ENTITY_ID))
        if self.control_mode is c.ControlMode.DRY_RUN:
            c.LOGGER.info("DRY RUN: would apply adjustment %s", adjustment.value)
            self._update_auto_mode(adjustment)
            return

        if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
            await self._call_service(
                "climate",
                "set_hvac_mode",
                {"entity_id": climate_entity, "hvac_mode": adjustment.value.lower()},
            )
            await self._call_service(
                "climate",
                "set_temperature",
                {"entity_id": climate_entity, "temperature": self.parameters.temperature_cool},
            )
        elif adjustment is HomeOutput.OFF:
            await self._call_service("climate", "turn_off", {"entity_id": climate_entity})
        elif adjustment is HomeOutput.TIMER:
            await self._call_service("timer", "start", {"entity_id": timer_entity})

        self._update_auto_mode(adjustment)

    def _get_state(self, entity_id: str, label: str, *, allow_unavailable: bool = False) -> State:
        state = self.hass.states.get(entity_id)
        if state is None:
            self._create_issue(c.ISSUE_ENTITY_MISSING, "entity_missing", {"entity_id": entity_id, "label": label})
            raise ValueError(f"missing entity: {entity_id}")

        raw = str(state.state).lower()
        if raw in {"unknown", "unavailable"} and allow_unavailable:
            return self._fallback_state(entity_id, label, state)
        if raw in {"unknown", "unavailable"}:
            self._create_issue(
                c.ISSUE_ENTITY_UNAVAILABLE,
                "entity_unavailable",
                {"entity_id": entity_id, "label": label},
            )
            raise ValueError(f"entity unavailable: {entity_id}")
        return state

    def _fallback_state(self, entity_id: str, label: str, state: State) -> State:
        if label in {"generation", "grid"}:
            return State(entity_id, "0", state.attributes)
        if label == "temperature":
            return State(entity_id, str(self.parameters.temperature_threshold - 0.1), state.attributes)
        if label == "humidity":
            return State(entity_id, str(self.parameters.humidity_threshold + 1.0), state.attributes)
        if label == "inverter":
            return State(entity_id, "offline", state.attributes)
        return state

    @staticmethod
    def _state_to_bool(state: State) -> bool:
        value = str(state.state).lower().strip().replace("-", "").replace("_", "")
        return value in {"on", "true", "1", "online"}

    @staticmethod
    def _state_to_float(state: State, label: str) -> float:
        try:
            return float(state.state)
        except ValueError as err:
            raise ValueError(f"invalid numeric {label}: {state.state}") from err

    def _timer_finishes_at(self, timer_state: State) -> datetime | None:
        if str(timer_state.state).lower() in {"idle", "cancelled"}:
            return None
        if finishes_at := timer_state.attributes.get("finishes_at"):
            return dt_util.parse_datetime(str(finishes_at))
        if (remaining := timer_state.attributes.get("remaining")) in (None, ""):
            return None
        if len(parts := str(remaining).split(":")) != 3:
            return None
        with suppress(ValueError):
            return dt_util.utcnow() + timedelta(
                hours=int(parts[0]),
                minutes=int(parts[1]),
                seconds=int(parts[2]),
            )
        return None

    def _normalized_power(self, state: State, label: str) -> float:
        value = self._state_to_float(state, label)
        unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip().lower()
        if source_unit := _POWER_UNITS.get(unit):
            return max(0.0, PowerConverter.convert(value, source_unit, UnitOfPower.WATT))
        self._create_issue(
            c.ISSUE_INVALID_UNIT, "invalid_unit", {"entity_id": state.entity_id, "unit": unit or "(none)"}
        )
        raise ValueError(f"unsupported power unit for {state.entity_id}: {unit}")

    def _normalized_temperature(self, state: State) -> float:
        value = self._state_to_float(state, "temperature")
        unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip()
        if unit in {"", "°C", "C", "°c", "c"}:
            return value
        if unit in {"°F", "F", "°f", "f"}:
            return TemperatureConverter.convert(value, UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.CELSIUS)
        raise ValueError(f"unsupported temperature unit for {state.entity_id}: {unit}")

    async def _save_state(self) -> None:
        await self._store.async_save(
            {
                "controls": {
                    "mode": self._controls.mode.value,
                    "cooling_enabled": self._controls.cooling_enabled,
                },
                "session": {
                    "reactivate_delay": self._session.reactivate_delay,
                    "tolerated": self._session.tolerated,
                    "last": self._session.last.value if self._session.last else None,
                    "failed_to_change": self._session.failed_to_change,
                },
                "auto_mode": self._auto_mode,
                "last_changed": self._last_changed,
                "recent_evaluations": list(self._recent),
            }
        )

    def _issue_id(self, suffix: str) -> str:
        return f"{self.config_entry.entry_id}_{suffix}"

    def _create_issue(self, suffix: str, translation_key: str, placeholders: dict[str, str]) -> None:
        ir.async_create_issue(
            self.hass,
            c.DOMAIN,
            self._issue_id(suffix),
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders=placeholders,
        )

    def _clear_issue(self, suffix: str) -> None:
        ir.async_delete_issue(self.hass, c.DOMAIN, self._issue_id(suffix))


type HomeRulesConfigEntry = ConfigEntry[HomeRulesCoordinator]
