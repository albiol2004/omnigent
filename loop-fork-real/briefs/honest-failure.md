# Builder brief — honest-failure

Workspace: `/home/alex/omnigent-fixes` (git WORKTREE, branch
`fork-compact-real`). Mailbox: `loop-fork-real/`. Slice id:
`honest-failure`. Luna model: `gpt-5.6-luna-max`.

You implement ONLY this slice. Do not `git commit` / push / stash /
reset / rebase / checkout / amend. Do not rewrite model routing
(slice 1 owns `fork_compact.py`). You MAY pass `on_llm_ready=` into
`compact_fork_items` if that kwarg exists; if it does not land yet,
call `_publish_compaction_in_progress` only after
`compact_fork_items` has been entered via that callback, or omit
the early publish and add a short comment that slice 1 supplies
`on_llm_ready`. Prefer:

```
await compact_fork_items(..., on_llm_ready=lambda _resolved: _publish_compaction_in_progress(source_id))
```

and **delete** the publish that currently runs before the await.

## HARD isolation
Never write `~/.omnigent`. Never `~/.claude/projects`, `:6767`,
`omni host`, git in `/home/alex/omnigent`. Never kill foreign
processes. Throwaway ≥ 17700 only.

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
```

## NEVER read these files whole
`routes_core.py` is >1 MB. `helpers.py`, `orchestration.py`,
`claude_native.py`, `workflow.py` likewise. Use sed.

## Diagnosed line ranges
- `omnigent/server/routes/sessions/routes_core.py:2370-2405`
  (`grep -n 'compact_fork_items\|_publish_compaction'`).
  Today: `_publish_compaction_in_progress(source_id)` at 2380,
  then `compact_fork_items`, then
  `except Exception as compact_exc: _publish_compaction_failed;
  raise OmnigentError(str(exc), code=exc.code) from compact_exc`
  — `compact_exc` is discarded from the HTTP body.
- Publish helpers (read only): `helpers.py:1542-1588`
  `sed -n '1542,1588p'`.
- Tests: `tests/server/routes/test_fork_compact.py` whole is OK
  (~400 lines). `test_summary_failure_keeps_original_413_and_source`
  ~355-381 currently asserts 413 **without** the compaction reason.

## Reproduced exception
`loop-fork-real/evidence/iter1/repro/ROOT_CAUSE.md`.
Production: 413 in 36 ms, no WARNING traceback, UI showed
Summarizing because in_progress fired first.
Unit-level: `httpx.HTTPStatusError` 401 on OpenAI for `model=fable`.

## Behavior
1. Log `compact_exc` at WARNING with `exc_info=True` and the
   compact model/provider if the exception or logger extra has it.
2. 413 message: original `ForkContextTooLarge` text plus
   `; compaction failed: <compact_exc>`.
3. `_publish_compaction_in_progress` only from `on_llm_ready` (or
   equivalent after resolve). Publish `_publish_compaction_failed`
   on this except path once. Do not publish in_progress when
   compact_fork_items raises before calling `on_llm_ready`.
4. Do not edit helpers.py unless a one-line export is required
   (it should not be). Comments short, no issue numbers.

## Tests first
In `test_fork_compact.py`:
- Update failure test: 413 body contains `compaction failed:` and
  the inner reason (`summary unavailable` today).
- `caplog` WARNING includes traceback / `summary unavailable`.
- Spy `session_stream.publish` (or patch
  `_publish_compaction_in_progress`): when compact_fork_items
  raises at resolve (patch it to raise before calling
  `on_llm_ready`), no `response.compaction.in_progress`.
- When compact is actually entered, in_progress published once
  (mock compact_fork_items to call `on_llm_ready` then return).

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
uv run pytest -q tests/server/routes/test_fork_compact.py \
  tests/server/routes/test_fork_oversize_guard.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/server/routes/sessions/routes_core.py \
  tests/server/routes/test_fork_compact.py
```

Write outputs under `loop-fork-real/evidence/iter1/honest-failure/`.
If pre-commit wants to format the 1 MB routes file, that is OK for
the hunk you touched; do not reformat unrelated regions by hand.
