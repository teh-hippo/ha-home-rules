# Copilot Instructions for Home Rules

## Project Overview

**Home Rules** is a Home Assistant custom integration that provides solar-aware aircon automation. It's designed to intelligently control climate devices based on solar power availability and other factors.

### Technologies
- **Language**: Python 3.12+
- **Framework**: Home Assistant Integration
- **Package Manager**: uv (fast Python package manager)
- **Testing**: pytest with Home Assistant custom component support
- **Linting**: ruff (both check and format)
- **Type Checking**: mypy with strict mode
- **Distribution**: HACS (Home Assistant Community Store)

### Key Components
- `custom_components/home_rules/`: Integration source code
- `tests/`: Test suite using pytest
- `scripts/check.sh`: Local validation script (mirrors CI)

## Development Workflow

### Setup
This project uses `uv` instead of traditional pip/venv workflows. No manual `.venv` creation needed.

### Local Validation
Always run before commits:
```bash
bash scripts/check.sh
```

This runs:
1. `ruff check` - Code linting
2. `ruff format --check` - Code formatting
3. `mypy` - Type checking (strict mode)
4. `pytest` with coverage (minimum 80%)

### Running Individual Tools
```bash
uv run ruff check .              # Lint code
uv run ruff format .             # Format code
uv run mypy custom_components/home_rules tests  # Type check
uv run pytest -q                 # Run tests
uv run coverage run -m pytest tests/  # Run with coverage
```

### Testing Requirements
- Minimum 80% code coverage required
- All tests must pass
- Mypy type checking is mandatory (don't skip it)
- Use `pytest -q` for quiet output during development
- Full coverage validation with `uv run coverage report --include="custom_components/home_rules/*" --fail-under=80`

## Coding Standards

### Python Style
- **Line Length**: 120 characters (enforced by ruff)
- **Target Version**: Python 3.12
- **Type Hints**: Required (mypy strict mode enabled)
- **Import Sorting**: Automated via ruff/isort
- **First-party Package**: `custom_components.home_rules`

### Commit Conventions
**CRITICAL**: All commits must follow [Conventional Commits](https://www.conventionalcommits.org/) format.

Format: `type[(scope)]: description`

**Allowed types**:
- `fix:` - Bug fixes (triggers patch release)
- `feat:` - New features (triggers minor release)
- `perf:` - Performance improvements (triggers patch release)
- `build:` - Build system changes (triggers patch release)
- `chore:` - Maintenance tasks (no release)
- `ci:` - CI/CD changes (no release)
- `docs:` - Documentation only (no release)
- `style:` - Code style changes (no release)
- `refactor:` - Code refactoring (no release)
- `test:` - Test changes (no release)

**Examples**:
- `feat(rules): add temperature threshold logic`
- `fix(coordinator): handle missing sensor data`
- `docs: update installation instructions`

CI validates commit messages via `.github/workflows/validate.yml`.

### Code Quality
- **Linter**: ruff with selected rules (B, E, F, I, N, S, UP, W)
- **Ignored Rules**: S101 (assert statements allowed in tests)
- **Type Checking**: Strict mypy, but relaxed in tests (see pyproject.toml overrides)
- **Security**: flake8-bandit rules enabled (S prefix)

## Home Assistant Integration Specifics

### Manifest Requirements
- **Integration Type**: Must be `"service"` so it appears under Integrations (not Helpers)
- **Keys Must Be Sorted**: hassfest requires alphabetically sorted keys in `manifest.json`
- **File**: `custom_components/home_rules/manifest.json`

### Integration Structure
- Uses `ConfigFlow` for configuration UI
- Implements `DataUpdateCoordinator` pattern for state management
- Exposes entities: sensors, binary sensors, selects, switches, buttons
- **Control Mode**: Uses `select.home_rules_control_mode` with options: Disabled, Dry Run, Live, Aggressive
- Decision sensors provide transparency into automation logic

### Testing Practices
- Use `pytest-homeassistant-custom-component` for HA-specific test utilities
- Mock Home Assistant core dependencies
- Tests are allowed to be less strictly typed (see mypy overrides)
- Coverage must include all `custom_components/home_rules/*` files

## Architecture Notes

### Decision Engine
The decision engine logic originated from an earlier TypeScript implementation and represents core functionality that should be preserved during refactoring.

### Icons and Branding
- Integration icons/logos must be provided via [home-assistant/brands](https://github.com/home-assistant/brands)
- Local `icon.png` files in the repo are NOT used by Home Assistant UI
- Submit to brands repository for official icon support

## Release Process

### Automated Releases
- Releases are fully automated via `.github/workflows/release.yml`
- Triggered after successful validation on `master` branch
- Uses `semantic-release` with configuration in `pyproject.toml`
- Version updates automatically applied to:
  - `pyproject.toml` (project.version)
  - `custom_components/home_rules/manifest.json` (version field)
- Commit format: `chore(release): {version}`
- Tag format: `v{version}`

### Manual Steps
DO NOT manually:
- Update version numbers (semantic-release handles this)
- Create git tags (automated)
- Edit CHANGELOG.md manually (auto-generated)

## Common Tasks

### Adding a New Feature
1. Create feature branch
2. Implement changes with appropriate commit messages (`feat:` or `fix:`)
3. Add/update tests to maintain 80%+ coverage
4. Run `bash scripts/check.sh` to validate
5. Submit PR
6. After merge to master, semantic-release will handle versioning

### Fixing a Bug
1. Use `fix:` commit type
2. Add regression test if applicable
3. Ensure existing tests pass
4. Run local validation

### Updating Dependencies
- Update `pyproject.toml` dependency groups
- Run `uv lock` to update `uv.lock`
- Test thoroughly
- Use `build:` commit type

## Common Pitfalls

### Build/Test Issues
- **Don't skip mypy**: Running only `uv run pytest` will miss type errors
- **Use full check script**: `bash scripts/check.sh` catches issues that individual commands might miss
- **hassfest validation**: Manifest keys must be alphabetically ordered
- **Coverage threshold**: Don't commit if coverage drops below 80%

### Git/Release Issues
- **Commit format is critical**: Invalid format will fail CI and prevent releases
- **Don't force push**: Not available in this environment
- **Don't rebase**: Not available in this environment
- **No manual version changes**: Let semantic-release handle it

### Home Assistant Specifics
- Verify all configured entities exist and are available in HA
- Keep Control Mode in "Dry Run" during development/testing
- Check HA logs for integration-specific issues (search for `home_rules`)

## File Exclusions

### .gitignore
Ensure these are excluded:
- `node_modules/` (if any)
- `dist/` or build artifacts
- `.venv/` or virtual environments
- `__pycache__/` and `.pyc` files
- `.coverage` and coverage reports
- IDE-specific files

## Additional Resources

- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [HACS Documentation](https://hacs.xyz/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [uv Documentation](https://docs.astral.sh/uv/)
