#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f ".venv/bin/activate" ]; then
  echo "ERROR: .venv not found. Create it first (see CONTRIBUTING.md)." >&2
  exit 2
fi

source .venv/bin/activate

ruff check .
ruff format --check .
mypy custom_components tests
pytest tests -q

