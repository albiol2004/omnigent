# GOAL — forking never blocks the app: diagnose the missed native passthrough, then make fork async with a per-session "preparing" state

Target repo: /home/alex/omnigent-fixes (git WORKTREE, branch `fork-async-preparing`, based on trio-v0.10.0-fixes c48533487, which is checked out LIVE in /home/alex/omnigent). Mailbox: loop-fork-async/. Prior loops (read their REPORT/VERDICT for context, do not redo): loop/ (diagnosis), loop-compact/, loop-fixes/ (hotfixes), loop-fork-real/, loop-fork-cli/ (native passthrough + CLI-only summaries, slices 3d26d9ecd / 77697270b).

## Production observation (live, 2026-08-28 21:57–21:58, branch c48533487)
The user forked their claude-native session `e34847899b7d47b3ad322948d4ea6002` (same CLI family, claude → claude). Server log:
```
21:57:19 fork_compact ...t_with_resolved | Fork compaction model resolved: source=source_override model=claude-cli/opus
21:58:15 POST /v1/sessions/e348…/fork  201 Created  56020.6ms
```
So the fork SUCCEEDED but took **56 s** because it compacted — the native passthrough from `3d26d9ecd` did **not** fire, even though this is exactly the same-family native case it was built for. Facts checked on the live box: `OMNIGENT_FORK_NATIVE_GUARD` / `OMNIGENT_FORK_COMPACT*` are unset in the server env; the source's `external_session_id` is set (`f4bd03c9-3c11-46fd-b0df-fdc7952301c2`); source labels are `omnigent.ui=terminal`, `omnigent.wrapper=claude-code-native-ui`; the source agent is `58a1bc5b…`. The fork row was deleted by the user afterwards, so its labels cannot be inspected — the diagnosis must be REPRODUCED, not guessed.

User report on UX (verbatim intent): the fork dialog is "a modal on top of everything" that cannot be closed while the 56 s call runs — "it should directly create the session and block it until available rather than freeze the whole app".

## Mission
(1) Determine and fix why a same-family native fork still took the compaction path, so the common case is instant; (2) make `POST /fork` return immediately in every case, with any needed compaction running in the background and the NEW session showing a "preparing" state that blocks only itself — never a blocking modal over the whole app.

## Relevant code (use `grep -n` + `sed -n` ONLY — routes_core.py, helpers.py, orchestration.py, claude_native.py, chatStore.ts exceed 1 MB and full-file ingest crashes the transport)
- `omnigent/server/routes/sessions/routes_core.py:2352-2371` — `native_clone_passthrough` predicate (all conditions must hold: `not fork_native_guard_enabled()`, source `external_session_id` non-empty, `resume_source_native_session`, `body.up_to_response_id is None`, `carry_history_into_native`, `target_is_native_clone`, then a re-resolve of `source_harness` into {claude-native, codex-native}).
- `:2299-2311` — `carry_history_into_native` / `resume_source_native_session` derivation; `:236-246` `_items_through_response` (returns all items when `up_to_response_id is None`).
- `:2372+` — the guard/compaction branch that ran.
- UI: `web/src/shell/ForkSessionDialog.tsx` (blocking "Summarizing history…" at ~847-857, added by 22793b2dd), `web/src/lib/sessionsApi.ts:527-572` `forkSession()`, `web/src/shell/ForkDialogContext.tsx`, session list/labels rendering for a session state badge.
- Compaction progress events: `omnigent/server/routes/_sessions/helpers.py:1542-1580` `_publish_compaction_in_progress/_completed/_failed`.

## Slices
1. **passthrough-why** — Add a single structured INFO log in `fork_session` naming exactly which condition(s) made `native_clone_passthrough` false (e.g. `fork passthrough skipped: up_to_response_id set`, `… source harness resolved to X`), so this is never a guessing game again. Then REPRODUCE the user's case on a throwaway server (see Verification floor) with a read-only copy of conversation `e34847899b7d47b3ad322948d4ea6002` and its real agent/labels, forking the same way the Web UI does (same agent, no explicit fork point) and record which condition actually failed. Deliver `loop-fork-async/evidence/iter1/passthrough-why/DECISION.md` with the log output and the identified cause.
2. **passthrough-fix** — Fix the identified miss with the smallest correct change, WITHOUT widening passthrough to cross-family/SDK/rebuild forks (that would resurrect "Prompt is too long"). Known candidates to evaluate: (a) `up_to_response_id` pointing at the LAST response is equivalent to a full fork and should still pass through; (b) the `_resolve_fork_target_harness` re-resolve returning something other than `claude-native` for a wrapper/sub-agent-labelled source; (c) `carry_history_into_native` false for this agent. Add regression tests for the real shape (a claude-native source with `omnigent.wrapper=claude-code-native-ui`, agent-less/same-agent fork) plus negative tests proving cross-family/SDK/truncated-prefix forks still compact.
3. **async-fork-preparing** — `POST /fork` must return **201 immediately** (target: < 1 s) in every path:
   - Create the fork conversation with the copied items and, when compaction is required, mark it `omnigent.fork.preparing=1` (plus `omnigent.fork.preparing_reason`), then run compaction in a background task (server-owned, survives the request; on completion swap in the compacted items and clear the label; on failure set `omnigent.fork.preparing=failed` + a human-readable reason label and publish the existing compaction-failed event).
   - The runner/launch path must refuse to launch a session while `preparing=1` (no half-built transcript) and launch normally once cleared.
   - UI: the fork dialog CLOSES immediately on 201 and navigates to the new session; that session's view shows a non-blocking "Preparing fork — summarizing history…" state and disables its composer until ready, updating live via the existing compaction SSE events; on failure it shows the reason in-session with a retry affordance. No modal may cover the app while preparing.
   - Env `OMNIGENT_FORK_ASYNC=0` restores the synchronous behavior.

