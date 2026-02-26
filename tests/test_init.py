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
    legacy_entities = {
        ("switch", f"{mock_entry.entry_id}_enabled"),
        ("switch", f"{mock_entry.entry_id}_aggressive_cooling"),
        ("switch", f"{mock_entry.entry_id}_dry_run"),
        ("switch", f"{mock_entry.entry_id}_notifications_enabled"),
        ("switch", f"{mock_entry.entry_id}_generation_cool_threshold"),
        ("switch", f"{mock_entry.entry_id}_generation_dry_threshold"),
        ("sensor", f"{mock_entry.entry_id}_timer_countdown"),
        ("sensor", f"{mock_entry.entry_id}_current"),
    }

    for platform, unique_id in legacy_entities:
        entity_registry.async_get_or_create(
            platform,
            "home_rules",
            unique_id,
            suggested_object_id=f"legacy_{unique_id}",
            config_entry=mock_entry,
        )

    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    for platform, unique_id in legacy_entities:
        assert entity_registry.async_get_entity_id(platform, "home_rules", unique_id) is None


async def test_migrate_entry_removes_legacy_timer_entity_id(hass) -> None:
    """Entry migration removes stale timer_entity_id from data and options."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.home_rules import async_migrate_entry
    from custom_components.home_rules.const import DOMAIN, LEGACY_CONF_TIMER_ENTITY_ID

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={LEGACY_CONF_TIMER_ENTITY_ID: "timer.legacy"},
        options={LEGACY_CONF_TIMER_ENTITY_ID: "timer.legacy"},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)
    assert LEGACY_CONF_TIMER_ENTITY_ID not in entry.data
    assert LEGACY_CONF_TIMER_ENTITY_ID not in entry.options
    assert entry.minor_version == 2


async def test_options_update_triggers_reload(hass, loaded_entry) -> None:
    """Updating options should invoke the registered config entry reload listener."""
    with patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as mock_reload:
        hass.config_entries.async_update_entry(loaded_entry, options={"eval_interval": 120})
        await hass.async_block_till_done()

    mock_reload.assert_awaited_once_with(loaded_entry.entry_id)


async def test_setup_retry_for_unavailable_required_entity_does_not_create_runtime_issue(hass, mock_entry) -> None:
    """Unavailable required entities during startup should retry setup without runtime repair issues."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.home_rules.const import DOMAIN, ISSUE_RUNTIME

    hass.states.async_set("climate.test", "unavailable")
    assert await hass.config_entries.async_setup(mock_entry.entry_id) is False
    await hass.async_block_till_done()
    assert mock_entry.state == ConfigEntryState.SETUP_RETRY

    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, f"{mock_entry.entry_id}_{ISSUE_RUNTIME}") is None
