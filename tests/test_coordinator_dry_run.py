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


async def test_monitor_timer_runs_for_configured_duration_without_climate_calls(coord_factory) -> None:
    from datetime import timedelta
    from unittest.mock import AsyncMock, patch

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.const import CONF_AIRCON_TIMER_DURATION
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(climate="cool", grid="100", options={CONF_AIRCON_TIMER_DURATION: 90})
    now = dt_util.utcnow()
    with (
        patch.object(coordinator, "_call_service", new_callable=AsyncMock) as call_service,
        patch("custom_components.home_rules.coordinator.dt_util.utcnow", return_value=now) as utcnow,
    ):
        await coordinator.async_run_evaluation("poll")
        initial = coordinator.data
        deadline = initial.timer_finishes_at
        assert initial.adjustment is HomeOutput.TIMER
        assert deadline == now + timedelta(minutes=90)
        assert coordinator._timer_expiry_handle is not None

        for minutes in (5, 60, 89):
            utcnow.return_value = now + timedelta(minutes=minutes)
            await coordinator.async_run_evaluation("poll")
            current = coordinator.data
            assert current.adjustment is HomeOutput.NO_CHANGE
            assert current.mode is HomeOutput.TIMER
            assert current.timer_finishes_at == deadline

        utcnow.return_value = now + timedelta(minutes=90)
        await coordinator.async_run_evaluation("timer_expired")
        expired = coordinator.data
        assert expired.adjustment is HomeOutput.OFF
        assert coordinator._last_record["reason"] == "Timer expired"
        assert expired.timer_finishes_at is None
        assert coordinator._timer_expiry_handle is None
        call_service.assert_not_awaited()


async def test_timer_adjustment_schedules_expiry_callback(coord_factory) -> None:
    from custom_components.home_rules.const import ControlMode

    coordinator = await coord_factory(climate="cool", grid="100")
    coordinator.control_mode = ControlMode.SOLAR_COOLING
    await coordinator.async_run_evaluation("poll")

    assert coordinator._timer_expiry_handle is not None
    await coordinator.async_shutdown()
    assert coordinator._timer_expiry_handle is None


async def test_monitor_timer_preserves_deadline_when_enabling_solar_cooling(coord_factory) -> None:
    from unittest.mock import AsyncMock, patch

    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory(climate="cool", grid="100")
    with patch.object(coordinator, "_call_service", new_callable=AsyncMock) as call_service:
        await coordinator.async_run_evaluation("poll")
        deadline = coordinator.data.timer_finishes_at
        assert deadline is not None

        await coordinator.async_set_mode(ControlMode.SOLAR_COOLING)
        assert coordinator.data.mode is HomeOutput.TIMER
        assert coordinator.data.adjustment is HomeOutput.NO_CHANGE
        assert coordinator.data.timer_finishes_at == deadline
        call_service.assert_not_awaited()
