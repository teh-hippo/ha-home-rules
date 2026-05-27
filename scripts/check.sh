#!/usr/bin/env bash
# Local preflight — mirrors CI exactly. Run before every push.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Lint ==="
uv sync --locked

uv run --no-sync ruff check .
uv run --no-sync ruff format --check .

echo "=== Mypy ==="
uv run --no-sync mypy custom_components/home_rules tests

echo "=== Test + Coverage ==="
uv run --no-sync coverage run -m pytest tests/ -v --tb=short
uv run --no-sync coverage report --include="custom_components/home_rules/*" --fail-under=80

echo ""
echo "✅ All checks passed — safe to push."
