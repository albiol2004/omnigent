# GOAL — compact-on-fork: when a fork's context is oversize, summarize it (with the source session's pinned model) instead of refusing

Target repo: /home/alex/omnigent-fixes (git WORKTREE, branch `trio-v0.10.0-fixes`, HEAD e11b40f95 = Trio patches + four shipped fix slices). Mailbox: loop-compact/. Prior diagnosis: `loop/REPORT.md` problem 1; prior fix: `slice(fork-oversize-guard)` eabf6b101 (`omnigent/fork_context.py`, `routes_core.py:2190-2215` `guard_fork_context` → 413 `ForkContextTooLarge`).

## Mission
Make an oversize fork succeed by compacting the copied history with an LLM summary — using the source session's pinned model by default — so that the forked harness receives a transcript under `OMNIGENT_FORK_MAX_CONTEXT_BYTES`, while a fork that is already small stays byte-identical to today's behavior and the 413 remains only as the last resort.

## Verification floor
Tests added for every branch (small fork unchanged; oversize → summarized under threshold; summary fails → 413 with the original message; model resolution order); `uv run pytest -q` on the touched test files + the fork-guard tests (tests/server/routes/test_fork_oversize_guard.py tests/runner/test_fork_context_guard.py tests/inner/test_claude_sdk_fork_context_guard.py) green; `pre-commit run --files …` clean; an evidence run under loop-compact/evidence/iter<N>/ against a THROWAWAY server (scratch OMNIGENT_DATA_DIR + OMNIGENT_CONFIG_HOME, port ≥ 17100, torn down) forking the ~3.9 MB synthetic session from `loop/evidence/iter1/rc-fork/scratch/measure_fork_bytes.py` (a fake/mock LLM is acceptable for the summary call in the throwaway run; record the resulting byte count).

## HARD isolation constraints
Same as loop-fixes/GOAL.md: never touch ~/.omnigent, ~/.claude/projects, the live server on :6767, `omni host`, the user's :17067 test instance and its data dir /home/alex/omnigent-fixes-data, or /home/alex/omnigent (shares .git; no git commands there). Never kill processes you did not start. Preserve all existing commits (no amend/rebase/revert); new work = new `slice(compact-on-fork): …` commit(s) with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Rebase-friendly vs upstream #5603/#5405/#4913/#5081: additive, env-overridable, no route/store restructuring. CLAUDE.md rules (short scenario comments, named DB sessions, no issue numbers in code).

## Design (Lead may refine, must record deviations)
1. In `fork_session` (`routes_core.py` ~2190-2215): when `guard_fork_context` raises, and `OMNIGENT_FORK_COMPACT=1` (default ON; `0` restores refuse-only), run compaction on `context_items` BEFORE `fork_conversation`:
   - Reuse `omnigent/runtime/compaction.py::compact` (layers: clear tool bodies → LLM summary → truncate) via the same wiring `_run_compact_locked` (`helpers.py:6559`) uses to obtain llm config/client, context window, and runner client — factor a small shared helper rather than duplicating.
   - **Model resolution order:** (a) the source conversation's pinned model (conversation model settings / `copy_model_settings` source), (b) the fork target's requested model if the request switches agent/model, (c) the source agent spec's `llm`/`executor.model`. Log which one was used at INFO. Never a hardcoded model.
   - Result: write the compaction summary + retained recent items into the fork's item set (the same compaction/summary item shape `compaction_to_history_items` (`compaction.py:478`) produces, so `summary_only_items` and the native rebuild paths — `claude_native.py` compact/`compact_boundary` handling ~1666-1700, codex/pi/qwen resume paths touched in eabf6b101 — already honor it). Re-run `guard_fork_context` on the compacted payload; if still oversize → existing 413.
   - The SOURCE conversation is never modified.
2. Fork must not run while the source has a running turn (mirror the `_session_status_cache` check in `_run_compact_locked`; return CONFLICT with a clear message).
3. UI: the fork dialog should show progress ("Summarizing N MB of history with <model>…") using the existing compaction SSE events (`_publish_compaction_in_progress/_completed/_failed`, `helpers.py:1542-1580`) on the SOURCE session id, and surface the 413 text unchanged on failure. Keep the web change minimal (`web/src/shell/ForkSessionDialog.tsx` / `web/src/lib/sessionsApi.ts`); vitest for any store logic added.
4. Env knobs: `OMNIGENT_FORK_COMPACT` (1/0), `OMNIGENT_FORK_COMPACT_TARGET_BYTES` (default = 70% of `OMNIGENT_FORK_MAX_CONTEXT_BYTES`), `OMNIGENT_FORK_COMPACT_MODEL` (explicit override that wins over the resolution order).

## Slices
1. **compact-on-fork** — server-side compaction + model resolution + tests + throwaway evidence.
2. **fork-compact-ui** — dialog progress/failure surfacing + tests (may be folded into slice 1 if tiny; then note it).

## Acceptance
1. Forking the 3.9 MB synthetic session on a throwaway server (mock LLM allowed) succeeds; evidence records bytes before/after and the model that was resolved; forking a small session produces an item set identical to a fork before this change (test asserts equality).
2. Model resolution order is unit-tested: pinned source model wins; explicit env override wins over everything; fallback chain verified.
3. Targeted suites + Trio-compat command (`uv run pytest -q tests/tools/builtins/test_spawn.py tests/runner/test_runner_dispatch.py tests/server/integration/test_sessions_child_sessions.py -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'`) green; pre-commit clean; `slice(compact-on-fork): …` commit(s) present; tree clean except mailbox.
4. Isolation audit: `:6767` health 200, :17067 untouched (its data dir mtime unchanged — record `stat -c %Y /home/alex/omnigent-fixes-data/chat.db` before/after), no leftover processes.
5. REPORT ends with operator steps: rebuild web, restart the test instance (`:17067`) to try it, then the live deploy/rollback as in loop-fixes/REPORT.md.
