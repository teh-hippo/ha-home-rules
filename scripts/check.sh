#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

UV_RUN="uv run --with-requirements requirements_test.txt"

$UV_RUN python - <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path("custom_components/home_rules/manifest.json")
manifest = json.loads(manifest_path.read_text())
keys = list(manifest)
expected = ["domain", "name"] + sorted(k for k in manifest if k not in {"domain", "name"})

if keys != expected:
    print(f"Manifest keys are not sorted as hassfest expects: {manifest_path}")
    print(f"Current:  {keys}")
    print(f"Expected: {expected}")
    sys.exit(1)
PY

$UV_RUN ruff check .
$UV_RUN ruff format --check .
$UV_RUN mypy custom_components tests
$UV_RUN pytest tests -q
