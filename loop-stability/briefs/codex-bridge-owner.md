# Builder brief — slice codex-bridge-owner

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent`. Mailbox `loop-stability/`. Iteration 1.

Do NOT read whole large files. Use Read offsets. Do NOT commit.
Do NOT edit `omnigent/codex_native_app_server.py` or
`omnigent/runner/native/orchestration.py` (other slices).
No live Codex login.

PATH: `PATH=/home/alex/omnigent/.venv/bin:$PATH`

## Writes (only)

- `omnigent/runner/app.py`
- `tests/runner/test_app_sessions_native_events_lifecycle.py`

## Line ranges (HEAD after slice codex-writer-resume)

- `_codex_native_bridge_state_for_session` `app.py` 4060–4094
  skip: `state.session_id != conv_id` logs
  "Codex-native %s skipped … bridge belongs to %s"
- `_codex_native_model_options` `app.py` 4221–4233
- existing tests in
  `tests/runner/test_app_sessions_native_events_lifecycle.py`
  ~548–600 (`test_codex_native_model_options_*`)

## Required behavior (test-first)

GOAL item 2: stale Codex models because model options skip when
the session's `omnigent.codex_native.bridge_id` label points at a
bridge whose `state.session_id` is another session (fork/resume
rotation; parent still listed as owner).

Smallest correct rule:

- **Read-only** `action=="model options"`: if labels name a bridge
  that has live state, return that state even when
  `state.session_id != conv_id`. That is the live app-server; skipping
  leaves the UI on a stale catalog.
- **Mutating** actions (`settings update`, `plan-mode update`, goal
  runner, etc.): keep the existing skip when `session_id` mismatches.
- A session with **no** labels and a foreign `state.json` under
  `bridge_dir_for_bridge_id(conv_id)` must still skip (do not drop
  all ownership checks).

Tests:

1. Write parent-owned bridge state; GET
   `/v1/sessions/{child}/codex-model-options` with child labels
   pointing at that bridge_id; monkeypatch `model/list` like
   `test_codex_native_model_options_query_model_list`; expect 200
   with those models (must fail before the fix).
2. Settings/update (or another mutating path already tested) still
   no-ops / skips on mismatch.

```
cd /home/alex/omnigent && uv run pytest -q \
  tests/runner/test_app_sessions_native_events_lifecycle.py \
  -k 'codex_native_model_options'
```

Capture to
`loop-stability/evidence/iter1/codex-bridge-owner/pytest.txt`
and a short NOTES.md. Lines < 88 chars. Comments on the new rule.
