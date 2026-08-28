# Builder brief — fork-compact-ui

Workspace: `/home/alex/omnigent-fixes`. Slice id: `fork-compact-ui`.

You implement ONLY this slice. Do not touch Python server/store
files. Do not `git commit` / push / stash / reset / rebase /
checkout / amend. Lead will commit.

## HARD isolation (non-negotiable)
Never touch `~/.omnigent`, `~/.claude/projects`, live `:6767`,
`omni host`, `:17067`, `/home/alex/omnigent-fixes-data`, or
`/home/alex/omnigent`. Never kill processes you did not start.
No throwaway server required for this UI-only slice.

## NEVER read these files whole
`chatStore.ts`, `routes_core.py`, `helpers.py`, `orchestration.py`,
`claude_native.py`. Use ranges below. `ForkSessionDialog.tsx` is
~965 lines — prefer ranges, not a blind full dump if avoidable.

## Diagnosed line ranges
- `web/src/shell/ForkSessionDialog.tsx:193` error state;
  `446-519` `handleFork` (`submitting`, `forkSession`, `setError`);
  `847-864` error slot + submit button (`data-testid`s
  `fork-session-error`, `fork-session-submit`).
- `web/src/lib/sessionsApi.ts:546-568` `forkSession` — keep 413
  message text from `readJsonOrThrow` (do not swallow/replace).
- `web/src/lib/sse.ts:468-479` already maps
  `response.compaction.in_progress/completed/failed`. Do not
  ingest `chatStore.ts` (compaction cases ~5296-5308).
- Existing tests: `web/src/shell/ForkSessionDialog.test.tsx`.

## Behavior
The fork POST is synchronous and may wait on server-side compact.
While `submitting` is true, show progress in the dialog:
`Summarizing N MB of history with <model>…`

- `N` = source history size in MB when the dialog already has
  session/items size; if unknown, omit N (`Summarizing history
  with <model>…` or `Summarizing history…`).
- `<model>` = source session pinned model if the dialog already
  has it (session `model_override` / agent model). Do not
  hardcode a model id. If unknown, omit the with-clause.
- If a source-session SSE subscription is already easy from this
  component without importing `chatStore.ts`, listen for
  `response.compaction.in_progress` to show the same copy; the
  blocked POST + `submitting` flag is sufficient if SSE is not
  in reach.
- On failure, keep `setError(e instanceof Error ? e.message : …)`
  so the 413 `Fork context too large: …` text is unchanged.
- Keep the change minimal. No new routes.

Server model-resolution order (for your copy only; do not
implement server): pinned source → requested target → agent spec;
`OMNIGENT_FORK_COMPACT_MODEL` overrides all.

## Tests
Extend `ForkSessionDialog.test.tsx`:
1. While `forkSession` is a deferred promise, assert the
   summarizing progress text is visible.
2. `forkSession` rejects with
   `new Error("Fork context too large: 3900000 bytes exceeds threshold 600000 bytes")`
   → `fork-session-error` shows that exact string.

## Commands (save output under
`loop-compact/evidence/iter1/fork-compact-ui/`)
```
cd web && npx vitest run src/shell/ForkSessionDialog.test.tsx
pre-commit run --files \
  web/src/shell/ForkSessionDialog.tsx \
  web/src/shell/ForkSessionDialog.test.tsx \
  web/src/lib/sessionsApi.ts
```

Write `loop-compact/evidence/iter1/fork-compact-ui/NOTES.md`.
Do not write README.md. Keep comments short.
