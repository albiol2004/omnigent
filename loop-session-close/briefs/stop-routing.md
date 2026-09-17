# Builder: slice(stop-routing)

You are a GLM 5.2 Trio builder. Workspace:
`/home/coder/omnigent-dev`. Implement this slice only.
Do not git commit or push. Do not touch `/home/coder/omnigent`.
No `uv tool install`, no omni processes, no port 6767.
Never ingest whole `tool_dispatch.py`, `app.py`, or
`orchestration.py`. Use `sed -n`.

Scout note: Codex bridge has no tmux helpers today, but the
Codex TUI still runs in tmux via
`resource_registry.launch_auxiliary_terminal` (~4226 in
`orchestration.py`). Cursor advertises `tmux.json` after
launch (orchestration ~2503-2516). Codex does not — you must
add that advertisement AND `kill_session` on the Codex
bridge, then a real `_codex_stop`.

## 1. REST close stop_session routing

`omnigent/runner/tool_dispatch.py` 5633-5646 and imports
52-54. Today `stop_session` only if wrapper ==
`CLAUDE_NATIVE_WRAPPER_VALUE`. Change to `stop_session` when
wrapper is Claude, Codex, or Cursor
(`CURSOR_NATIVE_WRAPPER_VALUE` from
`omnigent._wrapper_labels`). Keep interrupt for others.
Failed stop still tombstones (existing).

## 2. Advertise Codex tmux.json

`omnigent/runner/native/orchestration.py` **only** around
the successful `launch_auxiliary_terminal` for Codex
(~4226-4293). Mirror Cursor 2503-2516: if
`terminal_registry.get(session_id, "codex", "main")` is
running, `write_tmux_target` on the same `bridge_dir`
already in scope (`prepare_bridge_dir(session_id)` ~3800).
Add `write_tmux_target` / small tmux helpers on
`omnigent/codex_native_bridge.py` (copy Cursor
`write_tmux_target`, `read_tmux_info`, `_wait_for_tmux_info`,
`_run_tmux`, `kill_session` from cursor_native_bridge.py
934-944 and 470-538). Keep new helpers documented. File is
already large; keep additions tight.

## 3. NativeInterruptRunner Codex stop

`omnigent/runner/native/interrupt.py`:
- `stop()` 291-311: `codex` must NOT route to interrupt.
  Keep `pi` on interrupt unless trivial.
- New `_codex_stop` modeled on `_claude_stop` 438-479:
  1. `kill_session(bridge_dir_for_bridge_id(conv_id),
     timeout_s=1.0)` — `prepare_bridge_dir` uses session id
     as bridge id. If tmux not advertised, log and continue
     (do not fail the stop).
  2. `await self._teardown_session_terminals(conv_id)`
  3. `await teardown_codex_native_app_server(conv_id)`
     (orchestration.py ~199). That already cancels the
     forwarder — do not double-cancel unless needed.
  4. publish `session.status` idle + mark subagent
     cancelled like Claude stop.
- Import `teardown_codex_native_app_server` in the existing
  orchestration import block (~43-47).

## Tests

- `tests/runner/test_runner_dispatch.py` close cases: Cursor
  and Codex wrapper labels must POST `stop_session` not
  `interrupt`. Claude already does.
- `tests/runner/test_native_interrupt_runner.py` after
  ~285-333: `runner.stop("codex-native", ...)` calls
  kill_session, `_teardown_session_terminals`, and
  `teardown_codex_native_app_server` (monkeypatch).
- `tests/test_codex_native_bridge.py`: kill_session issues
  `tmux kill-session` like Claude's test ~3876-3934.

## Verify

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/runner/test_runner_dispatch.py \
  tests/runner/test_native_interrupt_runner.py \
  tests/test_codex_native_bridge.py
```

Return files changed, summary, pytest output, concerns.
