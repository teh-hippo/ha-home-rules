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

## Install

Install through HACS as a custom repository:
1. Add `https://github.com/teh-hippo/ha-home-rules` as an **Integration** repository.
2. Install **Home Rules**.
3. Restart Home Assistant.

## Configure

Add **Home Rules** from Settings -> Devices & Services, select your entities, then tune options.

`select.home_rules_control_mode` defaults to **Dry Run** for safe setup. Switch to **Live** once you're happy with decisions and want the integration to control your climate entity.

## Development

Run local validation with:

```bash
bash scripts/check.sh
```

`check.sh` verifies manifest key ordering plus ruff, mypy, and pytest (requires [uv](https://docs.astral.sh/uv/)).

### Pre-push CI checklist

Use this exact flow before every push:

```bash
git pull --rebase origin master
bash scripts/check.sh
git push
gh run watch --workflow Validate --exit-status
```

If the push rebases onto new commits, run `bash scripts/check.sh` again before pushing.

`Validate` currently treats HACS as informational while `brands` assets are pending upstream; `hassfest` and tests remain blocking.

## Release process

Releases are created by `.github/workflows/release.yml` after **Validate** succeeds on `master`.
Use conventional commits; `fix`, `perf`, and `build` commits trigger patch releases via semantic-release.
