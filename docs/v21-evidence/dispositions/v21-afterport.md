# v21-afterport — after-port focused suite, suite comparison, upstream-overlap check

Tip under test: all 78 v17 product commits cherry-picked onto `v0.21.0rc1` (code rev `afc642cd7`; later commits only touch
`scripts/` and `docs/v21-evidence/`, no `omnigent/` or `tests/` change).

## What was run

| what | command | result |
|---|---|---|
| after-port suite (11 groups, one invocation per group, same script/knobs as the baseline) | `TMPDIR=/var/tmp/pytest-of-coder V21_USE_TRIO_TEST=1 V21_ONLY=<group> bash scripts/v21_focused_suite.sh` → `docs/v21-evidence/after-port.txt` | 10 groups green apart from pre-existing failures, sessions-routes = pre-existing hang (below) |
| comparison | `python3 -I scripts/v21_compare_suites.py docs/v21-evidence/baseline-v0.21.0rc1.txt docs/v21-evidence/after-port.txt` | `REGRESSIONS: 0`, exit 0 |
| per-file breakdown of the hanging group, tip and pristine detached worktree of `v0.21.0rc1` (removed afterwards) | `V21_PER_FILE=1 V21_ONLY=sessions-routes V21_PYTEST_ARGS="--timeout=60"` (+ a second pair with `--capture=sys --timeout=120`) → `docs/v21-evidence/after-port-perfile.txt` | see below |
| upstream overlap | `bash scripts/v21_overlap_check.sh` → `docs/v21-evidence/overlap-check.txt` | exit 0, all 12 PRs, 0 absent / 0 moved lines |

Runner knobs added to `scripts/v21_focused_suite.sh` (all opt-in, default output unchanged): `V21_PER_FILE=1`
(one pytest process per file, header `== <group> :: <file> ==`), `V21_TT_FRESH=1` (`trio-test --fresh`; the first run of this
slice hit a stale cached `rc=2` because the worktree `.venv` had no pytest until `uv sync --frozen --extra all --group dev`),
`V21_PYTEST_ARGS` (extra pytest args, e.g. `--timeout=60`).

## Per-group result (baseline → tip)

| group | baseline (pristine rc1) | after-port (tip) |
|---|---|---|
| dispatch | 313 passed, 1 skipped | 317 passed, 1 skipped |
| interrupt | 25 passed | 28 passed |
| runner-native | 51 failed, 704 passed | 42 failed, 792 passed |
| sys-session | 60 passed | 61 passed |
| terminals | 177 passed, 2 skipped | 188 passed, 2 skipped |
| claude-native | 2327 passed, 1 skipped | 2328 passed, 1 skipped |
| codex-native | 1895 passed | 1925 passed |
| cursor-native | 267 passed | 561 passed (fork receipt/fence tests) |
| inner-proc | 45 passed, 8 skipped | 46 passed, 8 skipped |
| host | 1 failed, 407 passed | 1 failed, 408 passed |
| sessions-routes | PYTEST-TIMEOUT-HANG | PYTEST-TIMEOUT-HANG (same, see below) |

* No new FAILED/ERROR id. PRE-EXISTING (fail in both): 42 runner-native ids (the `.args` deselect list of v21-port-close, all
  "Codex-native settings update requires a loaded Codex bridge"-class failures) + `tests/host/test_connect.py::test_run_host_process_announces_session_log_dir_on_start`.
