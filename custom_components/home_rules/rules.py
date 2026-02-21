from dataclasses import dataclass
from enum import StrEnum

ALLOWED_FAILURES = 3
_NO_ACTION_REASONS = {"Insufficient solar", "Aggressive cooling hold"}


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


@dataclass(frozen=True)
class TurnOnDecision:
    output: HomeOutput | None
    reason: str


def evaluate_turn_on(config: RuleParameters, home: HomeInput) -> TurnOnDecision:
    if not home.have_solar:
        return TurnOnDecision(output=None, reason="No solar available")
    aggressive = home.aggressive_cooling and home.grid_usage == 0
    if home.generation >= config.generation_cool_threshold and (
        aggressive or home.humidity <= config.humidity_threshold
    ):
        if home.aircon_mode != AirconMode.COOL:
            return TurnOnDecision(output=HomeOutput.COOL, reason="Solar above cool threshold")
        if home.grid_usage == 0:
            return TurnOnDecision(output=None, reason="Already cooling on solar")
    if aggressive:
        return TurnOnDecision(output=None, reason="Aggressive cooling hold")
    if home.generation >= config.generation_dry_threshold:
        if home.aircon_mode != AirconMode.DRY:
            return TurnOnDecision(output=HomeOutput.DRY, reason="Solar above dry threshold")
        if home.grid_usage == 0:
            return TurnOnDecision(output=None, reason="Already drying on solar")
    return TurnOnDecision(output=None, reason="Insufficient solar")


def _activation_reason(config: RuleParameters, home: HomeInput) -> str | None:
    reason = evaluate_turn_on(config, home).reason
    return None if reason in _NO_ACTION_REASONS else reason


def current_state(home: HomeInput) -> HomeOutput:
    if not home.enabled:
        return HomeOutput.DISABLED
    if home.timer and home.aircon_mode != AirconMode.OFF:
        return HomeOutput.TIMER
    return {
        AirconMode.COOL: HomeOutput.COOL,
        AirconMode.DRY: HomeOutput.DRY,
    }.get(
        home.aircon_mode,
        HomeOutput.OFF if home.aircon_mode in (AirconMode.OFF, AirconMode.UNKNOWN) else HomeOutput.COOL,
    )


def adjust(config: RuleParameters, home: HomeInput, state: CachedState) -> HomeOutput:
    if not home.enabled:
        state.tolerated = 0
        return HomeOutput.NO_CHANGE if state.last is HomeOutput.DISABLED else HomeOutput.DISABLED
    if home.aircon_mode == AirconMode.UNKNOWN:
        return HomeOutput.NO_CHANGE
    if state.reactivate_delay > 0:
        state.reactivate_delay -= 1
        return HomeOutput.NO_CHANGE

    decision = evaluate_turn_on(config, home)
    if home.aircon_mode == AirconMode.OFF:
        state.tolerated = 0
        if home.cooling_enabled and home.temperature >= config.temperature_threshold and decision.output is not None:
            return decision.output
        if home.auto:
            return HomeOutput.OFF
        if state.last is HomeOutput.TIMER and not home.timer:
            return HomeOutput.RESET
    elif not home.have_solar or home.grid_usage > 0:
        if home.auto:
            if decision.output is not None:
                state.tolerated = 0
                return decision.output
            state.tolerated += 1
            if state.tolerated < config.grid_usage_delay:
                return HomeOutput.NO_CHANGE
            state.tolerated = 0
            state.reactivate_delay = config.reactivate_delay
            return HomeOutput.OFF
        if not home.timer:
            return HomeOutput.TIMER
    elif home.auto:
        state.tolerated = 0
        if decision.output is not None:
            return decision.output
    return HomeOutput.NO_CHANGE


def apply_adjustment(session: CachedState, current: HomeOutput, adjustment: HomeOutput) -> bool:
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


def explain(config: RuleParameters, home: HomeInput, state: CachedState) -> str:
    if not home.enabled:
        return "Disabled"
    if home.aircon_mode == AirconMode.UNKNOWN:
        return "Unknown aircon mode"
    if state.reactivate_delay > 0:
        return "Waiting reactivate delay"

    if home.aircon_mode == AirconMode.OFF:
        if not home.cooling_enabled:
            return "Cooling disabled"
        if home.temperature < config.temperature_threshold:
            return "Temperature below threshold"
        if reason := _activation_reason(config, home):
            return reason
        if home.auto:
            return "Auto idle"
        if state.last is HomeOutput.TIMER and not home.timer:
            return "Timer expired"
        return "No change"

    if not home.have_solar or home.grid_usage > 0:
        if home.auto:
            if reason := _activation_reason(config, home):
                return reason
            return "Grid usage tolerated" if (state.tolerated + 1) < config.grid_usage_delay else "Grid usage too high"
        return "Manual" if not home.timer else "No change"

    if home.auto and (reason := _activation_reason(config, home)):
        return reason
    return "No change"
