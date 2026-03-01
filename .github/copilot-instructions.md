# Copilot instructions for this repository

## Build, test, and lint commands

- Install/update dev dependencies: `uv sync --group dev`
- Full local preflight (mirrors CI lint/mypy/pytest+coverage): `bash scripts/check.sh`
- Lint only:
  - `uv run ruff check .`
  - `uv run ruff format --check .`
- Type-check only: `uv run mypy custom_components/home_rules tests`
- Test suite with coverage gate:
  - `uv run coverage run -m pytest tests/ -v --tb=short`
  - `uv run coverage report --include="custom_components/home_rules/*" --fail-under=80`
- Run a single test reliably from the full tests root:
  - `uv run pytest tests/ -k test_adjust_disabled_state -v --tb=short`

## High-level architecture

- **Home Assistant entry lifecycle** is in `custom_components/home_rules/__init__.py`:
  - `async_setup_entry` creates `HomeRulesCoordinator`, runs first refresh, stores it in `entry.runtime_data`, and forwards setup for all platforms.
  - `async_migrate_entry` removes legacy `timer_entity_id` from both `entry.data` and `entry.options`.
  - Setup also removes legacy entity registry entries by unique_id suffix.
- **Configuration flow and options** are in `custom_components/home_rules/config_flow.py`:
  - Initial setup is multi-step (`user -> solar -> comfort`).
  - Options flow owns thresholds, delays, notification service, and aircon timer duration.
  - Entity validation rejects selecting this integration's own entities and validates power units.
- **Decision engine split**:
  - `custom_components/home_rules/rules.py` is the pure rules engine (`adjust`, `current_state`, `apply_adjustment`) over `HomeInput`, `RuleParameters`, and cached state.
  - `custom_components/home_rules/coordinator.py` handles HA I/O: state reads, unit normalization, service calls, timer scheduling, persistence, event firing, and issue creation.
- **Entity model**:
  - All entity descriptions and implementations live in `custom_components/home_rules/entities.py`.
  - Platform files (`sensor.py`, `switch.py`, etc.) are thin re-export shims that delegate setup to `entities.py`.
  - Decision diagnostics are exposed through `sensor.home_rules_decision` attributes (`_last_record` + recent evaluations).
- **State persistence and timer model**:
  - Coordinator persists controls/session/history/parameter overrides via `homeassistant.helpers.storage.Store`.
  - Timer is integration-owned (`_aircon_timer_finishes_at`) and no `timer.*` helper entity is required.

## Key conventions specific to this codebase

- Prefer root-cause refactors over band-aid fixes. Do not patch a single function in isolation when the behavior spans config flow, coordinator, rules, entities, diagnostics, translations, and tests.
- Review changes holistically across lifecycle paths (startup refresh, poll evaluations, manual evaluate button, timer expiry callbacks, options reload, and persisted state migration) before finalizing.
- Core runtime files intentionally use a compact one-line style (`# fmt: off` + `ruff: noqa: E501,E701,E702` in `config_flow.py`, `coordinator.py`, `entities.py`). Preserve this style when editing those files.
- Keep entity display metadata translation-driven:
  - Use `translation_key` in entity descriptions.
  - Do not hardcode names/icons in descriptions; icons come from `icons.json`, strings from `strings.json`/`translations/en.json`.
- Keep generation thresholds (`generation_cool_threshold`, `generation_dry_threshold`) as **options-only** values; number entities currently expose only temperature/humidity-related thresholds.
- Manifest classification is enforced by tests: `integration_type` must stay `"service"` and `iot_class` must stay `"calculated"` (`tests/test_manifest.py`).
- Startup and runtime error handling has test-backed expectations:
  - Missing/unavailable required entities during first refresh should trigger setup retry behavior (not noisy runtime issues).
  - Runtime evaluation failures should create repair issues and raise `UpdateFailed`.
- Tests are designed for mixed environments (with/without HA plugin):
  - Many test modules use `pytest.importorskip("pytest_homeassistant_custom_component")`.
  - Imports are commonly inside test functions; follow this pattern when adding tests.
  - Reuse fixtures from `tests/conftest.py` (`coord_factory`, `mock_entry`, `loaded_entry`) instead of re-creating setup boilerplate.
- Releases are commit-message driven:
  - `release.yml` runs semantic-release after successful `Validate` on `master`.
  - Use Conventional Commit types recognized in `pyproject.toml` (`fix`, `feat`, `perf`, `docs`, `test`, etc.).
