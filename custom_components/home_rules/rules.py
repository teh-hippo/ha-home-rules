"""Pure decision engine for solar-aware aircon control.

No Home Assistant dependencies — all I/O is handled by the coordinator.
The engine evaluates environmental inputs and produces adjustment decisions.

Decision tree (high-level):
  1. Disabled → report DISABLED
  2. Unknown aircon mode → NO_CHANGE
  3. Automatic cooling disabled, or target-stop enabled at target → OFF
  4. Expired manual cooling timer → OFF
  5. Start or adopt cooling when temperature and solar qualify
  6. Other manual cooling on paid power/timer → apply timer cap
  7. Battery/grid permitted → finish a solar-started run within its allowance
  8. Solar only → tolerate brief paid-power use, then stop
"""

from dataclasses import dataclass, replace
from enum import StrEnum
from math import isfinite
from typing import NamedTuple

ALLOWED_FAILURES = 3

# Reason constants — every decision path has a named reason.
R_NO_SOLAR = "No solar available"
R_INSUFFICIENT_SOLAR = "Insufficient solar"
R_PAID_POWER = "Solar run-on allowance"
R_RUN_ON_EXPIRED = "Solar run-on allowance expired"
R_SOLAR_COOL = "Solar above cool threshold"
R_SOLAR_DRY = "Solar above dry threshold"
R_DRY_DISABLED = "Dry mode disabled"
R_HUMIDITY_TOO_LOW = "Humidity too low for dry mode"
R_ALREADY_COOLING = "Already cooling on solar"
R_ALREADY_DRYING = "Already drying on solar"
R_GRID_TOLERATED = "Grid usage tolerated"
R_GRID_TOO_HIGH = "Grid usage too high"
R_REACTIVATE_WAIT = "Waiting reactivate delay"
R_DISABLED = "Disabled"
R_UNKNOWN_MODE = "Unknown aircon mode"
R_TIMER_EXPIRED = "Timer expired"
R_MANUAL = "Manual"
R_AUTO_IDLE = "Auto idle"
R_NO_CHANGE = "No change"
R_COOLING_DISABLED = "Cooling disabled"
R_BELOW_COOL_SETPOINT = "Temperature below ideal temperature"
R_BELOW_THRESHOLD = "Temperature below comfort temperature"
R_BATTERY_ENGAGED = "Battery engaged"
R_BATTERY_TOLERATED = "Battery discharge tolerated"
R_TARGET_REACHED = "Cooling target reached"
R_TEMPERATURE_UNAVAILABLE = "Temperature unavailable"
R_HUMIDITY_UNAVAILABLE = "Humidity unavailable"
R_INVALID_TEMPERATURE_RANGE = "Comfort temperature must be above ideal temperature"
R_NO_ONE_HOME = "No one home"
R_OCCUPANCY_UNAVAILABLE = "Home occupancy unavailable"
R_BATTERY_SOC_UNAVAILABLE = "Battery state of charge unavailable"
R_BATTERY_FULL = "Battery full"
R_BATTERY_COOLING = "Battery-authorised cooling"
R_BATTERY_RESERVE = "Battery reserve reached"
R_AFTERNOON_WAITING = "Waiting for afternoon forecast window"
R_AFTERNOON_FORECAST_UNAVAILABLE = "Afternoon forecast unavailable"
R_AFTERNOON_NO_RECOVERY = "Afternoon forecast does not recover within tolerance"
R_AFTERNOON_RESERVE = "Afternoon battery reserve reached"
R_AFTERNOON_COOLING = "Afternoon battery comfort cooling"
R_AFTERNOON_OCCUPANCY = "Camille not home for afternoon battery cooling"
R_AFTERNOON_TARGET = "Afternoon comfort target reached"
R_AFTERNOON_WINDOW_CLOSED = "Afternoon forecast window closed"
R_AFTERNOON_POWER_UNAVAILABLE = "Afternoon live power data unavailable"


