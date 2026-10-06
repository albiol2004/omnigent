# Omnigent fork re-port onto v0.16.0 — report

Branch: `trio/loop` → lands on `trio-v0.16.0-fixes` (base: upstream tag `v0.16.0`
= `82a74473e`; the loop's mailbox-only base commit is `ca5b07c04`).
Fork source: `fork/release/omnigent-2a84483a` (tip `318264335`), fork range
`b04e266e3..fork/release/omnigent-2a84483a` = **60 commits** (GOAL says "58"; the
range actually has 60). Method: the 0.14.0 re-port method — `git cherry-pick -x`
in original fork order, conflicts resolved keeping upstream v0.16.0 behaviour
with the fork layered on top, adaptation work committed as `slice(<id>): …`.

Totals: **27 ported** (clean pick), **16 adapted** (conflicts resolved or
code/test changed for v0.16.0), **3 dropped** (superseded, with evidence),
**14 not ported** (2 release version bumps + 12 loop-mailbox commits).
Every ported/adapted commit carries a `(cherry picked from commit <sha>)` trailer
on the branch; check with:

```sh
git log --format=%B ca5b07c04..trio/loop | grep -oE 'cherry picked from commit [0-9a-f]{9}' | sort -u
```

## 1. Disposition table (all 60 fork commits, original order)

Per-slice notes (conflict resolutions, which upstream change was kept, test
evidence) are in `docs/v16-evidence/dispositions/<slice>.md`.

| # | fork sha | subject | disposition | new sha on trio/loop | slice / evidence |
| --- | --- | --- | --- | --- | --- |
| 1 | f43b4215d | release: v0.14.0rc1 | not ported (bookkeeping) | - | release version bump; upstream v0.16.0 version/pyproject/uv.lock kept (GOAL constraint) |
| 2 | fc89a3ba3 | release: v0.14.0 | not ported (bookkeeping) | - | release version bump; upstream v0.16.0 version/pyproject/uv.lock kept (GOAL constraint) |
| 3 | cecc8d7d5 | loop-v14-rebase: mission brief for the v0.14.0 re-port | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 4 | 0bd6d08f9 | loop-v14-rebase: list the fork commits to re-port | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 5 | 50a59c137 | loop-v14-rebase: initialize mailbox | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 6 | 77115e539 | loop-v14-rebase: addendum on the doctor session-contract probe | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 7 | 361bec3bc | loop-v14-rebase: restore the full mission brief (earlier write was lost) | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 8 | 5837d559d | slice(kill-on-close): stop the target harness on sys_session_close. | adapted | 48d792284 (+ 1da2e0ee1 follow-up) | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 9 | 49da161cd | fix(cursor-native): queue-aware yolo auto-accept for batched tools. | ported | de03a352c | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 10 | a60a600d7 | fix(cursor-native): drop phantom cards for stale yolo markers. | ported | d69671640 | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 11 | 3444f699f | slice(codex-bridge-owner): serve Codex model options from a labeled live bridge | adapted | d8aa8058d | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 12 | 4dfbe128d | slice(compact-on-fork-cross-harness): replay summary-only Codex compaction markers | adapted | ff86cbba7 | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 13 | 69db59457 | fix(sessions): re-export _resolve_agent_spec from the sessions package | ported | 39e45d8d4 | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 14 | 70d652bbc | slice(session-contract): alias _resolve_agent_spec to _resolve_subagent_spec | ported | d4f6816bf | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 15 | c7a454a78 | slice(close-guard): close tree-scoped children with unparsable titles | ported | cfeb9ee10 | `docs/v16-evidence/dispositions/port-v14-close.md` |
| 16 | 41d82337d | slice(stop-routing): hard-stop Claude, Codex and Cursor on close | adapted | ecfd01174 | `docs/v16-evidence/dispositions/port-v14-stop.md` |
| 17 | 4e4b88928 | slice(kill-escalation): share leftover-pane SIGKILL across native bridges | adapted | cb7807e2f (+ 2ed8634c8 follow-up) | `docs/v16-evidence/dispositions/port-v14-stop.md` |
| 18 | 642b879d7 | slice(reaper): reap native panes after harness subprocess release | adapted | 9734887b3 | `docs/v16-evidence/dispositions/port-v14-stop.md` |
| 19 | 305ac7cf7 | slice(codex-advertise-guard): do not abort Codex auto-create when tmux advertise is missing | adapted | 10887f8ed | `docs/v16-evidence/dispositions/port-v14-stop.md` |
| 20 | 043c00ec7 | slice(mailbox): restore loop-session-close from trio-v0.12.0-fixes | not ported (bookkeeping) | - | loop mailbox content (loop-session-close restore); mailbox commits are not ported (GOAL) |
| 21 | c20f65e54 | slice(readme): note trio-v0.14.0-fixes until live adopt | ported | b44be221b | `docs/v16-evidence/dispositions/port-v14-stop.md` |
| 22 | 694476595 | slice(import-paths): point stop/advertise helpers at harnesses packages | dropped | - | `docs/v16-evidence/dispositions/port-v14-stop.md` (superseded — see fragment notes) |
| 23 | 5a2abe8b9 | slice(session-contract): place agent-spec alias after imports | dropped | - | `docs/v16-evidence/dispositions/port-v14-stop.md` (superseded — see fragment notes) |
| 24 | 314f6a933 | slice(codex-bridge-owner): adapt labeled-bridge test to v0.14.0 catalog mark | dropped | - | `docs/v16-evidence/dispositions/port-v14-stop.md` (superseded — see fragment notes) |
| 25 | ead480375 | loop-v14-rebase: iteration 1 lead notes and evidence | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 26 | 61a04d0bb | loop-v14-rebase: iteration 1 LOG line and STATE bookkeeping | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 27 | c45506dee | loop-v14-rebase: add slices block to PLAN.md | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 28 | c88c71f9e | loop: iteration 1 — SHIP | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 29 | b830b9b0c | loop-v14-rebase: iteration 1 state bookkeeping after SHIP | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 30 | 5960f7871 | loop-v14-rebase: record post-SHIP documentation brief | not ported (bookkeeping) | - | loop mailbox / bookkeeping commit (loop-v14-rebase); not product code, not ported (GOAL) |
| 31 | 139c74a18 | docs(v14-report): summarize the 0.14.0 re-port disposition | adapted | fb483202e (+ README adaptation in the slice commit) | `docs/v16-evidence/dispositions/port-v14-stop.md` |
| 32 | 99d8a5884 | feat(cursor-native): opt-in completion receipts and durable input fence | adapted | 5f21ceaf5 | `docs/v16-evidence/dispositions/port-cursor-receipts.md` |
| 33 | 6bc9c6923 | fix(cursor-native): bind receipt turn ends to prompts; durable skipped rows | adapted | 1ecb111fc | `docs/v16-evidence/dispositions/port-cursor-receipts.md` |
| 34 | 0944602eb | test(cursor-native): serialize mixed binding reasons in e2e evidence dumps | ported | 2ed704fc8 | `docs/v16-evidence/dispositions/port-cursor-receipts.md` |
| 35 | 3b45e5573 | fix(cursor-native): withhold completion receipts when a foreign stop hook is configured | ported | 61812adf7 | `docs/v16-evidence/dispositions/port-cursor-receipts.md` |
| 36 | fa16a055d | fix(cursor-native): bind receipt stops to this chat; scope owned stop hooks | ported | 4b580b109 | `docs/v16-evidence/dispositions/port-cursor-receipts.md` |
| 37 | fb085ca12 | fix(cursor-native): abort launch when a stale receipt epoch cannot be removed | ported | d0db96552 | `docs/v16-evidence/dispositions/port-cursor-receipts.md` |
| 38 | 4de324dde | fix(cursor-native): no Backspace into an empty composer; stable readiness before the first paste | ported | 37c5ca35e | `docs/v16-evidence/dispositions/port-cursor-isolation.md` |
| 39 | c5444087c | fix(cursor-native): never write a session stop hook into the user hooks.json | adapted | cef70d04d | `docs/v16-evidence/dispositions/port-cursor-isolation.md` |
| 40 | af775e159 | fix(cursor-native): never register a session MCP server in the user mcp.json | ported | c40055f88 | `docs/v16-evidence/dispositions/port-cursor-isolation.md` |
| 41 | a04516b21 | fix(cursor-native): refuse Cursor launches whose project config is the user ~/.cursor | adapted | 09488293f | `docs/v16-evidence/dispositions/port-cursor-isolation.md` |
| 42 | 510511735 | fix(cursor-native): refuse Cursor launches from a repository subfolder | ported | eef83cd9e | `docs/v16-evidence/dispositions/port-cursor-isolation.md` |
| 43 | 5a782783f | test(cursor-native): keep the repo-subfolder refusal test's bridge under the launch root | ported | f62033d62 | `docs/v16-evidence/dispositions/port-cursor-isolation.md` |
| 44 | 0b2c6ce82 | fix(codex-native): compact via app-server thread/compact/start, not tmux keys | adapted | 0b90fce3e | `docs/v16-evidence/dispositions/port-codex-compact.md` |
| 45 | 2a84483a5 | fix(codex-native): keep the manual-compact guard until Codex reports an outcome | ported | da17fdc20 | `docs/v16-evidence/dispositions/port-codex-compact.md` |
| 46 | 354163318 | fix(cursor-native): never bind a session to another workspace's chat store | ported | 8264557b8 | `docs/v16-evidence/dispositions/port-cursor-binding.md` |
| 47 | e3778c9bf | fix(cursor-native): pin each fresh launch to a pre-minted chat id | adapted | 80eb3acbe | `docs/v16-evidence/dispositions/port-cursor-binding.md` |
| 48 | 041d74306 | fix(cursor-native): bind a discovered chat only when this session's pane owns it | adapted | 2a6546fc9 | `docs/v16-evidence/dispositions/port-cursor-binding.md` |
| 49 | 4032dde9d | fix(cursor-native): warn when a launch overwrites a live sibling's hooks/MCP slot | ported | 512d4d4a6 | `docs/v16-evidence/dispositions/port-cursor-binding.md` |
| 50 | da6045a2e | feat(cursor-native): opt-in per-launch --plugin-dir hooks/MCP config | ported | f910eac65 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 51 | dd33637ec | fix(cursor-native): let OMNIGENT_CURSOR_PLUGIN_DIR reach host-spawned runners | ported | 62baa7157 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 52 | d5bd4eb95 | fix(cursor-native): never delete the project mcp.json when clearing a dead entry | ported | 523b64788 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 53 | 93cbb7314 | fix(cursor-native): refuse plugin-route launches cursor-agent would run without the plugin | adapted | a11446be3 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 54 | b5d69a50c | fix(cursor-native): a plugin-route turn no longer fires a live sibling's project usage hook | ported | dfd54048c | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 55 | 3dd01eab0 | fix(cursor-native): owner-only bridge dir recreation; grace for mid-launch siblings | ported | 5f71a8390 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 56 | b9f3291bf | test(cursor-native): fix the pyrefly errors in the plugin-dir unit tests | ported | d70bafafc | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 57 | 1c1dcd7e2 | test(cursor-native): gate the plugin-dir real-CLI e2e; cover the sibling-hook skip | ported | fa967d38b | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 58 | ec2e5f2fc | fix(cursor-native): cursor_project_key matches the CLI's directory mangling (r17 N16) | ported | 53901f3ec | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 59 | e74900a77 | fix(cursor-native): bridge MCP refuses a parent bound to another bridge (r17 N11) | ported | 3add21910 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |
| 60 | 318264335 | fix(cursor-native): receipt gate scans passthrough and installed plugin stop hooks (r17 N12) | ported | 0a2b9b236 | `docs/v16-evidence/dispositions/port-cursor-plugin-dir.md` |

### Dropped commits — evidence
- `694476595` (import-paths): empty after conflict resolution — the resolutions of
  `41d82337d`/`4e4b88928` already point every reference at
  `omnigent.harnesses.{codex,claude}_native.bridge` (the v0.16.0 package layout).
- `5a2abe8b9` (alias after imports): empty — `_resolve_agent_spec = _resolve_subagent_spec`
  already sits after the imports (`d4f6816bf` + `slice(port-v14-close)`), and the unused
  `_proc` import it removed was removed by `2ed8634c8`.
- `314f6a933` (labeled-bridge test for v0.14 catalog mark): superseded by v0.16.0's own
  version of `test_codex_native_model_options_follow_labeled_foreign_bridge`
  (strips the `source` provenance and asserts upstream's 503
  `codex_native_settings_update_failed`), which is stricter than the fork's loosened assertion.

## 2. Upstream v0.16.0 overlaps kept

Check: for each upstream PR, every line it added that is still present at
`v0.16.0` must still be present at the branch tip (script in the loop evidence;
result below, run on `trio/loop` HEAD):

| upstream PR | commit | lines checked | absent at tip | notes |
| --- | --- | --- | --- | --- |
| #8079 claude_native Unix-socket MCP control ingress | 6fc7aaf67 | 99 | 0 | fork kill helpers added beside it (`5837d559d`, `4e4b88928`); `e74900a77` refuses only a parent bound to a *different* cursor bridge dir |
| #8090 MCP control socket root / body drain hardening | 19f6cbcbc | 41 | 0 | |
| #8103 StopFailure isolation | 8bbbf2a35 | 21 | 0 | |
| #8093 runner tunnel reconnect backoff | 394fa67b8 | 11 | 0 | |
| #8094 runner-disconnect failure hold | 9e22e26d7 | 0 (lines since reworked upstream) | 0 | file not touched by the port (`git diff v0.16.0 trio/loop -- omnigent/server/routes/_sessions/orchestration.py` only adds the fence check ahead of the codex side-chat return) |
| #8271 codex resume / compaction | 26249abaf | 67 | 0 | `4dfbe128d` adds only the summary-only marker ahead of upstream's replay; `0b2c6ce82` hooks live events only |
| #8320 attached viewer busy only on recent input | 4119c9c34 | 69 | 8 (moved) | the 8 `runner/app.py` lines moved verbatim into `terminals/pane_reaper.py::_pane_is_busy_after_harness` (`tmux_last_client_input_at`, `client_interaction_within`, `PANE_OUTPUT_BUSY_WINDOW_S`); upstream test `test_runner_busy_check_counts_a_viewer_only_on_recent_input` kept and passing |
| #8481 owner-only MCP configuration | f46ff65ce | 72 | 0 | not touched by the port |

## 3. Baseline (pristine v0.16.0) vs after-port (GOAL DoD 3)

Evidence: `docs/v16-evidence/baseline-v0.16.0.txt` (pristine product tree `ca5b07c04`)
and `docs/v16-evidence/after-port.txt` (tip `855d54cbd`, the last product commit), both produced by
`bash scripts/v16_focused_suite.sh <OUT>` (11 groups, one pytest process each).
"new failures" = FAILED/ERROR node ids at the tip that are not in the baseline at all.

| group | pristine v0.16.0 | after port (tip) | new failures | fixed by port |
| --- | --- | --- | --- | --- |
| dispatch | 3 failed, 277 passed, 1 skipped, 1 warning, 1 error in 42.03s | 284 passed, 1 skipped in 39.82s | 0 | 3 |
| interrupt | 15 passed in 0.37s | 18 passed in 0.36s | 0 | 0 |
| runner-native | 12 failed, 487 passed in 1034.63s (0:17:14) | 2 failed, 576 passed in 556.84s (0:09:16) | 0 | 10 |
| sys-session | 44 passed in 54.01s | 45 passed in 46.55s | 0 | 0 |
| terminals | 35 failed, 62 passed, 2 skipped in 7.85s | 35 failed, 73 passed, 2 skipped in 6.00s | 0 | 0 |
| claude-native | 3 failed, 1399 passed, 6 warnings in 181.02s (0:03:01) | 3 failed, 1400 passed, 6 warnings in 170.31s (0:02:50) | 0 | 0 |
| codex-native | 1028 passed, 1 warning in 35.38s | 1058 passed, 1 warning in 42.34s | 0 | 0 |
| cursor-native | 253 passed in 12.21s | 547 passed in 27.33s | 0 | 0 |
| inner-proc | 39 passed, 8 skipped in 0.44s | 40 passed, 8 skipped in 0.66s | 0 | 0 |
| host | 7 failed, 240 passed, 73 warnings in 39.36s | 6 failed, 242 passed, 74 warnings in 40.30s | 0 | 1 |
| sessions-routes | 19 passed in 14.25s | 18 failed, 46 passed in 35.54s | 18 | 0 |

**The only 18 "new" ids (sessions-routes) are environmental, not regressions.** They are all in
fork-added files absent from v0.16.0 (`test_cursor_cold_start_prompt.py`,
`test_cursor_receipt_binding_e2e.py`). Each fails in `tmux -S <socket> new-session` with exit 1
because the test puts the tmux socket under `$TMPDIR`, and the loop's ~150-character TMPDIR exceeds
the 108-byte AF_UNIX path limit. Rerun on the same tip with a short TMPDIR (recorded in after-port.txt):
`TMPDIR=/var/tmp/pytest-of-coder uv run --frozen pytest … sessions-routes files` → **64 passed**
(incl. `test_input_fence.py`, `test_cursor_receipt_epoch_clear_e2e.py`), so every fork-new file passes
entirely. The same rerun for `tests/terminals` → **108 passed, 2 skipped** (the 35 terminals failures,
identical ids in baseline and after-port, are the same socket-path limit).

**Pre-existing upstream failures (same ids on pristine v0.16.0, not counted as regressions):**
- runner-native: `test_app_sessions_native_events_lifecycle.py::test_claude_native_model_options_serves_probe_rows_after_pending`,
  `::test_claude_native_model_options_use_session_launch_catalog[False]`
- claude-native: `test_claude_native_status_file.py::test_poller_publishes_edges_only`,
  `::test_poller_publishes_when_only_the_reason_changes`, `::test_unknown_status_clears_dedup_so_next_read_publishes`
  (timing-sensitive; the baseline header notes them as flaky on pristine)
- host: 6 `tests/host/test_connect.py` model-options/log-dir tests (baseline has 7)
- terminals: 35 `test_control_bridge.py` / `test_registry*.py` ids (environmental, see above)

**Fixed by the port (failing on pristine, passing at the tip): 14 ids** — 3 in `test_runner_dispatch.py`,
8 codex settings/interrupt/stop lifecycle tests (on pristine they fail with "Terminal registry not
configured"; the fork's `305ac7cf7` test hunks stub the terminal registry — see `port-v14-stop.md`), `test_create_session_terminal_ensure_failure_returns_json_without_live_error`,
`test_publish_native_terminal_start_error_emits_failed_status_only`, and
`test_host_discovers_harness_skills_without_a_runner[claude-native-expected0]`. Some of these are
likely environment-sensitive on pristine too (the baseline header records load-related flakes); none was
changed to make it pass except the documented `305ac7cf7` stub hunks.

Static check on touched product paths: `uv run --frozen ruff check <full_check paths>` → `All checks passed!`.

## 4. Behaviour checks → tests (GOAL DoD 4)

| behaviour | covering tests (all run on the tip) |
| --- | --- |
| cursor receipt gate: `completion_receipts` labels, prompt binding, skipped rows | `tests/test_cursor_native_completion_receipt.py`, `tests/server/integration/test_cursor_receipt_binding_e2e.py`, `tests/server/integration/test_cursor_receipt_epoch_clear_e2e.py` |
| receipt gate: foreign stop-hook refusal (`3b45e5573`), passthrough + installed plugin stop hooks (r17 N12, `318264335`) | `tests/test_cursor_native_completion_receipt.py`, `tests/test_cursor_native_plugin_dir.py` |
| plugin-dir route (`OMNIGENT_CURSOR_PLUGIN_DIR`), host env pass-through, plugin-route refusal, N11/N16 | `tests/test_cursor_native_plugin_dir.py`, `tests/host/test_connect.py`, `tests/test_cursor_native_usage.py`, `tests/inner/test_cursor_native_executor.py`, `tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py` (real-CLI; skipped unless `OMNIGENT_E2E_CURSOR_NATIVE=1`) |
| durable input fence | `tests/server/integration/test_input_fence.py` |
| cursor isolation (user `~/.cursor`, repo subfolder, user hooks.json / mcp.json never written), chat binding/pinning | `tests/test_cursor_native_bridge.py`, `tests/runner/test_app_sessions_native_terminals_autocreate.py`, `tests/server/integration/test_cursor_cold_start_prompt.py`, `tests/test_cursor_native.py`, `tests/test_cursor_native_forwarder.py` |
| stop-routing (hard stop Claude/Codex/Cursor on close), kill-on-close, close-guard | `tests/runner/test_native_interrupt_runner.py`, `tests/runner/test_runner_dispatch.py`, `tests/tools/builtins/test_sys_session.py`, `tests/test_{claude,codex,cursor}_native_bridge.py` |
| kill escalation (`native_tmux_kill.py` leftover-pane SIGKILL), pane reaper | `tests/test_claude_native_bridge.py`, `tests/test_codex_native_bridge.py`, `tests/inner/test_proc_and_platform.py`, `tests/terminals/test_pane_reaper.py` |
| Codex manual compact via app-server `thread/compact/start`, guard until outcome | `tests/test_codex_native_manual_compact.py`, `tests/server/integration/test_sessions_compact.py`, `tests/runner/test_app_sessions_native_events_options.py` |
| claude_native hook bridge with the Unix-socket MCP and hook TMPDIR handling | `tests/test_claude_native_bridge.py`, `tests/test_claude_native_hook.py` |

## 5. Refreshed trio patch (GOAL DoD 5)

`patches/child-reasoning-effort.v0.16.0.patch` (touches `runner/tool_dispatch.py`,
`server/routes/_sessions/helpers.py`, `server/routes/sessions/__init__.py`, plus a new
`tests/tools/builtins/test_child_reasoning_effort.py`; it reuses v0.16.0's
`omnigent/util/reasoning_effort.py` and the `reasoning_effort` field v0.16.0 already has in
`spawn.py`, so it no longer edits spawn.py — that is where the old patch failed). Evidence in
`docs/v16-evidence/patch-check.txt`: `git apply --check` exit 0 on a `v0.16.0` index and on
the tip; the old release patch fails on both; patched tree → 60 passed
(`test_child_reasoning_effort.py`, `test_sys_session.py`, `test_reasoning_effort_validation.py`).
Re-check:

```sh
I=$(mktemp -u); GIT_INDEX_FILE=$I git read-tree v0.16.0 && GIT_INDEX_FILE=$I git apply --check --cached patches/child-reasoning-effort.v0.16.0.patch; echo $?; rm -f $I
git apply --check patches/child-reasoning-effort.v0.16.0.patch; echo $?
```

## 6. Risks

1. **64 KB preferences / snapshot cap (upstream v0.16.0).** `stores/project_store/sqlalchemy_store.py`
   caps a stored preference at `_PREFERENCE_MAX_STORED_BYTES = 65535` (and project config at
   64 KiB); `stores/conversation_store/sqlalchemy_store.py::_validate_inference_snapshot`
   rejects an inference snapshot whose compressed form exceeds 65,535 bytes
   ("Reduce the configured model catalog or allowlist"). The fork's receipt/fence/binding
   state lives in server-reserved conversation labels (each ≤ 256 chars, `_LABEL_MAX`), not
   in preferences/snapshots, so the port does not add to either. Residual risk: a large
   per-harness model catalog (many Codex/Claude/Cursor rows served by the labeled-bridge
   path, `3444f699f`) can still hit the snapshot cap — the failure is a hard
   `INVALID_INPUT` on session create/update. Mitigation: keep model allowlists short; if hit,
   trim the catalog rather than patching the cap.
2. **Owner-only MCP management (#8481, `f46ff65ce`).** v0.16.0 requires session *ownership*
   to configure a session's MCP servers and hides child MCP controls from collaborators.
   The fork never changes this; trio sub-sessions are created by the same user that owns
   them, so the trio stack is unaffected. Risk: any automation that edits another user's
   (or a shared) session's MCP servers now gets 403 — `sys_session_*` flows that run as a
   collaborator must not rely on editing a child's MCP config.
3. **Pane-reaper rule merge (#8320 + fork `642b879d7`).** The two rules were combined in
   `_pane_is_busy_after_harness`; a pane with a harness gone but recent human input is still
   kept. A mistake here reaps a pane someone is typing in, or keeps idle panes resident. Covered
   by `tests/terminals/test_pane_reaper.py` (29 passed) — first place to look on a reaping bug.
4. **Codex launch refactor (`_launch_codex_native_tui`).** v0.16.0 moved the inline Codex
   launch; the fork's tmux advertise (`41d82337d`/`305ac7cf7`) was re-applied inside it by
   hand. If Codex stop/advertise misbehaves live, compare with fork `41d82337d`.
5. **Input-fence placement in v0.16.0's batched external-item path.** Batched external
   conversation items (never user input) bypass the admission gate by design (see
   `port-cursor-receipts.md`); a future upstream change that batches input would bypass the fence.
6. **Test-environment sensitivity** (no product risk): a stray empty `/tmp/.git` on this host
   makes cursor's project-root refusal fire for every `/tmp` workspace; `tests/conftest.py`
   gained `_avoid_git_ancestor_temproot` (moves pytest's tmp root to `/var/tmp` only in that
   case). On a real host with `/tmp/.git`, cursor launches from under `/tmp` are refused —
   that is the intended fork behaviour (`510511735`).
7. **Venv extras.** Several suites need `uv sync --frozen --extra all --group dev`
   (e.g. `opentelemetry.sdk` for `test_claude_native_forwarder.py`); a venv synced without
   `--extra all` shows collection errors that are not regressions.

## 7. Not verifiable without a live server

GOAL forbids starting/stopping the Omnigent server, so these were not exercised live:
- Real `cursor-agent` turns: completion receipts end-to-end, plugin-dir route with the real
  CLI (`tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py`, `tests/e2e/test_cursor_native_cli_e2e.py`
  are skipped without `OMNIGENT_E2E_CURSOR_NATIVE=1` + `cursor-agent login`).
- Real Codex app-server `thread/compact/start` against a live `codex` (unit/integration tests
  use a fake app-server; `tests/e2e_ui/sessions/test_codex_native_compact_takes_effect.py`
  needs the UI stack).
- Live Claude Code hook bridge over the Unix-socket MCP with a real `claude` binary.
- Kill escalation and pane reaping against real tmux panes of a live runner under load.
- Host-spawned runner env propagation (`OMNIGENT_CURSOR_PLUGIN_DIR`) through a live host.
- The 64 KB snapshot cap against the user's real model catalogs.
- Trio loops (child `reasoning_effort`) through the refreshed patch on a live server.

## 8. Install and rollback (for later; nothing here was run)

The live server runs from the editable checkout `/home/coder/omnigent` (currently at the
fork tip `318264335`, branch `release/omnigent-2a84483a`, no local diff). Install, in a
maintenance window chosen by the human:

```sh
# 0. record the rollback point
cd /home/coder/omnigent
git status --short                     # must be clean (reverse the trio patch first if applied:
                                       #   git apply --reverse ~/.local/share/trio-agent-loop/current/omnigent/patches/child-reasoning-effort.patch)
git tag -f pre-v16-rollback HEAD       # = 318264335
# 1. bring in the re-ported branch
git fetch /home/coder/omnigent-v16 trio-v0.16.0-fixes:trio-v0.16.0-fixes
git switch trio-v0.16.0-fixes
# 2. apply the refreshed trio patch
git apply --check /home/coder/omnigent-v16/patches/child-reasoning-effort.v0.16.0.patch && \
  git apply /home/coder/omnigent-v16/patches/child-reasoning-effort.v0.16.0.patch
# 3. sync the env to v0.16.0's lock, with the same --extra set the current install uses
uv sync --frozen --extra all
# 4. restart the Omnigent server/runner the way it is normally restarted (human step);
#    run DB migrations if the server does not run them on start (v0.16.0 adds 9 migration files vs the fork tip, incl. `ll1a2b3c4d5e_compress_inference_snapshot`).
# 5. smoke: ~/.local/share/trio-agent-loop/current/omnigent/smoke-test.sh
```

When the trio release is next updated, ship `patches/child-reasoning-effort.v0.16.0.patch`
as the release's `omnigent/patches/child-reasoning-effort.patch` (that file is outside this
repo; it was deliberately not written).

Rollback:

```sh
cd /home/coder/omnigent
git apply --reverse /home/coder/omnigent-v16/patches/child-reasoning-effort.v0.16.0.patch   # if applied
git switch release/omnigent-2a84483a && git reset --hard pre-v16-rollback   # 318264335
uv sync --frozen --extra all
# restart the server (human step). Caveat: if v0.16.0 migrations ran, take a DB backup
# before step 4 of the install and restore it on rollback — 0.14-era code does not
# downgrade the schema.
```
