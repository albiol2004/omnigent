# Builder brief — async-fork-preparing-server

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`.
`cd /home/alex/omnigent-fixes` for every command. Tests:
`PYTHONPATH=/home/alex/omnigent-fixes`. Pre-commit:
`PATH=/home/alex/omnigent/.venv/bin:$PATH`.

Commit: `slice(async-fork-preparing-server): …` with trailer
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
Never amend/rebase/push/stash/reset/checkout. Never git in
`/home/alex/omnigent`. Never touch `:6767`, `omni host`, or write
`~/.omnigent` / `~/.claude/projects`. Leave mailbox uncommitted.
Do not edit GOAL.md or VERDICT.md. grep/sed only on files >1MB.

## Context

Passthrough for last-response native clones is (or will be) fixed in
`passthrough-fix`. Rebuild/SDK/cross-family/truncated forks still
compact. Compaction today runs **inside** `fork_session` before 201
(`routes_core.py` ~2416-2510, `compact_fork_items` in
`omnigent/fork_compact.py:209`). That blocked the Web UI modal 56 s.

Progress events already exist: `helpers.py:1542-1580`
`_publish_compaction_in_progress/_completed/_failed`. Publish them on
the **NEW** fork session id (not only the source).

`fork_conversation` stamps labels in sqlalchemy_store.py ~3753-3805.
`set_labels` ~1268. Label keys live in
`omnigent/stores/conversation_store/__init__.py` ~27-58.
Launch: `omnigent/server/routes/hosts.py:715` `launch_runner`.
Native launch config reads fork labels in `orchestration.py` ~904-931.

## Contract

When compaction is required and `OMNIGENT_FORK_ASYNC` is not `"0"`:

1. Create the fork with copied (uncompacted) items immediately.
2. Stamp `omnigent.fork.preparing=1` and
   `omnigent.fork.preparing_reason` (human-readable, e.g.
   summarizing history).
3. Return 201 immediately (target < 1 s). Do not await the LLM/CLI.
4. Server-owned background task (survives the HTTP request; FastAPI
   `BackgroundTasks` is OK if the process stays up — prefer an
   asyncio task owned by the app if that is the local pattern):
   run `compact_fork_items`, swap compacted items onto the fork,
   clear preparing labels, publish completed on the **fork** id.
5. On failure: `omnigent.fork.preparing=failed` plus a reason label,
   publish failed, leave the fork deletable. Never leave `preparing=1`.
6. `launch_runner` and native orchestration MUST refuse to launch
   while `preparing=1` (no half-built transcript). Launch normally
   once cleared.
7. `OMNIGENT_FORK_ASYNC=0` restores today's synchronous compact-then-201.

Passthrough path: no preparing label, no background compact.

NEVER widen native passthrough to cross-family / SDK / truncated
prefix forks.

## Tests (write first)

New `tests/server/routes/test_fork_async_preparing.py` (keep it
focused; reuse `_build_app` from `test_sessions_fork.py`):

- Rebuild/oversize fork with compact stub that sleeps ~0.3s: 201
  faster than the sleep; labels `preparing=1` on the response; after
  the task, labels cleared and items replaced.
- Stub compact raising: `preparing=failed` + reason; not stuck at `1`.
- `launch_runner` or a small extracted guard: preparing=1 → 409/400.
- `OMNIGENT_FORK_ASYNC=0` + compact stub: 201 only after compact
  (response wall ≥ stub sleep).
- Native passthrough (external_session_id + claude-native) still
  201 with no preparing label.

```
cd /home/alex/omnigent-fixes
PYTHONPATH=/home/alex/omnigent-fixes uv run pytest -q \
  tests/server/routes/test_fork_async_preparing.py \
  tests/server/routes/test_fork_compact.py \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_passthrough_skip.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files <changed>
```

Keep files small. Short scenario comments. No issue numbers.
If `passthrough-fix` has not landed, do not regress the skip log.
You MAY touch `routes_core.py` around the compaction branch only.
