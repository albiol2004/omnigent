# PLAN — v0.17.0 re-port of the Omnigent fork

## Iteration 1 — current increment (builders merged; Lead review done — see REPORT.md)
Objective: cherry-pick (`-x`, original order) all 58 product-carrying v16 port commits
(`v0.16.0..v16/trio-v0.16.0-fixes`, excluding loop-mailbox-only and merge commits) onto
v0.17.0 in 5 sequential port slices, record a pristine-v0.17.0 focused-suite baseline,
refresh the child-reasoning-effort patch, run the after-port suite, and write
`docs/v17-report.md` — i.e. the whole GOAL in one iteration.

GOAL scope covered: DoD 1–6 (all). Remaining after this iteration: only Evaluator findings.

### Recon facts (Lead, trial `git cherry-pick -x` of the whole range on v0.17.0, scratch worktree, removed)
- Commits with non-mailbox files: 58 (66 in range − 5 worker merges − 3 loop-only).
- Conflicts on real picks: 48d792284 (claude_native/bridge.py, test_native_interrupt_runner.py),
  de03a352c (docs/cursor-native-elicitation.md, cursor_native/permissions.py),
  d69671640 (test_cursor_native_permissions.py), 39e45d8d4 (sessions/__init__.py),
  ecfd01174 (test_app_sessions_native_events_lifecycle.py), cb7807e2f (cursor_native/bridge.py),
  10887f8ed (test_app_sessions_native_events_options.py), 5f21ceaf5 (cursor_native/forwarder.py,
  status.py, runner/app.py, _sessions/helpers.py, sessions/routes_events.py). Everything after
  5f21ceaf5 applied in the trial, but the trial resolved with `--theirs`, so later
  runner/app.py picks (0b90fce3e) may still conflict after a real resolution.
