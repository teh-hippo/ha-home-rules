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

- Separates **Control Mode** (**Disabled / Monitor / Automatic**) from **Automatic Power Use**.
- Exposes decision sensors so you can see why a mode/action was chosen.
- Can optionally send mode-change alerts to a `notify.*` target.
- Runtime integration code is intentionally compact to keep maintenance overhead low.

## Installation

Requires Home Assistant **2026.3.0** or newer.
Configuration forms support both Voluptuous and the Probatio schema backend introduced in Home Assistant 2026.10.

Install through HACS as a custom repository:
1. Add `https://github.com/teh-hippo/ha-home-rules` as an **Integration** repository.
2. Install **Home Rules**.
3. Restart Home Assistant.

## Configuration

Add **Home Rules** from Settings -> Devices & Services, select your entities, then tune options.
Home Rules manages its own aircon timer internally, so you do not need a separate `timer.*` helper entity.

`select.home_rules_control_mode` defaults to **Monitor** for safe setup.
Switch to **Automatic** once you are happy with decisions and want the integration to control your climate entity.

**Automatic Power Use** is a separate selector (`select.home_rules_power_policy`):

- **Solar only** (default): use generation thresholds to choose Cool or Dry; do not start while importing or discharging the battery beyond its tolerance.
  Existing automatic runs tolerate brief battery discharge or grid import, then stop after the configured **Paid-power tolerance**.
  Cool/Dry mode changes do not reset that tolerance.
- **Solar with battery/grid run-on**: starts require the same solar and temperature conditions as Solar only.
  An existing solar-started run can continue on battery/grid for the configurable **Solar run-on allowance**, default **60 minutes**, after the paid-power tolerance period.
  The allowance preserves the current Cool/Dry mode and cannot start a fresh run.
  Brief solar recoveries do not reset its deadline; sufficient free solar must recover for at least the tolerance period (or one evaluation interval when tolerance is zero).
  Setting the allowance to zero disables run-on.
  Home Rules does not enforce a battery charge reserve; inverter protections remain external.

**Minimum off time** applies after every switch-off, including manual stops and timer expiry.
It uses elapsed minutes, not evaluation counts, and its deadline survives restarts.
Manual starts remain possible during the automatic-start cooldown.

**Temperature control.** Normal automatic starts use **Comfort Temperature** (default 24°C) as the upper comfort boundary.
**Ideal Temperature** (default 22°C) is the target sent to the climate entity.
Comfort Temperature must be higher than Ideal Temperature to avoid repeated starts near the target.
The existing `number.home_rules_temperature_threshold` and `number.home_rules_cool_setpoint` entity IDs are retained.
An unavailable temperature sensor prevents automatic starts and cannot be treated as proof that the target has been reached.

Two independent device switches control what happens when the house reaches Ideal Temperature:

- **Stop at Ideal Temperature** (`switch.home_rules_stop_at_comfort_temperature`): stops automatic Cool/Dry runs at the target when on.
  When off, automatic cooling continues under the power rules.  The switch never shortens a manual timer.
- **Automatic Target Notifications** (`switch.home_rules_automatic_target_notifications`): enables information-only target-reached alerts for automatic runs, regardless of time.
  Manual Cool/Dry runs send a separate information-only alert at Comfort Temperature without shortening the timer.

Automatic target notifications default on and target stopping defaults off.
Both require the temperature input to be available; notifications require a configured notification service.
Each run receives at most one successfully delivered target alert, including across HA restarts.
Changing the aircon setpoint does not change run ownership or Home Rules' saved temperature settings.
An automatic run respects the adjusted aircon setpoint until it ends, including across restarts.
The next automatic start uses the saved temperature settings; target-stop decisions still use Ideal Temperature.

Turning **Cooling Enabled** off stops existing automatic cooling and prevents new automatic starts, without blocking manual cooling.
Turning **Dry Mode Enabled** off during automatic Dry switches to Cool if eligible, otherwise stops the run.
Manual Dry remains allowed.

Two independent switches control occupancy-aware starts:

- **Only Cool When Home** requires the optional **Comfort occupancy** entity to be home before an automatic cooling or drying start.
  It defaults to Home Assistant's `zone.home` aggregate, or it can be a person or device tracker so only a specific occupant authorises normal cooling.
  Arrivals and departures are evaluated on the next poll.
  A departure stops an automatic run unless it is covered by the full-battery exception.
  Manual cooling is not blocked.
