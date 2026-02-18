<p align="center">
  <img src="https://raw.githubusercontent.com/teh-hippo/ha-home-rules/master/logo.png" alt="Home Rules" width="420" />
</p>

# Home Rules

Solar-aware aircon automation for Home Assistant.

## What it does

- Starts safe in **Dry Run** mode so you can validate behavior first.
- Uses one **Control Mode** selector (**Disabled / Dry Run / Live / Aggressive**).
- Exposes decision sensors so you can see why a mode/action was chosen.
- Can optionally send mode-change alerts to a `notify.*` target.
- Runtime integration code is intentionally compact to keep maintenance overhead low.

## Install

Install through HACS as a custom repository:
1. Add `https://github.com/teh-hippo/ha-home-rules` as an **Integration** repository.
2. Install **Home Rules**.
3. Restart Home Assistant.

## Configure

Add **Home Rules** from Settings -> Devices & Services, select your entities, then tune options.

`select.home_rules_control_mode` defaults to **Dry Run** for safe setup. Switch to **Live** once you're happy with decisions and want the integration to control your climate entity.

## Development

```bash
bash scripts/check.sh
```

Requires [uv](https://docs.astral.sh/uv/). Uses [Conventional Commits](https://www.conventionalcommits.org/).