* FIXED BY PORT: 9 runner-native codex-native ids fail on pristine and pass at the tip (stop/interrupt/settings-change paths
  that the fork's v17 commits reworked). Not claimed as intended fixes — the compare script just lists them.

## sessions-routes: the hang is environmental, not caused by the port

* The group hangs on pristine v0.21.0rc1 as well (baseline) and at the tip. Per-file (`after-port-perfile.txt`, default capture,
  `--timeout=60`): on pristine all 3 files hang (`test_sessions_compact`, `test_routes_sessions_aliases`, `test_routes_sessions_title`);
  at the tip those 3 plus the fork-added `test_input_fence`, `test_cursor_receipt_binding_e2e`, `test_cursor_receipt_epoch_clear_e2e`
  hang; `test_cursor_cold_start_prompt` passes (it does not post a bundle). The baseline note's "title passes alone" does not
  reproduce: the title file hangs on pristine too.
* **Cause (≤20 min time-box, located but not root-caused down to the OS call):** the hang only happens under pytest's default
  **fd-level output capture** (`--capture=fd`). With `--capture=sys` (or `-s`) the very same tests pass:
  `test_list_sessions_search_query_filters_by_title` hangs under `--capture=fd` (also with stdin `</dev/null`), passes in 2.9 s with
  `--capture=sys` and `-s`. Not network, not #10906 bundle validation: an asyncio-task dump (debug plugin, not committed) of the
  hung test shows the test task awaiting `httpx.ASGITransport` → `starlette BaseHTTPMiddleware.call_next` → the request task blocked
  in `fastapi.dependencies.utils.solve_dependencies` → `run_in_threadpool(require_json_or_multipart_content_type)` (a trivial
  sync dependency in `omnigent/server/routes/_content_type.py`, used on `POST /v1/sessions`) → `anyio …run_sync_in_worker_thread`
  never returns; the single AnyIO worker thread is idle in `queue.get()`, and the event-loop thread sits in
  `selector_events._read_from_self → self._ssock.recv` (the loop's wake-up self-pipe), i.e. the worker's `call_soon_threadsafe`
  wake-up is lost/blocked under fd capture in this environment. Any request that solves a *sync* FastAPI dependency in the
  threadpool is affected; multipart session create is simply the first such call in these files.
* **With `--capture=sys --timeout=120` every file of the group completes on both sides** (`after-port-perfile.txt`, records
  `*-capsys`): pristine 11+9+1 = 21 passed (3 files); tip 14+17+6+14+5+9+1 = 66 passed (7 files) — including all fork-added files
  (`test_input_fence` 17, `test_cursor_*` 25) and the 3 extra tests the fork added to `test_sessions_compact`. So the regression
  signal for sessions-routes is real at the tip: **0 failures**.
* Extra check for #10251 (these also sit behind the same hang under fd capture):
  `--capture=sys` on `tests/server/test_host_runner_ownership.py tests/server/integration/test_session_host_launch.py` →
  `108 passed` (incl. `test_stopping_child_does_not_stop_parents_shared_runner`).
* **For iteration 2:** the Trio driver uploads bundles through a real server process (`POST /v1/sessions` multipart), not through
  pytest's captured in-process ASGI client, so it should not hit this. If a test run of server integration tests must be
  trusted, run those files with `--capture=sys` (or `-s`); an fd-capture run reports a hang, not a failure.

## compare script rule for the hang

`scripts/v21_compare_suites.py` only excuses an AFTER hang when the BASELINE group hangs the same way, the per-file record shows
every file that hangs at the tip also hangs on pristine, no new failing ids, every file absent on pristine passes at the tip
(default record or `tip-capsys`), and every `tip-capsys` file completes without new failures. Negative checks done: an appended
`FAILED` id → `REGRESSIONS: 1`/exit 1; a record without `SUITE_DONE` → exit 2; no per-file record → the hang counts as a regression.

## #10251 (shared host runner stays up) vs the fork's kill-on-close

They act on different layers and coexist:

1. `sys_session_close` → `_session_close_via_rest` (`omnigent/runner/tool_dispatch.py`) POSTs `{"type": "stop_session"}` (Claude
   wrapper; `interrupt` for the others) to `/v1/sessions/<child>/events`, then tombstones the title.
2. Server `omnigent/server/routes/sessions/routes_events.py:1941` `_stop_session_via_runner(...)` delivers the stop to the runner
   serving the child; the runner's `NativeInterruptRunner` calls `claude_native/bridge.py:4866 kill_session`, which runs
   `native_tmux_kill.kill_session_with_escalation` (`omnigent/native_tmux_kill.py:116`; fork: resolve the pane pid, tmux
   `kill-session`, SIGKILL the leftover group) at bridge.py:4918. This kills the **child's pane/harness** and is not guarded by #10251.
3. Only afterwards does #10251's `_owns_host_runner` (`omnigent/server/routes/_sessions/helpers.py:6134`) gate the **host-level
   runner stop**: `routes_events.py:1977` (stop_session), `_sessions/orchestration.py:1018` (archive stop) and
   `_sessions/helpers.py:6373` (superseded-runner reap). A child riding its parent's shared runner returns False, so the shared
   runner stays alive while the child's pane was already killed in step 2.

Tests: upstream `tests/server/integration/test_session_host_launch.py::test_stopping_child_does_not_stop_parents_shared_runner`
and `tests/server/test_host_runner_ownership.py` (ownership rule; 108 passed under `--capture=sys`, see above); fork
`tests/harnesses/claude_native/test_claude_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill`
(+`test_kill_session_*`, claude-native group green) and `tests/runner/test_runner_dispatch.py::test_session_close_routes_native_wrappers_to_stop_session`,
`test_session_close_tombstones_when_target_stop_fails` (dispatch group green).

## Overlap check

`bash scripts/v21_overlap_check.sh`: 12 upstream PR commits (all verified ancestors of `v0.21.0rc1`, subjects match the PR numbers),
3,536 checked lines, **0 absent, 0 moved** at the tip, so `docs/v21-evidence/overlap-allow.txt` is empty (comments only). The script
exits 1 if an absent-not-moved line lacks an allow-list entry (`<pr>\t<path>\t<stripped line>\t<reason>`).

## Fixes

None needed: no regression, no `omnigent/` or `tests/` change in this slice.
