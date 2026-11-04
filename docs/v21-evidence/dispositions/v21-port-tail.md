# v21-port-tail — v17 "tail" group (#68-78) re-ported onto v0.21.0rc1

Method: `git cherry-pick -x` of v17 commits #68-78 in original order on top of v21-port-binding. Product picks
were already on HEAD before this slice (on `00930adbe`, before the v21-patch/v21-afterport merges); this note records their disposition. Each pick's message carries
`(cherry picked from commit <full v17 sha>)`. `git patch-id --stable` of the pick equals the v17 commit unless
noted `adapted`.

| # | v17 sha | subject | disposition | new sha | notes |
|---|---|---|---|---|---|
| 68 | 31236382c | slice(v17-patch): child-reasoning-effort patch for v0.17.0 | ported | 0c9333f73 | historical evidence (`patches/`, `docs/v17-evidence/patch-check.txt`) |
| 69 | bf6c3a8d2 | slice(v17-afterport): after-port suite and upstream-overlap check | ported | f2e33720e | historical evidence (`scripts/v17_overlap_check.sh`, `docs/v17-evidence/`) |
| 70 | 2d5655b6b | slice(v17-report): v0.17.0 re-port report | ported | 1c2cbdc73 | historical evidence (`docs/v17-report.md`) |
| 71 | c2bedad97 | slice(v17-port-stop): fix ruff format of ported stop/kill hunks for v0.17.0 line length | adapted | b87d0cf23 | empty after conflict resolution — v17 reformatted stop/kill hunks for v0.17.0 line length; those files were already ruff-formatted on v0.21.0rc1 by `1febb04f9`. `git range-diff c2bedad97^! b87d0cf23^!` shows the v17 tree rewrite with no corresponding pick hunks. Pick still carries `-x` from `c2bedad974cab7fca6cb7ecbf481b4ab68352149`. |
| 72 | 8001e9de9 | slice(v17-port-receipts): fix ruff format and unused noqa (RUF100) in receipt/fence tests | ported | c11e2c181 | clean |
| 73 | 250f4c3e5 | slice(v17-port-receipts): fix pyrefly errors in the cursor receipt/turn-outcome block | ported | 491f01e85 | clean |
| 74 | 7470ce929 | slice(v17-afterport): fix overlap check counting lines quoted in docs/v17-report.md as moved | ported | 4957673f4 | historical evidence (`scripts/v17_overlap_check.sh`) |
| 75 | c813e0b82 | slice(v17-afterport): fix evidence: final-tip suite re-run, overlap check refreshed at tip | ported | c25404f26 | historical evidence (`docs/v17-evidence/`, `docs/v17-report.md`) |
| 76 | 7c04ae6a5 | fix(cursor-native): receipt re-post keeps the turn's failed outcome | ported | d29c61e72 | clean |
| 77 | 503a80a41 | fix(cursor-native): server keeps a failed child turn and dedups repeated terminal posts | ported | 11a604d98 | clean |
| 78 | 2e62ffd54 | fix(cursor-native): only an authorised receipt caller records the turn marker; correct v17 report knob names | ported | 4dddf165d | clean |

## Branch-only commits

- `6c7541a83` — `slice(v21-port-tail): fix ruff at the ported tip — drop BLE001 noqa that v0.21 per-file ignores make unused (RUF100), one blank line in native_controls`. Needed on v0.21 because rc1 already per-file-ignores BLE001 in `omnigent/harnesses/codex_native/manual_compact.py` and `omnigent/server/routes/_sessions/input_fence.py`, so the v17 `# noqa: BLE001` comments are unused (RUF100). Also dropped one extra blank line in `omnigent/runner/native_controls.py` so ruff format is clean at the ported tip.

## Pre-existing failures (deselected)

`docs/v21-evidence/deselects/v21-port-tail.args` is byte-identical in content to
`docs/v21-evidence/deselects/v21-port-close.args` (`diff <(sort docs/v21-evidence/deselects/v21-port-tail.args) <(sort docs/v21-evidence/deselects/v21-port-close.args)` is empty).

