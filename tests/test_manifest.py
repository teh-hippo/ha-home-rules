"""Manifest metadata tests."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_classifies_home_rules_as_service() -> None:
    """Home Rules should be discoverable under integrations, not helpers."""
    manifest_path = Path(__file__).resolve().parents[1] / "custom_components" / "home_rules" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["integration_type"] == "service"
