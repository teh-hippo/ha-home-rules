"""Coordinator HVAC mode regression tests.

These tests require Home Assistant's pytest plugin; they are skipped automatically
when running only the pure rules-engine unit tests.
"""

from __future__ import annotations


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
