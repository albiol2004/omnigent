# Scout: v0.14.0 --yolo + close kill/teardown (read-only)

You are the Trio Scout. Read-only. Workspace: `/home/coder/omnigent-dev`.
Never touch `/home/coder/omnigent`. Never ingest whole
`tool_dispatch.py`, `app.py`, or `orchestration.py`.

## Questions

1. On current HEAD, does a Cursor child created from a *registered*
   native spec still receive `--yolo` (or equivalent) in
   `terminal_launch_args`? Cite the function name and a small line
   range in `omnigent/server/routes/_sessions/helpers.py` around
   `_derive_terminal_launch_args_from_spec` (grep; do not dump the
   whole file). Also cite
   `tests/server/integration/test_sessions_child_sessions.py`
   `test_native_subagent_yolo_args_derived_from_trusted_spec` expected
   args for `cursor-native`.

2. For close of Claude / Codex / Cursor children: which functions
   POST `stop_session`, then call `kill_session` and
   `_teardown_session_terminals`? Give function names + line ranges
   only in:
   - `omnigent/runner/tool_dispatch.py` (search `stop_session` /
     `_session_close_via_rest`; 40-line windows)
   - `omnigent/runner/native/interrupt.py` (`stop`, `_uniform_stop`,
     `_claude_stop`, `_codex_stop`)
   Confirm Cursor is in `_UNIFORM_STOP`.

## Return

Short bullets. File:line ranges. No whole-file dumps.
