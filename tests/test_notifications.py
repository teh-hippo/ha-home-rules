"""Notification behavior regression tests."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_notifications_fire_on_mode_change(hass) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

    from custom_components.home_rules.const import (
        CONF_CLIMATE_ENTITY_ID,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_NOTIFICATION_SERVICE,
        CONF_TEMPERATURE_ENTITY_ID,
        CONF_TIMER_ENTITY_ID,
        DOMAIN,
    )
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    calls = async_mock_service(hass, "notify", "mobile_app_test")

    hass.states.async_set("climate.test", "off")
    hass.states.async_set("timer.test", "idle")
    hass.states.async_set("sensor.generation", "6000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.temperature", "25", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.humidity", "40", {"unit_of_measurement": "%"})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CLIMATE_ENTITY_ID: "climate.test",
            CONF_TIMER_ENTITY_ID: "timer.test",
            CONF_GENERATION_ENTITY_ID: "sensor.generation",
            CONF_GRID_ENTITY_ID: "sensor.grid",
            CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
            CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        },
        options={CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"},
    )
    entry.add_to_hass(hass)

    coordinator = HomeRulesCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_set_control("notifications_enabled", True)

    assert len(calls) == 1

    # Re-evaluations while the desired mode hasn't changed should not spam notifications.
    for _ in range(5):
        await coordinator._evaluate("poll")

    assert len(calls) == 1
