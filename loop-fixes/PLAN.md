# PLAN — iter 1: land sqlite-pool + kill-on-close (wave 1)

## Objective
Ship the four diagnosed production fixes from `loop/REPORT.md` as
independent `slice(<id>):` commits on `trio-v0.10.0-fixes`, without
touching the live install. Iteration 1 lands all four slices.

## Verification standard
Mode: **test-first**. Each slice must add or extend tests, run them
green, keep `pre-commit run --files <changed>` clean, and drop
behavioral evidence under `loop-fixes/evidence/iter1/<slice>/` against
a throwaway data dir / temp sqlite / fake subprocess — never
`~/.omnigent` or `:6767`.

## Slices

### 1. sqlite-pool
status: complete
writes: [omnigent/db/utils.py, tests/db/test_utils.py, tests/db/test_sqlite_pool_concurrency.py]

Give sqlite `create_engine` (`omnigent/db/utils.py:228-238`) an
explicit QueuePool: env-overridable `OMNIGENT_SQLITE_POOL_SIZE`,
`OMNIGENT_SQLITE_MAX_OVERFLOW`, `OMNIGENT_SQLITE_POOL_TIMEOUT_S`
(timeout ≤ 10 s), `pool_pre_ping=True`. Keep the existing connect-hook
WAL / `busy_timeout` (`:247-256`). Postgres block (`:268-289`) is the
spirit, not the 200-conn size.

Done: 20+ concurrent checkout-like calls against a temp sqlite DB
complete without a 30 s QueuePool wait; `uv run pytest -q tests/db`
green; evidence in `loop-fixes/evidence/iter1/sqlite-pool/`.

### 2. kill-on-close
status: complete
writes: [omnigent/runner/tool_dispatch.py, omnigent/runner/native/interrupt.py, omnigent/claude_native_bridge.py, tests/runner/test_runner_dispatch.py, tests/runner/test_native_interrupt_runner.py, tests/test_claude_native_bridge.py, tests/inner/test_proc_and_platform.py]

(a) `sys_session_close` (`tool_dispatch.py:4934-5005`) POSTs the same
stop as the UI / `_cancel_subagent_task` (`:7076-7087`) before/with the
tombstone PATCH; sibling sessions must stay alive.
(b) `_claude_stop` (`interrupt.py:438-472`) cancels the auto-forwarder
like `_uniform_stop` (`:396`).
(c) After `tmux kill-session` (`claude_native_bridge.py:3139-3174`),
verify the pane/pgid is gone; escalate SIGKILL of recorded pgid/pids
via `_proc.py` helpers with a bounded wait; never signal our own pgid.
Do **not** add kill-on-SSE-disconnect.

Done: unit tests with fake subprocess/tmux for each path; closed
session process tree gone in a throwaway script; targeted pytest
green; evidence in `loop-fixes/evidence/iter1/kill-on-close/`.

### 3. fork-oversize-guard
status: complete
writes: [omnigent/fork_context.py, omnigent/errors.py, omnigent/server/routes/sessions/routes_core.py, omnigent/runner/native/orchestration.py, omnigent/claude_native.py, omnigent/inner/claude_sdk_executor.py, omnigent/codex_native.py, omnigent/pi_native_resume.py, omnigent/qwen_native_bridge.py, tests/inner/test_claude_sdk_fork_context_guard.py, tests/runner/test_fork_context_guard.py, tests/server/routes/test_fork_oversize_guard.py]

On fork, measure bytes/approx tokens the target harness would receive;
if above `OMNIGENT_FORK_MAX_CONTEXT_BYTES` (default ~600 kB) refuse
with a 4xx naming size+threshold, after honoring summary-only
compaction. Paginate item fetch past `limit: 1000`
(`claude_native.py:4223`). Small sessions fork unchanged.

Done: ~3.9 MB synthetic from
`loop/evidence/iter1/rc-fork/scratch/measure_fork_bytes.py` is
refused/compacted; tests for threshold, compaction, pagination;
evidence in `loop-fixes/evidence/iter1/fork-oversize-guard/`.

### 4. render-latency
status: complete
writes: [omnigent/cursor_native_forwarder.py, omnigent/claude_native_forwarder.py, web/src/store/chatStore.ts, tests/test_cursor_native_forwarder.py, tests/test_claude_native_forwarder.py, web/src/store/chatStore.test.ts]

(a) cursor-native poll 0.7 s → adaptive ~0.15 s while arriving, back
off to 0.7 s idle, env-overridable.
(b) claude-native poll 0.25 → 0.1 s + idle backoff; batch per-delta
POSTs (`claude_native_forwarder.py:3962-3995`, `:4041-4062`) into one
POST per poll tick, order preserved.
(c) UI `tapLiveDeltas`/`applyLiveDelta` (`chatStore.ts:4292-4327`,
`:4371-4393`) coalesce per rAF like the generic pump (`:4152-4183`).

Done: python unit tests for backoff+batching; vitest for store
coalescing; measured cadence vs
`loop/evidence/iter1/rc-render/TIMING.md`; evidence in
`loop-fixes/evidence/iter1/render-latency/`.

## Out of scope
- Live `~/.omnigent`, `~/.claude/projects`, `~/.cursor`, `:6767`,
  `omni host` PID 1270936, `/home/alex/omnigent`.
- Kill-on-SSE-disconnect (deferred; note in REPORT).
- HTTP/2, sidebar WS rescan, hydrate/SSE reorder, competing teardown
  vs #4976, route/store rewrites vs #5603/#5405.
- Amending/rebasing Trio patches `480b6eea9`, `780962a5d`, `ead098caf`.
- Editing `GOAL.md` / `VERDICT.md`. Pushing. Touching other git
  worktrees of this repo.

```yaml
slices:
  - id: sqlite-pool
    repo: .
    writes: [omnigent/db/utils.py, tests/db/test_utils.py, tests/db/test_sqlite_pool_concurrency.py]
    reads: []
    status: complete
    iteration: 1
  - id: kill-on-close
    repo: .
    writes: [omnigent/runner/tool_dispatch.py, omnigent/runner/native/interrupt.py, omnigent/claude_native_bridge.py, tests/runner/test_runner_dispatch.py, tests/runner/test_native_interrupt_runner.py, tests/test_claude_native_bridge.py, tests/inner/test_proc_and_platform.py]
    reads: []
    status: complete
    iteration: 1
  - id: fork-oversize-guard
    repo: .
    writes: [omnigent/fork_context.py, omnigent/errors.py, omnigent/server/routes/sessions/routes_core.py, omnigent/runner/native/orchestration.py, omnigent/claude_native.py, omnigent/inner/claude_sdk_executor.py, omnigent/codex_native.py, omnigent/pi_native_resume.py, omnigent/qwen_native_bridge.py, tests/inner/test_claude_sdk_fork_context_guard.py, tests/runner/test_fork_context_guard.py, tests/server/routes/test_fork_oversize_guard.py]
    reads: []
    status: complete
    iteration: 1
  - id: render-latency
    repo: .
    writes: [omnigent/cursor_native_forwarder.py, omnigent/claude_native_forwarder.py, web/src/store/chatStore.ts, tests/test_cursor_native_forwarder.py, tests/test_claude_native_forwarder.py, web/src/store/chatStore.test.ts]
    reads: []
    status: complete
    iteration: 1
```