## Verification floor
Test-first. Server unit/integration tests for the passthrough predicate + the async contract (201 fast, labels set/cleared, background task success and failure, launch refused while preparing). Web tests in `web/src/shell/*.test.tsx` / store tests for: dialog closes on 201, preparing badge + disabled composer, failure surface. AND a REAL e2e on a throwaway server (port ≥ 18000, scratch `OMNIGENT_DATA_DIR`/`OMNIGENT_CONFIG_HOME`, `OMNIGENT_PROCESS_LOG_FILE` unset, config.yaml copied read-only with key-kind providers REMOVED) using a read-only copy of conversation `e34847899b7d47b3ad322948d4ea6002` (16-byte blob ids; copy conversations / omnigent_conversation_metadata / conversation_labels / conversation_items / agents / users / session_permissions / files rows — reuse the scripts under `loop-fork-cli/evidence/iter1/real-e2e/` and `loop-fork-real/evidence/iter1/eval-e2e/`) and a read-only copy of that session's `~/.claude/projects/<ws>/<sid>.jsonl` into a scratch `_CLAUDE_PROJECTS_DIR`:
  (a) same-agent fork → **201 in < 1 s**, no compaction, no `preparing` label, fake-`claude` launch uses `--resume` on the cloned transcript;
  (b) agent-switch (rebuild) fork → **201 in < 1 s** with `preparing=1`, then the background CLI summary completes (real `claude -p`, keys unset in the child env) and the label clears, rendered transcript < 600 kB;
  (c) same as (b) with `claude` absent from PATH → label becomes `failed` with a reason, no stuck `preparing`, and the fork remains deletable.
Record wall times for the POST and for the background completion.

## HARD isolation
`~/.omnigent` and `~/.claude/projects` are READ-ONLY (copies only; any `claude -p` run uses a scratch cwd so its project dir is scratch-scoped). Never touch the live server on :6767, `omni host`, or /home/alex/omnigent (shares .git — run no git commands there). Throwaway servers only, torn down; never kill processes you did not start. Preserve every existing commit (no amend/rebase/revert); new work = `slice(<slice-id>): …` commits with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Additive and env-overridable; CLAUDE.md rules (short scenario comments, no issue numbers in code). Tests need `PYTHONPATH=/home/alex/omnigent-fixes`; pre-commit via `PATH=/home/alex/omnigent/.venv/bin:$PATH`.

## Acceptance
1. `DECISION.md` names the reproduced cause of the passthrough miss, with the new log line as evidence.
2. e2e (a): same-agent native fork of the real session → 201 in < 1 s, no compaction item, `--resume` launch on the >600 kB clone.
3. e2e (b)/(c): 201 in < 1 s with `preparing`, background completion clears it; missing CLI → `failed` + reason, never a stuck preparing session; launch refused while preparing.
4. UI: fork dialog closes on 201 (test asserts it is unmounted), the app is interactive while a fork prepares, the preparing session shows its state and a disabled composer; `OMNIGENT_FORK_ASYNC=0` restores sync behavior.
5. Suites green: `uv run pytest -q tests/fork_context tests/server/routes/test_fork_compact.py tests/server/routes/test_fork_oversize_guard.py tests/runner/test_fork_clone_fallback.py tests/runner/test_fork_context_guard.py tests/runner/test_fork_resume_oversize_guard.py tests/test_claude_native_bridge.py` + the new tests; `cd web && npx vitest run` for touched web tests; Trio-compat (`uv run pytest -q tests/tools/builtins/test_spawn.py tests/runner/test_runner_dispatch.py tests/server/integration/test_sessions_child_sessions.py -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'`); pre-commit clean on changed files; slice commits present; tree clean except mailbox.
6. Isolation audit: `:6767/health` 200; no files written by the loop under `~/.omnigent` or `~/.claude/projects`; no `:180xx` listeners left; no leftover `claude` processes started by the loop.
7. REPORT ends with operator steps: fast-forward `trio-v0.10.0-fixes`, `cd web && npm run build` (web changed), `omni server stop`, then fork the session and expect it to open immediately.
