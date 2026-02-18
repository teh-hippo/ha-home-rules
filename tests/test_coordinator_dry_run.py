"""Coordinator regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


def test_timer_countdown_sensor_is_registered() -> None:
    from custom_components.home_rules.sensor import SENSORS

    assert any(description.key == "timer_countdown" for description in SENSORS)


async def test_dry_run_does_not_fail_on_repeated_adjustments(hass, coord_factory) -> None:
    """Dry-run mode must not trip the failed_to_change safety counter."""
    from homeassistant.helpers.storage import Store

    from custom_components.home_rules.const import STORAGE_KEY_TEMPLATE, STORAGE_VERSION
    from custom_components.home_rules.coordinator import HomeRulesCoordinator
    from custom_components.home_rules.rules import HomeOutput

    coordinator = await coord_factory()

    for _ in range(10):
        await coordinator.async_run_evaluation("poll")
        assert coordinator.data.adjustment is HomeOutput.COOL

    # Verify that the old "NoChange" string stored in previous versions
    # is migrated to HomeOutput.NO_CHANGE on reload.
    key = STORAGE_KEY_TEMPLATE.format(entry_id=coordinator.config_entry.entry_id)
    store = Store(hass, STORAGE_VERSION, key)
    await store.async_save({"session": {"last": "NoChange"}})

    reloaded = HomeRulesCoordinator(hass, coordinator.config_entry)
    await reloaded.async_initialize()
    assert reloaded._session.last is HomeOutput.NO_CHANGE


async def test_timer_countdown_uses_remaining_attribute(coord_factory) -> None:
    coordinator = await coord_factory(
        timer="active",
        timer_attributes={"remaining": "0:04:59"},
    )
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.timer_countdown == "0:04:59"


async def test_timer_countdown_is_off_when_timer_idle(coord_factory) -> None:
    coordinator = await coord_factory()  # timer="idle" by default
    await coordinator.async_run_evaluation("poll")
    assert coordinator.data.timer_countdown == "Off"
