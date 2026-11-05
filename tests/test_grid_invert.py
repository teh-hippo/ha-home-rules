"""Grid sign inversion tests (meters that report export as positive)."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")


@pytest.mark.parametrize(
    ("grid", "invert", "expected"), [("-500", True, 500.0), ("500", True, 0.0), ("500", False, 500.0)]
)
async def test_grid_invert(coord_factory, grid: str, invert: bool, expected: float) -> None:
    from custom_components.home_rules.const import CONF_GRID_INVERT

    coordinator = await coord_factory(generation="6000", grid=grid, options={CONF_GRID_INVERT: invert})
    await coordinator.async_run_evaluation("manual")
    assert coordinator._last_record["grid_usage"] == expected
