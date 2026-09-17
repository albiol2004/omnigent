# Builder: slice(codex-advertise-guard)

You are a GLM 5.2 Trio builder. Workspace:
`/home/coder/omnigent-dev`. Implement this slice only.
No commit/push. Never touch `/home/coder/omnigent`.
No omni, no port 6767, no `uv tool install`.
**Never ingest whole `app.py` or `tool_dispatch.py`.**
`orchestration.py` is huge: use `sed -n '4280,4310p'`
and `sed -n '2498,2520p'` only.

## Bug (from Lead verification)

`slice(stop-routing)` advertised Codex `tmux.json` with:

```
terminal_registry = resource_registry.terminal_registry
```

at `omnigent/runner/native/orchestration.py` ~4290 after
`launch_auxiliary_terminal`. Test fakes have
`launch_auxiliary_terminal` but **no** `terminal_registry`
attribute. Auto-create then raises `AttributeError`, the
`except` closes the Codex app-server, and session create
leaves no loaded bridge.

Evidence: `loop-session-close/evidence/iter1/pytest-final.txt`
— 15 slice-related failures (not the 4 databricks UC tests):

- `AttributeError: '_FakeResourceRegistry' object has no
  attribute 'terminal_registry'` in
  `test_app_sessions_native_terminals_runtime.py` (resume,
  fork, worktree, relay, catalog pin) and
  `test_app_sessions_native_wake_forwarders.py::
  test_auto_create_codex_terminal_recreate_cancels_prior_forwarder`
- Cascade 503 `Codex-native settings update requires a
  loaded Codex bridge` and interrupt `fake_client.connected`
  False in `test_app_sessions_native_events_lifecycle.py`
  because auto-create aborted the app-server.
- `test_events_compact_on_codex_native_returns_503_when_no_terminal`
  got 200: session create auto-created a real pane into the
  empty `TerminalRegistry()` the test passed in. Stub
  auto-create in **that test only** so "no terminal" stays
  true. Do not weaken the 503 production path.

Do **not** touch `tests/runner/test_uc_function.py`
(pre-existing `ModuleNotFoundError: databricks`).

## Product fix (orchestration.py ONLY ~4287-4300)

Match the existing `if terminal_registry is not None` guard
but do not assume the attribute exists. Cursor at ~2506
uses the same attribute; **only change the Codex advertise
block** unless cursor tests fail the same way (they did not).

```python
# Fakes (and some runners) implement launch_auxiliary_terminal
# without a terminal_registry attribute. Missing advertise is
# fine: kill_session already treats "tmux.json not advertised"
# as best-effort. Never abort auto-create after a successful
# launch — that tears down the app-server and strands the
# session with no loaded Codex bridge.
terminal_registry = getattr(
    resource_registry, "terminal_registry", None
)
```

Keep the rest of the advertise block (get + running +
`write_tmux_target`) unchanged. Lots of comments.

## Tests

1. Every failing `_FakeResourceRegistry` that launches
   Codex may stay attribute-less; the getattr fix must make
   them pass. Optionally set `terminal_registry = None` on
   the recreate fake at
   `tests/runner/test_app_sessions_native_wake_forwarders.py`
   ~881 (the claude fake above it already has that).
2. Compact 503 test in
   `tests/runner/test_app_sessions_native_events_options.py`
   (~7740): monkeypatch
   `_auto_create_codex_terminal` (or the launch adapter) so
   session create does **not** register a pane. Assert 503
   still. Comment why: the test is about compact-with-no-
   pane, not about blocking auto-create in production.
3. Do not add skips.

## Verify (must all pass)

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/runner/test_app_sessions_native_terminals_runtime.py \
  tests/runner/test_app_sessions_native_wake_forwarders.py \
  tests/runner/test_app_sessions_native_events_lifecycle.py \
  tests/runner/test_app_sessions_native_events_options.py \
  tests/runner/test_native_interrupt_runner.py \
  tests/test_codex_native_bridge.py
```

Also:

```
uv run --project /home/coder/omnigent-dev ruff check \
  omnigent/runner/native/orchestration.py \
  tests/runner/test_app_sessions_native_events_options.py \
  tests/runner/test_app_sessions_native_wake_forwarders.py
```

Return files changed, summary, exact pytest line, concerns.
Do not commit.
