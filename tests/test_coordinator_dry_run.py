"""Coordinator regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


def test_timer_countdown_sensor_is_registered() -> None:
    from custom_components.home_rules.sensor import SENSORS

    assert any(description.key == "timer_finishes_at" for description in SENSORS)


async def test_dry_run_does_not_fail_on_repeated_adjustments(hass, coord_factory) -> None:
    """Dry-run mode must not trip the failed_to_change safety counter."""
    from homeassistant.helpers.storage import Store

    from custom_components.home_rules.const import DOMAIN, STORAGE_VERSION
    from custom_components.home_rules.coordinator import HomeRulesCoordinator
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()

    for _ in range(10):
        await coordinator.async_run_evaluation("poll")
        assert coordinator.data.adjustment is HomeOutput.COOL

    # Verify that the old "NoChange" string stored in previous versions
    # is migrated to HomeOutput.NO_CHANGE on reload.
    key = f"{DOMAIN}_{coordinator.config_entry.entry_id}"
    store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, key)
    await store.async_save({"session": {"last": "NoChange"}})

    reloaded = HomeRulesCoordinator(hass, coordinator.config_entry)
    await reloaded.async_initialize()
    assert reloaded._session.last is HomeOutput.NO_CHANGE


async def test_timer_countdown_uses_remaining_attribute(coord_factory) -> None:
    from datetime import UTC, datetime, timedelta

    coordinator = await coord_factory(
        timer="active",
        timer_attributes={"remaining": "0:04:59"},
    )
    await coordinator.async_run_evaluation("poll")
    result = coordinator.data.timer_finishes_at
    assert isinstance(result, datetime)
    expected = datetime.now(tz=UTC) + timedelta(minutes=4, seconds=59)
    assert abs((result - expected).total_seconds()) < 5


async def test_timer_countdown_is_off_when_timer_idle(coord_factory) -> None:
    coordinator = await coord_factory()  # timer="idle" by default
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.timer_finishes_at is None