class AirconMode(StrEnum):
    DRY = "dry"
    COOL = "cool"
    AUTO = "auto"
    HEAT = "heat"
    HEAT_COOL = "heat_cool"
    FAN_ONLY = "fan_only"
    OFF = "off"
    UNKNOWN = "unknown"


class HomeOutput(StrEnum):
    NO_CHANGE = "No Change"
    OFF = "Off"
    ON = "On"
    COOL = "Cool"
    DRY = "Dry"
    TIMER = "Timer"
    DISABLED = "Disabled"
    RESET = "Reset"


OUT = HomeOutput


@dataclass
class HomeInput:
    aircon_mode: AirconMode
    have_solar: bool
    generation: float
    grid_usage: float
    timer: bool
    temperature: float | None
    humidity: float | None
    auto: bool
    allow_paid_power: bool
    enabled: bool
    cooling_enabled: bool
    battery_discharge: float = 0.0
    temperature_available: bool = True
    humidity_available: bool = True
    now: float = 0.0
    someone_home: bool | None = None
    only_cool_when_home: bool = False
    battery_soc: float | None = None
    allow_away_battery_cooling: bool = False
    afternoon_enabled: bool = False
    afternoon_planning: bool = False
    afternoon_window_open: bool = False
    afternoon_forecast_available: bool = True
    afternoon_forecast_recovery: bool = False
    afternoon_window_start: str | None = None
    afternoon_window_end: str | None = None
    afternoon_window_energy: float = 0.0
    afternoon_start_allowed: bool = False
    generation_available: bool = True
    grid_available: bool = True
    battery_power_available: bool = True


@dataclass
class RuleParameters:
    generation_cool_threshold: float
    generation_dry_threshold: float
    temperature_threshold: float
    dry_mode_humidity_cutoff: float
    dry_mode_enabled: bool
    grid_usage_delay: int
    reactivate_delay: float
    temperature_cool: float
    stop_at_comfort_temperature: bool = False
    solar_run_on_minutes: float = 60.0
    evaluation_interval: float = 180.0
    battery_full_threshold: float = 100.0
    battery_reserve_threshold: float = 80.0
    afternoon_energy_budget: float = 6.1
    afternoon_battery_reserve: float = 40.0

    @property
    def temperature_range_valid(self) -> bool:
        return (
            isfinite(self.temperature_cool)
            and isfinite(self.temperature_threshold)
            and self.temperature_threshold > self.temperature_cool
        )

    @property
    def battery_range_valid(self) -> bool:
        return (
            isfinite(self.battery_full_threshold)
            and isfinite(self.battery_reserve_threshold)
            and 0 <= self.battery_reserve_threshold < self.battery_full_threshold <= 100
        )

    @property
    def afternoon_range_valid(self) -> bool:
        return (
            isfinite(self.afternoon_energy_budget)
            and self.afternoon_energy_budget > 0
            and isfinite(self.afternoon_battery_reserve)
            and 0 <= self.afternoon_battery_reserve <= 100
        )


@dataclass
class CachedState:
    reactivate_at: float = 0.0
    tolerated: int = 0
    last: HomeOutput | None = None
    failed_to_change: int = 0
    solar_run_eligible: bool = False
    solar_lost_at: float | None = None
    solar_recovered_at: float | None = None
    battery_run_authorized: bool = False
    afternoon_run_authorized: bool = False
    afternoon_battery_run: bool = False
    afternoon_window_start: str | None = None
    afternoon_window_end: str | None = None
    afternoon_window_energy: float = 0.0

    def clear_solar_run(self) -> None:
        self.solar_run_eligible = False
        self.solar_lost_at = self.solar_recovered_at = None

    def clear_power_run(self) -> None:
        self.clear_solar_run()
        self.battery_run_authorized = self.afternoon_run_authorized = self.afternoon_battery_run = False

    def record_stop(self, now: float, delay_minutes: float) -> None:
        self.reactivate_at = max(self.reactivate_at, now + delay_minutes * 60)
        self.tolerated = 0
        self.clear_power_run()

    def solar_run_on_deadline(self, config: RuleParameters) -> float | None:
        if self.solar_lost_at is None:
            return None
        return (
            self.solar_lost_at + config.grid_usage_delay * config.evaluation_interval + config.solar_run_on_minutes * 60
        )


