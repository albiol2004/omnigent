# Builder: finish slice(codex-advertise-guard)

Workspace `/home/coder/omnigent-dev`. Continue the same
slice. **Product getattr is already in the tree — do not
revert it.** No commit/push. Never touch
`/home/coder/omnigent`. No omni, no port 6767.

## Already done (keep)

- `orchestration.py` ~4290: `getattr(..., "terminal_registry", None)`
- compact 503 stub in `test_app_sessions_native_events_options.py`
- `terminal_registry = None` on the wake-forwarders recreate fake

Those 10 tests now pass. Remaining **5** failures are
lifecycle tests that pre-seed Codex bridge state, then
`POST /v1/sessions` auto-creates. Auto-create calls
`clear_bridge_state` then `launch_auxiliary_terminal`,
which raises `RuntimeError: Terminal registry not configured`
(these tests do not pass a `terminal_registry`). Failed
auto-create leaves **no** bridge state, so settings/interrupt
return 503 / `connected is False`.

This is the same class of "session create must not destroy
the fixture's seeded bridge". Mirror the compact stub.

## Only edit

`tests/runner/test_app_sessions_native_events_lifecycle.py`

Add one helper (next to the other fakes, <40 lines) that
monkeypatches
`omnigent.runner.native.orchestration._auto_create_codex_terminal`
to return a `SessionResourceView` **without** launching
tmux or clearing bridge state. `SessionResourceView` is
already imported.

Call the helper from:

1. `test_events_codex_native_settings_change_uses_thread_settings_update`
2. `test_codex_native_model_options_follow_labeled_foreign_bridge`
3. `test_events_interrupt_on_codex_native_uses_turn_interrupt_without_marker`

Lots of comments: auto-create on POST /v1/sessions would
wipe the pre-written bridge state when no terminal registry
is configured; these tests assert the settings/interrupt
RPC against that seeded state, not terminal launch.

Do not stub production. Do not skip. Do not touch
`test_uc_function.py`.

## Verify ONLY these (keep it fast)

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_codex_native_settings_change_uses_thread_settings_update \
  tests/runner/test_app_sessions_native_events_lifecycle.py::test_codex_native_model_options_follow_labeled_foreign_bridge \
  tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_interrupt_on_codex_native_uses_turn_interrupt_without_marker
```

Return pytest output. No commit.
