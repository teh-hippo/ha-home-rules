"""Test fixtures for Home Rules."""

from typing import Any

import pytest


@pytest.fixture
async def virtual_climates(hass):
    """Create stateful virtual climate entities through Home Assistant's climate platform."""
    from homeassistant.components.climate import (
        ATTR_HVAC_MODE,
        ATTR_TEMPERATURE,
        ClimateEntity,
        ClimateEntityFeature,
        HVACMode,
    )
    from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
    from homeassistant.const import UnitOfTemperature
    from homeassistant.setup import async_setup_component
    from homeassistant.util import slugify
    from pytest_homeassistant.common import setup_test_component_platform

    class VirtualClimate(ClimateEntity):
        """Stateful climate entity for integration tests."""

        _attr_should_poll = False
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        _attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
        )
        _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL, HVACMode.DRY]

        def __init__(self, name: str, hvac_mode: HVACMode, target_temperature: float) -> None:
            self._attr_name = name
            self._attr_unique_id = f"virtual_{slugify(name)}"
            self.entity_id = f"{CLIMATE_DOMAIN}.{slugify(name)}"
            self._attr_hvac_mode = hvac_mode
            self._attr_native_current_temperature = 25.0
            self._attr_native_target_temperature = target_temperature

        async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
            self._attr_hvac_mode = hvac_mode
            self.async_write_ha_state()

        async def async_set_temperature(self, **kwargs: Any) -> None:
            if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
                self._attr_native_target_temperature = float(temperature)
            if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
                self._attr_hvac_mode = HVACMode(hvac_mode)
            self.async_write_ha_state()

    async def _create(
        *names: str,
        hvac_mode: HVACMode = HVACMode.OFF,
        target_temperature: float = 22.0,
    ) -> list[VirtualClimate]:
        entities = [VirtualClimate(name, hvac_mode, target_temperature) for name in (names or ("Virtual AC",))]
        setup_test_component_platform(hass, CLIMATE_DOMAIN, entities)
        assert await async_setup_component(
            hass,
            CLIMATE_DOMAIN,
            {CLIMATE_DOMAIN: {"platform": "test"}},
        )
        await hass.async_block_till_done()
        return entities

    return _create


@pytest.fixture
async def coord_factory(hass):
    """Factory fixture: creates an initialized HomeRulesCoordinator with configurable HA states.

    Usage::

        async def test_something(coord_factory) -> None:
            coordinator = await coord_factory()           # default high-solar scenario
            coordinator = await coord_factory(generation="0")  # no solar

    Coordinators are shut down on teardown so scheduled timers do not linger
    past the test, mirroring config-entry unload.
    """
    from pytest_homeassistant.common import MockConfigEntry

    from custom_components.home_rules.const import (
        CONF_CLIMATE_ENTITY_ID,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_TEMPERATURE_ENTITY_ID,
        DOMAIN,
    )
    from custom_components.home_rules.coordinator import HomeRulesCoordinator

    created: list[HomeRulesCoordinator] = []

    async def _make(
        *,
        generation: str = "6000",
        grid: str = "0",
        temperature: str = "25",
        humidity: str = "40",
        climate: str = "off",
        climate_entity: str = "climate.test",
        options: dict | None = None,
        extra_data: dict | None = None,
    ) -> HomeRulesCoordinator:
        if hass.states.get(climate_entity) is None:
            hass.states.async_set(climate_entity, climate)
        hass.states.async_set("sensor.generation", generation, {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.grid", grid, {"unit_of_measurement": "W"})
        hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
        hass.states.async_set("sensor.humidity", humidity, {"unit_of_measurement": "%"})

        data: dict[str, Any] = {
            CONF_CLIMATE_ENTITY_ID: climate_entity,
            CONF_GENERATION_ENTITY_ID: "sensor.generation",
            CONF_GRID_ENTITY_ID: "sensor.grid",
            CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
            CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        }
        data.update(extra_data or {})
        entry = MockConfigEntry(domain=DOMAIN, data=data, options=options or {})
        entry.add_to_hass(hass)
        coordinator = HomeRulesCoordinator(hass, entry)
        await coordinator.async_initialize()
        created.append(coordinator)
        return coordinator

    yield _make

    for coordinator in created:
        await coordinator.async_shutdown()


@pytest.fixture
def mock_entry(hass):
    """Create a MockConfigEntry with default Home Rules input entities."""
    from pytest_homeassistant.common import MockConfigEntry

    from custom_components.home_rules.const import (
        CONF_CLIMATE_ENTITY_ID,
        CONF_GENERATION_ENTITY_ID,
        CONF_GRID_ENTITY_ID,
        CONF_HUMIDITY_ENTITY_ID,
        CONF_TEMPERATURE_ENTITY_ID,
        DOMAIN,
    )

    hass.states.async_set("climate.test", "off")
    hass.states.async_set("sensor.generation", "6000", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.grid", "0", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.temperature", "25", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.humidity", "40", {"unit_of_measurement": "%"})

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_CLIMATE_ENTITY_ID: "climate.test",
            CONF_GENERATION_ENTITY_ID: "sensor.generation",
            CONF_GRID_ENTITY_ID: "sensor.grid",
            CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
            CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def loaded_entry(hass, mock_entry):
    """Set up Home Rules through the config entry lifecycle."""
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry
