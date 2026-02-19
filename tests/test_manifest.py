"""Manifest metadata tests."""

from __future__ import annotations

import json
from pathlib import Path


def test_manifest_classification() -> None:
    """Manifest should keep the agreed integration and IoT classification."""
    manifest_path = Path(__file__).resolve().parents[1] / "custom_components" / "home_rules" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["integration_type"] == "service"
    assert manifest["iot_class"] == "calculated"
