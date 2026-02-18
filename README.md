<p align="center">
  <img src="https://raw.githubusercontent.com/teh-hippo/ha-home-rules/master/logo.png" alt="Home Rules" width="420" />
</p>

# Home Rules

Solar-aware aircon automation as a Home Assistant custom integration.

## Highlights

- Sunshine in, chill out.
- Safe by default: starts in **Dry Run** so you can watch decisions first
- One **Control Mode** selector (Disabled / Dry Run / Live / Aggressive)
- Sensors that explain the "why" (mode/action/decision + last change)

## Installation

Install via HACS (custom repository): add `https://github.com/teh-hippo/ha-home-rules` as an **Integration**, install **Home Rules**, then restart Home Assistant.

## Setup

Add the **Home Rules** integration in Home Assistant and follow the prompts to select your entities and tune options.

## How it works

Home Rules watches your climate + sensor inputs (solar, grid usage, temperature, humidity) and runs a small rules engine. In **Dry Run** it only reports decisions; in **Live/Aggressive** it applies changes to your climate entity, and can optionally notify a `notify.*` target on mode changes.

## Control Mode
`select.home_rules_control_mode` defaults to **Dry Run** for safe setup. Switch to **Live** once you're happy with decisions and want the integration to control your climate entity.

## Development

Run all checks (manifest key ordering, ruff, mypy, pytest) with:

```bash
bash scripts/check.sh
```

Requires [uv](https://docs.astral.sh/uv/) — no manual venv setup needed.

### Pre-push CI checklist

Use this exact flow before every push to reduce CI failures:

```bash
git pull --rebase origin master
bash scripts/check.sh
git push
gh run watch --workflow Validate --exit-status
```

If the push rebases onto new commits, run `bash scripts/check.sh` again before pushing.

`Validate` currently runs HACS as non-blocking while `brands` assets are pending upstream; `hassfest` and tests remain blocking.

Common CI pitfall: hassfest requires manifest keys to be ordered as `domain`, `name`, then alphabetical keys. `bash scripts/check.sh` now enforces this locally before push.
