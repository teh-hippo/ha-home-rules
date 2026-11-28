"""Coordinator HVAC mode regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations

import pytest


async def test_execute_adjustment_updates_virtual_climate(hass, coord_factory, virtual_climates) -> None:
    """Verify solar cooling updates an actual Home Assistant climate entity."""
    from custom_components.home_rules.const import ControlMode

    climate, other_climate = await virtual_climates("Integration Test AC", "Other Test AC", target_temperature=26)
    coordinator = await coord_factory(climate_entity=climate.entity_id)
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("manual")

    state = hass.states.get(climate.entity_id)
    assert state is not None
    assert state.state == "cool"
    assert state.attributes["temperature"] == coordinator.parameters.temperature_cool
    other_state = hass.states.get(other_climate.entity_id)
    assert other_state is not None
    assert other_state.state == "off"
    assert other_state.attributes["temperature"] == 26


async def test_stale_auto_mode_self_heals_for_heat(hass, coord_factory) -> None:
    """A stale auto=True (home-rules ran cool, user then switched to HEAT) self-heals to
    auto=False and starts a manual cap instead of flipping the unit back to COOL."""
    from custom_components.home_rules.const import ControlMode
    from custom_components.home_rules.rules import HomeOutput

    commanded: list[str] = []

    async def record(call) -> None:
        commanded.append(call.data.get("hvac_mode", call.service))

    hass.services.async_register("climate", "set_hvac_mode", record)
    hass.services.async_register("climate", "set_temperature", record)
    hass.services.async_register("climate", "turn_off", record)

    # Strong free solar + heat: the old engine would have commanded COOL.
    coordinator = await coord_factory(climate="heat", generation="6000", grid="0")
    coordinator._auto_mode = True  # simulate a prior cool cycle that home-rules owned
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("manual")

    assert coordinator._auto_mode is False  # self-healed: heat is never home-rules-owned
    assert coordinator.data.adjustment is HomeOutput.TIMER  # capped, not cooled
    assert "cool" not in commanded  # never issued set_hvac_mode: cool on a heat run


async def test_manual_timer_expires_after_mode_change_and_can_start_again(
    hass, coord_factory, virtual_climates, freezer
) -> None:
    from datetime import timedelta

    from homeassistant.components.climate import HVACMode
    from homeassistant.util import dt as dt_util

    from custom_components.home_rules.const import CONF_AIRCON_TIMER_DURATION, ControlMode
    from custom_components.home_rules.rules import R_TIMER_EXPIRED

    (climate,) = await virtual_climates()
    coordinator = await coord_factory(
        climate_entity=climate.entity_id, generation="0", options={CONF_AIRCON_TIMER_DURATION: 2}
    )
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("startup")

    for _ in range(5):
        started = dt_util.utcnow()
        await hass.services.async_call(
            "climate", "set_hvac_mode", {"entity_id": climate.entity_id, "hvac_mode": HVACMode.COOL}, blocking=True
        )
        await hass.async_block_till_done()
        deadline = coordinator.data.timer_finishes_at
        assert deadline == started + timedelta(minutes=2)
        freezer.tick(timedelta(minutes=1))
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": climate.entity_id, "hvac_mode": HVACMode.DRY, "temperature": 25},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert coordinator.data.timer_finishes_at == deadline
        freezer.tick(timedelta(minutes=1))
        await coordinator.async_run_evaluation("poll")
        await hass.async_block_till_done()
        assert coordinator.last_evaluation["reason"] == R_TIMER_EXPIRED
        assert coordinator.data.timer_finishes_at is None
        assert hass.states.get(climate.entity_id).state == HVACMode.OFF


@pytest.mark.parametrize("fail", [False, True])
async def test_expired_timer_retries_if_off_not_observed(hass, coord_factory, freezer, fail) -> None:
    from datetime import timedelta

    from homeassistant.exceptions import HomeAssistantError
    from homeassistant.helpers.update_coordinator import UpdateFailed

    from custom_components.home_rules.const import CONF_AIRCON_TIMER_DURATION, ControlMode
    from custom_components.home_rules.rules import R_TIMER_EXPIRED

    attempts = 0

    async def turn_off(call) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            hass.states.async_set(call.data["entity_id"], "off")
        elif fail:
            raise HomeAssistantError("Turn-off failed")

    hass.services.async_register("climate", "turn_off", turn_off)
    coordinator = await coord_factory(climate="cool", options={CONF_AIRCON_TIMER_DURATION: 2})
    await coordinator.async_set_mode(ControlMode.AUTOMATIC)
    await coordinator.async_run_evaluation("startup")
    freezer.tick(timedelta(minutes=2))
    if fail:
        with pytest.raises(UpdateFailed) as err:
            await coordinator.async_run_evaluation("poll")
        assert str(err.value.__cause__) == "Turn-off failed"
    else:
        await coordinator.async_run_evaluation("poll")
    await coordinator.async_run_evaluation("poll")
    await hass.async_block_till_done()

    assert attempts == 2
    assert coordinator.last_evaluation["reason"] == R_TIMER_EXPIRED
    assert coordinator.data.timer_finishes_at is None
    assert hass.states.get("climate.test").state == "off"
