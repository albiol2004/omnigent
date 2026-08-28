# Builder brief — cursor-live-deltas + cursor-live-order (ONE worker, TWO commits)

You are GPT-5.6 Luna (`gpt-5.6-luna-max`, effort max). Workspace: `/home/alex/omnigent-cursor`. `cd /home/alex/omnigent-cursor` for every command. Tests: `PYTHONPATH=/home/alex/omnigent-cursor`. Pre-commit: `PATH=/home/alex/omnigent/.venv/bin:$PATH`. Do not git-amend/rebase/push/stash/reset/checkout. Do not touch `/home/alex/omnigent`, live :6767, `omni host`, `~/.omnigent`, `~/.claude/projects`, `~/.cursor` (read-only). Do not kill processes you did not start. Do not edit `loop-cursor-ux/GOAL.md` or `VERDICT.md`. Large files: `grep -n` / `sed -n` only — never full-file read `chatStore.ts`.

## Isolation
No throwaway servers required for these unit tests. If you start anything, port ≥ 18300, scratch data/config dirs, tear down.

## Diagnosed ranges (HEAD c1dc1d9b5 — confirm before edit)

Symptom 1: `chatStore.ts:4427-4433` (`tapLiveDeltas` + `isStaleCompletedResponse`), `:4495-4501`, `REVIVE_WINDOW_MS` `:4489`, live append `:4331-4335`, `finalizeCurrentActive` `:6085-6095`. Executor `omnigent/inner/cursor_native_executor.py:61-63`, `:109-117`. Live id `omnigent/cursor_native_stream.py:163-165`.

Symptom 2: consume tail-append `chatStore.ts:5652-5662` and `:5687-5697`; pending `:18`, `:244`; `LIVE_ITEM_PREFIX` `:57`; `isLiveBlock` `:4249`.

## Test-first (write tests, run, watch fail, then fix)

`cd /home/alex/omnigent-cursor/web && npx vitest run src/store/chatStore.test.ts`

Patterns: `describe("chatStore — pumpStreamEvents frame batching")` (~7158) uses `pumpStreamEvents` + `pushableStream` + `sse(...)`. Native live deltas: `nativeDeltaFrame` / `livePreviews` ~8581. `session.input.consumed` ~4582. `isStaleCompletedResponse` ~2823. `LIVE_FLUSH_DEADLINE_MS` is already exported.

### Commit 1 — `slice(cursor-live-deltas): …`

Tests in `web/src/store/chatStore.test.ts`:

1. Pump a `cursor-live-sess-1` (or any id starting with `cursor-live-`) `response.output_text.delta` with `message_id`. First stamp `activeResponse` completed with `completedAt: Date.now() - 16_000`. The delta MUST still land in a `live:` preview (today it is ignored and the id blacklisted).
2. Control: a non-cursor live `message_id` (e.g. `wake-msg-1`) after the same stale completed MUST still be ignored (scheduled-wake gate stays).

Fix in `tapLiveDeltas` only: skip the stale ignore for native cursor live message ids (`cursor-live-` prefix / LIVE_ITEM_PREFIX message). Do **not** delete `isStaleCompletedResponse`. Do **not** change rAF coalescing / `LIVE_FLUSH_DEADLINE_MS`. Do not change `OMNIGENT_CURSOR_STREAM` behavior (no python unless you must). Preferred extra (only if a few lines): pass `response_id` into cursor forwarder idle post — skip if it expands scope.

No-regression: claude-native/codex streaming tests in the same file must stay green; cursor sub-agents do not use this web `activeResponse` slam.

### Commit 2 — `slice(cursor-live-order): …`

Tests: pending user + existing `text_done` with `ctx.itemId` `live:cursor-live-…`. Fire `session.input.consumed`. User block must be **before** the live block. Keep the existing FIFO tail-append test that uses a **non-live** prior assistant item (`msg_asst_prev`) unchanged.

Fix: both promote paths (`clearedPendingId` and FIFO head) splice `committedUserBlock` immediately before the first live trailing block (`isLiveBlock` / `LIVE_ITEM_PREFIX`), else append as today.

## Writes
`web/src/store/chatStore.ts`, `web/src/store/chatStore.test.ts` only.

## Commits
Two commits, messages:

```
slice(cursor-live-deltas): keep cursor-live deltas after injection-complete

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

```
slice(cursor-live-order): splice consumed user block before live preview

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

HEREDOC commit; do not skip hooks. Append one line to `loop-cursor-ux/LOG.md` only if the Lead brief required it — **do not** append LOG (Lead will). Never commit mailbox files.

## Report back
Commands, pass/fail, shas, any undeclared files, deviations.
