# Builder brief — native-fork-passthrough

Workspace: `/home/alex/omnigent-fixes` (git WORKTREE, branch
`fork-compact-cli`). Mailbox: `loop-fork-cli/`. Slice id:
`native-fork-passthrough`. Luna model: `gpt-5.6-luna-max`.

You implement ONLY this slice. Do not git commit, push, stash,
reset, rebase, checkout, or amend. Lead will commit.
Do not edit `omnigent/fork_compact.py` or
`omnigent/fork_compact_cli.py` (slice `cli-summary-for-rebuild-paths`).
Do not edit GOAL.md / VERDICT.md.

## HARD isolation

Never write `~/.omnigent` or `~/.claude/projects`. Never git
`/home/alex/omnigent`. Never live `:6767`, `omni host`. Never kill
processes you did not start. `OMNIGENT_PROCESS_LOG_FILE` unset if
you start anything (you should not start a server).

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
```

## NEVER read these files whole

`routes_core.py`, `helpers.py`, `orchestration.py`, `claude_native.py`,
`codex_native.py`. Use `sed -n` / `grep -n` on the ranges below.

## Diagnosed line ranges

- `omnigent/server/routes/sessions/routes_core.py`
  `fork_session` **2170-2510**. Family/native flags **2269-2311**.
  Guard/estimate/compact block **2348-2420** (continues to ~2460).
  Store call `resume_source_native_session and replacement_items
  is None` **2472-2474**.
  Source native id: `source.external_session_id`
  (`entities/conversation.py:229`). Target family:
  `_same_provider_family` / `resume_source_native_session`.
  Native target: `_agent_carries_native_fork_history`.
  Truncation: `body.up_to_response_id` (rebuild path — do NOT skip).
- `omnigent/runner/native/orchestration.py`
  `_auto_create_claude_terminal` **6088+**. Clone branch
  **6358-6440** (`_clone_claude_transcript`, catches
  `ForkContextTooLarge` → `clone_context_too_large`).
  Hotfix-2/3 rebuild **6448-6520**
  (`_ensure_local_claude_resume_transcript(..., guard=True)`).
  Codex analogue `_auto_create_codex_terminal` **3717+**, clone
  **3825-3870** (`_clone_codex_rollout`).
- `omnigent/claude_native.py` `_clone_claude_transcript`
  **1826-1898**: always calls `guard_fork_context_bytes` at
  **1888**. `_compact_cloned_transcript` **1666-1704** — KEEP
  calling this when oversize (free compact_boundary trim).
- `omnigent/codex_native.py` `_clone_codex_rollout` **1753-1833**:
  same guard at **1825**. Keep `_compact_codex_rollout`.
- `omnigent/fork_context.py` `guard_fork_context_bytes` **122-149**
  already has `guard: bool = True`. Do not rewrite that file
  unless you add a tiny env helper; prefer reading the env in
  the clone helpers / route.

## Probe decision (mandatory)

KEEP clone + `--resume <clone-uuid>`. Do NOT add `--fork-session`.
See `loop-fork-cli/evidence/iter1/probe/DECISION.md`.

## Behavior

1. In `fork_session`, AFTER computing `resume_source_native_session`
   and `carry_history_into_native`, skip the entire
   estimate/guard/`compact_fork_items` block when ALL of:
   - `source.external_session_id` is a non-empty str
   - `body.up_to_response_id` is None
   - `resume_source_native_session` is True
   - `carry_history_into_native` is True
   - source harness canonicalizes to claude-native or codex-native
     (not pi, not SDK). Existing tests without agent_cache treat
     native-history as False — they MUST keep hitting the guard.
   - `os.environ.get("OMNIGENT_FORK_NATIVE_GUARD", "").strip() != "1"`
   Then `replacement_items` stays None and the handler returns 201.
2. `_clone_claude_transcript` / `_clone_codex_rollout`: add
   `guard: bool | None = None`. Default: True only when
   `OMNIGENT_FORK_NATIVE_GUARD=1`, else False. Pass that into
   `guard_fork_context_bytes(..., guard=...)`. Still run
   `_compact_cloned_transcript` / `_compact_codex_rollout` when
   oversize. Orchestration clone call can omit the kwarg.
3. When guard is False, clone oversize must NOT raise, so the
   hotfix-2 rebuild branch is not taken. Keep the rebuild branch
   for missing source transcript, clone exceptions, and
   native-guard raises.
4. Comments: short, scenario not PR numbers. Lines < 88 chars.
   `dict` not `typing.Dict`.

## Tests first

Write/adjust tests BEFORE the product change.

- Same-family native fork: conversation with `external_session_id`,
  agent_cache harness `claude-native` (reuse
  `tests/server/routes/test_sessions_fork.py` stubs
  `_StubAgentCache` / `_make_conversation`). Payload > 600 kB
  (or threshold 32). POST `/fork` → 201, `compact_fork_items` not
  called, no compaction item. Cross-family switch of that source
  (or SDK target / no external_session_id) STILL estimates and
  compact/413 as today.
- `test_claude_clone_refuses_oversized_transcript`: default clone
  SUCCEEDS and writes the dest file; with
  `OMNIGENT_FORK_NATIVE_GUARD=1` it still raises and does not
  commit the dest. Keep compact_boundary trim test.
- `test_claude_fork_clone_oversize_rebuilds_from_items`: keep as
  the native-guard / clone-raise path. Add a case where clone
  returns a >600 kB path and launch argv contains `--resume` and
  does not call the rebuild helper.
- Existing rendered-size compact tests have no
  `external_session_id` and no native cache — they must stay 201
  with compaction (or 413 when compact disabled).

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
uv run pytest -q \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_compact.py \
  tests/runner/test_fork_clone_fallback.py \
  tests/runner/test_fork_context_guard.py \
  tests/runner/test_fork_resume_oversize_guard.py \
  tests/test_claude_native_bridge.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/server/routes/sessions/routes_core.py \
  omnigent/runner/native/orchestration.py \
  omnigent/claude_native.py \
  omnigent/codex_native.py \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_compact.py \
  tests/runner/test_fork_clone_fallback.py \
  tests/runner/test_fork_context_guard.py \
  tests/runner/test_fork_resume_oversize_guard.py
```

Write outputs under
`loop-fork-cli/evidence/iter1/native-fork-passthrough/`.
Print a compressed summary of files changed and test results.
