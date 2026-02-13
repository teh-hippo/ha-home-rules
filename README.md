# Home Rules

Solar-aware aircon automation as a Home Assistant custom integration.

## Highlights

- Native HA integration (no external HTTP server)
- Entity-picker setup flow
- Dry-run switch for safe validation
- Diagnostics download and repair issues
- Rule parity with existing Go decision engine

## Development

```bash
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements_test.txt
ruff check .
ruff format --check .
mypy custom_components tests
pytest tests -v
```
