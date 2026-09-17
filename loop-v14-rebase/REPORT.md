# REPORT — iteration 1 (Lead)

Worktree `/home/coder/omnigent-dev`, branch `trio-v0.14.0-fixes`.
HEAD after this pass is the mailbox commit that lands this report.

## GLM workers

Resolved builder: `glm-5.2-max` / effort `max`
(`trioctl omnigent resolve builder --json`, captured in
`loop-v14-rebase/evidence/iter1/trioctl-resolve-builder.txt`).

No `trioctl omnigent run builder` invocation this iteration. Cherry-pick
conflicts were import-path / keep-both-tests hunks (not large-file
semantic merges). Lead resolved them in-tree against
`omnigent/harnesses/*`. Drop-candidate coverage used targeted pytest
rather than a scout.

`trioctl omnigent doctor` from this worktree: **all PASS**, including
`omnigent:session-contract` (evidence:
`loop-v14-rebase/evidence/iter1/trioctl-doctor.txt`). Trioctl should
still be updated to import `_resolve_subagent_spec` (or a public
name); the alias is a compatibility seam, not the long-term contract.

## Per-commit disposition

| sha | subject | verdict | reason |
|-----|---------|---------|--------|
| 760441438 | kill-on-close | **kept** | Cherry-picked `-x` as `5837d559d`. Claude leftover SIGKILL + close POST stop/interrupt; kept upstream `archived=True`. |
| 4292b1a7d | queue-aware yolo | **kept** | Clean pick `49da161cd`. v0.14.0 still had pre-queue `_yolo_auto_accept`. |
| 6d97d3ecc | phantom yolo cards | **kept** | Pick `a60a600d7` (import conflict only). |
| c04442f16 | launch args from root spec | **dropped** | Upstream `test_native_subagent_yolo_args_derived_from_trusted_spec` (claude/codex/cursor) **3 passed** on pristine v0.14.0. |
| 0c8082af2 | Codex writer-resume as loaded | **dropped** | New resume reaps leftover writers; `test_is_unreadable_thread_error` requires active-writer to fail loud (`7 passed` on preload/unreadable filters). Applying the fork would fight #7055/#7147. |
| c1128dc3c | Codex labeled-bridge model options | **kept** | Pick `3444f699f` + test adapt `314f6a933`. Read-only model options follow a labeled foreign bridge; mutations stay owner-bound. |
| 6bb85ac39 | summary-only compaction | **kept** | Clean pick `4dfbe128d`. `test_rollout_records_summary_only_compaction_replays_summary` passed. |
| fd38b1ea8 | re-export `_resolve_agent_spec` | **kept as alias** | Pick `69db59457` imported a missing helpers symbol; follow-ups `70d652bbc` + `5a2abe8b9` alias `_resolve_agent_spec = _resolve_subagent_spec` after imports. Doctor session-contract PASS. |
| 96b5639d8 | Claude compacted resume (#6364) | **dropped** | CHANGELOG #6364 + `test_claude_transcript_records_handles_native_compaction_messages` **1 passed**. |
| cc40d1513 | close-guard | **kept** | Clean pick `c7a454a78`. `test_close_accepts_child_with_unparsable_title` passed. |
| 97d84a2fc | stop-routing | **kept** | Pick `41d82337d` + import-path fix `694476595`. Codex `kill_session` + `_codex_stop`; Cursor in `_UNIFORM_STOP`. |
| 208aada58 | kill-escalation | **kept** | Pick `4e4b88928`. Shared `omnigent/native_tmux_kill.py`. |
| eea0c6862 | pane reaper after release | **kept** | Pick `642b879d7`. Merged with upstream `approval_wait_is_fresh` so parked approval cards stay busy. |
| d18393174 / 005399286 | README fork notes | **rewritten** | `c20f65e54` `slice(readme)` for `trio-v0.14.0-fixes` on stock v0.14.0; live install still `trio-v0.12.0-fixes`. |
| 6220807f3…863d1cf97 | loop-session-close mailbox | **restored** | `git checkout trio-v0.12.0-fixes -- loop-session-close` → `043c00ec7`. |
| ec696c5fc | Codex advertise guard | **kept** | Clean pick `305ac7cf7`. |

## Baseline vs branch

Full `tests/runner` (2535 items, one process) aborted at ~14% / ~32m
(memory/time). Baseline and post-port comparison used the GOAL focused
set, `tests/tools`, `tests/terminals`, and current bridge files
(paths unchanged vs v0.12: `tests/test_*_native_bridge.py`).

Pristine summaries: `loop-v14-rebase/evidence/baseline-v0.14.0.txt`

| surface | baseline | after ports |
|---------|----------|-------------|
| test_runner_dispatch.py | 270 passed, 1 skipped | 274 passed, 1 skipped |
| test_native_interrupt_runner.py | 15 passed | 18 passed after import-path fix (3 failed on old module names, then fixed) |
| test_sys_session.py | 44 passed | 45 passed |
| tests/terminals | 91 passed, 1 skipped | 100 passed, 1 skipped |
| tests/tools | 952 passed | not re-run in full (memory); sys_session + builtins close cases passed |
| claude/codex/cursor bridges + permissions | 392+44+24+59 passed | 529 passed together |
| drop-candidate filters | all passed | n/a (not re-ported) |

Zero new focused failures vs baseline. New tests from kept patches all
pass. Interrupt retry: `evidence/iter1/pytest-interrupt-retry.txt`
(91 passed with pane_reaper + codex bridge).

Fake-transport: `test_codex_stop_kills_tears_down_and_goes_idle`,
Claude stop forwarder-cancel, Cursor `kill_session` tests issue
kill + teardown without a live server.

## Verification extras

- ruff on touched product/test files: All checks passed
  (`evidence/iter1/ruff.txt`).
- Old-import grep on `*.py`: empty
  (`evidence/iter1/old-import-grep.txt`). Residual string hits live
  only in upstream docs/designs (`docs/QWEN_FOLLOWUPS.md`,
  `designs/opencode-native-gaps-qa.md`, `docs/cursor-native-cost-tracking.md`).
- Isolated smoke: `OMNIGENT_DATA_DIR=/tmp/omnigent-dev-data`
  `omni server --port 7767`. `GET /health` → 200 `{"status":"ok"}`.
  Server stopped afterwards. Live 6767 (`omni` pid 765) untouched.
  No migration warnings on stdout. Evidence:
  `evidence/iter1/dev-server-smoke.txt`.

## Upstream overlap (not a substitute for our close path)

- #6364 compacted Claude resume — drop 96b5639d8.
- #6156/#6388 `_derive_terminal_launch_args_from_spec` /
  `_resolve_subagent_spec` — drop c04442f16; alias fd38b1ea8.
- Codex resume rewrite (#7055/#7147/#7101) + writer reap — drop 0c8082af2.
- #5919 cancel hard-stop (`native_cancel_capability` → `stop` for
  `_UNIFORM_STOP` keys) is the **cancel** path. Close still needed
  the title-parse guard, explicit `stop_session` POST, Codex
  `kill_session`, and leftover SIGKILL. #7498 remains open.
- v0.14.0 close PATCH already sets `archived=True`; keepers add the
  events POST beside it, not instead of it.
- Pane reaper gained `approval_wait_is_fresh`; kept that in front of
  the harness-release busy helper.

## Follow-ups (not this iteration)

- Update trioctl doctor to import `_resolve_subagent_spec`.
- Optional: move `omnigent/native_tmux_kill.py` under `omnigent/native/`.
- Full `tests/runner` directory still too large for one process here.
