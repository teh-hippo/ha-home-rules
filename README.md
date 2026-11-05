<p align="center">
  <img src="https://raw.githubusercontent.com/teh-hippo/ha-home-rules/master/logo.png" alt="Home Rules" width="420" />
</p>

# Home Rules

[![HACS][hacs-badge]][hacs-url]
[![GitHub Release][release-badge]][release-url]
[![Validate][validate-badge]][validate-url]
[![Home Assistant][ha-badge]][ha-url]

Solar-aware aircon automation for Home Assistant.

## Features

- Uses one **Control Mode** selector (**Disabled / Dry Run / Live / Aggressive**).
- Exposes decision sensors so you can see why a mode/action was chosen.
- Can optionally send mode-change alerts to a `notify.*` target.
- Runtime integration code is intentionally compact to keep maintenance overhead low.

## Installation

Install through HACS as a custom repository:
1. Add `https://github.com/teh-hippo/ha-home-rules` as an **Integration** repository.
2. Install **Home Rules**.
3. Restart Home Assistant.

## Configuration

Add **Home Rules** from Settings -> Devices & Services, select your entities, then tune options.
Home Rules manages its own aircon timer internally, so you do not need a separate `timer.*` helper entity.

`select.home_rules_control_mode` defaults to **Monitor** for safe setup. Switch to **Solar Cooling** once you're happy with decisions and want the integration to control your climate entity.

**Boost Cooling** uses normal solar rules before the configured afternoon start hour (default 14:00 local time).
From that hour, it allows cooling above the cool setpoint with generation at or above the boost threshold, tolerating grid draw to keep cooling as daylight fades.
The separate **Afternoon Cooling** switch blocks all automatic starts before that hour when enabled.

**Battery and forecast (optional).** In options, select a battery charge sensor, a battery power sensor and a solar forecast "remaining energy today" sensor (for example from Forecast.Solar). All are optional; leave them empty to keep the old behaviour.
- `number.home_rules_battery_minimum_charge`: no automatic start below this charge. A running aircon stops only once charge is 5 points below it. 0 disables the guard.
- `number.home_rules_battery_discharge_tolerance`: battery discharge above this (W) counts as grid usage, so a battery covering the aircon load can no longer hide it from the grid meter. Battery power is expected positive when discharging (GoodWe); enable the invert option if yours is the opposite.
- `number.home_rules_forecast_minimum_remaining`: no automatic start when the forecast energy remaining today is below this (kWh). 0 disables the gate.

Monitor runs the internal timer for the configured duration and exposes its remaining seconds through `sensor.home_rules_timer_countdown`, without controlling the aircon.

## Development

```bash
bash scripts/check.sh
```

Requires [uv](https://docs.astral.sh/uv/). Uses [Conventional Commits](https://www.conventionalcommits.org/).

## Troubleshooting

- Verify all configured entities exist and are available.
- Keep Control Mode in **Dry Run** until behavior matches expectations.
- Check Home Assistant logs for `home_rules` issues.

## License

MIT

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/teh-hippo/ha-home-rules
[release-url]: https://github.com/teh-hippo/ha-home-rules/releases
[validate-badge]: https://img.shields.io/github/actions/workflow/status/teh-hippo/ha-home-rules/validate.yml?branch=master&label=validate
[validate-url]: https://github.com/teh-hippo/ha-home-rules/actions/workflows/validate.yml
[ha-badge]: https://img.shields.io/badge/HA-2026.2%2B-blue.svg
[ha-url]: https://www.home-assistant.io
