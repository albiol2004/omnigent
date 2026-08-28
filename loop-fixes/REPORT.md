# REPORT — iter 1 Lead (resume after builders)

This pass reviewed the four builder trees, kept necessary out-of-writes
files on fork-oversize-guard, pinned SQLite to QueuePool (builders' pool
kwargs would TypeError on SQLAlchemy's sqlite SingletonThreadPool), ran
targeted verification, and committed four `slice(<id>):` commits.
`python3 /home/alex/pruebas/agent-trio-template/metrics/trio-shadow.py --mailbox loop-fixes --require-commits` → exit 0.

Luna model used by the builders: `gpt-5.6-luna-max` (profile-resolved).
This resume Lead did not re-dispatch Luna.

## slice sqlite-pool — `b47adae25`

Changed paths: `omnigent/db/utils.py`, `tests/db/test_utils.py`,
`tests/db/test_sqlite_pool_concurrency.py`.

Lead fix: pass `poolclass=QueuePool`. SQLite's dialect default rejects
`max_overflow` / `pool_timeout`. Env: `OMNIGENT_SQLITE_POOL_SIZE` (32),
`OMNIGENT_SQLITE_MAX_OVERFLOW` (20), `OMNIGENT_SQLITE_POOL_TIMEOUT_S`
(10, max 10). WAL connect-hook unchanged.

Commands:

```
uv run pytest -q tests/db
# 371 passed, 1 skipped in 110.78s

uv run pytest -q tests/db/test_sqlite_pool_concurrency.py \
  tests/db/test_utils.py::test_sqlite_engine_uses_pool_settings_and_enables_wal \
  tests/db/test_utils.py::test_sqlite_engine_honors_pool_environment_overrides
# 3 passed in 0.16s
```

Evidence: `loop-fixes/evidence/iter1/sqlite-pool/PYTEST.txt`.
Deviations: builders mentioned `README.md`; it was not in the tree.
Weakness: QueuePool + `check_same_thread=False` is the intended
multi-thread model; writes still serialize in SQLite.

## slice kill-on-close — `4f8f6f673`

Changed paths: `omnigent/runner/tool_dispatch.py`,
`omnigent/runner/native/interrupt.py`, `omnigent/claude_native_bridge.py`,
`tests/runner/test_runner_dispatch.py`,
`tests/runner/test_native_interrupt_runner.py`,
`tests/test_claude_native_bridge.py`,
`tests/inner/test_proc_and_platform.py`.

`sys_session_close` POSTs `stop_session` (claude-native) or `interrupt`
(else) before the tombstone PATCH; stop failure is suppressed.
`_claude_stop` cancels the auto-forwarder. After `tmux kill-session`,
escalates via `_proc._killpg` (refuses own pgid) with a 1s wait.

Commands:

```
uv run pytest -q tests/runner/test_runner_dispatch.py \
  tests/runner/test_native_interrupt_runner.py \
  tests/test_claude_native_bridge.py \
  tests/inner/test_proc_and_platform.py
# included in the 1314 passed / 8 skipped combined run below
```

Evidence: `loop-fixes/evidence/iter1/kill-on-close/` (`pytest.log`,
`fake_tmux_kill.py`). Kill-on-SSE-disconnect was not added.

Deviations: PLAN originally listed `omnigent/inner/_proc.py` in `writes:`;
the file was not changed (existing helpers). Removed from PLAN writes.

Weakness: stop is best-effort; a 404 stop still tombstones.

## slice fork-oversize-guard — `eabf6b101`

Changed paths: `omnigent/fork_context.py` (new), `omnigent/errors.py`,
`omnigent/server/routes/sessions/routes_core.py`,
`omnigent/runner/native/orchestration.py`, `omnigent/claude_native.py`,
`omnigent/inner/claude_sdk_executor.py`, `omnigent/codex_native.py`,
`omnigent/pi_native_resume.py`, `omnigent/qwen_native_bridge.py`,
`tests/inner/test_claude_sdk_fork_context_guard.py`,
`tests/runner/test_fork_context_guard.py`,
`tests/server/routes/test_fork_oversize_guard.py`.

`OMNIGENT_FORK_MAX_CONTEXT_BYTES` default 600000. Compaction markers
drop the covered prefix; still-oversize → `ForkContextTooLarge` / HTTP
413 `fork_context_too_large` naming actual and threshold bytes. Item
fetch paginates past limit 1000.

Out-of-writes kept as part of this slice (same fork/resume size hole):
`fork_context.py`, `errors.py`, `codex_native.py`, `pi_native_resume.py`,
`qwen_native_bridge.py`, plus the three new test files. Added to PLAN
`writes:`. README.md was not present in the diff (not reverted because
unchanged).

Commands:

```
uv run pytest -q tests/inner/test_claude_sdk_fork_context_guard.py \
  tests/runner/test_fork_context_guard.py \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_sessions_fork.py
# green in the combined 1314-pass run

python3 loop-fixes/evidence/iter1/fork-oversize-guard/measure_fork_context.py
# full_context_bytes 3907941 refused; compacted 134 allowed;
# oversized compacted 600093 refused
```

Evidence: `loop-fixes/evidence/iter1/fork-oversize-guard/`.

Weakness: route copies full items on fork when a compaction view would
fit; harness rebuild honors summary-only. SDK guard applies only to
full-history first prompts (`resume_session=False`), not trailing
resume turns.

## slice render-latency — `b0dc3bfaa`

Changed paths: `omnigent/cursor_native_forwarder.py`,
`omnigent/claude_native_forwarder.py`, `web/src/store/chatStore.ts`,
`tests/test_cursor_native_forwarder.py`,
`tests/test_claude_native_forwarder.py`, `web/src/store/chatStore.test.ts`.

Cursor poll 0.15s active / 0.7s idle (`OMNIGENT_CURSOR_POLL_FAST_S` /
`_IDLE_S`). Claude 0.1s / 0.25s (`OMNIGENT_CLAUDE_POLL_*`). Claude
batches one POST per message per poll. UI coalesces live deltas per rAF.

Commands:

```
uv run pytest -q tests/test_cursor_native_forwarder.py \
  tests/test_claude_native_forwarder.py
# green in the combined run

cd web && npx vitest run src/store/chatStore.test.ts
# Test Files 1 passed; Tests 352 passed in 1.64s
```

Evidence: `loop-fixes/evidence/iter1/render-latency/`.

## Cross-slice verification

```
uv run pytest -q tests/db tests/runner/test_runner_dispatch.py \
  tests/tools/builtins tests/server/integration/test_sessions_child_sessions.py \
  tests/test_claude_native_bridge.py tests/test_claude_native_forwarder.py \
  tests/test_cursor_native_forwarder.py tests/inner/test_proc_and_platform.py \
  tests/runner/test_native_interrupt_runner.py \
  tests/inner/test_claude_sdk_fork_context_guard.py \
  tests/runner/test_fork_context_guard.py \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_sessions_fork.py
# 1314 passed, 8 skipped in 154.79s

uv run pytest -q tests/tools/builtins/test_spawn.py \
  tests/runner/test_runner_dispatch.py \
  tests/server/integration/test_sessions_child_sessions.py \
  -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'
# 5 passed, 250 deselected in 2.31s
```

`uv run pre-commit run --files <all product files>`: ruff/pyrefly/prettier/tsc
passed. `web-oxlint` fails on pre-existing files (`Sidebar.tsx`,
`AppShell.tsx`, `ChatPage.tsx`, …) with **no** `chatStore` findings.
`SKIP=web-oxlint` is clean. Full `tests/runner` was not all-green on this
host: `test_app_sessions_native_events_lifecycle.py` already fails at
HEAD when Codex CLI is installed (auto-create hits “Terminal registry not
configured”). Confirmed by temporarily restoring HEAD product files.

## Isolation self-audit

| Check | Baseline | Now |
|---|---|---|
| `stat -c %Y ~/.omnigent` | 1787840749 | **1787900763** |
| `curl` `:6767/health` | 200 | **200** |
| `omni host` PID | 1270936 (then 888956 during the dead Lead) | **1270936** |

No throwaway servers on port ≥ 17000 were left. No `pytest` processes
remain. This pass did not start `omni host`, talk to `:6767`, or run git
in `/home/alex/omnigent`. `~/.omnigent` mtime advanced versus the mailbox
baseline (report only; not investigated).

## Operator deploy / rollback (GOAL Acceptance 4)

Deploy into the live install (`/home/alex/omnigent` or the running
checkout), **not** this worktree:

1. Fast-forward or check out `trio-v0.10.0-fixes` (commits `b47adae25`,
   `4f8f6f673`, `eabf6b101`, `b0dc3bfaa` on top of the Trio patches).
2. Rebuild web assets (chatStore changed): `cd web && npm run build`
   (or `just electron-build` if using the desktop shell).
3. Restart the Omnigent server and runner (`omni host` / runner) so
   Python picks up pool, close, fork, and forwarder changes.
4. Optional env: `OMNIGENT_SQLITE_*`, `OMNIGENT_FORK_MAX_CONTEXT_BYTES`,
   `OMNIGENT_CURSOR_POLL_*`, `OMNIGENT_CLAUDE_POLL_*`.

Rollback: `git checkout trio-v0.10.0` in that install, rebuild web if
you built it, restart server and runner.