class AdjustResult(NamedTuple):
    output: HomeOutput
    reason: str


class TargetResult(NamedTuple):
    """Result from _evaluate_target_mode.

    output: the mode to switch to, or None if no action needed.
    reason: human-readable explanation.
    is_actionable: True if this represents a real activation reason
        (not just a status like "Insufficient solar"). Used by
        _idle_reason to decide whether to surface the reason.
    """

    output: HomeOutput | None
    reason: str
    is_actionable: bool


def _evaluate_target_mode(config: RuleParameters, home: HomeInput) -> TargetResult:
    """Determine what mode the aircon should be in based on current conditions.

    Returns a TargetResult with the suggested mode (or None for no change),
    a reason string, and whether the reason is actionable (suitable for
    display as an idle reason when the aircon is off).
    """
    h = home
    if not h.have_solar:
        return TargetResult(None, R_NO_SOLAR, True)

    # Solar COOL: generation above cool threshold
    if h.generation >= config.generation_cool_threshold:
        if h.aircon_mode != AirconMode.COOL:
            return TargetResult(HomeOutput.COOL, R_SOLAR_COOL, True)
        return TargetResult(None, R_ALREADY_COOLING, False)

    # Solar DRY: generation above dry threshold, if dry mode is allowed and useful.
    if h.generation >= config.generation_dry_threshold:
        if not config.dry_mode_enabled:
            return TargetResult(None, R_DRY_DISABLED, True)
        if h.aircon_mode == AirconMode.DRY:
            return TargetResult(None, R_ALREADY_DRYING, False)
        if not h.humidity_available or h.humidity is None:
            return TargetResult(None, R_HUMIDITY_UNAVAILABLE, True)
        if h.humidity < config.dry_mode_humidity_cutoff:
            return TargetResult(None, R_HUMIDITY_TOO_LOW, True)
        return TargetResult(HomeOutput.DRY, R_SOLAR_DRY, True)

    return TargetResult(None, R_INSUFFICIENT_SOLAR, False)


def current_state(home: HomeInput) -> HomeOutput:
    """Map the current aircon mode to a HomeOutput value."""
    if not home.enabled:
        return HomeOutput.DISABLED
    if home.timer and home.aircon_mode != AirconMode.OFF:
        return HomeOutput.TIMER
    return {AirconMode.COOL: HomeOutput.COOL, AirconMode.DRY: HomeOutput.DRY}.get(
        home.aircon_mode,
        HomeOutput.OFF if home.aircon_mode in (AirconMode.OFF, AirconMode.UNKNOWN) else HomeOutput.ON,
    )


def _idle_reason(config: RuleParameters, home: HomeInput, activation: str | None, default: str) -> str:
    """Explain why the aircon is idle (off and not activating).

    Checks are in priority order — first match wins.
    """
    if not home.cooling_enabled:
        return R_COOLING_DISABLED
    if not config.temperature_range_valid:
        return R_INVALID_TEMPERATURE_RANGE
    if not home.temperature_available or home.temperature is None:
        return R_TEMPERATURE_UNAVAILABLE
    if home.only_cool_when_home and home.someone_home is None:
        return R_OCCUPANCY_UNAVAILABLE
    if home.afternoon_enabled and home.afternoon_planning:
        if not home.afternoon_forecast_available:
            return R_AFTERNOON_FORECAST_UNAVAILABLE
        if not home.afternoon_window_open:
            return R_AFTERNOON_WAITING
        if not (home.generation_available and home.grid_available and home.battery_power_available):
            return R_AFTERNOON_POWER_UNAVAILABLE
        if home.someone_home is None:
            return R_OCCUPANCY_UNAVAILABLE
        if home.someone_home is True:
            if home.battery_soc is None:
                return R_BATTERY_SOC_UNAVAILABLE
            if home.battery_soc < config.afternoon_battery_reserve:
                return R_AFTERNOON_RESERVE
    if home.only_cool_when_home and home.someone_home is False and not _battery_start_allowed(config, home):
        if home.allow_away_battery_cooling and home.battery_soc is None:
            return R_BATTERY_SOC_UNAVAILABLE
        return R_NO_ONE_HOME
    if home.battery_discharge > 0:
        return R_BATTERY_ENGAGED
    if home.grid_usage > 0:
        return R_GRID_TOO_HIGH
    if home.temperature <= config.temperature_cool:
        return R_BELOW_COOL_SETPOINT
    if home.temperature < config.temperature_threshold:
        return R_BELOW_THRESHOLD
    return activation or default


