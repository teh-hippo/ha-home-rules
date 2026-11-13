"""Pure decision engine for solar-aware aircon control.

No Home Assistant dependencies — all I/O is handled by the coordinator.
The engine evaluates environmental inputs and produces adjustment decisions.

Decision tree (high-level):
  1. Disabled → report DISABLED
  2. Unknown aircon mode → NO_CHANGE
  3. Automatic cooling disabled, or target-stop enabled at target → OFF
  4. Manual cooling on paid power/timer → apply timer cap
  5. Reactivation delay active → NO_CHANGE (countdown)
  6. Aircon OFF → evaluate temperature and solar eligibility
  7. Battery/grid permitted → finish a solar-started run within its allowance
  8. Solar only → tolerate brief paid-power use, then stop
"""

from dataclasses import dataclass
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
R_BELOW_COOL_SETPOINT = "Temperature below cool setpoint"
R_BELOW_THRESHOLD = "Temperature below threshold"
R_BATTERY_ENGAGED = "Battery engaged"
R_BATTERY_TOLERATED = "Battery discharge tolerated"
R_TARGET_REACHED = "Cooling target reached"
R_TEMPERATURE_UNAVAILABLE = "Temperature unavailable"
R_INVALID_TEMPERATURE_RANGE = "Start temperature must be above comfort temperature"


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
    temperature: float
    humidity: float
    auto: bool
    allow_paid_power: bool
    enabled: bool
    cooling_enabled: bool
    pre_cooling: bool = False
    battery_discharge: float = 0.0
    temperature_available: bool = True
    now: float = 0.0


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
    temperature_precool: float = 20.0
    solar_run_on_minutes: float = 60.0
    evaluation_interval: float = 180.0

    @property
    def temperature_range_valid(self) -> bool:
        return (
            isfinite(self.temperature_cool)
            and isfinite(self.temperature_threshold)
            and self.temperature_threshold > self.temperature_cool
        )

    def cooling_target(self, home: HomeInput) -> float:
        return self.temperature_precool if home.pre_cooling else self.temperature_cool

    @property
    def precooling_range_valid(self) -> bool:
        return isfinite(self.temperature_precool) and self.temperature_precool <= self.temperature_cool

    def start_temperature(self, home: HomeInput) -> float:
        return self.temperature_precool + 1.0 if home.pre_cooling else self.temperature_threshold


@dataclass
class CachedState:
    reactivate_at: float = 0.0
    tolerated: int = 0
    last: HomeOutput | None = None
    failed_to_change: int = 0
    solar_run_eligible: bool = False
    solar_lost_at: float | None = None
    solar_recovered_at: float | None = None

    def clear_solar_run(self) -> None:
        self.solar_run_eligible = False
        self.solar_lost_at = self.solar_recovered_at = None

    def record_stop(self, now: float, delay_minutes: float) -> None:
        self.reactivate_at = max(self.reactivate_at, now + delay_minutes * 60)
        self.tolerated = 0
        self.clear_solar_run()

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
    if home.pre_cooling and not config.precooling_range_valid:
        return R_INVALID_TEMPERATURE_RANGE
    if not home.temperature_available:
        return R_TEMPERATURE_UNAVAILABLE
    if home.battery_discharge > 0:
        return R_BATTERY_ENGAGED
    if home.grid_usage > 0:
        return R_GRID_TOO_HIGH
    if home.temperature <= (config.temperature_precool if home.pre_cooling else config.temperature_cool):
        return R_BELOW_COOL_SETPOINT
    if home.temperature < config.start_temperature(home):
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


def adjust(config: RuleParameters, home: HomeInput, state: CachedState) -> AdjustResult:
    """Core decision function. Evaluates inputs and returns the adjustment to make.

    Mutates `state` (tolerance counters, reactivation delay, last output).
    """
    h = home
    if h.aircon_mode is AirconMode.OFF or not h.auto:
        state.clear_solar_run()
    if not h.enabled:
        state.tolerated = 0
        state.clear_solar_run()
        out = HomeOutput.NO_CHANGE if state.last is HomeOutput.DISABLED else HomeOutput.DISABLED
        return AdjustResult(out, R_DISABLED)
    if h.aircon_mode == AirconMode.UNKNOWN:
        return AdjustResult(HomeOutput.NO_CHANGE, R_UNKNOWN_MODE)
    if h.auto and not h.cooling_enabled and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY):
        return _stop(config, h, state, R_COOLING_DISABLED)
    if (
        h.aircon_mode in (AirconMode.COOL, AirconMode.DRY)
        and config.stop_at_comfort_temperature
        and not (h.auto and h.pre_cooling)
        and h.temperature_available
        and h.temperature <= config.temperature_cool
    ):
        return _stop(config, h, state, R_TARGET_REACHED)
    if not h.auto and h.aircon_mode in (AirconMode.COOL, AirconMode.DRY):
        if state.last is HomeOutput.TIMER and not h.timer:
            return _stop(config, h, state, R_TIMER_EXPIRED)
        if h.timer or not h.have_solar or h.grid_usage > 0 or h.battery_discharge > 0:
            state.tolerated = 0
            if h.timer:
                return AdjustResult(HomeOutput.NO_CHANGE, R_NO_CHANGE)
            return AdjustResult(HomeOutput.TIMER, R_MANUAL)

    target = _evaluate_target_mode(config, h)
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
    if h.aircon_mode is AirconMode.OFF and h.now < state.reactivate_at:
        return AdjustResult(HomeOutput.NO_CHANGE, R_REACTIVATE_WAIT)

    activation = target.reason if target.is_actionable else None

    # --- Aircon is OFF ---
    if h.aircon_mode == AirconMode.OFF:
        state.tolerated = 0
        if (
            h.cooling_enabled
            and h.battery_discharge <= 0
            and h.grid_usage <= 0
            and config.temperature_range_valid
            and (not h.pre_cooling or config.precooling_range_valid)
            and h.temperature_available
            and h.temperature >= config.start_temperature(h)
            and target.output is not None
        ):
            state.solar_run_eligible = True
            return AdjustResult(target.output, target.reason)
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
        if not h.temperature_available:
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
