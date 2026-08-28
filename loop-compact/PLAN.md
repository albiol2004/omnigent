# PLAN — compact-on-fork (iter 1)

## Objective
When a fork's copied history exceeds `OMNIGENT_FORK_MAX_CONTEXT_BYTES`,
compact that copy with an LLM summary (source pinned model by default)
so the fork is under the limit. Small forks stay byte-identical. 413
remains only after compact is off, fails, or still exceeds the limit.
The source conversation is never modified.

## Verification standard
mode: test-first

Evidence lives under `loop-compact/evidence/iter1/<slice>/`.
Each slice must land failing-then-passing tests, `pre-commit` on
touched files, and captured command output in its evidence dir.
Slice 1 also records a throwaway-server fork of the ~3.9 MB
synthetic session (mock LLM allowed): bytes before/after and the
resolved model.

## Slices

### compact-on-fork
status: complete
writes: [omnigent/fork_compact.py, omnigent/server/routes/sessions/routes_core.py, omnigent/stores/conversation_store/__init__.py, omnigent/stores/conversation_store/sqlalchemy_store.py, tests/server/routes/test_sessions_fork.py, tests/server/routes/test_fork_oversize_guard.py, tests/server/routes/test_fork_compact.py, tests/fork_context/test_fork_compact_model.py]

Done criteria:
- `OMNIGENT_FORK_COMPACT` default ON (`0` restores refuse-only 413).
- Oversize fork: compact `context_items` in memory, then
  `fork_conversation` copies the compacted item set (summary marker
  + retained tail via `compaction_to_history_items` shape /
  `type=compaction` + tail). Re-guard; still oversize → 413.
- Model order: pinned source `model_override` → requested target
  model → agent spec `llm`/`executor.model`. Env
  `OMNIGENT_FORK_COMPACT_MODEL` overrides all. Never hardcoded.
  INFO log names the chosen model.
- Source running/waiting → 409 CONFLICT (same cache check as
  `_run_compact_locked`). Summary failure → 413 with the original
  `ForkContextTooLarge` message.
- Small fork item set equals pre-change fork (test equality).
- Target bytes default 70% of max via
  `OMNIGENT_FORK_COMPACT_TARGET_BYTES`.
- Tests: small unchanged; oversize summarized under threshold;
  summary fail → 413; model resolution order; compact=0 refuse.
- `uv run pytest -q tests/server/routes/test_fork_oversize_guard.py tests/server/routes/test_fork_compact.py tests/fork_context/test_fork_compact_model.py tests/runner/test_fork_context_guard.py tests/inner/test_claude_sdk_fork_context_guard.py`
- `pre-commit run --files` on writes.

### fork-compact-ui
status: complete
writes: [web/src/shell/ForkSessionDialog.tsx, web/src/shell/ForkSessionDialog.test.tsx]

Done criteria:
- While the fork POST is in flight, dialog shows
  `Summarizing N MB of history with <model>…` (N from known source
  size if available; model from session pin / same resolution hint).
  Use existing compaction SSE on the SOURCE session id when a
  stream subscription is already in reach; do not ingest
  `chatStore.ts`.
- 413 body text surfaces unchanged in the existing error slot.
- vitest covers progress-while-submitting and 413 error text.
- `cd web && npx vitest run src/shell/ForkSessionDialog.test.tsx`
- `pre-commit run --files` on writes.

## Out of scope
- Live :6767, ~/.omnigent, ~/.claude/projects, :17067,
  /home/alex/omnigent-fixes-data, /home/alex/omnigent.
- Amending/rebasing shipped slices. Killing foreign processes.
- Native JSONL clone rewrite beyond existing summary-only /
  compact_boundary handling (`claude_native.py:1666-1700`).
- chatStore.ts / orchestration.py / helpers.py full-file reads.
- Upstream route/store restructure (#5603/#5405).

```yaml
slices:
  - id: compact-on-fork
    repo: .
    writes: [omnigent/fork_compact.py, omnigent/server/routes/sessions/routes_core.py, omnigent/stores/conversation_store/__init__.py, omnigent/stores/conversation_store/sqlalchemy_store.py, tests/server/routes/test_sessions_fork.py, tests/server/routes/test_fork_oversize_guard.py, tests/server/routes/test_fork_compact.py, tests/fork_context/test_fork_compact_model.py]
    reads: []
    status: complete
    iteration: 1
  - id: fork-compact-ui
    repo: .
    writes: [web/src/shell/ForkSessionDialog.tsx, web/src/shell/ForkSessionDialog.test.tsx]
    reads: []
    status: complete
    iteration: 1
```
