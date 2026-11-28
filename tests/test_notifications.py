"""Notification behaviour regression tests."""

import pytest


async def test_notifications_fire_once_on_mode_change(hass, coord_factory) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE

    calls = async_mock_service(hass, "notify", "mobile_app_test")
    coordinator = await coord_factory(options={CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"})
    await coordinator.async_run_evaluation("manual")

    assert len(calls) == 1
    assert calls[0].data["message"] == "Switched from Off to Cool"
    await coordinator.async_run_evaluation("poll")
    assert len(calls) == 1


async def test_manual_comfort_alert_is_information_only_and_survives_reload(hass, coord_factory) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE, ControlMode
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    calls = async_mock_service(hass, "notify", "mobile_app_test")
    stops = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(climate="cool", options={CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"})
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_set_control("stop_at_comfort_temperature", True)
    await coordinator.async_set_control("automatic_target_notifications", False)
    await coordinator.async_run_evaluation("poll")
    deadline = coordinator.data.timer_finishes_at
    assert deadline is not None

    for temperature in ("24", "26", "21"):
        hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
        await coordinator.async_run_evaluation("poll")

    await coordinator.async_shutdown()
    restored = HomeRulesCoordinator(hass, coordinator.config_entry)
    try:
        await restored.async_initialize()
        await restored.async_run_evaluation("poll")
        alerts = [call.data for call in calls if call.data["title"] == "Aircon comfort temperature reached"]
        assert len(alerts) == 1
        assert "Room: 24°C" in alerts[0]["message"]
        assert "data" not in alerts[0]
        assert not stops
        assert restored.data.timer_finishes_at == deadline
    finally:
        await restored.async_shutdown()


async def test_failed_manual_comfort_alert_is_retried_without_changing_deadline(hass, coord_factory) -> None:
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE, ControlMode

    attempts: list[str] = []

    async def notify(call):
        if call.data["title"] == "Aircon comfort temperature reached":
            attempts.append(call.data["message"])
            if len(attempts) == 1:
                raise HomeAssistantError("Delivery failed")

    hass.services.async_register("notify", "mobile_app_test", notify)
    coordinator = await coord_factory(climate="cool", options={CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"})
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("poll")
    deadline = coordinator.data.timer_finishes_at
    for temperature in ("unavailable", "nan", "24", "24", "24"):
        hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
        await coordinator.async_run_evaluation("poll")

    assert len(attempts) == 2
    assert all("Room: 24°C" in message for message in attempts)
    assert coordinator.data.timer_finishes_at == deadline


@pytest.mark.parametrize("notify", [False, True])
@pytest.mark.parametrize("stop", [False, True])
async def test_automatic_target_alert_is_optional_information_only(
    hass, coord_factory, virtual_climates, notify, stop
) -> None:
    from pytest_homeassistant.common import async_mock_service

    from custom_components.home_rules.const import CONF_NOTIFICATION_SERVICE, ControlMode

    notifications = async_mock_service(hass, "notify", "mobile_app_test")
    (climate,) = await virtual_climates()
    coordinator = await coord_factory(
        climate_entity=climate.entity_id, options={CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"}
    )
    coordinator.stop_at_comfort_temperature = stop
    coordinator.automatic_target_notifications = notify
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("poll")
    hass.states.async_set("sensor.temperature", "22", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")

    target_alerts = [call for call in notifications if call.data["title"] == "Aircon target reached"]
    assert len(target_alerts) == int(notify)
    assert all("data" not in call.data for call in target_alerts)
    assert (hass.states.get(climate.entity_id).state == "off") is stop
    assert coordinator.data.timer_finishes_at is None
