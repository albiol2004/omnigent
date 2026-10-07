# v17-port-stop — v14 "stop" group re-ported onto v0.17.0

Source: `v16/trio-v0.16.0-fixes` (nine commits, original order), picked with
`git cherry-pick -x` after v17-port-close.

Conflicts and how they were resolved (upstream v0.17.0 kept, fork layered on top):

- **ecfd01174 stop-routing** — `tests/runner/test_app_sessions_native_events_lifecycle.py`:
  v0.17.0 added `test_events_interrupt_codex_side_chat_leaves_parent_turn_running`
  right before the test the fork renames. Kept the upstream side-chat test intact
  and applied the fork rename/body change
  (`..._uses_turn_interrupt_without_marker` -> `..._hard_stops_without_marker`) after it.
- **cb7807e2f kill-escalation** — `omnigent/harnesses/cursor_native/bridge.py`:
  upstream #8523 (7cbad8613) added the required `native_input_ready` provider probe right
  below `kill_session`. Kept it unchanged; `kill_session` now delegates to
  `native_tmux_kill.kill_session_with_escalation` (new `omnigent/native_tmux_kill.py`).
- **2ed8634c8** — `omnigent/harnesses/claude_native/bridge.py`: import block moved upstream
  (`kiro_bridge` module import). Kept upstream's `kiro_bridge` import and dropped only the
  now-unused `_proc` import. The codex bridge test import fix applied to the moved test
  `tests/harnesses/codex_native/test_codex_native_bridge.py` (kill-escalation's new test used the
  pre-split `omnigent.codex_native_bridge` path; now `omnigent.harnesses.codex_native.bridge`).
- **9734887b3 reaper** — applied cleanly: the busy-check lines still live in
  `omnigent/runner/app.py` on v0.17.0 and move into
  `omnigent/terminals/pane_reaper.py::_pane_is_busy_after_harness`. The approval-wait check
  stays ahead of the helper; upstream
  `test_runner_busy_check_counts_a_viewer_only_on_recent_input` still passes.
- **10887f8ed codex-advertise-guard** — `tests/runner/test_app_sessions_native_events_options.py`:
  upstream replaced the hand-built app with `_build_app_for_spec(...)` (tests/runner/conftest.py).
  Kept the helper call and layered the fork's `_auto_create_codex_terminal` stub on top.
- **README commits** — b44be221b/fb483202e/9ab5c600d picked as-is, then adapted by the
  separate commit `slice(v17-port-stop): README for v0.17.0` (names branch
  `trio-v0.17.0-fixes`, base `v0.17.0`, source `trio-v0.16.0-fixes`).
- **aa1568f22** — edits only `docs/v16-evidence` (historical v16 notes); ported as-is.

| v16 sha | fork sha | subject | ported/adapted/dropped | new sha | notes |
|---|---|---|---|---|---|
| ecfd01174 | 97d84a2fc, 41d82337d | slice(stop-routing): hard-stop Claude, Codex and Cursor on close | adapted | 30764d7e9 | lifecycle test conflict; upstream side-chat test kept |
| cb7807e2f | 208aada58, 4e4b88928 | slice(kill-escalation): share leftover-pane SIGKILL across native bridges | adapted | 150efd6ff | cursor bridge: upstream `native_input_ready` kept; adds `omnigent/native_tmux_kill.py` |
| 2ed8634c8 | (v16-only) | slice(port-v14-stop): drop unused _proc import and fix pre-split codex bridge test import | adapted | a526deb64 | kept upstream `kiro_bridge` import, dropped only `_proc` |
| 9734887b3 | eea0c6862, 642b879d7 | slice(reaper): reap native panes after harness subprocess release | ported | 958ee4c24 | clean; #8297 semantics and viewer-busy test intact |
| 10887f8ed | ec696c5fc, 305ac7cf7 | slice(codex-advertise-guard): do not abort Codex auto-create when tmux advertise is missing | adapted | 54f5172bf | options test uses upstream `_build_app_for_spec` + fork stub |
| b44be221b | c20f65e54 | slice(readme): note trio-v0.14.0-fixes until live adopt | ported | c69e6e76f | text adapted in the README commit |
| fb483202e | 139c74a18 | docs(v14-report): summarize the 0.14.0 re-port disposition | ported | 7e50a304d | |
| 9ab5c600d | (v16-only) | slice(port-v14-stop): README adapted for v0.16.0 and disposition notes | ported | 477b2e2e8 | README text readapted for v0.17.0 in the next commit; adds historical v16 disposition note |
| aa1568f22 | (v16-only) | slice(port-v14-stop): clarify disposition note | ported | 3c16f63ee | docs/v16-evidence only, as-is |
| — | — | slice(v17-port-stop): README for v0.17.0 | adaptation | 9d7976a0d | branch `trio-v0.17.0-fixes`, base v0.17.0 |

## Pristine-proven deselects

All seven fail identically on pristine `v0.17.0` (same node ids, run in a detached
worktree: `7 failed, 7 passed, 51 deselected in 30.68s` for
`-k "side_chat or claude_native_model_options"`; on this branch the same selection gives
`7 failed, 7 passed, 51 deselected in 29.90s`):

- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_claude_native_model_options_use_session_launch_catalog[False]`
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_claude_native_model_options_serves_probe_rows_after_pending`
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_interrupt_codex_side_chat_leaves_parent_turn_running[running|idle|newer_turn|missing_turn|rpc_failure]` (5 ids)

Targeted check with those seven deselected: `1061 passed, 1 skipped, 7 deselected in 578.36s`.
