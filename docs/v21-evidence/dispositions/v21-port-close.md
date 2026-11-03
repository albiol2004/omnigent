# v21-port-close — v17 "close" group re-ported onto v0.21.0rc1

Method: `git cherry-pick -x` of the 11 commits in original order onto v0.21.0rc1 (+ mailbox commit `1b72ac3af`).

## Conflicts and how they were resolved

- **#2 8f7f924c2 kill-on-close** — conflicts in `omnigent/harnesses/claude_native/bridge.py` and
  `tests/runner/test_runner_dispatch.py`.
  - Imports: kept upstream's `in_managed_sandbox` import (and the new `submit_verification` / diagnostics imports) and added
    `from omnigent.inner import _proc`. In the test file both `CLAUDE_NATIVE_WRAPPER_VALUE` and
    `SESSION_AGENT_MISSING_MESSAGE` imports are kept.
  - `kill_session`: upstream's kill markers (`_OMNIGENT_KILL_FILE` / `_EXPECTED_CLOSE_FILE`, `allow_missing_target=True`
    in `_run_tmux`, marker unlink on failure) are kept; the fork's pane-pid capture before the kill and
    `_kill_leftover_tmux_process(pane_pid)` after it are layered on top (the fork's string-matching of "can't find
    session" is superseded by upstream's `allow_missing_target`).
  - The fork's helpers `_tmux_pane_pid` / `_recorded_tmux_pid` / `_kill_leftover_tmux_process` and the two
    `_TMUX_KILL_VERIFY_*` constants are inserted before `_capture_pane`; upstream's `_usable_composer_height` context manager
    (which now precedes it) is untouched.
  - Follow-up `f6fc77242`: `test_expected_close_marks_the_pane_before_the_kill` faked `subprocess.run` and recorded every
    call; the fork's `list-panes` pid lookup now runs first, so the fake records only the `kill-session` call (same assertion:
    the marker exists when the kill runs).
- **#4 033e6837e codex-bridge-owner** — applied textually but did not compile on rc1: upstream refactored
  `_codex_native_bridge_state_and_dir_for_session` to return `(state, bridge_dir)` and resolves the label inside
  `_codex_native_bridge_dir_for_session`, so `labels` / `CODEX_NATIVE_BRIDGE_ID_LABEL_KEY` are not in scope. Follow-up
  `27da4e27e` adds a small `_codex_native_bridge_id_label(conv_id)` helper (same label lookup) and returns `(state, bridge_dir)`.
- **#6 669e05bfd** — applied cleanly: `_resolve_subagent_spec` is still re-exported from `_sessions/helpers.py`; the alias
  `_resolve_agent_spec = _resolve_subagent_spec` is kept (trioctl calls it).
- **#1, #3, #5, #7, #8, #9, #10, #11** — applied cleanly. #1/#11 add historical v17 evidence unchanged
  (`scripts/v17_focused_suite.sh`, `docs/v17-evidence/baseline-v0.17.0.txt`).
- Follow-up `c9e200827`: ruff-format of two fork test hunks (`test_app_sessions_native_events_lifecycle.py`,
  `test_runner_dispatch.py`) that no longer fit the rc1 formatter's line-length reflow.

Upstream code kept untouched in the hotspots: #12200/#12153/#12150/#11485 (idle watchdog, live-work hold, cancelled-turn) in
`runner/app.py`; #10861/#11821 in `claude_native/bridge.py`; interrupt.py and tool_dispatch.py picked cleanly.

## #10251 vs kill-on-close

Traced by reading code; no layering needed.

- `sys_session_close` → `_session_close_via_rest` (`runner/tool_dispatch.py`) POSTs `{"type": "stop_session"}` (Claude wrapper)
  or `{"type": "interrupt"}` to `/v1/sessions/<child>/events` on the server, ignoring failures, then PATCHes the tombstone title.
