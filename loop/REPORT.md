# Report — iteration 1

## What was done
Whole GOAL (DoD 1–6) in one iteration: 9 builder slices merged by the driver, then a Lead review with 5 corrective commits.
- **Port slices** (cherry-pick `-x`, original order, from `v16/trio-v0.16.0-fixes`): v17-port-close, v17-port-stop, v17-port-receipts,
  v17-port-isolation-compact, v17-port-binding-plugin. Per-slice notes: `docs/v17-evidence/dispositions/*.md`.
  Result: 66 v16 commits → 43 ported, 12 adapted, 3 dropped (de03a352c/d69671640 superseded by upstream #8516; 39e45d8d4 points at a helper
  v0.17.0 no longer has, its alias comes from d4f6816bf→669e05bfd), 8 not ported (5 worker merges, 3 loop-only).
  Hunks from the v0.17.0 `runner/app.py` split were moved into `omnigent/runner/native_controls.py` (input fence, Codex manual compact);
  the manual-compact test moved to `tests/harnesses/codex_native/`.
- **v17-baseline**: `scripts/v17_focused_suite.sh` (11 groups) + `docs/v17-evidence/baseline-v0.17.0.txt` (pristine 12b5f67d2).
- **v17-patch**: `patches/child-reasoning-effort.v0.17.0.patch` + `docs/v17-evidence/patch-check.txt`.
- **v17-afterport**: `scripts/v17_overlap_check.sh`, `docs/v17-evidence/{after-port,overlap-check}.txt`.
- **v17-report**: `docs/v17-report.md` (disposition table, overlaps, baseline vs after-port, DoD-4 map, migrations, risks, live-server gaps, install/rollback).
- **Lead review corrections** (on top of the merges):
  - `c2bedad97` slice(v17-port-stop): fix ruff format — 7 ported stop/kill files were not ruff-format clean under v0.17.0's line length (pristine is clean). Formatting only.
  - `8001e9de9` slice(v17-port-receipts): fix ruff format + RUF100 (unused `# ruff: noqa: F811`) in `tests/test_cursor_native_completion_receipt.py`, `tests/server/integration/test_input_fence.py`.
  - `250f4c3e5` slice(v17-port-receipts): fix 7 pyrefly errors that the port added in `omnigent/harnesses/cursor_native/forwarder.py` (receipt/turn-outcome block on top of #8516's `pending_turn_end`): explicit `pending_turn_end is not None` narrowing, `cast` of receipt key/counts, and one `posted_update` tuple in place of maybe-unbound `key/rev/digest`. No behaviour change. `pyrefly check` now `0 errors`.
  - `7470ce929` slice(v17-afterport): fix `scripts/v17_overlap_check.sh` — its "moved" detection also searched `docs/v17-report.md`, which quotes the absent lines, so a tip re-run turned a real absence into a false "moved". It now excludes the report.
  - `c813e0b82` slice(v17-afterport): fix evidence — Lead final-tip suite re-run added to `after-port.txt`, `overlap-check.txt` regenerated at the tip, report §2 forwarder line refs updated, report §3 note added.

## Deviations from plan
- Lead review added 5 `slice(<id>): fix …` commits (above). `c813e0b82` (v17-afterport) also edits `docs/v17-report.md`, a v17-report write (trio-shadow lists it as 1 undeclared touch; shadow-only).
- One focused-suite failure id at the final tip is not in the baseline: `tests/harnesses/claude_native/test_claude_native_status_file.py::test_poller_publishes_when_only_the_reason_changes`. It also fails on a pristine v0.17.0 worktree (`2 failed, 19 passed`), and the module and its test are unchanged from v0.17.0. Recorded as a timing-dependent pre-existing failure, not a regression (after-port.txt Lead section, report §3).

## How I verified it
- Table vs trailers (script over `docs/v17-report.md`): `rows 66`, `Counter({'ported': 43, 'adapted': 12, 'not ported': 8, 'dropped': 3})`, mismatches `[]` (every ported/adapted new sha carries `cherry picked from commit <v16 sha>` and is an ancestor of HEAD); all 66 commits in `v0.16.0..v16/trio-v0.16.0-fixes` are in the table, `missing []`.
- Patch: `git apply --check` on a detached pristine v0.17.0 worktree → `pristine=0`; on the tip before and after the fixes → `tip=0`, `tip_apply=0`.
- Lint: `ruff check` / `ruff format --check` on all 59 .py files added or modified since b52507b70 → `All checks passed!`, `59 files already formatted` (before the fixes: 1 error, 8 files would reformat; pristine versions of the same files: clean).
- Typecheck: `.venv/bin/pyrefly check` → before `INFO 7 errors` (all in cursor_native/forwarder.py receipt block), after `INFO 0 errors (437 suppressed, …)`.
- Goal-probe tests: `TMPDIR=/var/tmp/pytest-of-coder uv run --frozen pytest -q -p no:cacheprovider -x tests/test_cursor_native_completion_receipt.py tests/test_cursor_native_plugin_dir.py tests/server/integration/test_input_fence.py tests/harnesses/codex_native/test_codex_native_manual_compact.py tests/terminals/test_pane_reaper.py tests/test_cursor_native_permissions.py tests/tools/builtins/test_sys_session.py` → `316 passed in 89.12s`. After the forwarder fix: receipt + forwarder + plugin-dir + cursor_native + fence → `279 passed in 31.07s`.
- full_check at final tip 250f4c3e5: `TMPDIR=/var/tmp/pytest-of-coder bash scripts/v17_focused_suite.sh /var/tmp/pytest-of-coder/v17-full-lead.txt` → exit 0, SUITE_DONE, 0 TIMEOUT:
  dispatch 284 passed/1 skipped; interrupt 24 passed; runner-native 7 failed/583 passed; sys-session 45 passed; terminals 109 passed/2 skipped;
  claude-native 3 failed/1546 passed; codex-native 1484 passed; cursor-native 556 passed; inner-proc 40 passed/8 skipped; host 6 failed/257 passed; sessions-routes 64 passed.
  16 FAILED ids; 15 in the pristine baseline; 1 extra = the status_file timing test above, which also fails on pristine.
- Overlap: `bash scripts/v17_overlap_check.sh` at the tip → every PR 0 absent except #8516 (6 absent, 1 moved), all in cursor_native/forwarder.py where the fork's receipt layer reshaped the same post. The report §2 shows each one is still present as reshaped code (checked the code at forwarder.py:1900/1947/1953/1960/1965 and `_post_external_session_status`).
- Report §6 spot-checks: `git diff --name-only --diff-filter=A 318264335 v0.17.0 -- omnigent/db/migrations/versions` → the 10 listed revisions; `feature_flags.py` refuses unknown names at startup (line 96/121) and renames the flag to `HARNESS_SETTINGS_UI`.
- Wiring of the re-homed handlers: `runner/app.py:6523` → `_handle_cursor_native_input_fence`, `:6710` → `_handle_codex_native_compact`, both bound from `native_controls` (`app.py:7038/7043`).
- Commit gate: `trio-shadow.py --mailbox loop --require-commits` → `commit gate: PASS`.

## Known weaknesses
- `test_claude_native_status_file.py` is timing-flaky upstream (the failing subset changes between runs on both trees). A strict "no new ids" diff can flag it. The evidence for it being pre-existing is a pristine re-run, not a code fix.
- The 3 dropped commits rely on upstream #8516 covering the same yolo-accept behaviour. The covering tests pass, but there is no live cursor-agent run.
- `cursor_native/forwarder.py` receipt + turn-outcome merge (5f21ceaf5 adaptation, plus the Lead's pyrefly refactor) is the riskiest hand-resolved area. Look there first if cursor parent-wake or receipt re-posts misbehave.
- Nothing needing a live server, real CLIs or real tmux under load was exercised (report §7). Install/rollback (§8) is documentation only.

## Delegation summary
All implementation and evidence went to 9 Sonnet builders, run by the driver in isolated worktrees. Three port slices took 2 attempts: the first attempts stopped mid-cherry-pick after permission denials. The Lead reviewed the merged diff and fixed lint/format (2 commits), pyrefly type errors (1), an overlap-script false "moved" (1) and refreshed the evidence (1).

## Implementation provenance
- Primary Sonnet builder(s):
  - v17-port-close (builder v17-port-close-a4f3aa87; 1st attempt v17-port-close-99240980 not merged) — 10 v16 commits, 7 picked (3 adapted), 3 dropped; merged bc433e1b28e5b5df355883b8effde7f19174fd54.
  - v17-port-stop (v17-port-stop-8c96f720; 1st attempt v17-port-stop-0f5d0b2c not merged) — 9 stop/kill/reaper commits + README; merged 79fcc12e6241fdd26d0cccff8deb5a5746c1e0b4.
  - v17-port-receipts (v17-port-receipts-a0f065ed; 1st attempt v17-port-receipts-c145c968 not merged) — 9 receipt/fence commits + 2 adaptation commits; merged d5f485f7f8b4ca5be9800548874de7def4473e7f.
  - v17-port-isolation-compact (v17-port-isolation-compact-6b4be251) — 12 commits, 0b90fce3e re-homed into native_controls.py, compact test moved; merged a13bf28a67a277f9db59b38ae37a9742def73166.
  - v17-port-binding-plugin (v17-port-binding-plugin-c453af6d) — 18 commits (16 clean, 2 adapted); merged 5ad14e711271bf72ee8e4d2bdd15b70ccad611a5.
  - v17-baseline (v17-baseline-0c9aad2d) — suite script + pristine baseline; merged ecd6d0f3f2ce3b0e28e9c08b25299477e07f691d.
  - v17-patch (v17-patch-7b5b0e57) — v0.17.0 patch + check; merged bec4ae12d24fd0388284a18d67e688d8e21d2ba7.
  - v17-afterport (v17-afterport-da238cd4) — after-port suite, overlap script/check; merged 903c3aeaba90826f8ac51a6e15d66725bca6197c.
  - v17-report (v17-report-61328491) — docs/v17-report.md; merged 33d3c2b568e2eeb59ba1b38f4c329be7891e4612.
- Opus corrective edits: c2bedad97 (ruff format, 7 files), 8001e9de9 (ruff format + RUF100, 2 test files), 250f4c3e5 (pyrefly fixes, cursor_native/forwarder.py, no behaviour change), 7470ce929 (overlap script exclusion), c813e0b82 (evidence refresh + report line refs/§3 note). These were direct fixes because they are mechanical lint/type corrections and evidence upkeep on top of the merged work, not reimplementation.