- v0.17.0 split runner/app.py 14092→8011 lines (#8854 model-option/MCP routes →
  model_option_routes.py/mcp_routes.py, #8856 native controls → native_controls.py,
  #8858 session_history.py, #8861 subagent_recovery.py, #8862 sign_in_watch.py): fork hunks
  whose context moved must be re-homed into the new module, not re-added to app.py.
- v0.17.0 moved claude/codex native tests to tests/harnesses/{claude_native,codex_native}/
  (rename detection carries modified files over); the fork-new file
  tests/test_codex_native_manual_compact.py must be moved to tests/harnesses/codex_native/.
- DB migration added v0.16.0→v0.17.0: omnigent/db/migrations/versions/mm1a2b3c4d5e_index_agents_by_owner_created.py.
- Upstream overlaps to keep (DoD 2): #9048 021d19951, #9008 06a055ac1, #9005 f651b5d6a,
  #8672 8bb13323f, #8572 61d96f74b, #8745 56272dfd7, #8761 ee3ca7cca, cursor_native #8516
  a16334f78 and #8523 7cbad8613, sessions #9025 106e2260b, #9020 6f9f8f838, #8795 1c0190294.

### Tasks
1. v17-port-close — v16 commits 1–10 (48d792284…a902a5ddc). Done: 10 picks/drops recorded,
   disposition notes committed, targeted check green (or only pristine-proven upstream failures).
2. v17-port-stop — 9 commits (ecfd01174…aa1568f22) + README adaptation to v0.17.0. Same done-criterion.
3. v17-port-receipts — 9 commits (5f21ceaf5…f51c5e01f). Same.
4. v17-port-isolation-compact — 12 commits (37c5ca35e…5aee0eee0) + move manual-compact test into tests/harnesses/codex_native/. Same.
5. v17-port-binding-plugin — 18 commits (8264557b8…cef9794cf). Same.
6. v17-baseline — scripts/v17_focused_suite.sh (v16 groups, v0.17.0 test paths) + pristine
   v0.17.0 run → docs/v17-evidence/baseline-v0.17.0.txt. Parallel with ports.
7. v17-patch — patches/child-reasoning-effort.v0.17.0.patch applying to pristine v0.17.0 and to
   the port tip; docs/v17-evidence/patch-check.txt. After port slices.
8. v17-afterport — after-port suite run at the port tip → docs/v17-evidence/after-port.txt, and
   the DoD-2 line-presence check → docs/v17-evidence/overlap-check.txt (+ scripts/v17_overlap_check.sh). After port slices + baseline.
9. v17-report — docs/v17-report.md (disposition table of all v16 commits, overlaps, baseline vs
   after-port, DoD-4 behaviour map, risks/migrations, unverifiable list, install/rollback). Last.

### Out-of-scope fence (from GOAL constraints)
- Never modify /home/coder/omnigent, /home/coder/omnigent-v16, ~/omnigent-dev, ~/.omnigent,
  ~/omnigent-backups, ~/.claude, the installed trio release. Never start/stop the Omnigent
  server; never pkill/killall by pattern. No push. No `uv tool install`/pip into user envs —
  repo-local `uv sync --frozen --extra all --group dev` + `uv run --frozen` only.
- Keep upstream v0.17.0 version/pyproject/uv.lock. Base exactly v0.17.0. No bypassPermissions.
- Do not port loop/ or loop-archive-* content.

## DECISION lines
- DECISION: v16-port documentation commits (docs/v16-evidence/*, docs/v16-report.md,
  scripts/v16_focused_suite.sh, patches/child-reasoning-effort.v0.16.0.patch) are cherry-picked
  too ("ported", historical record) so every one of the 58 v16 commits carries a `-x` trailer
  and the v16 patch stays next to its v17 refresh. Veto = drop them in a later iteration.
- DECISION: all focused-suite runs (baseline and after-port) use TMPDIR=/var/tmp/pytest-of-coder
  (GOAL env quirk: AF_UNIX 108-byte limit) so tmux suites measure product, not socket-path noise.
- DECISION: port slices are chained (depends) to keep the original cherry-pick order on the branch.
- DECISION: a targeted check may append `--deselect <nodeid>` only for a failure the builder
  proved also fails on pristine v0.17.0 (same id, recorded in the slice's disposition notes).

## Verification standard
mode: implement-then-smoke
evidence: per port slice, its targeted pytest command (short TMPDIR) green; the after-port focused
suite vs pristine baseline shows 0 new failure ids; overlap check shows 0 absent upstream lines
(or each absence explained as moved); `git apply --check` of the v17 patch on pristine v0.17.0 and
on the tip exits 0; `git log --format=%B b52507b70..HEAD | grep -c 'cherry picked from commit'`
covers every ported/adapted v16 sha in the report table.
full_check: TMPDIR=/var/tmp/pytest-of-coder bash scripts/v17_focused_suite.sh /var/tmp/pytest-of-coder/v17-full.txt && ! grep -q '^TIMEOUT' /var/tmp/pytest-of-coder/v17-full.txt
full_check_budget_s: 3600
cross_cutting: true
lead_integration: none — every deliverable (docs/v17-report.md, docs/v17-evidence/*, scripts/v17_*.sh, patches/*.v0.17.0.patch) is owned by a slice's writes:.
goal_acceptance:
- "git log --format=%B b52507b70..HEAD -> one `cherry picked from commit <v16 sha>` trailer for every v16 commit the docs/v17-report.md table marks ported/adapted; every dropped row cites an upstream commit or test | oracle: diff" (GOAL DoD 1)
- "bash scripts/v17_overlap_check.sh at HEAD -> every listed upstream PR (#9048 #9008 #9005 #8672 #8572 #8745 #8761 #8516 #8523) has 0 absent lines or each absence is a documented move | oracle: value" (GOAL DoD 2)
- "TMPDIR=/var/tmp/pytest-of-coder bash scripts/v17_focused_suite.sh OUT at HEAD vs docs/v17-evidence/baseline-v0.17.0.txt -> no FAILED/ERROR node id at HEAD that is absent from the baseline | oracle: diff" (GOAL DoD 3/4)
- "git apply --check patches/child-reasoning-effort.v0.17.0.patch on a detached v0.17.0 worktree and on HEAD -> exit 0 both | oracle: value" (GOAL DoD 5)
- "docs/v17-report.md -> lists migration mm1a2b3c4d5e (and every migration added since 318264335), and install/rollback steps that restore the pre-upgrade DB copy | oracle: static" (GOAL DoD 6)
goal_probe: cd <tip> && git worktree add --detach $T/p v0.17.0 && git -C $T/p apply --check $PWD/patches/child-reasoning-effort.v0.17.0.patch && git apply --check -R patches/child-reasoning-effort.v0.17.0.patch 2>/dev/null; git apply --check patches/child-reasoning-effort.v0.17.0.patch; then TMPDIR=/var/tmp/pytest-of-coder uv run --frozen pytest -q -p no:cacheprovider tests/test_cursor_native_completion_receipt.py tests/test_cursor_native_plugin_dir.py tests/server/integration/test_input_fence.py tests/harnesses/codex_native/test_codex_native_manual_compact.py tests/terminals/test_pane_reaper.py -> expected: both apply checks exit 0; pytest "N passed" with 0 failed. offline: yes (uv cache present; no network/server needed)

### Task-specific checklist (from GOAL; results filled at review)
| ref | input/action | expected observable | evidence | result |
| --- | --- | --- | --- | --- |
| G1 | every v16 product commit | ported/adapted (-x trailer) or dropped with upstream evidence | report §1 + git log trailers | verified — 66 rows, 55 ported/adapted all with matching -x trailer on HEAD ancestry (Lead script), 3 dropped cite upstream #8516/v0.17.0 helpers |
| G2 | upstream overlap PRs | lines still present at tip | overlap-check.txt | verified — scripts/v17_overlap_check.sh at tip: only #8516 6 absent lines, explained in report §2 (fork receipt layer reshaped call) |
| G3 | focused suites | 0 new failure ids vs pristine | baseline + after-port txt | verified — Lead full_check rerun at 250f4c3e5: 16 FAILED ids, 15 in baseline; the 1 extra (status_file reason_changes) also fails on pristine v0.17.0 (timing-dependent, files unchanged) — after-port.txt Lead section |
| G4a | cursor receipt gate: labels, plugin-dir, foreign stop-hook refusal, passthrough scan N12 | tests pass | test_cursor_native_completion_receipt.py, test_cursor_native_plugin_dir.py | verified — 316 passed (receipt, plugin-dir, fence, manual-compact, pane-reaper, permissions, sys_session) |
| G4b | cursor isolation: no session MCP in user mcp.json; refuse ~/.cursor; refuse repo subfolder | tests pass | test_cursor_native_bridge.py ids named in report | verified — cursor-native group 556 passed at 250f4c3e5 |
| G4c | input fence | tests pass | tests/server/integration/test_input_fence.py | verified — in the 316-passed run |
| G4d | stop-routing + kill escalation | tests pass | test_native_interrupt_runner.py, test_runner_dispatch.py, test_pane_reaper.py | verified — dispatch 284 passed, interrupt 24 passed, terminals 109 passed at 250f4c3e5 |
| G4e | Codex manual compact via app-server | tests pass | test_codex_native_manual_compact.py, test_sessions_compact.py | verified — in the 316-passed run |
| G4f | claude_native hook bridge + Unix-socket MCP + hook TMPDIR | tests pass | tests/harnesses/claude_native (bridge/hook) ids named in report | verified — claude-native group: only status_file timing failures (pre-existing on pristine), hook/bridge tests pass |
| G5 | v17 patch | applies to pristine and tip | patch-check.txt | verified — git apply --check exit 0 on pristine v0.17.0 worktree and on tip (Lead rerun) |
| G6 | report risks/migrations/rollback | present, correct migration ids | docs/v17-report.md | verified — report §6.1 lists mm1a2b3c4d5e + 10 revisions since 318264335 (matches git diff), §8 install/rollback restores DB backup |

### Shared contracts (all slices)
- Port slices cherry-pick v16 shas from ref `v16/trio-v0.16.0-fixes` with `git cherry-pick -x`.
- Each slice writes notes to `docs/v17-evidence/dispositions/<slice-id>.md`, one row per v16 commit:
  `| v16 sha | fork sha (from the -x trailer in the v16 message) | subject | ported/adapted/dropped | new sha | notes |`.
  v17-report builds its table from these files.
- Every slice ends with ≥1 commit whose subject starts `slice(<slice-id>): `.
- Suite runner: `scripts/v17_focused_suite.sh [OUT]` (same output format as v16's script).

```yaml
slices:
  - id: v17-port-close
    writes: [omnigent/harnesses/claude_native/bridge.py, omnigent/harnesses/codex_native/main.py, omnigent/harnesses/cursor_native/permissions.py, omnigent/runner, omnigent/server/routes/sessions/__init__.py, omnigent/tools/builtins/spawn.py, docs/cursor-native-elicitation.md, docs/v16-evidence/dispositions/port-v14-close.md, docs/v17-evidence/dispositions/v17-port-close.md, tests/inner/test_proc_and_platform.py, tests/runner, tests/harnesses/claude_native, tests/harnesses/codex_native, tests/test_cursor_native_permissions.py, tests/tools/builtins/test_sys_session.py]
    reads: []
    status: complete
    iteration: 1
    accepts:
      - "sys_session_close on a native child (claude/codex/cursor) -> target harness stop/kill path invoked, per tests/tools/builtins/test_sys_session.py + tests/runner/test_runner_dispatch.py | oracle: value"
      - "cursor yolo auto-accept with batched tools / stale markers -> queue-aware accept, no phantom cards (tests/test_cursor_native_permissions.py) | oracle: value"
  - id: v17-port-stop
    writes: [README.md, omnigent/harnesses/claude_native/bridge.py, omnigent/harnesses/codex_native/bridge.py, omnigent/harnesses/cursor_native/bridge.py, omnigent/native_tmux_kill.py, omnigent/runner, omnigent/terminals/pane_reaper.py, docs/v16-evidence/dispositions/port-v14-stop.md, docs/v17-evidence/dispositions/v17-port-stop.md, tests/runner, tests/terminals/test_pane_reaper.py, tests/harnesses/claude_native, tests/harnesses/codex_native, tests/test_cursor_native_bridge.py]
    reads: []
    status: complete
    iteration: 1
    accepts:
      - "close of a Claude/Codex/Cursor native session -> hard stop then leftover-pane SIGKILL escalation (tests/runner/test_native_interrupt_runner.py) | oracle: value"
      - "harness subprocess released with pane left -> pane reaped (tests/terminals/test_pane_reaper.py) | oracle: value"
  - id: v17-port-receipts
    writes: [omnigent/harnesses/cursor_native, omnigent/runner, omnigent/server/routes/_sessions, omnigent/server/routes/sessions/routes_events.py, patches/child-reasoning-effort.v0.16.0.patch, scripts/v16_focused_suite.sh, docs/v16-evidence, docs/v17-evidence/dispositions/v17-port-receipts.md, tests/runner/test_app_sessions_native_terminals_autocreate.py, tests/server/integration, tests/test_cursor_native_bridge.py, tests/test_cursor_native_completion_receipt.py]
    reads: []
    status: complete
    iteration: 1
    accepts:
      - "cursor receipt turn end with foreign stop hook configured -> receipt withheld (tests/test_cursor_native_completion_receipt.py) | oracle: refusal"
      - "send while a cursor input fence is held -> fenced input queued/refused per fence contract (tests/server/integration/test_input_fence.py) | oracle: value"
  - id: v17-port-isolation-compact
    writes: [omnigent/harnesses/codex_native, omnigent/harnesses/cursor_native/bridge.py, omnigent/runner, omnigent/server/routes/sessions/routes_events.py, docs/v16-evidence/dispositions, docs/v17-evidence/dispositions/v17-port-isolation-compact.md, tests/conftest.py, tests/e2e_ui/sessions/test_codex_native_compact_takes_effect.py, tests/runner, tests/server/integration, tests/harnesses/codex_native, tests/test_codex_native_manual_compact.py, tests/test_cursor_native_bridge.py]
    reads: []
    status: complete
    iteration: 1
    accepts:
      - "cursor launch whose project config is ~/.cursor or from a repo subfolder -> launch refused (tests/test_cursor_native_bridge.py) | oracle: refusal"
      - "manual compact of a codex-native session -> app-server thread/compact/start sent, no tmux keys, guard held until outcome (tests/harnesses/codex_native/test_codex_native_manual_compact.py) | oracle: value"
  - id: v17-port-binding-plugin
    writes: [omnigent/harnesses/claude_native/bridge.py, omnigent/harnesses/cursor_native, omnigent/host/connect.py, omnigent/runner/native/orchestration.py, docs/v16-evidence, docs/v16-report.md, docs/v17-evidence/dispositions/v17-port-binding-plugin.md, tests/conftest.py, tests/e2e, tests/host/test_connect.py, tests/inner/test_cursor_native_executor.py, tests/runner/test_app_sessions_native_terminals_autocreate.py, tests/test_cursor_native.py, tests/test_cursor_native_bridge.py, tests/test_cursor_native_forwarder.py, tests/test_cursor_native_permissions.py, tests/test_cursor_native_plugin_dir.py, tests/test_cursor_native_usage.py]
    reads: []
    status: complete
    iteration: 1
    accepts:
      - "cursor plugin-route launch whose cursor-agent would run without the plugin -> refused; passthrough/installed plugin stop hooks scanned by the receipt gate (r17 N12) (tests/test_cursor_native_plugin_dir.py) | oracle: refusal"
      - "discovered cursor chat owned by another pane/workspace -> not bound (tests/test_cursor_native_bridge.py) | oracle: refusal"
  - id: v17-baseline
    writes: [scripts/v17_focused_suite.sh, docs/v17-evidence/baseline-v0.17.0.txt]
    reads: []
    status: complete
    iteration: 1
    accepts:
      - "TMPDIR=/var/tmp/pytest-of-coder bash scripts/v17_focused_suite.sh OUT on a detached pristine v0.17.0 worktree -> 11 '== group ==' headers, a summary line each, SUITE_DONE, no ABSENT-GROUP | oracle: rerun"
  - id: v17-patch
    writes: [patches/child-reasoning-effort.v0.17.0.patch, docs/v17-evidence/patch-check.txt]
    reads: [patches/child-reasoning-effort.v0.16.0.patch]
    status: complete
    iteration: 1
    accepts:
      - "git apply --check patches/child-reasoning-effort.v0.17.0.patch on pristine v0.17.0 and on the port tip -> exit 0 both; applied tree passes tests/tools/builtins/test_child_reasoning_effort.py | oracle: rerun"
  - id: v17-afterport
    writes: [scripts/v17_overlap_check.sh, docs/v17-evidence/after-port.txt, docs/v17-evidence/overlap-check.txt]
    reads: [scripts/v17_focused_suite.sh, docs/v17-evidence/baseline-v0.17.0.txt]
    status: complete
    iteration: 1
    accepts:
      - "after-port suite at the tip vs baseline -> 0 FAILED/ERROR ids absent from the baseline | oracle: diff"
      - "bash scripts/v17_overlap_check.sh -> per-PR lines-checked/absent table, 0 unexplained absences | oracle: value"
  - id: v17-report
    writes: [docs/v17-report.md]
    reads: [docs/v17-evidence]
    status: complete
    iteration: 1
    accepts:
      - "docs/v17-report.md table -> one row per v16 commit (58 product + mailbox rows not ported), each ported/adapted row's new sha has a matching -x trailer | oracle: diff"
      - "docs/v17-report.md -> migrations since v0.16.0 and since 318264335 listed with ids, install + rollback (DB restore) steps | oracle: static"
```
