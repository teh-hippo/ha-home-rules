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
- Supports solar-powered afternoon pre-cooling with configurable start and finish times.
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
Legacy reactivation settings are converted using their configured evaluation interval.
Manual starts remain possible during the automatic-start cooldown.

**Temperature control.** Normal automatic starts use **Start Temperature** (default 24°C).
**Comfort Temperature** (default 22°C) is the actual desired room temperature and the target sent to the climate entity.
Start Temperature must be higher than Comfort Temperature to avoid repeated starts near the target.
The existing `number.home_rules_temperature_threshold` and `number.home_rules_cool_setpoint` entity IDs are retained.
An unavailable temperature sensor prevents automatic starts and cannot be treated as proof that the target has been reached.

Two independent device switches control what happens when the house reaches Comfort Temperature:

- **Stop at Comfort Temperature** (`switch.home_rules_stop_at_comfort_temperature`): stops automatic and manual Cool/Dry runs at the target when on.
  When off, cooling continues under the existing power rules and any manual timer cap.
- **Automatic Target Notifications** (`switch.home_rules_automatic_target_notifications`): enables information-only target-reached alerts for automatic runs, regardless of time.
  Manual target-reached alerts are always enabled and are not affected by this switch.

Automatic target notifications default on and target stopping defaults off.
Both require the temperature input to be available; notifications require a configured notification service.
Each run receives at most one successfully delivered target alert, including across HA restarts.
Changing the aircon setpoint does not change run ownership or Home Rules' saved temperature settings.
An automatic run respects the adjusted aircon setpoint until it ends, including across pre-cooling boundaries and restarts.
The next automatic start uses the saved temperature settings; target-stop decisions still use Comfort Temperature.

Turning **Cooling Enabled** off stops existing automatic cooling and prevents new automatic starts, without blocking manual cooling.
Turning **Dry Mode Enabled** off during automatic Dry switches to Cool if eligible, otherwise stops the run.
Manual Dry remains allowed.

**Afternoon Pre-cooling** is an independent switch, initially off.
Enable it to use **Pre-cooling Temperature** (default 20°C) during the local-time window:

- `time.home_rules_pre_cooling_start`: defaults to **14:00**.
- `time.home_rules_pre_cooling_finish`: defaults to **17:00**.

Pre-cooling can start 1°C above its target, below the normal Start Temperature.
It lets the aircon maintain that target until the window ends, subject to Automatic Power Use.
The target-stop and automatic target-notification switches apply outside the pre-cooling window; power limits still apply throughout it.
Outside the window, the target returns to Comfort Temperature unless you adjusted the aircon setpoint during the run.
An already-cool run stops only when Stop at Comfort Temperature is enabled.
Normal cooling remains available before and after the window, and pre-cooling does not resume when an evening tariff changes back to off-peak.
Times are adjustable on the integration device; the start must precede the finish on the same day.

Optionally select your existing **Current tariff entity** in integration options and specify its **Peak tariff state** (default `peak`).
Peak or unavailable tariff readings suppress pre-cooling, without blocking ordinary comfort cooling.
The finish time remains the explicit daily limit even when no tariff entity is configured.
Window boundaries and tariff changes trigger evaluation immediately; other decisions use the configured evaluation interval.
No tariff schedule, battery charging or export settings are changed by Home Rules.

Saved Solar Cooling and Boost Cooling modes migrate to Automatic with Solar only and Solar with battery/grid run-on respectively.
The former unrestricted Allow battery and grid policy now permits bounded continuation only, not paid-power starts.
Existing comfort temperatures and afternoon-switch settings are preserved.
The old afternoon start hour is used to initialise the new start-time entity.
The former Manual cooling target behaviour option is replaced by the two switches: Auto off enables Stop at Comfort Temperature; Timer and Ask leave it off.
Automatic Target Notifications initially defaults on, and manual target alerts remain enabled regardless of the previous choice.

**Battery power (optional).** Select a battery power sensor in options to detect discharge.
**Battery Discharge Tolerance** ignores discharge up to the configured wattage.
Battery power is expected positive when discharging (GoodWe); enable the invert option if yours is the opposite.

Manually started cooling remains uncapped while free solar is available.
Once it uses battery/grid power or solar is unavailable, the configured timer cap starts independently of Automatic Power Use.
Automatic cooling does not receive a manual timer merely because battery/grid use is permitted.
Manual target alerts offer **Turn off**, **Keep running**, and **5 mins** buttons while cooling remains on; a target-based stop sends an information-only alert.
Interactive buttons require a Home Assistant Companion `notify.mobile_app_*` service.
No response or **Keep running** leaves the original deadline unchanged.
**5 mins** shortens the remaining timer to five minutes from the response, without extending a shorter remaining time.
If a manual run is still uncapped, **5 mins** explicitly starts a five-minute timer.
Target prompts and pending responses survive HA restarts, and buttons from completed or replaced timer sessions are ignored.
Timer expiry still stops the run if solar generation recovers.
Unavailable temperature readings cannot trigger target prompts or target-based stops.
Heat and other non-cooling manual modes retain their timer-only behaviour.

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
[ha-badge]: https://img.shields.io/badge/HA-2026.2%2B-blue.svg
[ha-url]: https://www.home-assistant.io
