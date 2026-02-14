<p align="center">
  <img src="https://raw.githubusercontent.com/teh-hippo/ha-home-rules/master/logo.png" alt="Home Rules" width="420" />
</p>

# Home Rules

Solar-aware aircon automation as a Home Assistant custom integration.

## Highlights

- Native HA integration (no external HTTP server)
- Step-by-step, entity-picker setup flow
- Single **Control Mode** selector (Disabled / Dry Run / Live / Aggressive)
- Diagnostics download and repair issues
- Rule parity with existing Go decision engine
- Decision history sensor ("why did it do that?")

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
2. Select the entities used as inputs (step-by-step):
   - Climate entity (your aircon)
   - Timer entity (aircon timer)
   - Solar online status entity (optional)
   - Generation sensor
   - Grid usage sensor
   - Temperature sensor
   - Humidity sensor
3. (Optional) Configure thresholds and delays via the integration **Options**.

## Control Mode
`select.home_rules_control_mode` defaults to **Dry Run** for safe setup. Switch to **Live** once you're happy with decisions and want the integration to control your climate entity.

## Notifications (optional)
Pick a `notify.*` target in **Options → Notification service** (or set it to **Disabled**). Notifications fire on mode changes.

## Diagnostics
Settings → Devices → Home Rules → **Download diagnostics** will include:
- Config + options
- Control mode + flags
- Current normalized readings used by the engine (from your existing sensors)
- Session counters (tolerated/reactivateDelay/failedToChange/last)
- Recent evaluation history

## Migration from the Go container
Recommended sequence:
1. Use **Dry Run** and verify `sensor.home_rules_mode` matches expectations.
2. Switch to **Live** and confirm the integration can control the climate entity correctly.
3. Stop the old container and remove helper booleans:
   - Stop container: `docker compose stop rules` (or your service name)
   - Remove helper entities if desired: `input_boolean.brain*`
4. Monitor Repair issues + Diagnostics for the first 24 hours.

Rollback:
1. Set **Control Mode** back to **Dry Run** or **Disabled**
2. Restart the old container and re-enable the prior helper booleans/automations.

## Lovelace card (quick start)
```yaml
type: entities
title: Home Rules
entities:
  - entity: select.home_rules_control_mode
  - entity: switch.home_rules_cooling_enabled
  - entity: button.home_rules_evaluate_now
  - type: section
  - entity: sensor.home_rules_mode
  - entity: sensor.home_rules_action
  - entity: sensor.home_rules_decision
  - entity: binary_sensor.home_rules_solar_available
  - entity: binary_sensor.home_rules_auto_mode
  - entity: sensor.home_rules_last_changed
```

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
