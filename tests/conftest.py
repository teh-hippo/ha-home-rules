"""Test fixtures for Home Rules.

This repo includes pure unit tests (rules engine) and HA integration tests.
Locally, you may not have the HA pytest plugin installed, so keep fixtures optional.
"""

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ModuleNotFoundError:
    # Unit tests (e.g., rules engine) can run without HA.
    pass
else:

    @pytest.fixture(autouse=True)
    def _enable_custom_integrations(enable_custom_integrations):
        """Enable custom component loading in HA tests."""
