# Verification

- Command: `PATH=/home/alex/omnigent/.venv/bin:$PATH uv run pytest -q`
  `tests/runner/test_app_sessions_native_events_lifecycle.py`
  `-k 'codex_native_model_options'`
- Result: `3 passed, 38 deselected in 5.81s`.
- The regression covers labeled foreign-bridge model discovery and mutation
  ownership.
- Codex app-server RPCs were mocked; no live Codex login was performed.
