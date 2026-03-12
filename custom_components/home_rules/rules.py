"""Pure decision engine for solar-aware aircon control.

No Home Assistant dependencies — all I/O is handled by the coordinator.
The engine evaluates environmental inputs and produces adjustment decisions.

Decision tree (high-level):
  1. Disabled → report DISABLED
  2. Unknown aircon mode → NO_CHANGE
  3. Reactivation delay active → NO_CHANGE (countdown)
  4. Aircon OFF → evaluate activation (solar thresholds or boost)
  5. Aircon ON + grid draw → tolerate, downgrade, or shut off
  6. Aircon ON + free solar → maintain or upgrade mode
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

ALLOWED_FAILURES = 3

# Reason constants — every decision path has a named reason.
R_NO_SOLAR = "No solar available"
R_INSUFFICIENT_SOLAR = "Insufficient solar"
R_BOOST_SOLAR = "Boost solar available"
R_BOOST_COOLING = "Boost cooling on solar"
R_BOOST_GRID_TOLERATED = "Boost grid tolerated"
R_SOLAR_COOL = "Solar above cool threshold"
R_SOLAR_DRY = "Solar above dry threshold"
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
    aggressive_cooling: bool
    enabled: bool
    cooling_enabled: bool


@dataclass
class RuleParameters:
    generation_cool_threshold: float
    generation_dry_threshold: float
    temperature_threshold: float
    humidity_threshold: float
    grid_usage_delay: int
    reactivate_delay: int
    temperature_cool: float


@dataclass
class CachedState:
    reactivate_delay: int = 0
    tolerated: int = 0
    last: HomeOutput | None = None
    failed_to_change: int = 0


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

    # Boost: any generation → COOL (ignores thresholds + humidity)
    if h.aggressive_cooling and h.generation > 0:
        if h.aircon_mode != AirconMode.COOL:
            return TargetResult(HomeOutput.COOL, R_BOOST_SOLAR, True)
        return TargetResult(None, R_BOOST_COOLING, False)

    # Solar COOL: generation above cool threshold + humidity OK
    if h.generation >= config.generation_cool_threshold and h.humidity <= config.humidity_threshold:
        if h.aircon_mode != AirconMode.COOL:
            return TargetResult(HomeOutput.COOL, R_SOLAR_COOL, True)
        return TargetResult(None, R_ALREADY_COOLING, False)

    # Solar DRY: generation above dry threshold
    if h.generation >= config.generation_dry_threshold:
        if h.aircon_mode != AirconMode.DRY:
            return TargetResult(HomeOutput.DRY, R_SOLAR_DRY, True)
        return TargetResult(None, R_ALREADY_DRYING, False)

    return TargetResult(None, R_INSUFFICIENT_SOLAR, False)


def current_state(home: HomeInput) -> HomeOutput:
    """Map the current aircon mode to a HomeOutput value."""
    if not home.enabled:
        return HomeOutput.DISABLED
    if home.timer and home.aircon_mode != AirconMode.OFF:
        return HomeOutput.TIMER
    return {AirconMode.COOL: HomeOutput.COOL, AirconMode.DRY: HomeOutput.DRY}.get(
        home.aircon_mode,
        HomeOutput.OFF if home.aircon_mode in (AirconMode.OFF, AirconMode.UNKNOWN) else HomeOutput.COOL,
    )


def _idle_reason(config: RuleParameters, home: HomeInput, activation: str | None, default: str) -> str:
    """Explain why the aircon is idle (off and not activating).

    Checks are in priority order — first match wins.
    """
    if not home.cooling_enabled:
        return R_COOLING_DISABLED
    if home.aggressive_cooling and home.temperature <= config.temperature_cool:
        return R_BELOW_COOL_SETPOINT
    if home.temperature < config.temperature_threshold:
        return R_BELOW_THRESHOLD
    return activation or default


def adjust(config: RuleParameters, home: HomeInput, state: CachedState) -> AdjustResult:
    """Core decision function. Evaluates inputs and returns the adjustment to make.

    Mutates `state` (tolerance counters, reactivation delay, last output).
    """
    h = home
    if not h.enabled:
        state.tolerated = 0
        out = HomeOutput.NO_CHANGE if state.last is HomeOutput.DISABLED else HomeOutput.DISABLED
        return AdjustResult(out, R_DISABLED)
    if h.aircon_mode == AirconMode.UNKNOWN:
        return AdjustResult(HomeOutput.NO_CHANGE, R_UNKNOWN_MODE)
    if state.reactivate_delay:
        state.reactivate_delay -= 1
        return AdjustResult(HomeOutput.NO_CHANGE, R_REACTIVATE_WAIT)

    target = _evaluate_target_mode(config, h)
    activation = target.reason if target.is_actionable else None

    # --- Aircon is OFF ---
    if h.aircon_mode == AirconMode.OFF:
        state.tolerated = 0
        temp_ok = (
            h.temperature > config.temperature_cool
            if h.aggressive_cooling
            else h.temperature >= config.temperature_threshold
        )
        if h.cooling_enabled and temp_ok and target.output is not None:
            return AdjustResult(target.output, target.reason)
        if h.auto:
            return AdjustResult(HomeOutput.OFF, _idle_reason(config, h, activation, R_AUTO_IDLE))
        if state.last is HomeOutput.TIMER and not h.timer:
            return AdjustResult(HomeOutput.RESET, R_TIMER_EXPIRED)
        return AdjustResult(HomeOutput.NO_CHANGE, _idle_reason(config, h, activation, R_NO_CHANGE))

    # --- Aircon is ON + grid draw (or no solar) ---
    if not h.have_solar or h.grid_usage > 0:
        if h.auto:
            # If a mode transition is available (e.g. COOL→DRY downgrade), apply immediately.
            if target.output is not None:
                state.tolerated = 0
                return AdjustResult(target.output, target.reason)
            # Boost: tolerate grid draw while solar is available.
            if h.aggressive_cooling and h.have_solar and h.generation > 0:
                state.tolerated = 0
                return AdjustResult(HomeOutput.NO_CHANGE, R_BOOST_GRID_TOLERATED)
            # Solar: tolerate briefly, then shut off.
            state.tolerated += 1
            if state.tolerated < config.grid_usage_delay:
                return AdjustResult(HomeOutput.NO_CHANGE, R_GRID_TOLERATED)
            state.tolerated = 0
            state.reactivate_delay = config.reactivate_delay
            return AdjustResult(HomeOutput.OFF, R_GRID_TOO_HIGH)
        if h.timer:
            return AdjustResult(OUT.NO_CHANGE, R_NO_CHANGE)
        if state.last is HomeOutput.TIMER:
            return AdjustResult(OUT.OFF, R_TIMER_EXPIRED)
        return AdjustResult(OUT.TIMER, R_MANUAL)

    # --- Aircon is ON + free solar ---
    if h.auto:
        state.tolerated = 0
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
