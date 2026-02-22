"""Test fixtures for Home Rules.

This repo includes pure unit tests (rules engine) and HA integration tests.
Locally, you may not have the HA pytest plugin installed, so keep fixtures optional.
"""

import pytest

try:
    from typing import Any

    import pytest_homeassistant_custom_component  # noqa: F401
except ModuleNotFoundError:
    # Unit tests (e.g., rules engine) can run without HA.
    pass
else:

    @pytest.fixture(autouse=True)
    def _enable_custom_integrations(enable_custom_integrations):
        """Enable custom component loading in HA tests."""

    @pytest.fixture
    def coord_factory(hass):
        """Factory fixture: creates an initialized HomeRulesCoordinator with configurable HA states.

        Usage::

            async def test_something(coord_factory) -> None:
                coordinator = await coord_factory()           # default high-solar scenario
                coordinator = await coord_factory(generation="0")  # no solar
        """
        from pytest_homeassistant_custom_component.common import MockConfigEntry

        from custom_components.home_rules.const import (
            CONF_CLIMATE_ENTITY_ID,
            CONF_GENERATION_ENTITY_ID,
            CONF_GRID_ENTITY_ID,
            CONF_HUMIDITY_ENTITY_ID,
            CONF_INVERTER_ENTITY_ID,
            CONF_TEMPERATURE_ENTITY_ID,
            DOMAIN,
        )
        from custom_components.home_rules.coordinator import HomeRulesCoordinator

        async def _make(
            *,
            generation: str = "6000",
            grid: str = "0",
            temperature: str = "25",
            humidity: str = "40",
            climate: str = "off",
            inverter: str | None = None,
            options: dict | None = None,
            extra_data: dict | None = None,
        ) -> HomeRulesCoordinator:
            hass.states.async_set("climate.test", climate)
            hass.states.async_set("sensor.generation", generation, {"unit_of_measurement": "W"})
            hass.states.async_set("sensor.grid", grid, {"unit_of_measurement": "W"})
            hass.states.async_set("sensor.temperature", temperature, {"unit_of_measurement": "°C"})
            hass.states.async_set("sensor.humidity", humidity, {"unit_of_measurement": "%"})

            data: dict[str, Any] = {
                CONF_CLIMATE_ENTITY_ID: "climate.test",
                CONF_GENERATION_ENTITY_ID: "sensor.generation",
                CONF_GRID_ENTITY_ID: "sensor.grid",
                CONF_TEMPERATURE_ENTITY_ID: "sensor.temperature",
                CONF_HUMIDITY_ENTITY_ID: "sensor.humidity",
            }
            if inverter is not None:
                hass.states.async_set("sensor.inverter", inverter)
                data[CONF_INVERTER_ENTITY_ID] = "sensor.inverter"
            data.update(extra_data or {})
            entry = MockConfigEntry(domain=DOMAIN, data=data, options=options or {})
            entry.add_to_hass(hass)
            coordinator = HomeRulesCoordinator(hass, entry)
            await coordinator.async_initialize()
            return coordinator

        return _make

    @pytest.fixture
    def mock_entry(hass):
        """Create a MockConfigEntry with default Home Rules input entities."""
        from pytest_homeassistant_custom_component.common import MockConfigEntry

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