def _stop(config: RuleParameters, home: HomeInput, state: CachedState, reason: str) -> AdjustResult:
    state.record_stop(home.now, config.reactivate_delay)
    return AdjustResult(HomeOutput.OFF, reason)


def _solar_run_on(config: RuleParameters, home: HomeInput, state: CachedState) -> AdjustResult | None:
    sufficient = home.have_solar and home.grid_usage <= 0 and home.battery_discharge <= 0
    tolerance = max(1, config.grid_usage_delay) * config.evaluation_interval
    if sufficient:
        state.solar_run_eligible = True
        if state.solar_lost_at is not None:
            if state.solar_recovered_at is None:
                state.solar_recovered_at = home.now
            if home.now - state.solar_recovered_at >= tolerance:
                state.solar_lost_at = state.solar_recovered_at = None
        return None
    state.solar_recovered_at = None
    if not home.allow_paid_power or not state.solar_run_eligible or config.solar_run_on_minutes <= 0:
        return None
    if state.solar_lost_at is None:
        state.solar_lost_at = home.now
    deadline = state.solar_run_on_deadline(config)
    if deadline is not None and home.now >= deadline:
        return _stop(config, home, state, R_RUN_ON_EXPIRED)
    state.tolerated = 0
    return AdjustResult(HomeOutput.NO_CHANGE, R_PAID_POWER)


def _battery_start_allowed(config: RuleParameters, home: HomeInput) -> bool:
    return (
        home.only_cool_when_home
        and home.someone_home is False
        and home.allow_away_battery_cooling
        and home.grid_usage <= 0
        and config.battery_range_valid
        and home.battery_soc is not None
        and home.battery_soc >= config.battery_full_threshold
    )


