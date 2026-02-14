# Home Rules

Solar-aware aircon automation as a Home Assistant custom integration.

## Highlights

- Native HA integration (no external HTTP server)
- Entity-picker setup flow
- Dry-run switch for safe validation
- Diagnostics download and repair issues
- Rule parity with existing Go decision engine

## Installation

### HACS (custom repository)
1. In Home Assistant: **HACS → Integrations → ⋮ → Custom repositories**
2. Add `https://github.com/teh-hippo/ha-home-rules` as an **Integration**
3. Install **Home Rules**
4. Restart Home Assistant

### Manual
Copy `custom_components/home_rules/` into your HA config at `config/custom_components/home_rules/`, then restart HA.

## Setup
1. **Settings → Devices & Services → Add Integration → Home Rules**
2. Select the entities used as inputs:
   - Climate entity (your aircon)
   - Timer entity (aircon timer)
   - Inverter/solar online status entity
   - Generation sensor
   - Grid usage sensor
   - Temperature sensor
   - Humidity sensor
3. (Optional) Configure thresholds and delays via the integration **Options**.

## Dry-run mode
Turn on `switch.home_rules_dry_run` to evaluate and emit events without calling climate/timer services.

## Diagnostics
Settings → Devices → Home Rules → **Download diagnostics** will include:
- Config + options
- Control flags (enabled/cooling/aggressive/dry-run)
- Current normalized readings used by the engine
- Session counters (tolerated/reactivateDelay/failedToChange/last)
- Recent evaluation history

## Migration from the Go container
Recommended sequence:
1. Enable **dry-run** and verify `sensor.home_rules_mode` matches expectations.
2. Turn off dry-run and confirm the integration can control the climate entity correctly.
3. Stop the old container and remove helper booleans:
   - Stop container: `docker compose stop rules` (or your service name)
   - Remove helper entities if desired: `input_boolean.brain*`
4. Monitor Repair issues + Diagnostics for the first 24 hours.

Rollback:
1. Turn on dry-run or disable `switch.home_rules_enabled`
2. Restart the old container and re-enable the prior helper booleans/automations.

## Development

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements_test.txt
ruff check .
ruff format --check .
mypy custom_components tests
pytest tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for CI-matching checks and token-based GitHub auth guidance.