- Server `routes_events.py`: `stop_session` calls `_stop_session_via_runner(session_id, runner_router)`
  (`_sessions/helpers.py`), which POSTs the stop to the runner serving the child. The runner kills the child's
  pane/harness (`NativeInterruptRunner` → `kill_session` incl. the fork's leftover-process SIGKILL). This step is
  not guarded by #10251.
- #10251's `_owns_host_runner(conv, store)` gates only the *host-level* runner stop afterwards
  (`_stop_host_runner_intentionally`, in the `stop_session` branch, `_archive_stop`, and `_launch_runner_on_host_locked`'s
  superseded-runner reap). For a child riding its parent's shared runner it returns False, so the shared runner stays up
  while the child's harness/pane has already been stopped by the runner-level step. Therefore #10251 cannot prevent the trio
  child's harness from being stopped, and kill-on-close does not touch the shared runner. The `interrupt` event path (non-Claude
  children) never reaches the host stop at all.
- Existing coverage: upstream `tests/server/integration/test_session_host_launch.py::test_stopping_child_does_not_stop_parents_shared_runner`
  and `tests/server/test_host_runner_ownership.py` (ownership rule); fork `tests/runner/test_runner_dispatch.py::test_session_close_*`
  (stop event sent, tombstone still written when the stop fails). Note: the `test_session_host_launch.py` integration tests
  hang (pytest-timeout) in this environment on pristine v0.21.0rc1 too (checked with
  `test_stopping_child_does_not_stop_parents_shared_runner`), so they could not be run here; I did not add an unverifiable test.

## Pre-existing failures (deselected)

All 50 failures of `tests/runner/test_app_sessions_native_events_lifecycle.py` fail identically on pristine v0.21.0rc1
(detached worktree, `TMPDIR=/var/tmp/pytest-of-coder uv run --frozen --extra all --group dev pytest -q -p no:cacheprovider tests/runner/test_app_sessions_native_events_lifecycle.py`
→ `50 failed, 64 passed`); the failing node-id set is identical to the port's before deselecting (`comm` of the two sets is empty).
Typical failure line: `AssertionError: codex-native model_change must return 204; got 503: {"error":"codex_native_settings_update_failed","detail":"Codex-native settings update requires a loaded Codex bridge."}`.
The 50 ids are listed in `docs/v21-evidence/deselects/v21-port-close.args`.
With them deselected the targeted check is green.

## Dispositions

| # | v17 sha | subject | disposition | new sha | notes |
| --- | --- | --- | --- | --- | --- |
| 1 | 4f1fc58f8 | v17-baseline: add v17 focused-suite runner | ported | 8493f640c | Historical evidence script, unchanged. |
| 2 | 8f7f924c2 | kill-on-close: stop the target harness on sys_session_close | adapted | ba43bd520 | Conflicts in bridge.py / test_runner_dispatch.py resolved as above; follow-up f6fc77242 (+ c9e200827 format). |
| 3 | fb38228b0 | port-v14-close: adapt kill-on-close pick (wrapper label import, bridge module path) | ported | d56bf2d8e | Clean. |
| 4 | 033e6837e | codex-bridge-owner: serve Codex model options from a labeled live bridge | adapted | 177b7a77f | Follow-up 27da4e27e for upstream's (state, bridge_dir) refactor. |
| 5 | 561681c55 | compact-on-fork-cross-harness: replay summary-only Codex compaction markers | ported | cb5c7c492 | Clean. |
| 6 | 669e05bfd | session-contract: alias _resolve_agent_spec to _resolve_subagent_spec | ported | c366fd184 | Clean; re-export still present on rc1. |
| 7 | ab9d2c7cb | close-guard: close tree-scoped children with unparsable titles | ported | c1ab67984 | Clean. |
| 8 | 2eed26a21 | port-v14-close: disposition notes for v14 close slice | ported | 9d4b414e8 | Clean (v16 evidence note). |
| 9 | 2f74c179a | v17-port-close: ruff-format fork hunks in runner/app.py and tool_dispatch.py | ported | 2837f48a0 | Clean. |
| 10 | 88344b862 | v17-port-close: disposition notes | ported | 7ab19d2e1 | Clean (v17 evidence note). |
| 11 | b1c8373de | v17-baseline: focused-suite runner and pristine v0.17.0 baseline | ported | 5f1b63f04 | Historical evidence, unchanged. |
