"""Coordinator regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


def test_timer_countdown_sensor_is_registered() -> None:
    from custom_components.home_rules.entities import SENSORS

    assert any(description.key == "timer_finishes_at" for description in SENSORS)


async def test_dry_run_does_not_fail_on_repeated_adjustments(hass, coord_factory) -> None:
    """Dry-run mode must not trip the failed_to_change safety counter."""
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()

    for _ in range(10):
        await coordinator.async_run_evaluation("poll")
        assert coordinator.data.adjustment is HomeOutput.COOL


async def test_timer_countdown_uses_internal_timer_duration(coord_factory) -> None:
    from datetime import UTC, datetime, timedelta

    from custom_components.home_rules.const import (
        DEFAULT_AIRCON_TIMER_DURATION,
        ControlMode,
    )

    coordinator = await coord_factory(climate="cool", grid="100")
    coordinator.control_mode = ControlMode.SOLAR_COOLING
    await coordinator.async_run_evaluation("poll")
    result = coordinator.data.timer_finishes_at
    assert isinstance(result, datetime)
    expected = datetime.now(tz=UTC) + timedelta(minutes=DEFAULT_AIRCON_TIMER_DURATION)
    assert abs((result - expected).total_seconds()) < 5


async def test_timer_countdown_is_off_when_timer_idle(coord_factory) -> None:
    coordinator = await coord_factory()
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.timer_finishes_at is None


async def test_timer_adjustment_schedules_expiry_callback(coord_factory) -> None:
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory(climate="cool", grid="100")
    coordinator.control_mode = ControlMode.SOLAR_COOLING
    await coordinator.async_run_evaluation("poll")

    assert coordinator._timer_expiry_handle is not None
    await coordinator.async_shutdown()
    assert coordinator._timer_expiry_handle is None
