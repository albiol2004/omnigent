# PLAN — sys_session_close teardown, iteration 1

Iteration **1**. First Lead pass. Mailbox `loop-session-close/`.
Worktree `/home/coder/omnigent-dev`, branch
`trio-v0.12.0-fixes-close`. Do not touch `/home/coder/omnigent`,
do not `uv tool install`, do not start/stop any `omni` process,
do not bind port 6767, do not `git worktree`, switch branch, or
push.

## Objective (this iteration)

Close must tombstone tree-scoped native children even when the
session title is the verbatim `sys_session_create` string (no
`<agent>:<title>` parse). Close must hard-stop Claude, Codex and
Cursor (tmux kill + terminal teardown; Codex also tears down the
app-server). Share leftover-pane SIGKILL across those three
bridges. Confirm or disprove the harness-`release` / pane-reaper
orphaning hypothesis with a regression test and fix the actual
cause. Correct the README fork note.

## Verification standard

mode: `implement-then-verify`

- Tests only as
  `uv run --project /home/coder/omnigent-dev pytest -q <paths>`.
- Focused set (GOAL):
  `tests/runner/test_runner_dispatch.py`
  `tests/tools/builtins/test_sys_session.py`
  `tests/runner/test_native_interrupt_runner.py`
  `tests/test_claude_native_bridge.py`
  `tests/test_cursor_native_bridge.py`
  `tests/test_codex_native_bridge.py`
  `tests/terminals/test_pane_reaper.py`
- Then full directories: `tests/runner`, `tests/tools/builtins`,
  `tests/terminals`. No new skips.
- `uv run --project /home/coder/omnigent-dev ruff check` on
  touched files if ruff is configured.
- Save stdout/stderr under `loop-session-close/evidence/iter1/`.
- Workers must **not** ingest whole `tool_dispatch.py` or
  `app.py` (>10k lines). Use the line ranges below (`sed -n`).
- Commit gate (Lead, after product commits):
  `python3 /home/coder/personal/trio-agent-loop/metrics/trio-shadow.py --mailbox loop-session-close --require-commits`

## Diagnosed ranges (do not ingest whole files)

- `omnigent/runner/tool_dispatch.py`
  `_parse_session_title` ~4089-4113
  `_close_tree_scope_error` ~5525-5579
  `_session_close_via_rest` ~5582-5668 (title guard ~5630-5632;
  stop vs interrupt ~5636-5646)
  `_subagent_label` / snapshot agent fields ~1164-1178
  (GOAL's ~3007-3013 display analog; those lines are now
  bundle tar code — use `_subagent_label` + session
  `agent_id` / `tool` / `session_name`)
  wrapper imports ~52-53; add `CURSOR_NATIVE_WRAPPER_VALUE`
- `omnigent/tools/builtins/spawn.py`
  `_agent_title_from_conversation` ~1194-1221
  tree + parent gate ~1318-1334
  `SysSessionCloseTool` ~1693
- `omnigent/runner/native/interrupt.py`
  `_UNIFORM_STOP` ~207-244
  `stop()` ~291-311 (codex/pi → interrupt)
  `_uniform_stop` ~381-413
  `_codex_interrupt` ~481
  `_claude_stop` ~438-479 (pattern for Codex stop)
  `_teardown_session_terminals` ~328-355
- `omnigent/runner/native/orchestration.py`
  `teardown_codex_native_app_server` ~199
- `omnigent/claude_native_bridge.py`
  `kill_session` ~3278-3326
  `_tmux_pane_pid` ~3843-3872
  `_recorded_tmux_pid` ~3875-3880
  `_kill_leftover_tmux_process` ~3883-3894
- `omnigent/cursor_native_bridge.py`
  `kill_session` ~934-944
- `omnigent/codex_native_bridge.py`
  no `kill_session` today; add one mirroring Cursor
  (`tmux.json` + `tmux kill-session`). Scout the file for
  existing tmux helpers before inventing a second protocol.
- `omnigent/runner/app.py` **offset reads only**
  pane-reaper wiring ~10617-10686
  `_native_pane_status` ~2460, pop on delete ~3882
  busy uses status `"running"` ~10647
- `omnigent/terminals/pane_reaper.py` module + classify loop
- `omnigent/runtime/harnesses/process_manager.py`
  `release` ~1040-1109, `_idle_reaper_loop` ~1420-1455,
  `has_active_turn` ~980, `clear_in_flight` ~1025
- `omnigent/terminals/registry.py` `native_panes()` ~355
- Tests: `tests/runner/test_runner_dispatch.py` ~5850-6061
  `tests/tools/builtins/test_sys_session.py` ~776-823 and
  close invoke ~836+
  `tests/runner/test_native_interrupt_runner.py` ~285-333
  `tests/test_claude_native_bridge.py` ~3892-4000
  `tests/test_cursor_native_bridge.py`, `tests/test_codex_native_bridge.py`
  `tests/terminals/test_pane_reaper.py`
- README.md ~612-618
- Read-only runner log (reaper evidence, do not copy secrets):
  `/home/coder/.omnigent/logs/runner/runner-13839e479047419e8d446c50a2cca38f-20260915-140650-755225.log`

## Tasks

1. **Slice `close-guard`** — this iteration.
   After `_close_tree_scope_error` returns None, do **not**
   reject because `_parse_session_title` failed. Same for
   in-process close: parent-set is enough. Keep top-level
   (`parent_session_id` / `parent_conversation_id` None)
   as `session_not_a_sub_agent`. Registration-anchor
   `config_path` sessions with no parent stay non-closable.
   Tombstone agent/title from snapshot/conversation agent
   fields when the title has no colon (see `_subagent_label`).
   Tests in the existing close files.
   Done: unparsable in-tree child closes; top-level still
   rejected; no PATCH/tombstone for top-level.

