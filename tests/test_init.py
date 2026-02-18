"""Integration lifecycle tests for Home Rules."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

pytest.importorskip("pytest_homeassistant_custom_component")


async def test_setup_and_unload_entry(hass, mock_entry) -> None:
    """Config entry should set up and unload cleanly through HA lifecycle APIs."""
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state == ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_entry.state == ConfigEntryState.NOT_LOADED


async def test_setup_removes_legacy_entities(hass, mock_entry, entity_registry) -> None:
    """Setup removes legacy entities replaced by the control-mode select."""
    legacy_unique_ids = {
        f"{mock_entry.entry_id}_enabled",
        f"{mock_entry.entry_id}_aggressive_cooling",
        f"{mock_entry.entry_id}_dry_run",
        f"{mock_entry.entry_id}_notifications_enabled",
    }

    for unique_id in legacy_unique_ids:
        entity_registry.async_get_or_create(
            "switch",
            "home_rules",
            unique_id,
            suggested_object_id=f"legacy_{unique_id}",
            config_entry=mock_entry,
        )

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    for unique_id in legacy_unique_ids:
        assert entity_registry.async_get_entity_id("switch", "home_rules", unique_id) is None


async def test_options_update_triggers_reload(hass, loaded_entry) -> None:
    """Updating options should invoke the registered config entry reload listener."""
    with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as mock_reload:
        hass.config_entries.async_update_entry(loaded_entry, options={"eval_interval": 120})
        await hass.async_block_till_done()

    mock_reload.assert_awaited_once_with(loaded_entry.entry_id)
