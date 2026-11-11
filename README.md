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

**Temperature control.** Both modes start automatic cooling at or above **Temperature Threshold** and turn off automatic Cool or Dry runs at or below **Cool Setpoint**, using the configured home temperature sensor.
Temperature Threshold must be higher than Cool Setpoint; the gap prevents repeated starts near the target.
The same Cool Setpoint is sent to the climate entity.
These decisions run at the configured evaluation interval, not continuously.
An unavailable temperature sensor prevents automatic starts and cannot be treated as proof that the target has been reached.
Existing installations with equal or inverted temperature settings must correct them before automatic starts resume.

**Solar Cooling** uses the configured generation thresholds to choose Cool or Dry and retains the grid-usage tolerance.
Battery discharge is not free solar: it blocks automatic starts and turns automatically started Cool or Dry runs off.
Manual cooling that uses battery or grid power receives the configured timer cap instead.

**Boost Cooling** can start with any positive solar generation and supplement the aircon's demand with battery or grid power.
Once an automatic run starts, it continues towards Cool Setpoint even if solar generation disappears.
Boost applies whenever selected, not just in the afternoon.
The separate **Afternoon Cooling** switch blocks automatic starts in either mode before the configured start hour (default 14:00 local time), without interrupting an existing run.
Home Rules does not enforce a battery charge reserve; Boost may import grid power or use stored energy until the target is reached.
Inverter battery protections remain external to Home Rules.

**Battery power (optional).** Select a battery power sensor in options to let Solar Cooling detect discharge.
**Battery Discharge Tolerance** ignores discharge up to the configured wattage.
Battery power is expected positive when discharging (GoodWe); enable the invert option if yours is the opposite.

The shared temperature stop applies only to automatically started Cool and Dry runs.
For manually started Cool or Dry runs on Timer, choose **Manual cooling target behaviour** in the integration options:

- **Timer:** keep running until the configured timer expires.
- **Ask** (default): notify once at Cool Setpoint, with **Turn off**, **Keep running**, and **5 mins** buttons.
- **Auto off:** stop at Cool Setpoint or timer expiry, whichever comes first.

Ask requires a configured notification service; interactive buttons require a Home Assistant Companion `notify.mobile_app_*` service.
No response or **Keep running** leaves the original deadline unchanged.
**5 mins** shortens the remaining timer to five minutes from the response, without extending a shorter remaining time.
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