The 50 failures of `tests/runner/test_app_sessions_native_events_lifecycle.py` fail identically on pristine
v0.21.0rc1, as recorded in `docs/v21-evidence/dispositions/v21-port-close.md`: detached worktree,
`TMPDIR=/var/tmp/pytest-of-coder uv run --frozen --extra all --group dev pytest -q -p no:cacheprovider tests/runner/test_app_sessions_native_events_lifecycle.py`
→ `50 failed, 64 passed`; the failing node-id set is identical to the port's before deselecting. Typical failure
line: `AssertionError: codex-native model_change must return 204; got 503: {"error":"codex_native_settings_update_failed","detail":"Codex-native settings update requires a loaded Codex bridge."}`.
The 50 ids are listed in that args file. No additional ids needed for this slice's targeted check.

## Checks

Targeted check (builder role; deselects from `v21-port-tail.args`):

`ruff format --check` + `ruff check` on `git diff --name-only --diff-filter=AMR v0.21.0rc1 -- "*.py"`, then
`TMPDIR=/var/tmp/pytest-of-coder pytest -q -p no:cacheprovider @docs/v21-evidence/deselects/v21-port-tail.args` plus
`tests/test_cursor_native_completion_receipt.py tests/test_cursor_native_forwarder.py tests/server/routes/test_cursor_child_terminal_repost.py tests/server/integration/test_input_fence.py tests/runner/test_runner_dispatch.py tests/runner/test_native_interrupt_runner.py tests/runner/test_app_sessions_native_events_lifecycle.py tests/harnesses/codex_native/test_codex_native_bridge.py`.

**FAILED.** `trio-test run --role builder -- …` → `TRIO_TEST: FAIL rc=1 passed=0 failed=0 skipped=0 errors=0 dur=341.9s` (`reused=no`). Ruff format/check were clean (`60 files already formatted`; `All checks passed!`). Pytest then collected `696` items and printed dots through `[ 20%]` plus more before `pytest-timeout` dumped stacks (`Timeout`) with no pytest summary and **no failed node id** in the log (`0830bab5b757…-20261103T235111605473Z.log`). The dump shows a hung `run_server` thread blocked in `sock.accept()` (`pytest_rerunfailures`) and the main thread inside an async test call — not one of the 50 deselected `test_app_sessions_native_events_lifecycle.py` ids (those are excluded via `@docs/v21-evidence/deselects/v21-port-tail.args`). Product code was not changed (other slices own `omnigent/` and `tests/`).

### Lead take-over (review call)

The builder's run above hung in `tests/server/integration/test_input_fence.py` under pytest's default fd-level capture — the
same environmental hang the pristine v0.21.0rc1 tree shows for every server-integration file that solves a sync FastAPI
dependency (diagnosed in `docs/v21-evidence/dispositions/v21-afterport.md`, per-file pristine/tip records in
`docs/v21-evidence/after-port-perfile.txt`). The slice's targeted check therefore runs pytest with `--capture=sys` (output
capture only; no test skipped or loosened). The ruff step also needed `scripts/v21_compare_suites.py` formatted (fixed in a
`slice(v21-afterport): fix …` commit). Re-run at the Lead's HEAD with `--capture=sys`:
`TRIO_TEST: PASS rc=0 passed=695 failed=0 skipped=1 errors=0 dur=88.1s`.

### Order-dependent hang also with `--capture=sys` (found while re-running all targeted checks)

The isocompact targeted check (`--capture=sys`, all files in one process) hung at item 475/519 — the first tests of
`tests/server/integration/test_sessions_compact.py`, main thread in `asyncio … _read_from_self`, AnyIO worker idle in
`queue.get()` (the same stack as the fd-capture hang). Reduced:

| tree | command (TMPDIR=/var/tmp/pytest-of-coder, `uv run --frozen --extra all --group dev`) | result |
|---|---|---|
| tip | `pytest -q -p no:cacheprovider --capture=sys --timeout=120 tests/runner/test_app_sessions_native_events_options.py tests/server/integration/test_sessions_compact.py` | hang after 120 dots (all options tests passed), `Timeout` stack dump, no summary |
| tip | same, `tests/server/integration/test_sessions_compact.py` alone | `14 passed` |
| pristine v0.21.0rc1 (`20e15700f`, detached worktree, own `uv sync`, removed afterwards; run directly, not via trio-test) | same pair as row 1 | `Running 127 items`, `...............F…` then hang after 117 dots (killed by `timeout 580`, rc 124) |

So it is a pre-existing upstream/environment hang that depends on test order, not a port regression. The receipts,
isocompact and tail targeted checks therefore run their `tests/server/integration/` files in a separate pytest process
(`--capture=sys`) after the other files (`&&`).