- **Allow Away Cooling at Full Battery** permits an automatic cooling start while the house is empty once the configured battery state of charge reaches **Battery Full Threshold** (default 100%).
  The run remains authorised until the battery reaches **Battery Reserve** (default 80%), the room reaches its target, or existing safety conditions stop it.
  The reserve prevents a 99% reading immediately cancelling a run that started at 100%; Home Rules must see the full threshold again before a later away run can start.
  This switch has no effect unless Only Cool When Home is enabled.

Select a percentage battery state-of-charge sensor in options to use the full-battery exception.
Away battery-authorised cooling requires no net grid import at start and retains the configured paid-power tolerance for grid use during the run.
The existing 100 W battery-power noise floor is fixed.
Presence alone does not authorise a fresh battery or grid start; ordinary home-present starts still follow Automatic Power Use and require its normal solar conditions.

Existing comfort and ideal temperatures are preserved.
Supported earlier releases migrate saved settings automatically during an upgrade.

**Afternoon comfort planning (optional).** Turn on **Afternoon Comfort Cooling** to select a cooling window before the configured deadline (default 17:00) using a Forecast.Solar config entry.
Home Rules reads Forecast.Solar's cached time series; it does not force an upstream refresh.
It chooses the latest remaining one-hour window that can cover the configured **Afternoon Cooling Energy Budget**, default 6.1 kWh.
The budget is a conservative starting value for about 5.5 kW of aircon plus ordinary house load.

The forecast only selects a window.
Live generation, grid and battery sensors still authorise each evaluation.
While the selected comfort occupant is away, the policy prioritises battery charging and blocks a new battery-backed start until the existing full-battery away exception's conditions are met.
While the selected comfort occupant is home, a late comfort top-up can use the battery down to the separate **Central Cooling Battery Reserve**, default 40%, and stops at Comfort Temperature (24°C by default) rather than chasing the 22°C ideal target.
This reserve applies only to Home Rules central cooling; it does not change GoodWe export or inverter reserve settings.

An existing run may bridge a solar interruption for no longer than the existing paid-power tolerance when Forecast.Solar predicts recovery during that interval.
Sustained grid import, missing live battery/occupancy data, no forecast recovery or a breached reserve stops the afternoon policy.
Missing or malformed forecast data prevents an afternoon start and is reported in the decision sensor.
The policy is off by default and should be observed in Monitor mode before enabling Automatic control.

**Battery power (optional).** Select a battery power sensor in options to detect discharge.
Battery discharge readings up to 100 W are treated as noise.
Battery power is expected positive when discharging (GoodWe); enable the invert option if yours is the opposite.

Turning the aircon on manually starts the configured timer, even below the battery reserve or with ample solar.
Home Rules does not take over a manual run, change its target, or shorten its timer when the mode or setpoint changes.
Turning the aircon off cancels the timer; otherwise Home Rules turns it off on the first evaluation at or after expiry.
The deadline survives restarts.

With **Only Cool When Home** enabled, Home Rules may end a manual run early after a confirmed departure if there is live solar, no grid import, and the battery is measurably charging below the configured full threshold.
An already-away manual start is still honoured.  Missing readings do not trigger this early stop.

Monitor runs the internal timer for the configured duration and exposes its remaining seconds through `sensor.home_rules_timer_countdown`, without controlling the aircon.

## Development

```bash
bash scripts/check.sh
```

Requires [uv](https://docs.astral.sh/uv/). Uses [Conventional Commits](https://www.conventionalcommits.org/).

## Troubleshooting

- Verify all configured entities exist and are available.
- Keep Control Mode in **Monitor** until behaviour matches expectations.
- Check Home Assistant logs for `home_rules` issues.

## License

MIT

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/teh-hippo/ha-home-rules
[release-url]: https://github.com/teh-hippo/ha-home-rules/releases
[validate-badge]: https://img.shields.io/github/actions/workflow/status/teh-hippo/ha-home-rules/validate.yml?branch=master&label=validate
[validate-url]: https://github.com/teh-hippo/ha-home-rules/actions/workflows/validate.yml
[ha-badge]: https://img.shields.io/badge/HA-2026.3%2B-blue.svg
[ha-url]: https://www.home-assistant.io