def adjust(config: RuleParameters, home: HomeInput, state: CachedState) -> AdjustResult:
    """Core decision function. Evaluates inputs and returns the adjustment to make.

    Mutates `state` (tolerance counters, reactivation delay, last output).
    """
    h = home
    if h.aircon_mode is AirconMode.OFF or not h.auto:
        state.clear_power_run()
    if not h.enabled:
        state.tolerated = 0
        state.clear_power_run()
        out = HomeOutput.NO_CHANGE if state.last is HomeOutput.DISABLED else HomeOutput.DISABLED
        return AdjustResult(out, R_DISABLED)
    if h.aircon_mode == AirconMode.UNKNOWN:
        return AdjustResult(HomeOutput.NO_CHANGE, R_UNKNOWN_MODE)
    afternoon_planning = h.afternoon_enabled and h.afternoon_planning
    afternoon_running = h.auto and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY) and state.afternoon_run_authorized
    if h.auto and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY) and afternoon_planning and h.afternoon_window_open:
        state.afternoon_run_authorized = True
    if (
        h.auto
        and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY)
        and (afternoon_planning or state.afternoon_run_authorized)
        and not (h.generation_available and h.grid_available and h.battery_power_available)
    ):
        return _stop(config, h, state, R_AFTERNOON_POWER_UNAVAILABLE)
    if h.auto and not h.cooling_enabled and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY):
        return _stop(config, h, state, R_COOLING_DISABLED)
    if afternoon_running and state.afternoon_battery_run:
        if not afternoon_planning:
            return _stop(config, h, state, R_AFTERNOON_WINDOW_CLOSED)
        if not h.afternoon_forecast_available:
            return _stop(config, h, state, R_AFTERNOON_FORECAST_UNAVAILABLE)
        if not h.afternoon_window_open:
            return _stop(config, h, state, R_AFTERNOON_WINDOW_CLOSED)
        if h.grid_usage > 0:
            return _stop(config, h, state, R_GRID_TOO_HIGH)
        if not (h.generation_available and h.grid_available and h.battery_power_available):
            return _stop(config, h, state, R_AFTERNOON_POWER_UNAVAILABLE)
        if h.battery_soc is None:
            return _stop(config, h, state, R_BATTERY_SOC_UNAVAILABLE)
        if h.battery_soc < config.afternoon_battery_reserve:
            return _stop(config, h, state, R_AFTERNOON_RESERVE)
        if h.someone_home is not True:
            return _stop(config, h, state, R_AFTERNOON_OCCUPANCY)
        if not h.temperature_available or h.temperature is None:
            return _stop(config, h, state, R_TEMPERATURE_UNAVAILABLE)
        if h.temperature_available and h.temperature is not None and h.temperature <= config.temperature_threshold:
            return _stop(config, h, state, R_AFTERNOON_TARGET)
        state.tolerated = 0
        return AdjustResult(HomeOutput.NO_CHANGE, R_AFTERNOON_COOLING)
    if (
        h.aircon_mode in (AirconMode.COOL, AirconMode.DRY)
        and config.stop_at_comfort_temperature
        and h.temperature_available
        and h.temperature is not None
        and h.temperature <= config.temperature_cool
    ):
        return _stop(config, h, state, R_TARGET_REACHED)
    manual_cooling = not h.auto and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY)
    if manual_cooling and state.last is HomeOutput.TIMER and not h.timer:
        return _stop(config, h, state, R_TIMER_EXPIRED)
    if h.aircon_mode is AirconMode.OFF and h.now < state.reactivate_at:
        return AdjustResult(HomeOutput.NO_CHANGE, R_REACTIVATE_WAIT)

    target = _evaluate_target_mode(config, replace(h, aircon_mode=AirconMode.OFF) if manual_cooling else h)
    battery_start_allowed = _battery_start_allowed(config, h)
    occupancy_allows_start = not h.only_cool_when_home or h.someone_home is True or battery_start_allowed
    if (
        h.aircon_mode is AirconMode.OFF
        and h.cooling_enabled
        and h.grid_usage <= 0
        and config.temperature_range_valid
        and h.temperature_available
        and h.temperature is not None
        and h.temperature >= config.temperature_threshold
        and battery_start_allowed
    ):
        state.tolerated = 0
        state.clear_solar_run()
        state.battery_run_authorized = True
        return AdjustResult(HomeOutput.COOL, R_BATTERY_FULL)
    if (
        h.aircon_mode is AirconMode.OFF
        and afternoon_planning
        and h.afternoon_window_open
        and h.afternoon_start_allowed
        and h.cooling_enabled
        and h.grid_usage <= 0
        and h.generation_available
        and h.grid_available
        and h.battery_power_available
        and config.temperature_range_valid
        and h.temperature_available
        and h.temperature is not None
        and h.temperature > config.temperature_threshold
        and h.someone_home is True
        and h.battery_soc is not None
        and h.battery_soc >= config.afternoon_battery_reserve
    ):
        state.tolerated = 0
        state.clear_solar_run()
        state.afternoon_run_authorized = state.afternoon_battery_run = True
        return AdjustResult(HomeOutput.COOL, R_AFTERNOON_COOLING)
    if (
        (h.aircon_mode is AirconMode.OFF or manual_cooling)
        and h.cooling_enabled
        and h.battery_discharge <= 0
        and h.grid_usage <= 0
        and config.temperature_range_valid
        and h.temperature_available
        and h.temperature is not None
        and h.temperature >= config.temperature_threshold
        and target.output is not None
        and occupancy_allows_start
        and (not afternoon_planning or h.afternoon_window_open)
        and (not afternoon_planning or h.afternoon_start_allowed)
        and (not afternoon_planning or (h.generation_available and h.grid_available and h.battery_power_available))
    ):
        state.tolerated = 0
        state.solar_run_eligible = True
        if afternoon_planning:
            state.afternoon_run_authorized = True
        return AdjustResult(target.output, target.reason)

    if manual_cooling:
        if h.timer or not h.have_solar or h.grid_usage > 0 or h.battery_discharge > 0:
            state.tolerated = 0
            if h.timer:
                return AdjustResult(HomeOutput.NO_CHANGE, R_NO_CHANGE)
            return AdjustResult(HomeOutput.TIMER, R_MANUAL)

    if h.auto and h.aircon_mode is AirconMode.DRY and not config.dry_mode_enabled:
        if (
            target.output is HomeOutput.COOL
            and h.temperature_available
            and h.grid_usage <= 0
            and h.battery_discharge <= 0
        ):
            state.tolerated = 0
            return AdjustResult(target.output, target.reason)
        return _stop(config, h, state, R_DRY_DISABLED)
    activation = target.reason if target.is_actionable else None

    if h.auto and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY) and h.only_cool_when_home:
        if h.someone_home is None:
            return _stop(config, h, state, R_OCCUPANCY_UNAVAILABLE)
        if h.someone_home is False:
            if battery_start_allowed:
                state.battery_run_authorized = True
            elif (
                afternoon_planning and state.afternoon_run_authorized and h.battery_discharge <= 0 and h.grid_usage <= 0
            ):
                pass
            elif not state.battery_run_authorized:
                return _stop(config, h, state, R_NO_ONE_HOME)
    if h.auto and state.battery_run_authorized and (not h.only_cool_when_home or h.someone_home is True):
        state.battery_run_authorized = False
        state.clear_solar_run()

    if (
        afternoon_planning
        and h.auto
        and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY)
        and not state.battery_run_authorized
    ):
        if not (h.generation_available and h.grid_available and h.battery_power_available):
            return _stop(config, h, state, R_AFTERNOON_POWER_UNAVAILABLE)
        if h.grid_usage > 0:
            return _stop(config, h, state, R_GRID_TOO_HIGH)
        if h.battery_discharge > 0:
            if not h.afternoon_forecast_recovery:
                return _stop(config, h, state, R_AFTERNOON_NO_RECOVERY)
            if h.battery_soc is None:
                return _stop(config, h, state, R_BATTERY_SOC_UNAVAILABLE)
            if h.someone_home is True:
                if h.battery_soc < config.afternoon_battery_reserve:
                    return _stop(config, h, state, R_AFTERNOON_RESERVE)
            elif h.someone_home is False:
                if h.battery_soc < config.battery_reserve_threshold:
                    return _stop(config, h, state, R_BATTERY_RESERVE)
            else:
                return _stop(config, h, state, R_AFTERNOON_OCCUPANCY)
            state.afternoon_run_authorized = True
            state.tolerated += 1
            if state.tolerated >= config.grid_usage_delay:
                return _stop(config, h, state, R_BATTERY_ENGAGED)
            return AdjustResult(HomeOutput.NO_CHANGE, R_BATTERY_TOLERATED)
        elif (
            h.someone_home is False
            and not state.afternoon_run_authorized
            and not state.battery_run_authorized
            and h.battery_soc is not None
            and h.battery_soc < config.battery_full_threshold
        ):
            return _stop(config, h, state, R_NO_ONE_HOME)

    # --- Aircon is OFF ---
    if h.aircon_mode == AirconMode.OFF:
        state.tolerated = 0
        if h.auto:
            return AdjustResult(HomeOutput.OFF, _idle_reason(config, h, activation, R_AUTO_IDLE))
        if state.last is HomeOutput.TIMER and not h.timer:
            return AdjustResult(HomeOutput.RESET, R_TIMER_EXPIRED)
        return AdjustResult(HomeOutput.NO_CHANGE, _idle_reason(config, h, activation, R_NO_CHANGE))

    # --- Aircon is ON in a mode home-rules never commands (heat/heat_cool/fan_only/auto) ---
    # Such a run is external by definition: cap it and turn it off at expiry, independent of
    # solar. Only COOL/DRY runs follow the solar economics below.
    if h.aircon_mode not in (AirconMode.COOL, AirconMode.DRY):
        if h.timer:
            return AdjustResult(HomeOutput.NO_CHANGE, R_NO_CHANGE)
        if state.last is HomeOutput.TIMER:
            return _stop(config, h, state, R_TIMER_EXPIRED)
        return AdjustResult(HomeOutput.TIMER, R_MANUAL)

    if h.auto and state.battery_run_authorized:
        if not h.allow_away_battery_cooling or not h.only_cool_when_home:
            return _stop(config, h, state, R_NO_ONE_HOME)
        if h.battery_soc is None:
            return _stop(config, h, state, R_BATTERY_SOC_UNAVAILABLE)
        if h.battery_soc < config.battery_reserve_threshold:
            return _stop(config, h, state, R_BATTERY_RESERVE)
        if not h.temperature_available or h.temperature is None:
            return _stop(config, h, state, R_TEMPERATURE_UNAVAILABLE)
        if h.temperature <= config.temperature_cool:
            return _stop(config, h, state, R_TARGET_REACHED)
        if h.grid_usage > 0:
            state.tolerated += 1
            if state.tolerated >= config.grid_usage_delay:
                return _stop(config, h, state, R_GRID_TOO_HIGH)
        else:
            state.tolerated = 0
        return AdjustResult(HomeOutput.NO_CHANGE, R_BATTERY_COOLING)

    if h.auto and (run_on := _solar_run_on(config, h, state)) is not None:
        return run_on

    # --- Cooling run + grid draw (or no solar) ---
    if h.auto and (not h.have_solar or h.grid_usage > 0 or h.battery_discharge > 0):
        state.tolerated += 1
        if state.tolerated < config.grid_usage_delay:
            if target.output is not None and h.temperature_available and h.battery_discharge <= 0:
                return AdjustResult(target.output, target.reason)
            return AdjustResult(
                HomeOutput.NO_CHANGE, R_BATTERY_TOLERATED if h.battery_discharge > 0 else R_GRID_TOLERATED
            )
        return _stop(config, h, state, R_BATTERY_ENGAGED if h.battery_discharge > 0 else R_GRID_TOO_HIGH)
    # --- Cooling run + free solar ---
    if h.auto:
        state.tolerated = 0
        if not h.temperature_available or h.temperature is None:
            return AdjustResult(HomeOutput.NO_CHANGE, R_TEMPERATURE_UNAVAILABLE)
        if target.output is not None:
            return AdjustResult(target.output, target.reason)
        return AdjustResult(HomeOutput.NO_CHANGE, activation or R_NO_CHANGE)

    return AdjustResult(HomeOutput.NO_CHANGE, R_NO_CHANGE)


def apply_adjustment(session: CachedState, current: HomeOutput, adjustment: HomeOutput) -> bool:
    """Track whether an adjustment was successfully applied.

    Returns True if the adjustment should proceed, False if too many
    consecutive failures to change to the same state.
    """
    if adjustment in (HomeOutput.NO_CHANGE, HomeOutput.RESET):
        if adjustment is HomeOutput.RESET:
            session.last = current
        session.failed_to_change = 0
        return True

    if session.last is None or session.last != adjustment:
        session.last = adjustment
        session.failed_to_change = 0
        return True

    session.failed_to_change += 1
    return session.failed_to_change <= ALLOWED_FAILURES
