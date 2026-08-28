# Builder brief — compact-on-fork (server)

Workspace: `/home/alex/omnigent-fixes` (git worktree, branch
`trio-v0.10.0-fixes`). Mailbox: `loop-compact/`. Slice id:
`compact-on-fork`.

You implement ONLY this slice. Do not touch UI files. Do not
`git commit`, `git push`, `git stash`, `git reset`, `git rebase`,
`git checkout`, or `git amend`. Lead will commit.

## HARD isolation (non-negotiable)
Never touch `~/.omnigent`, `~/.claude/projects`, live server
`:6767`, `omni host`, the user's `:17067` test instance, data dir
`/home/alex/omnigent-fixes-data`, or repo `/home/alex/omnigent`
(shares `.git`; no git commands there). Never kill processes you
did not start. Throwaway servers only on port ≥ 17100 with a
scratch `OMNIGENT_DATA_DIR` + `OMNIGENT_CONFIG_HOME`; tear them
down yourself.

## NEVER read these files whole
They exceed 1 MB / crash transport. Use the line ranges below
(`sed -n 'A,Bp'` or Python slice). Forbidden full ingest:
`routes_core.py`, `helpers.py`, `orchestration.py`,
`claude_native.py`, `chatStore.ts`, `sqlalchemy_store.py`,
`workflow.py`.

## Diagnosed line ranges (use these)
- `omnigent/server/routes/sessions/routes_core.py:2034-2267`
  `fork_session`. Guard today: `2195-2213`
  (`guard_fork_context` → raise `OmnigentError` 413). Insert
  compact-on-raise HERE, before `fork_conversation` at `2215`.
- `omnigent/server/routes/_sessions/helpers.py:6559-6638`
  `_run_compact_locked` — llm/client wiring to copy via a small
  shared helper (spec.llm else executor.model → LLMConfig).
  Running-turn check: `6583-6587` `_session_status_cache`.
  Publish helpers: `1542-1588`
  `_publish_compaction_in_progress/_completed/_failed`.
- `omnigent/runtime/compaction.py:53-71` `SummaryMetadata`;
  `478-556` `compaction_to_history_items`; `559-626` `compact()`.
  Call `compact(..., force=True, fail_on_summary_error=True,
  conversation_id=source_id)` so SSE lands on the SOURCE stream.
  Do NOT call `compact_conversation_now` — it persists onto the
  source (`workflow.py:2649-2755` / `_maybe_persist_compaction_item`
  `2791+`). Source must stay unmodified.
- `omnigent/stores/conversation_store/sqlalchemy_store.py:3397-3412`
  signature; item copy loop `3633-3672`. Add optional
  `replacement_items: Sequence[ConversationItem] | None = None`.
  When set, copy those items (new ids, dense positions) instead
  of querying source rows. Mirror the kwarg on
  `omnigent/stores/conversation_store/__init__.py:1485-1501` and
  on stub `tests/server/routes/test_sessions_fork.py:123-192`
  (record it in `fork_calls`).
- `omnigent/fork_context.py` is SMALL (147 lines) — you MAY read
  it whole. Extend env knobs here or in new
  `omnigent/fork_compact.py` (keep each file focused, <200 lines).
- `omnigent/claude_native.py:1666-1700` already honors
  `isCompactSummary` / `compact_boundary`. Do not rewrite it.
  Fork items must use the compaction marker shape so
  `summary_only_items` (`fork_context.py:102-147`) still works.

## Behavior
1. After `guard_fork_context` raises `ForkContextTooLarge`:
   if `OMNIGENT_FORK_COMPACT` is `0` → existing 413.
   Default ON (unset or `1`).
2. If `_session_status_cache.get(source_id)` in
   `("running", "waiting")` → `OmnigentError` CONFLICT 409:
   cannot fork-compact while a turn is running.
3. Resolve compact model (never hardcoded):
   (a) `OMNIGENT_FORK_COMPACT_MODEL` if set (wins over all);
   (b) source conversation `model_override` (pinned);
   (c) requested target model when the fork switches agent/model;
   (d) source agent spec `llm.model` else `executor.model`.
   Log at INFO which step won and the model id.
4. Factor llm/client wiring (llm_config, context window,
   `_get_llm_client` / runner client) like `_run_compact_locked`.
   Import workflow privates if needed; do not duplicate compact
   layers. Build messages from `context_items` (in-memory list),
   run `compact()`. Map `summary_metadata` to a `ConversationItem`
   `type="compaction"` (`CompactionData`) plus retained items
   after `last_item_id`. Do not write that item to the source.
5. Re-run `guard_fork_context` on the compacted API payload
   (target = `OMNIGENT_FORK_COMPACT_TARGET_BYTES` default 70% of
   `max_fork_context_bytes()`, then also the hard max). If still
   oversize or compact/summary raises → 413 with the **original**
   `ForkContextTooLarge` message (bytes from the first guard).
6. Pass `replacement_items` into `fork_conversation`. Publish
   in_progress before compact and completed/failed after, on
   SOURCE session id.

## Tests (write first)
- Small fork: item set identical to today's copy
  (`test_fork_keeps_small_history_unchanged` must still pass
  with compact default ON).
- Oversize + mocked `compact` producing a short summary → 201,
  `fork_calls` include replacement items under threshold.
- Oversize + compact disabled → 413, `fork_calls == []`
  (update `test_fork_refuses_oversized_history_before_store_fork`
  to set `OMNIGENT_FORK_COMPACT=0` OR keep it as the last-resort
  path when mock compact fails).
- Summary failure → 413 original message, source items unchanged.
- Model resolution unit tests (new file
  `tests/fork_context/test_fork_compact_model.py`): pinned wins;
  env override wins over pinned; fallback to spec.
- Running source → 409.

## Commands (run; save output under
`loop-compact/evidence/iter1/compact-on-fork/`)
```
uv run pytest -q \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_compact.py \
  tests/fork_context/test_fork_compact_model.py \
  tests/runner/test_fork_context_guard.py \
  tests/inner/test_claude_sdk_fork_context_guard.py
pre-commit run --files \
  omnigent/fork_context.py omnigent/fork_compact.py \
  omnigent/server/routes/sessions/routes_core.py \
  omnigent/server/routes/_sessions/helpers.py \
  omnigent/stores/conversation_store/__init__.py \
  omnigent/stores/conversation_store/sqlalchemy_store.py \
  tests/server/routes/test_sessions_fork.py \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_compact.py \
  tests/fork_context/test_fork_compact_model.py
```

Write a short `loop-compact/evidence/iter1/compact-on-fork/NOTES.md`
with files changed, test results, and the resolved-model log line
format. Keep comments short and scenario-focused. No issue numbers.
Do not write README.md. Line length < 88.
