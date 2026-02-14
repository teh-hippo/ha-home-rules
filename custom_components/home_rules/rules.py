"""Pure decision engine for Home Rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

ALLOWED_FAILURES = 3


class AirconMode(StrEnum):
    """Known aircon modes."""

    DRY = "dry"
    COOL = "cool"
    HEAT = "heat"
    HEAT_COOL = "heat_cool"
    FAN_ONLY = "fan_only"
    OFF = "off"
    UNKNOWN = "unknown"


class HomeOutput(StrEnum):
    """Decision engine output modes."""

    NO_CHANGE = "NoChange"
    OFF = "Off"
    COOL = "Cool"
    DRY = "Dry"
    TIMER = "Timer"
    DISABLED = "Disabled"
    RESET = "Reset"


@dataclass
class HomeInput:
    """Current home state required by the rule engine."""

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
    """Configurable thresholds and delays."""

    generation_cool_threshold: float
    generation_dry_threshold: float
    temperature_threshold: float
    humidity_threshold: float
    grid_usage_delay: int
    reactivate_delay: int
    temperature_cool: float


@dataclass
class CachedState:
    """Persisted decision session state."""

    reactivate_delay: int = 0
    tolerated: int = 0
    last: HomeOutput | None = None
    failed_to_change: int = 0


def turn_on_aircon(config: RuleParameters, home: HomeInput) -> HomeOutput | None:
    """Return desired activation mode when aircon should turn on or change mode."""
    if not home.have_solar:
        return None

    aggressive_cooling_active = home.aggressive_cooling and home.grid_usage == 0

    if home.generation >= config.generation_cool_threshold and (
        aggressive_cooling_active or home.humidity <= config.humidity_threshold
    ):
        if home.aircon_mode != AirconMode.COOL:
            return HomeOutput.COOL
        if home.grid_usage == 0:
            return None

    if aggressive_cooling_active:
        return None

    if home.generation >= config.generation_dry_threshold:
        if home.aircon_mode != AirconMode.DRY:
            return HomeOutput.DRY
        if home.grid_usage == 0:
            return None

    return None


def current_state(home: HomeInput) -> HomeOutput:
    """Map current input to high-level state."""
    if not home.enabled:
        return HomeOutput.DISABLED

    if home.timer and home.aircon_mode != AirconMode.OFF:
        return HomeOutput.TIMER

    if home.aircon_mode == AirconMode.COOL:
        return HomeOutput.COOL
    if home.aircon_mode == AirconMode.DRY:
        return HomeOutput.DRY
    if home.aircon_mode in (AirconMode.OFF, AirconMode.UNKNOWN):
        return HomeOutput.OFF

    return HomeOutput.COOL


def adjust(config: RuleParameters, home: HomeInput, state: CachedState) -> HomeOutput:
    """Evaluate desired adjustment from current state and config."""
    if not home.enabled:
        state.tolerated = 0
        if state.last is HomeOutput.DISABLED:
            return HomeOutput.NO_CHANGE
        return HomeOutput.DISABLED

    if home.aircon_mode == AirconMode.UNKNOWN:
        return HomeOutput.NO_CHANGE

    if state.reactivate_delay > 0:
        state.reactivate_delay -= 1
        return HomeOutput.NO_CHANGE

    if home.aircon_mode == AirconMode.OFF:
        state.tolerated = 0
        if home.cooling_enabled and home.temperature >= config.temperature_threshold:
            change = turn_on_aircon(config, home)
            if change is not None:
                return change

        if home.auto:
            return HomeOutput.OFF

        if state.last is HomeOutput.TIMER and not home.timer:
            return HomeOutput.RESET

    elif not home.have_solar or home.grid_usage > 0:
        if home.auto:
            change = turn_on_aircon(config, home)
            if change is not None:
                state.tolerated = 0
                return change

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
        change = turn_on_aircon(config, home)
        if change is not None:
            return change

    return HomeOutput.NO_CHANGE


def apply_adjustment(session: CachedState, current: HomeOutput, adjustment: HomeOutput) -> bool:
    """Update session state after applying adjustment and return success."""
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
    """Return a short, human-readable explanation for the next adjustment.

    This function is pure (does not mutate ``state``) and is intended for HA UI/history.
    """

    def turn_on_reason() -> str:
        if not home.have_solar:
            return "No solar available"

        aggressive_cooling_active = home.aggressive_cooling and home.grid_usage == 0

        if home.generation >= config.generation_cool_threshold and (
            aggressive_cooling_active or home.humidity <= config.humidity_threshold
        ):
            if home.aircon_mode != AirconMode.COOL:
                return "Solar above cool threshold"
            if home.grid_usage == 0:
                return "Already cooling on solar"

        if aggressive_cooling_active:
            return "Aggressive cooling hold"

        if home.generation >= config.generation_dry_threshold:
            if home.aircon_mode != AirconMode.DRY:
                return "Solar above dry threshold"
            if home.grid_usage == 0:
                return "Already drying on solar"

        return "Insufficient solar"

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

        reason = turn_on_reason()
        if reason not in {"Insufficient solar", "Aggressive cooling hold"}:
            return reason

        if home.auto:
            return "Auto idle"

        if state.last is HomeOutput.TIMER and not home.timer:
            return "Timer cleared (reset)"

        return "No change"

    # Aircon running (or timer/manual states).
    if not home.have_solar or home.grid_usage > 0:
        if home.auto:
            reason = turn_on_reason()
            if reason not in {"Insufficient solar", "Aggressive cooling hold"}:
                return reason

            if (state.tolerated + 1) < config.grid_usage_delay:
                return "Grid usage tolerated"
            return "Grid usage too high (turn off)"

        if not home.timer:
            return "Manual mode (start timer)"

        return "No change"

    if home.auto:
        reason = turn_on_reason()
        if reason not in {"Insufficient solar", "Aggressive cooling hold"}:
            return reason

    return "No change"
