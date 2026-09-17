# REPORT — iteration 1 (Lead)

Mailbox: `loop-session-close/`. Worktree `/home/coder/omnigent-dev`,
branch `trio-v0.12.0-fixes-close`. Worker model: **glm-5.2-max** via
`trioctl omnigent run builder|scout --prompt-file <brief> --workspace .`
(`model_effort: max` in PLAN). Lead did not re-plan or re-implement
the five original slices; a sixth slice was added only because Lead
verification failed after those commits.

## Per-slice commits

| Slice | SHA | Summary |
| --- | --- | --- |
| close-guard | `cc40d1513` | Tree-scoped children with unparsable titles close; top-level still `session_not_a_sub_agent`. Tombstone from snapshot agent fields. |
| stop-routing | `97d84a2fc` | REST close POSTs `stop_session` for Claude, Codex, Cursor. Codex `kill_session` + terminal teardown + `teardown_codex_native_app_server`. Advertise `tmux.json` after Codex launch. |
| kill-escalation | `208aada58` | Shared leftover-pane SIGKILL in `omnigent/native_tmux_kill.py`; Claude/Codex/Cursor `kill_session` reuse it. |
| reaper | `eea0c6862` | After harness `release`, orphaned native panes are busy only if a tmux client is attached. Helper `_pane_is_busy_after_harness`. |
| readme | `d18393174` | Live install is `trio-v0.12.0-fixes`; this branch carries close/teardown until adopted. No CHANGELOG. |
| codex-advertise-guard | `ec696c5fc` | Follow-up: `getattr(resource_registry, "terminal_registry", None)` so missing advertise does not abort Codex auto-create; lifecycle/compact tests stub auto-create where they seed bridge state / assert no pane. |

## Reaper-orphaning hypothesis

**Hypothesis (GOAL):** `HarnessProcessManager.release` drops state that
`native_panes()` listing or the busy check depends on, so after the ~1h
harness idle reaper the native tmux pane is never pane-reaped.

**Scout verdict (`briefs/scout-reaper.md` +
`evidence/iter1/trioctl-scout-reaper.txt`): DISPROVED on mechanism.**
Symptom (idle Cursor panes surviving 15+ hours) is real; cause is not
a listing drop.

Evidence:

- `release` (~1040-1109) only pops `_entries`. It does not pop
  `_in_flight_response_ids` and does not touch terminals.
- `native_panes()` (`registry.py` 355-377) is registry-only. After
  `release` the pane **stays listed**.
- Busy check (`_native_pane_is_busy`) used `_native_pane_status ==
  "running"` (cleared only in `delete_session`) and tmux
  `window_activity` (<120s). Cursor TUI redraws keep both true.
- The 1h harness reaper is correlated, not causal. Two convs that
  went truly quiet were pane-reaped; five that kept redrawing were not.

**Actual cause:** after harness subprocess release, stale `"running"`
and redraw-driven `window_activity` pin the orphaned pane forever.

**Fix (slice reaper):** if a `process_manager` is wired and
`not has_session(conv_id)`, only an attached tmux client spares the
pane. Extracted to `pane_reaper._pane_is_busy_after_harness` so tests
do not import `app.py`.

**Reaper test (`tests/terminals/test_pane_reaper.py`):**
`test_busy_orphaned_stale_running_fresh_activity_no_clients_is_reapable`
asserts orphaned + stale `"running"` + fresh activity + no clients →
**not busy**. Also: live harness + `"running"` → busy; orphaned +
attached client → busy; in-flight turn → busy even with no session
entry. Builder reported `24 passed` on
`tests/terminals/test_pane_reaper.py`. Directory run after the slice
includes those tests in the Lead suite below.

## Test commands and results

Focused directories (Lead, after `ec696c5fc`):

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/runner tests/tools/builtins tests/terminals \
  tests/test_claude_native_bridge.py \
  tests/test_cursor_native_bridge.py \
  tests/test_codex_native_bridge.py
```

Saved: `evidence/iter1/pytest-final.txt`.

**Result: `5 failed, 2726 passed, 2 skipped, 4 xfailed, 7 warnings in 2487.86s (0:41:27)`**

Failures (not introduced by the close/teardown slices; not skipped):

1. `test_codex_native_model_options_follow_labeled_foreign_bridge` —
   GET model options 200; `model_change` on an owner-bound parent
   bridge returns **503**, test asserts **204**. Builder confirmed the
   same fail at the test's origin commit. Out of mission scope.
2. Four `tests/runner/test_uc_function.py` cases —
   `ModuleNotFoundError: No module named 'databricks'`. Env/optional
   extra, not close-path.

First Lead run (before advertise-guard) is in
`evidence/iter1/pytest-final.txt` history via
`pytest-dirs.txt` / the pre-fix capture: **19 failed** including
`AttributeError: '_FakeResourceRegistry' object has no attribute
'terminal_registry'` from Codex `tmux.json` advertise. After
`ec696c5fc`, those ten auto-create tests pass. Mid-fix capture:
`evidence/iter1/pytest-advertise-guard.txt` (`5 failed, 206 passed`
on the Codex subset; four of five remaining lifecycle fails then
fixed by the auto-create stub).

Per-slice builder pytest (glm-5.2-max captures under
`evidence/iter1/trioctl-builder-*.txt`):

- close-guard: 256 passed, 1 skipped (`test_runner_dispatch` +
  `test_sys_session`)
- stop-routing: 266 passed, 1 skipped
- kill-escalation: 326 passed (three native-bridge files)
- reaper: 24 passed (`test_pane_reaper.py`)
- readme: no pytest (docs only)
- advertise-guard: first `trioctl` timed out at 1800s after writing
  the product/test diffs; lifecycle follow-up builder: 4/5 targeted
  tests passed, labeled-bridge left failing as above

`ruff check` on advertise-guard files: all checks passed.

## Open risks

- Remaining 5 directory failures (UC/databricks; labeled-bridge 503
  vs 204). Evaluator should treat them as pre-existing unless a
  focused bisect shows otherwise.
- `sys_cancel_task` still routes Codex to `interrupt` (close path
  only was in scope).
- Reaper orphan fast-path is `process_manager`-gated; `None` PM
  keeps the old busy signals.
- README heading is still `## trio-v0.12.0-fixes (this worktree)`.
- Codex `kill_session` depends on `tmux.json` advertise; if launch
  has no `terminal_registry`, kill is best-effort (no advertised
  tmux), matching Cursor's missing-file behavior.
- Live install `/home/coder/omnigent` and port 6767 were not
  touched; adoption is the user's decision after Evaluator review.
- First advertise-guard `trioctl` hit the 1800s timeout; product
  diffs were kept and committed after a second builder + Lead verify.

## Handoff

Evaluator: re-run the same pytest command against
`ec696c5fc` (product HEAD before this mailbox commit) and confirm
Cursor/Codex close issues kill/teardown (unit/fake-transport, not
the live server). Commit gate:
`python3 /home/coder/personal/trio-agent-loop/metrics/trio-shadow.py --mailbox loop-session-close --require-commits`.
