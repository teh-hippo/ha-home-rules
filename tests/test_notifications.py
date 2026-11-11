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
    assert calls[0].data["title"] == "❄️ Aircon → Cool"
    assert calls[0].data["message"] == "Switched from Off to Cool"
    for _ in range(5):
        await coordinator.async_run_evaluation("poll")
    assert len(calls) == 1


@pytest.fixture
async def manual_timer(hass, coord_factory):
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import (
        CONF_BATTERY_POWER_ENTITY_ID,
        CONF_NOTIFICATION_SERVICE,
        ControlMode,
    )

    notifications = async_mock_service(hass, "notify", "mobile_app_test")
    off_calls = async_mock_service(hass, "climate", "turn_off")
    hass.states.async_set("sensor.battery", "1600", {"unit_of_measurement": "W"})
    coordinator = await coord_factory(
        climate="cool",
        generation="0",
        options={
            CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test",
            CONF_BATTERY_POWER_ENTITY_ID: "sensor.battery",
        },
    )
    await coordinator.async_set_mode(ControlMode.BOOST_COOLING)
    return coordinator, notifications, off_calls


async def test_timer_target_prompt_once_without_changing_deadline(hass, manual_timer) -> None:
    coordinator, notifications, off_calls = manual_timer
    deadline, changed = coordinator.data.timer_finishes_at, coordinator.data.last_changed
    assert len(notifications) == 1

    hass.states.async_set("sensor.temperature", "22", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")

    assert notifications[-1].data["title"] == "Aircon target reached"
    assert [a["title"] for a in notifications[-1].data["data"]["actions"]] == ["Turn off", "Keep running", "5 mins"]
    for temperature in ("21.8", "23", "21.9"):
        hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
        await coordinator.async_run_evaluation("poll")

    assert len(notifications) == 2
    assert not off_calls
    assert coordinator.data.timer_finishes_at == deadline
    assert coordinator.data.last_changed == changed


@pytest.mark.parametrize(("choice", "remaining"), [("off", 45), ("keep", 45), ("five", 45), ("five", 2)])
async def test_timer_notification_response(hass, manual_timer, monkeypatch, choice, remaining) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.const import EVENT_NOTIFICATION_ACTION
    from custom_components.home_rules.rules import HomeOutput

    coordinator, notifications, off_calls = manual_timer
    now = dt_util.utcnow()
    monkeypatch.setattr(dt_util, "utcnow", lambda: now)
    deadline = now + timedelta(minutes=remaining)
    coordinator._aircon_timer_finishes_at = deadline
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    action = next(a["action"] for a in notifications[-1].data["data"]["actions"] if a["action"].endswith(f"_{choice}"))

    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
    await hass.async_block_till_done()

    if choice == "off":
        assert len(off_calls) == 1
        assert coordinator.data.mode is HomeOutput.OFF
        assert coordinator.data.timer_finishes_at is None
    else:
        assert not off_calls
        assert coordinator.data.mode is HomeOutput.TIMER
        expected = min(deadline, now + timedelta(minutes=5)) if choice == "five" else deadline
        assert coordinator.data.timer_finishes_at == expected

    count = len(notifications)
    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
    await hass.async_block_till_done()
    assert len(notifications) == count
    assert len(off_calls) == (1 if choice == "off" else 0)
    assert coordinator._timer_prompt_id is None


async def test_ignored_target_prompt_still_expires_at_original_deadline(hass, manual_timer, monkeypatch) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.rules import HomeOutput

    coordinator, _, off_calls = manual_timer
    deadline = coordinator.data.timer_finishes_at
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    monkeypatch.setattr(dt_util, "utcnow", lambda: deadline + timedelta(seconds=1))
    await coordinator.async_run_evaluation("timer_expired")

    assert len(off_calls) == 1
    assert coordinator.data.mode is HomeOutput.OFF
    assert coordinator._last_record["reason"] == "Timer expired"
    assert coordinator.data.timer_finishes_at is None


@pytest.mark.parametrize("choice", ["keep", "five"])
async def test_response_at_expiry_still_turns_off_without_waiting_for_poll(
    hass, manual_timer, monkeypatch, choice
) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.const import EVENT_NOTIFICATION_ACTION
    from custom_components.home_rules.rules import HomeOutput

    coordinator, notifications, off_calls = manual_timer
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    action = next(a["action"] for a in notifications[-1].data["data"]["actions"] if a["action"].endswith(f"_{choice}"))
    deadline = coordinator.data.timer_finishes_at
    monkeypatch.setattr(dt_util, "utcnow", lambda: deadline + timedelta(seconds=1))
    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
    await hass.async_block_till_done()

    assert len(off_calls) == 1
    assert coordinator.data.mode is HomeOutput.OFF
    assert coordinator._last_record["reason"] == "Timer expired"
    assert coordinator.data.timer_finishes_at is None
    assert coordinator._timer_expiry_handle is None


async def test_failed_target_notification_is_persisted_as_unsent_and_retried(hass, manual_timer) -> None:
    from homeassistant.exceptions import HomeAssistantError

    coordinator, _, off_calls = manual_timer
    deadline = coordinator.data.timer_finishes_at
    assert deadline is not None
    failed = True
    attempts: list[object] = []

    async def notify(call):
        attempts.append(call)
        if failed:
            raise HomeAssistantError("Delivery failed")

    hass.services.async_register("notify", "mobile_app_test", notify)
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    stored = await coordinator._store.async_load()

    assert stored is not None
    assert not stored["timer_target_notified"]
    assert stored["timer_prompt_id"] is None
    assert stored["aircon_timer_finishes_at"] == deadline.isoformat()
    assert not off_calls

    failed = False
    await coordinator.async_run_evaluation("poll")
    await coordinator.async_run_evaluation("poll")
    assert len(attempts) == 2
    assert coordinator._timer_target_notified
    assert coordinator.data.timer_finishes_at == deadline


async def test_target_prompt_and_response_survive_restart(hass, manual_timer) -> None:
    from custom_components.home_rules.const import EVENT_NOTIFICATION_ACTION
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    coordinator, notifications, off_calls = manual_timer
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    action = notifications[-1].data["data"]["actions"][0]["action"]
    deadline = coordinator.data.timer_finishes_at
    await coordinator.async_shutdown()

    restored = HomeRulesCoordinator(hass, coordinator.config_entry)
    try:
        await restored.async_initialize()
        await restored.async_run_evaluation("restart")
        assert len(notifications) == 2
        assert restored.data.timer_finishes_at == deadline
        hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
        await hass.async_block_till_done()
        assert len(off_calls) == 1
        assert restored.data.timer_finishes_at is None
    finally:
        await restored.async_shutdown()


async def test_old_target_prompt_cannot_control_new_timer(hass, manual_timer) -> None:
    from custom_components.home_rules.const import EVENT_NOTIFICATION_ACTION

    coordinator, notifications, off_calls = manual_timer
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    old_action = notifications[-1].data["data"]["actions"][0]["action"]
    hass.states.async_set("climate.test", "off")
    await coordinator.async_run_evaluation("poll")
    hass.states.async_set("climate.test", "cool")
    await coordinator.async_run_evaluation("poll")
    new_action = notifications[-1].data["data"]["actions"][0]["action"]
    deadline = coordinator.data.timer_finishes_at

    assert new_action != old_action
    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": old_action})
    await hass.async_block_till_done()
    assert not off_calls
    assert coordinator.data.timer_finishes_at == deadline


@pytest.mark.parametrize("mode", ["monitor", "disabled"])
async def test_target_prompt_cannot_control_inactive_integration(hass, manual_timer, mode) -> None:
    from custom_components.home_rules.const import EVENT_NOTIFICATION_ACTION, ControlMode

    coordinator, notifications, off_calls = manual_timer
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    action = notifications[-1].data["data"]["actions"][0]["action"]
    await coordinator.async_set_mode(ControlMode(mode))
    deadline = coordinator.data.timer_finishes_at
    hass.bus.async_fire(EVENT_NOTIFICATION_ACTION, {"action": action})
    await hass.async_block_till_done()

    assert not off_calls
    assert coordinator.data.timer_finishes_at == deadline


@pytest.mark.parametrize("temperature", ["unavailable", "nan"])
async def test_unavailable_temperature_does_not_prompt(hass, manual_timer, temperature) -> None:
    coordinator, notifications, off_calls = manual_timer
    hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")
    assert len(notifications) == 1
    assert not off_calls


@pytest.mark.parametrize(("behaviour", "stops"), [("timer", False), ("stop", True)])
async def test_manual_timer_non_interactive_modes(hass, coord_factory, behaviour, stops) -> None:
    from pytest_homeassistant_custom_component.common import async_mock_service

    from custom_components.home_rules.const import (
        CONF_MANUAL_COOLING_BEHAVIOUR,
        CONF_NOTIFICATION_SERVICE,
        ControlMode,
    )

    notifications = async_mock_service(hass, "notify", "mobile_app_test")
    off_calls = async_mock_service(hass, "climate", "turn_off")
    coordinator = await coord_factory(
        climate="cool",
        generation="0",
        options={CONF_MANUAL_COOLING_BEHAVIOUR: behaviour, CONF_NOTIFICATION_SERVICE: "notify.mobile_app_test"},
    )
    await coordinator.async_set_mode(ControlMode.BOOST_COOLING)
    deadline = coordinator.data.timer_finishes_at
    hass.states.async_set("sensor.temperature", "21.8", {"unit_of_measurement": "°C"})
    await coordinator.async_run_evaluation("poll")

    assert bool(off_calls) is stops
    assert coordinator.data.timer_finishes_at == (None if stops else deadline)
    assert all("data" not in call.data for call in notifications)
