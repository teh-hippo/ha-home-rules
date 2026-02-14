"""Coordinator for Home Rules integration."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_EVAL_INTERVAL,
    CONF_GENERATION_COOL_THRESHOLD,
    CONF_GENERATION_DRY_THRESHOLD,
    CONF_GENERATION_ENTITY_ID,
    CONF_GRID_ENTITY_ID,
    CONF_GRID_USAGE_DELAY,
    CONF_HUMIDITY_ENTITY_ID,
    CONF_HUMIDITY_THRESHOLD,
    CONF_INVERTER_ENTITY_ID,
    CONF_REACTIVATE_DELAY,
    CONF_TEMPERATURE_COOL,
    CONF_TEMPERATURE_ENTITY_ID,
    CONF_TEMPERATURE_THRESHOLD,
    CONF_TIMER_ENTITY_ID,
    DEFAULT_EVAL_INTERVAL,
    DEFAULT_GENERATION_COOL_THRESHOLD,
    DEFAULT_GENERATION_DRY_THRESHOLD,
    DEFAULT_GRID_USAGE_DELAY,
    DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_REACTIVATE_DELAY,
    DEFAULT_TEMPERATURE_COOL,
    DEFAULT_TEMPERATURE_THRESHOLD,
    DOMAIN,
    EVENT_EVALUATION,
    ISSUE_ENTITY_MISSING,
    ISSUE_INVALID_UNIT,
    ISSUE_RUNTIME,
    LOGGER,
    MAX_RECENT_EVALUATIONS,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
)
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


@dataclass
class ControlState:
    """User-facing control flags."""

    enabled: bool = True
    cooling_enabled: bool = True
    aggressive_cooling: bool = False
    # Safety default: start in dry-run until explicitly disabled.
    dry_run: bool = True


@dataclass
class CoordinatorData:
    """Data exposed to coordinator entities."""

    mode: HomeOutput = HomeOutput.OFF
    current: HomeOutput = HomeOutput.OFF
    adjustment: HomeOutput = HomeOutput.NO_CHANGE
    solar_available: bool = False
    solar_generation_w: float = 0.0
    grid_usage_w: float = 0.0
    auto_mode: bool = False
    dry_run: bool = False
    last_evaluated: str | None = None
    last_changed: str | None = None
    recent_evaluations: list[dict[str, Any]] = field(default_factory=list)


class HomeRulesCoordinator(DataUpdateCoordinator[CoordinatorData]):
    """Coordinate entity polling, decisioning, and action execution."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self._lock = asyncio.Lock()
        self._session = CachedState()
        self._controls = ControlState()
        self._auto_mode = False
        self._recent: list[dict[str, Any]] = []
        self._last_changed: str | None = None
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            STORAGE_KEY_TEMPLATE.format(entry_id=config_entry.entry_id),
        )

        super().__init__(
            hass,
            LOGGER,
            name=f"Home Rules ({config_entry.entry_id})",
            config_entry=config_entry,
            update_interval=timedelta(seconds=self._eval_interval),
            always_update=True,
        )
        self.data = CoordinatorData()

    @property
    def _eval_interval(self) -> int:
        return int(self.config_entry.options.get(CONF_EVAL_INTERVAL, DEFAULT_EVAL_INTERVAL))

    @property
    def parameters(self) -> RuleParameters:
        return RuleParameters(
            generation_cool_threshold=float(
                self.config_entry.options.get(CONF_GENERATION_COOL_THRESHOLD, DEFAULT_GENERATION_COOL_THRESHOLD)
            ),
            generation_dry_threshold=float(
                self.config_entry.options.get(CONF_GENERATION_DRY_THRESHOLD, DEFAULT_GENERATION_DRY_THRESHOLD)
            ),
            temperature_threshold=float(
                self.config_entry.options.get(CONF_TEMPERATURE_THRESHOLD, DEFAULT_TEMPERATURE_THRESHOLD)
            ),
            humidity_threshold=float(
                self.config_entry.options.get(CONF_HUMIDITY_THRESHOLD, DEFAULT_HUMIDITY_THRESHOLD)
            ),
            grid_usage_delay=int(self.config_entry.options.get(CONF_GRID_USAGE_DELAY, DEFAULT_GRID_USAGE_DELAY)),
            reactivate_delay=int(self.config_entry.options.get(CONF_REACTIVATE_DELAY, DEFAULT_REACTIVATE_DELAY)),
            temperature_cool=float(self.config_entry.options.get(CONF_TEMPERATURE_COOL, DEFAULT_TEMPERATURE_COOL)),
        )

    @property
    def controls(self) -> ControlState:
        return self._controls

    async def async_initialize(self) -> None:
        stored = await self._store.async_load()
        if not stored:
            return

        controls = stored.get("controls", {})
        session = stored.get("session", {})

        self._controls = ControlState(
            enabled=bool(controls.get("enabled", True)),
            cooling_enabled=bool(controls.get("cooling_enabled", True)),
            aggressive_cooling=bool(controls.get("aggressive_cooling", False)),
            dry_run=bool(controls.get("dry_run", True)),
        )
        self._session = CachedState(
            reactivate_delay=int(session.get("reactivate_delay", 0)),
            tolerated=int(session.get("tolerated", 0)),
            last=HomeOutput(session["last"]) if session.get("last") else None,
            failed_to_change=int(session.get("failed_to_change", 0)),
        )
        self._auto_mode = bool(stored.get("auto_mode", False))
        self._last_changed = stored.get("last_changed")
        self._recent = list(stored.get("recent_evaluations", []))[:MAX_RECENT_EVALUATIONS]

    async def async_set_control(self, key: str, value: bool) -> None:
        setattr(self._controls, key, value)
        await self._save_state()
        await self.async_run_evaluation("control")

    async def async_run_evaluation(self, trigger: str = "manual") -> None:
        data = await self._evaluate(trigger)
        self.async_set_updated_data(data)

    async def _async_update_data(self) -> CoordinatorData:
        try:
            return await self._evaluate("poll")
        except Exception as err:  # noqa: BLE001
            self._create_issue(ISSUE_RUNTIME, "runtime_error", {"error": str(err)})
            raise UpdateFailed(str(err)) from err

    async def _evaluate(self, trigger: str) -> CoordinatorData:
        async with self._lock:
            now = dt_util.utcnow().isoformat()
            home = self._build_home_input()
            current = current_state(home)

            if self._session.last is None:
                self._session.last = current

            adjustment = adjust(self.parameters, home, self._session)
            await self._execute_adjustment(adjustment)

            previous = self._session.last
            applied = apply_adjustment(self._session, current, adjustment)
            if self._controls.dry_run:
                # In dry-run we intentionally avoid service calls; never treat repeated
                # adjustments as a runtime failure.
                self._session.failed_to_change = 0
                applied = True
            if not applied:
                raise RuntimeError("failed to apply adjustment")

            if previous != self._session.last:
                self._last_changed = now

            record = {
                "time": now,
                "trigger": trigger,
                "current": current.value,
                "adjustment": adjustment.value,
                "generation": home.generation,
                "grid_usage": home.grid_usage,
                "temperature": home.temperature,
                "humidity": home.humidity,
                "have_solar": home.have_solar,
                "auto": home.auto,
                "dry_run": self._controls.dry_run,
            }
            self._recent.insert(0, record)
            self._recent = self._recent[:MAX_RECENT_EVALUATIONS]

            await self._save_state()

            self.hass.bus.async_fire(EVENT_EVALUATION, record)

            self._clear_issue(ISSUE_RUNTIME)
            self._clear_issue(ISSUE_ENTITY_MISSING)
            self._clear_issue(ISSUE_INVALID_UNIT)

            return CoordinatorData(
                mode=self._session.last or current,
                current=current,
                adjustment=adjustment,
                solar_available=home.have_solar and home.generation > 0.0,
                solar_generation_w=home.generation,
                grid_usage_w=home.grid_usage,
                auto_mode=self._auto_mode,
                dry_run=self._controls.dry_run,
                last_evaluated=now,
                last_changed=self._last_changed,
                recent_evaluations=list(self._recent),
            )

    def _build_home_input(self) -> HomeInput:
        climate_state = self._get_state(self.config_entry.data[CONF_CLIMATE_ENTITY_ID], "climate")
        timer_state = self._get_state(self.config_entry.data[CONF_TIMER_ENTITY_ID], "timer")
        inverter_entity = self.config_entry.data.get(CONF_INVERTER_ENTITY_ID)
        inverter_state = self._get_state(inverter_entity, "inverter") if inverter_entity else None

        generation_state = self._get_state(self.config_entry.data[CONF_GENERATION_ENTITY_ID], "generation")
        grid_state = self._get_state(self.config_entry.data[CONF_GRID_ENTITY_ID], "grid")
        temp_state = self._get_state(self.config_entry.data[CONF_TEMPERATURE_ENTITY_ID], "temperature")
        humidity_state = self._get_state(self.config_entry.data[CONF_HUMIDITY_ENTITY_ID], "humidity")

        have_solar = self._state_to_bool(inverter_state) if inverter_state else True

        generation = self._normalized_power(generation_state, "generation") if have_solar else 0.0
        grid_usage = self._normalized_power(grid_state, "grid") if have_solar else 0.0
        temperature = self._normalized_temperature(temp_state)
        humidity = self._state_to_float(humidity_state, "humidity")

        mode_raw = str(climate_state.state).lower().strip()
        try:
            mode = AirconMode(mode_raw)
        except ValueError:
            mode = AirconMode.UNKNOWN

        timer_active = str(timer_state.state).lower() not in {"idle", "cancelled"}

        return HomeInput(
            aircon_mode=mode,
            have_solar=have_solar,
            generation=generation,
            grid_usage=grid_usage,
            timer=timer_active,
            temperature=temperature,
            humidity=humidity,
            auto=self._auto_mode,
            aggressive_cooling=self._controls.aggressive_cooling,
            enabled=self._controls.enabled,
            cooling_enabled=self._controls.cooling_enabled,
        )

    async def _execute_adjustment(self, adjustment: HomeOutput) -> None:
        if adjustment in (HomeOutput.NO_CHANGE, HomeOutput.RESET, HomeOutput.DISABLED):
            return

        climate_entity = self.config_entry.data[CONF_CLIMATE_ENTITY_ID]
        timer_entity = self.config_entry.data[CONF_TIMER_ENTITY_ID]

        if self._controls.dry_run:
            LOGGER.info("DRY RUN: would apply adjustment %s", adjustment.value)
            if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
                self._auto_mode = True
            elif adjustment is HomeOutput.OFF:
                self._auto_mode = False
            return

        try:
            if adjustment in (HomeOutput.COOL, HomeOutput.DRY):
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": climate_entity,
                        "hvac_mode": adjustment.value.lower(),
                        "temperature": self.parameters.temperature_cool,
                    },
                    blocking=True,
                )
                self._auto_mode = True
                return

            if adjustment is HomeOutput.OFF:
                await self.hass.services.async_call(
                    "climate",
                    "turn_off",
                    {"entity_id": climate_entity},
                    blocking=True,
                )
                self._auto_mode = False
                return

            if adjustment is HomeOutput.TIMER:
                await self.hass.services.async_call(
                    "timer",
                    "start",
                    {"entity_id": timer_entity},
                    blocking=True,
                )
        except ServiceValidationError as err:
            raise RuntimeError(f"service call failed: {err}") from err

    def _get_state(self, entity_id: str, label: str) -> State:
        state = self.hass.states.get(entity_id)
        if state is None:
            self._create_issue(
                ISSUE_ENTITY_MISSING,
                "entity_missing",
                {"entity_id": entity_id, "label": label},
            )
            raise ValueError(f"missing entity: {entity_id}")
        if str(state.state).lower() in {"unknown", "unavailable"}:
            raise ValueError(f"entity unavailable: {entity_id}")
        return state

    def _state_to_bool(self, state: State) -> bool:
        value = str(state.state).lower().strip()
        return value in {"on", "true", "1", "online", "on-line"}

    def _state_to_float(self, state: State, label: str) -> float:
        try:
            return float(state.state)
        except ValueError as err:
            raise ValueError(f"invalid numeric {label}: {state.state}") from err

    def _normalized_power(self, state: State, label: str) -> float:
        value = self._state_to_float(state, label)
        unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip().lower()
        if unit in {"", "w", "watt", "watts"}:
            return max(0.0, value)
        if unit in {"kw", "kilowatt", "kilowatts"}:
            return max(0.0, value * 1000)
        if unit in {"mw"}:
            return max(0.0, value * 1_000_000)

        self._create_issue(
            ISSUE_INVALID_UNIT,
            "invalid_unit",
            {"entity_id": state.entity_id, "unit": unit or "(none)"},
        )
        raise ValueError(f"unsupported power unit for {state.entity_id}: {unit}")

    def _normalized_temperature(self, state: State) -> float:
        value = self._state_to_float(state, "temperature")
        unit = str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "")).strip().lower()
        if unit in {"", "°c", "c"}:
            return value
        if unit in {"°f", "f"}:
            return (value - 32) * 5 / 9
        raise ValueError(f"unsupported temperature unit for {state.entity_id}: {unit}")

    async def _save_state(self) -> None:
        await self._store.async_save(
            {
                "controls": asdict(self._controls),
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
            DOMAIN,
            self._issue_id(suffix),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders=placeholders,
        )

    def _clear_issue(self, suffix: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(suffix))
