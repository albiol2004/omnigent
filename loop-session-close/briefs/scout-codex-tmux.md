# Scout: Codex native tmux kill surface

You are the Trio Scout. Read-only. Workspace:
`/home/coder/omnigent-dev`. Never touch `/home/coder/omnigent`.
Never ingest whole `tool_dispatch.py` or `app.py`.

## Question

Where does a Codex-native session advertise its tmux socket
and target, so `kill_session(bridge_dir)` can mirror Cursor
(`omnigent/cursor_native_bridge.py` `kill_session` ~934-944
and `_wait_for_tmux_info` ~513-521)?

## Read exactly

- `omnigent/codex_native_bridge.py`: grep for tmux, socket,
  `kill_session`, `bridge_dir_for_session_id`. Read only
  matching functions (sed ranges). File may be ~1k lines;
  do not dump it all.
- `omnigent/cursor_native_bridge.py` 110-120, 480-544,
  934-944 only.
- `omnigent/claude_native_bridge.py` kill_session 3278-3326
  only.
- `omnigent/runner/native/interrupt.py` stop() 291-311,
  `_claude_stop` 438-479, `_codex_interrupt` 481-end of
  that method (sed until next def).
- `omnigent/runner/native/orchestration.py`
  `teardown_codex_native_app_server` ~199-225.
- How tests write tmux.json (grep `write_tmux` /
  `tmux.json` under `tests/`, report paths + 20-line
  snippets).

## Return

Exact function names and line ranges to copy for Codex
`kill_session`. Note if Codex uses a different tmux
advertisement than `tmux.json` in the bridge dir. How
`NativeInterruptRunner.stop` should call it plus
`_teardown_session_terminals` plus
`teardown_codex_native_app_server`.