2. **Slice `stop-routing`** — this iteration.
   REST close: `event_type=stop_session` for Claude, Codex
   and Cursor wrapper labels (and cheaply any `_UNIFORM_STOP`
   wrapper). `NativeInterruptRunner.stop`: real Codex stop
   (not interrupt) — `codex_native_bridge.kill_session`,
   `_teardown_session_terminals`,
   `teardown_codex_native_app_server`. Failed stop still
   tombstones.
   Done: tests show stop_session for the three wrappers;
   Codex stop test asserts kill + teardown + app-server
   teardown.

3. **Slice `kill-escalation`** — this iteration.
   Factor leftover-pane SIGKILL into one helper. Reuse from
   Claude, Codex, Cursor `kill_session`. Other bridges only
   if trivial. Keep files <200 lines for any **new** module.
   Done: Claude existing escalation tests still pass; Cursor
   and Codex gain equivalent leftover-pid tests.

4. **Slice `reaper`** — this iteration.
   Regression test for `process_manager.release` vs native
   pane reaper (cursor/codex/claude conv). If the hypothesis
   holds (release drops listing/busy-check state so the pane
   is never reaped), fix so idle panes still reap after
   harness subprocess release — or reap together. If
   disproved, fix the actual cause; do not leave the leak
   unexplained. Prefer tests in `tests/terminals/` and/or
   process_manager tests; `app.py` edits only in the
   10617-10686 / status-clear windows.
   Done: failing-then-fixed test; REPORT records confirmed
   or disproved with evidence.

5. **Slice `readme`** — this iteration.
   README fork note: live install is `trio-v0.12.0-fixes`;
   this branch `trio-v0.12.0-fixes-close` carries the close
   fix until adopted. No CHANGELOG unless recent fork
   commits added one (they did not).

## Out of scope

- `/home/coder/omnigent`, port 6767, `uv tool install`,
  starting/stopping `omni`, live server restarts, adoption
- Other mailboxes; GOAL.md / VERDICT.md edits
- Amend, rebase, push, AI coauthor trailers
- Untracked `.cursor/`
- Whole-file reads of `tool_dispatch.py` / `app.py`

## Delegation

GLM 5.2 (`glm-5.2-max`, `model_effort: max`) via
`trioctl omnigent run builder|scout --prompt-file <brief> --workspace .`
from this worktree only.

```
trioctl omnigent run scout --prompt-file loop-session-close/briefs/scout-reaper.md --workspace . --timeout 900
trioctl omnigent run scout --prompt-file loop-session-close/briefs/scout-codex-tmux.md --workspace . --timeout 600
trioctl omnigent run builder --prompt-file loop-session-close/briefs/close-guard.md --workspace . --timeout 1800
trioctl omnigent run builder --prompt-file loop-session-close/briefs/stop-routing.md --workspace . --timeout 1800
trioctl omnigent run builder --prompt-file loop-session-close/briefs/kill-escalation.md --workspace . --timeout 1800
trioctl omnigent run builder --prompt-file loop-session-close/briefs/reaper.md --workspace . --timeout 1800
trioctl omnigent run builder --prompt-file loop-session-close/briefs/readme.md --workspace . --timeout 600
```

```yaml
slices:
  - id: close-guard
    repo: .
    writes:
      - omnigent/runner/tool_dispatch.py
      - omnigent/tools/builtins/spawn.py
      - tests/runner/test_runner_dispatch.py
      - tests/tools/builtins/test_sys_session.py
    reads:
      - loop-session-close/GOAL.md
      - loop-session-close/PLAN.md
    gate: true
    status: complete
    iteration: 1
  - id: stop-routing
    repo: .
    writes:
      - omnigent/runner/tool_dispatch.py
      - omnigent/runner/native/interrupt.py
      - omnigent/codex_native_bridge.py
      - tests/runner/test_runner_dispatch.py
      - tests/runner/test_native_interrupt_runner.py
      - tests/test_codex_native_bridge.py
    reads:
      - loop-session-close/GOAL.md
      - loop-session-close/PLAN.md
    gate: true
    status: complete
    iteration: 1
  - id: kill-escalation
    repo: .
    writes:
      - omnigent/claude_native_bridge.py
      - omnigent/cursor_native_bridge.py
      - omnigent/codex_native_bridge.py
      - tests/test_claude_native_bridge.py
      - tests/test_cursor_native_bridge.py
      - tests/test_codex_native_bridge.py
    reads:
      - loop-session-close/GOAL.md
      - loop-session-close/PLAN.md
    gate: true
    status: complete
    iteration: 1
  - id: reaper
    repo: .
    writes:
      - omnigent/terminals/pane_reaper.py
      - omnigent/runtime/harnesses/process_manager.py
      - omnigent/runner/app.py
      - tests/terminals/test_pane_reaper.py
    reads:
      - loop-session-close/GOAL.md
      - loop-session-close/PLAN.md
    gate: true
    status: complete
    iteration: 1
  - id: readme
    repo: .
    writes:
      - README.md
    reads:
      - loop-session-close/GOAL.md
      - loop-session-close/PLAN.md
    gate: false
    status: complete
    iteration: 1
  - id: codex-advertise-guard
    repo: .
    writes:
      - omnigent/runner/native/orchestration.py
      - tests/runner/test_app_sessions_native_events_lifecycle.py
      - tests/runner/test_app_sessions_native_events_options.py
      - tests/runner/test_app_sessions_native_wake_forwarders.py
    reads:
      - loop-session-close/GOAL.md
      - loop-session-close/PLAN.md
    gate: true
    status: complete
    iteration: 1
```
