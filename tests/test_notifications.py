"""Notification behavior regression tests."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_notifications_fire_on_mode_change(hass, coord_factory) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE

    calls = async_mock_service(hass, "notify", "mobile_app_test")

    coordinator = await coord_factory(
        options={CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"},
    )
    await coordinator.async_run_evaluation("manual")

    assert len(calls) == 1

    # Re-evaluations while the desired mode hasn't changed should not spam notifications.
    for _ in range(5):
        await coordinator.async_run_evaluation("poll")

    assert len(calls) == 1
