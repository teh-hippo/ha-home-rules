from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

ALLOWED_FAILURES = 3
_NO_ACTION_REASONS = frozenset({"Insufficient solar", "Aggressive cooling hold"})


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


class AdjustResult(NamedTuple):
    output: HomeOutput
    reason: str


def _evaluate_turn_on(config: RuleParameters, home: HomeInput) -> tuple[HomeOutput | None, str]:
    if not home.have_solar:
        return None, "No solar available"
    aggressive = home.aggressive_cooling and home.grid_usage == 0
    if home.generation >= config.generation_cool_threshold and (
        aggressive or home.humidity <= config.humidity_threshold
    ):
        if home.aircon_mode != AirconMode.COOL:
            return HomeOutput.COOL, "Solar above cool threshold"
        if home.grid_usage == 0:
            return None, "Already cooling on solar"
    if aggressive:
        return None, "Aggressive cooling hold"
    if home.generation >= config.generation_dry_threshold:
        if home.aircon_mode != AirconMode.DRY:
            return HomeOutput.DRY, "Solar above dry threshold"
        if home.grid_usage == 0:
            return None, "Already drying on solar"
    return None, "Insufficient solar"


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


def adjust(config: RuleParameters, home: HomeInput, state: CachedState) -> AdjustResult:
    """Compute the next adjustment and its human-readable reason."""
    if not home.enabled:
        state.tolerated = 0
        out = HomeOutput.NO_CHANGE if state.last is HomeOutput.DISABLED else HomeOutput.DISABLED
        return AdjustResult(out, "Disabled")
    if home.aircon_mode == AirconMode.UNKNOWN:
        return AdjustResult(HomeOutput.NO_CHANGE, "Unknown aircon mode")
    if state.reactivate_delay > 0:
        state.reactivate_delay -= 1
        return AdjustResult(HomeOutput.NO_CHANGE, "Waiting reactivate delay")

    output, reason = _evaluate_turn_on(config, home)
    activation = reason if reason not in _NO_ACTION_REASONS else None

    if home.aircon_mode == AirconMode.OFF:
        state.tolerated = 0
        if (
            home.cooling_enabled
            and home.aggressive_cooling
            and home.have_solar
            and home.generation > 0
            and home.temperature > config.temperature_cool
        ):
            return AdjustResult(HomeOutput.COOL, "Boost above cool setpoint")
        if home.cooling_enabled and home.temperature >= config.temperature_threshold and output is not None:
            return AdjustResult(output, reason)
        why = (
            "Cooling disabled"
            if not home.cooling_enabled
            else "Temperature below cool setpoint"
            if home.aggressive_cooling and home.temperature <= config.temperature_cool
            else "Temperature below threshold"
            if home.temperature < config.temperature_threshold
            else activation
        )
        if home.auto:
            return AdjustResult(HomeOutput.OFF, why or "Auto idle")
        if state.last is HomeOutput.TIMER and not home.timer:
            return AdjustResult(HomeOutput.RESET, "Timer expired")
        return AdjustResult(HomeOutput.NO_CHANGE, why or "No change")

    if not home.have_solar or home.grid_usage > 0:
        if home.auto:
            if output is not None:
                state.tolerated = 0
                return AdjustResult(output, reason)
            state.tolerated += 1
            if state.tolerated < config.grid_usage_delay:
                return AdjustResult(HomeOutput.NO_CHANGE, "Grid usage tolerated")
            state.tolerated = 0
            state.reactivate_delay = config.reactivate_delay
            return AdjustResult(HomeOutput.OFF, "Grid usage too high")
        if not home.timer:
            return AdjustResult(HomeOutput.TIMER, "Manual")
        return AdjustResult(HomeOutput.NO_CHANGE, "No change")

    if home.auto:
        state.tolerated = 0
        if output is not None:
            return AdjustResult(output, reason)
        return AdjustResult(HomeOutput.NO_CHANGE, activation or "No change")

    return AdjustResult(HomeOutput.NO_CHANGE, "No change")


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
