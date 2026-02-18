#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

UV_RUN="uv run --with-requirements requirements_test.txt"

$UV_RUN ruff check .
$UV_RUN ruff format --check .
$UV_RUN mypy custom_components tests
$UV_RUN pytest tests -q
