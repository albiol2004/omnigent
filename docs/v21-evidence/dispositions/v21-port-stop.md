# v21-port-stop — v17 "stop" group re-ported onto v0.21.0rc1

Method: `git cherry-pick -x` of the v17 commits #12-22 in original order on top of v21-port-close.

**Completed by the Lead (review call):** the builder's harness denied `git cherry-pick -x 9d7976a0d`; the Lead
picked #21 `9d7976a0d` -> `58fd53ffb` and #22 `48757757d` -> `9bbbc9552` (both clean) and adapted the README fork
section for v0.21.0rc1 in `83fc04a14` (`slice(v21-port-stop): README for v0.21.0rc1`).

## Conflicts and how they were resolved (upstream v0.21.0rc1 kept, fork layered on top)

- **#12 30764d7e9 stop-routing** — `omnigent/runner/native/interrupt.py`: upstream added opencode (interrupt via
  `POST /api/session/{id}/interrupt`, stop aliased to interrupt) and the eighth uniform interrupt harness. Kept all of it;
  the fork's `_codex_stop` is added and `stop()` routes `codex` to it, `pi`/`opencode` still alias to interrupt. Upstream
  dropped the `_session_labels_for_runner_spawn` import from this module, so only `teardown_codex_native_app_server` is
  imported on top. `tests/harnesses/codex_native/test_codex_native_bridge.py`: both upstream's new tests and the fork's
  `kill_session` tests kept. `tests/runner/test_runner_dispatch.py`: kept `SESSION_AGENT_MISSING_MESSAGE` import, added
  the Codex/Cursor wrapper imports.
- **#13 150efd6ff kill-escalation** — the port-close slice had already inlined the pane-pid capture + leftover SIGKILL in
  `claude_native/bridge.py::kill_session` (and its helpers/constants). Replaced those with the shared
  `omnigent/native_tmux_kill.py` helper (new file); upstream's kill markers (`_OMNIGENT_KILL_FILE` /
  `_EXPECTED_CLOSE_FILE`, `allow_missing_target=True`, marker unlink on failure) are kept around the helper call. Removed
  the now-duplicate `_tmux_pane_pid` / `_recorded_tmux_pid` / `_kill_leftover_tmux_process` and the duplicated
  `_TMUX_KILL_VERIFY_*` constants. Codex bridge keeps upstream's `CertificateFailure` / `policy_allow_cache` /
  `DATA_DIR_ENV_VAR` imports plus `native_tmux_kill`.
- **#14 a526deb64** — only `omnigent.inner._proc` import dropped; upstream's `in_managed_sandbox` import kept.
- **#15 958ee4c24 reaper** — upstream (#12200/#12153) had rewritten `_native_pane_is_busy` (screen-diff via
  `TerminalInstance.screen_changed_within`, `_server_confirms_turn_in_flight`, replaced-pane re-check in the reap).
  Kept all of it and moved the busy decision into `pane_reaper._pane_is_busy_after_harness`, which gained two optional
  parameters (`screen_changed_within`, `server_confirms_turn_in_flight`) so the fork's orphaned-pane rule (harness
  subprocess released => stale `running` status and TUI redraw activity no longer pin the pane; only recent human input
  does) sits on top of upstream's signals. Upstream's `resolve_native_pane_idle_timeout_s(default_timeout_s)` signature and
  the early `approval_wait_is_fresh` check are kept. All upstream reaper tests and the fork's helper tests pass.
- **#16 54f5172bf codex-advertise-guard** — `test_app_sessions_native_events_options.py`: upstream added
  `test_events_clear_on_codex_native_types_clear_into_the_tui` right above the test the fork edits; both kept, fork stub
  applied to the compact-503 test.
- **#17-#20** — applied cleanly (README fork section and historical v14/v16 evidence).

Follow-up commits:

- `1febb04f9` ruff-format of fork hunks (pick conflict resolutions + reaper helper extension).
- `61ff5dbdf` upstream's `test_events_codex_native_stop_clears_resolved_bridge_not_conv_default[stop_session]` drives
  `stop_session` against a codex bridge under a label-resolved (non-conv-id) id. The fork's `_codex_stop` used the conv-id
  default dir. It now uses the same `codex_bridge_state_for_session` lookup as interrupt (skipping the kill if the bridge
  belongs to another session), clears the killed turn's recorded id, and notes the session idle. The fork's unit tests
  now inject the lookup instead of patching `bridge_dir_for_bridge_id`; the fake registry gained
  `note_external_session_status`.

## Pristine-proven deselects

42 node ids (see `docs/v21-evidence/deselects/v21-port-stop.args`), all in
`tests/runner/test_app_sessions_native_events_lifecycle.py` (claude-native model options, codex-native settings/effort,
codex side-chat interrupt). All are also listed in `docs/v21-evidence/baseline-v0.21.0rc1.txt` and were re-run on a detached
pristine `v0.21.0rc1` worktree:

```
cd <rc1 worktree> && TMPDIR=/var/tmp/pytest-of-coder uv run --frozen --extra all --group dev pytest -q -p no:cacheprovider <42 node ids>
42 failed in 306.58s (0:05:06)
E       AssertionError: assert {'models': [{...-4-10', ...}]} == {'models': [{...-opus-4-10'}]}   (first failure)
```

| # | v17 sha | subject | disposition | new sha | notes |
|---|---|---|---|---|---|
| 12 | 30764d7e9 | slice(stop-routing): hard-stop Claude, Codex and Cursor on close | adapted | 46480dd27 | interrupt.py opencode/side-chat kept; `_codex_stop` added; follow-up 61ff5dbdf |
| 13 | 150efd6ff | slice(kill-escalation): share leftover-pane SIGKILL across native bridges | adapted | 665c6ce2c | claude kill_session now delegates to `native_tmux_kill`; upstream kill markers kept |
| 14 | a526deb64 | slice(port-v14-stop): drop unused _proc import and fix pre-split codex bridge test import | adapted | 3093f32b4 | `in_managed_sandbox` import kept |
| 15 | 958ee4c24 | slice(reaper): reap native panes after harness subprocess release | adapted | 0bb8d876b | helper extended with upstream screen-diff + server-confirm; #12200 idle timeout intact |
| 16 | 54f5172bf | slice(codex-advertise-guard): do not abort Codex auto-create when tmux advertise is missing | adapted | e21133d27 | options test: upstream `/clear` test kept |
| 17 | c69e6e76f | slice(readme): note trio-v0.14.0-fixes until live adopt | ported | 230289c25 | clean |
| 18 | 7e50a304d | docs(v14-report): summarize the 0.14.0 re-port disposition | ported | 0dfc26c9c | clean |
| 19 | 477b2e2e8 | slice(port-v14-stop): README adapted for v0.16.0 and disposition notes | ported | d173a98d0 | clean |
| 20 | 3c16f63ee | slice(port-v14-stop): clarify disposition note | ported | 2bc192c1f | clean |
| 21 | 9d7976a0d | slice(v17-port-stop): README for v0.17.0 | ported | 58fd53ffb | clean; `git log --format='%h %b' | grep -B1 'cherry picked from'` → `(cherry picked from commit 9d7976a0d58b4ebdfbcb4723e1d9f52336408444)` |
| 22 | 48757757d | slice(v17-port-stop): disposition notes | ported | 9bbbc9552 | clean; `(cherry picked from commit 48757757d7ad57fd4674863ba9b1f4db425bacb6)` |
