# Builder: slice(kill-escalation)

You are a GLM 5.2 Trio builder. Workspace:
`/home/coder/omnigent-dev`. Implement this slice only.
No commit/push. Never touch `/home/coder/omnigent`. No omni
processes, no port 6767, no whole-file ingest of
`tool_dispatch.py` / `app.py`.

Claude `kill_session` already SIGKILLs leftover pane pids
(`omnigent/claude_native_bridge.py` 3278-3326 and helpers
3843-3894). Cursor `kill_session` (934-944) is plain
`tmux kill-session`. Codex `kill_session` was added in
slice(stop-routing) and may also be plain.

## Work

1. Factor `_recorded_tmux_pid`, `_tmux_pane_pid`, and
   `_kill_leftover_tmux_process` (and the small timeout
   constants they need) into a **new** focused module
   under 200 lines, e.g.
   `omnigent/native_tmux_kill.py`. Keep lots of comments.
   Reuse `_proc.process_alive` / `_proc._killpg` the same
   way Claude does — read those call sites with sed, do
   not invent a new kill protocol.
2. Claude `kill_session` calls the shared helper (behavior
   unchanged).
3. Cursor and Codex `kill_session`: same pattern as Claude
   — capture pane pid from tmux.json or `list-panes`,
   `kill-session`, then leftover SIGKILL.
4. Do not churn other bridges unless a one-line import is
   truly trivial.

## Tests

- Keep `tests/test_claude_native_bridge.py` ~3892-4000
  passing (may need import path updates if tests patched
  `claude_native_bridge._proc`).
- Add leftover-pid escalation tests to
  `tests/test_cursor_native_bridge.py` and
  `tests/test_codex_native_bridge.py` modeled on Claude's
  `test_kill_session_escalates_live_pane_after_tmux_kill`.

## Verify

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/test_claude_native_bridge.py \
  tests/test_cursor_native_bridge.py \
  tests/test_codex_native_bridge.py
```

If those files are huge, still run them; do not skip.

Return files changed, summary, pytest output, concerns.
