# Contributing

## Goals
- Keep **rule parity** with the original Go implementation (`rules.go` + `rules_test.go`).
- Keep CI green (Hassfest + HACS + ruff + mypy + pytest).
- Use **token-based GitHub auth** for pushes and API calls.

## Local checks (match CI)

### 1) Environment
- Python: **3.13** recommended (matches CI workflow).
- If you see `Python.h: No such file or directory` during `pip install`, install dev headers:
  - Ubuntu: `sudo apt-get install -y python3.13-dev build-essential`

### 2) Create venv + install deps
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
```

### 3) Run the exact CI checks
```bash
ruff check .
ruff format --check .
mypy custom_components tests
pytest tests -q
```

## GitHub auth (token-based)
- Prefer `GH_TOKEN=... git push` and `GH_TOKEN=... gh ...`.
- Avoid interactive `gh auth login/switch` in automation.

