# PLAN — v0.14.0 re-port, iteration 1

Iteration **1**. First Lead pass. Mailbox `loop-v14-rebase/`.
Worktree `/home/coder/omnigent-dev`, branch `trio-v0.14.0-fixes`
(tag `v0.14.0` = `fc89a3ba3` plus mailbox commits).

Hard boundaries: never touch `/home/coder/omnigent`, never
`uv tool install`, never start/stop any `omni` on port 6767,
never `git worktree`, never switch branches, never push, never
rewrite existing commits. Commits: `git cherry-pick -x <sha>`
for kept patches (keep original message); new work as
`slice(<id>): ...`. No AI coauthor trailers.

## Objective (this iteration)

Re-port the `trio-v0.12.0-fixes` keeper set onto upstream v0.14.0
after the #6721 harness regroup. Drop commits that upstream now
covers. Re-export `_resolve_agent_spec` so `trioctl omnigent
doctor` session-contract PASSes. Re-add `loop-session-close/`
and the README fork note for `trio-v0.14.0-fixes`.

## Verification standard

mode: `implement-then-smoke`

Evidence lives in `loop-v14-rebase/evidence/` (baseline) and
`loop-v14-rebase/evidence/iter1/` (this pass).

- Baseline on the pristine tree (before any product cherry-pick),
  one directory at a time, no xdist, no whole-suite process:
  `uv run --project /home/coder/omnigent-dev pytest -q -p no:cacheprovider <dir>`
  for `tests/runner`, `tests/tools`, `tests/terminals`, plus
  the current claude/codex/cursor bridge files:
  `tests/test_claude_native_bridge.py`,
  `tests/test_codex_native_bridge.py`,
  `tests/test_cursor_native_bridge.py`,
  `tests/test_cursor_native_permissions.py`,
  `tests/test_claude_native.py` (compaction overlap),
  `tests/test_codex_native.py` (writer-resume overlap).
  Save summary lines to
  `loop-v14-rebase/evidence/baseline-v0.14.0.txt`.
- After ports, re-run the same directories. Zero **new**
  failures vs baseline. Focused GOAL files must pass:
  `tests/runner/test_runner_dispatch.py`,
  `tests/tools/builtins/test_sys_session.py`,
  `tests/runner/test_native_interrupt_runner.py`,
  `tests/terminals/test_pane_reaper.py`,
  plus the bridge/permissions tests above.
- `uv run --project /home/coder/omnigent-dev ruff check` on
  every touched product file.
- `trioctl omnigent doctor` from this worktree:
  `omnigent:session-contract` must PASS.
- Isolated smoke: `OMNIGENT_DATA_DIR=/tmp/omnigent-dev-data`
  `uv run --project /home/coder/omnigent-dev -- omni server --port 7767`,
  hit `/health` (or equivalent), then stop the process.
  Never bind 6767.
- Old-import grep must be empty outside git history:
  `omnigent\.(claude_native_bridge|codex_native_|cursor_native_)`.
- GLM workers only via
  `trioctl omnigent run builder --prompt-file loop-v14-rebase/briefs/<name>.md --workspace .`
  for heavy conflict resolutions. Briefs carry exact
  `git diff --diff-filter=U` hunks and new path + line ranges,
  never whole large files (`tool_dispatch.py`, `app.py`,
  orchestration).

## Disposition plan (oldest first)

Keep (cherry-pick `-x`, resolve onto `omnigent/harnesses/*`):

1. `760441438` kill-on-close — leftover SIGKILL on Claude
   `kill_session` + stop event on close. Map
   `omnigent/claude_native_bridge.py` →
   `omnigent/harnesses/claude_native/bridge.py`. Keep
   upstream `archived=True` on the close PATCH; add the
   stop/interrupt POST beside it.
2. `4292b1a7d` queue-aware yolo — map
   `omnigent/cursor_native_permissions.py` →
   `omnigent/harnesses/cursor_native/permissions.py`.
   v0.14.0 still has the pre-queue `_yolo_auto_accept`.
3. `6d97d3ecc` phantom yolo cards — same permissions file.
4. `c1128dc3c` Codex bridge-owner model options —
   `omnigent/runner/app.py`.
5. `6bb85ac39` Codex compaction markers — map
   `omnigent/codex_native.py` →
   `omnigent/harnesses/codex_native/` (follow the function).
6. `cc40d1513` close-guard — title-parse still rejects
   verbatim `sys_session_create` titles (~6081-6083).
7. `97d84a2fc` stop-routing — Codex still has no
   `kill_session`; `_UNIFORM_STOP` still omits Codex.
8. `208aada58` kill-escalation — new helper; prefer
   `omnigent/native/native_tmux_kill.py` (or harnesses)
   and update imports.
9. `eea0c6862` pane reaper after harness `release`.
10. `ec696c5fc` Codex advertise guard.

Drop after scout/targeted evidence (record in REPORT):

- `96b5639d8` Claude compacted resume — CHANGELOG #6364 +
  `test_claude_transcript_records_handles_native_compaction_messages`.
- `c04442f16` launch args from root spec — upstream
  `test_native_subagent_yolo_args_derived_from_trusted_spec`.
- `0c8082af2` Codex active-writer resume-as-loaded —
  new resume path reaps leftover writers
  (`process_registry.reap_codex_native_processes_for_state_dir`)
  and `test_is_unreadable_thread_error` requires an active
  writer to fail loud. Keep only if a targeted test still
  reproduces the old bug.

Re-port as alias (Addendum; not a blind cherry-pick of the
helpers import):

- `fd38b1ea8` — in `omnigent/server/routes/sessions/__init__.py`
  re-export `_resolve_agent_spec` as an alias of
  `_resolve_subagent_spec`. Note whether trioctl should
  switch to the upstream name.

Bookkeeping:

- `git checkout trio-v0.12.0-fixes -- loop-session-close`
- README fork section: this worktree is `trio-v0.14.0-fixes`
  on stock `v0.14.0`; live install stays on
  `trio-v0.12.0-fixes` until adopt. Include #7498 leak
  rationale from `005399286`. Combined as
  `slice(readme): ...` rather than two conflicting 0.12 notes.

## Relocated paths (do not ingest whole files)

- Claude bridge `kill_session` ~
  `omnigent/harnesses/claude_native/bridge.py:4006-4047`
- Cursor bridge `kill_session` ~
  `omnigent/harnesses/cursor_native/bridge.py:1007-1017`
- Cursor yolo ~
  `omnigent/harnesses/cursor_native/permissions.py:327-938`
- Codex `preload_codex_thread_for_resume` ~
  `omnigent/harnesses/codex_native/app_server.py:3436-3483`
- Close REST ~
  `omnigent/runner/tool_dispatch.py:5982-6109`
  (`_parse_session_title` still required after tree-scope)
- Native interrupt `_UNIFORM_STOP` / `stop()` ~
  `omnigent/runner/native/interrupt.py:207-413`
- Sessions package export ~
  `omnigent/server/routes/sessions/__init__.py:509-511`
- Pane reaper `omnigent/terminals/pane_reaper.py`

## GLM workers

Profile-resolved builder via `trioctl omnigent run builder`.
Use for any cherry-pick that leaves unresolved hunks in
files >200 lines after mapping paths. Each brief: conflicting
hunks only + destination path + nearby line ranges.

Scout (optional): drop-candidate confirmation if the targeted
tests above are not decisive.

## Commit gate

After product commits:
`python3 /home/coder/personal/trio-agent-loop/metrics/trio-shadow.py --mailbox loop-v14-rebase --require-commits`
