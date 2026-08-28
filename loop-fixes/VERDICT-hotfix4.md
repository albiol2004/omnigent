VERDICT: SHIP

Hotfix `e06c3d264` races rAF against a 100 ms deadline, flushes on
`visibilitychange`/`pageshow`, drains `liveBuffer` in `cancelFrame()`,
and ignores live deltas for message ids finalized in the current stream.

## 1. Adversarial behavior

Inspected `git show HEAD -- web/src/store/chatStore.ts` (did not ingest
the 1 MB file). `createRafScheduler` (`chatStore.ts:4159-4200`) stores
one pending callback, schedules rAF and `setTimeout(LIVE_FLUSH_DEADLINE_MS)`,
and `run()` cancels the loser. `schedule()` still coalesces (`pendingCallback !== null`).

Committed blocks after first paint use the same `scheduleFrame()` → `flush()`
path as live deltas (`chatStore.ts:4619-4627`, `4853-4858`), so a stalled rAF
cannot freeze either lane while `tool_output_delta` stays sync.

Builder tests in `chatStore.test.ts`: stalled-rAF deadline, visibility +
pageshow, fire-flush drain, no resurrect after `response.completed`, plus
existing coalescing/order cases.

Scratch eval (4/4, then removed; not product): post-first-paint chunks flush
by 100 ms with never-firing rAF; healthy rAF is one apply, order `"Hello world"`,
deadline does not double-apply; `AbortError` unwind drains via `cancelFrame()`;
a second pump can preview the same `messageId` after `finalizedLiveMessageIds.clear()`.

Aborting only the pump `AbortController` while the byte stream stays open
does not run `finally` until the reader unblocks. Production
`startStreamPump` forwards outer abort to the fetch `attempt` controller
(`chatStore.ts:3989-3991`), which errors the body and hits `finally`.
Not a ship blocker.

## 2. Commands

| Check | Result |
|---|---|
| `npx vitest run src/store/chatStore.test.ts` | 356 passed (`eval/vitest.out`) |
| scratch adversarial | 4 passed (`eval/scratch-vitest.out`) |
| `npx tsc --noEmit -p tsconfig.app.json` | EXIT 0 |
| `npx oxlint` on the two store files | EXIT 0 |
| prettier `--check` on those files | passed |

## 3. Pre-commit vs chatStore

Builder `loop-fixes/evidence/hotfix4/pre-commit.out`: `web oxlint` Failed
on repo-wide react lint (hooks, TerminalView, BlockRenderer, …). No
diagnostic names `chatStore` / `chatStore.ts` / `chatStore.test.ts`.
Unrelated to this hotfix; focused oxlint on the two files is clean.

## 4. Timer / listener dispose

`cancelPending()` clears rAF + deadline timeout (`4173-4182`).
`removeWakeListeners()` drops `visibilitychange`/`pageshow`; abort
`{ once: true }` and `finally` (`4867-4880`) both call it. Scheduler
`cancel()` runs from `cancelFrame()` in `finally`.

## 5. Isolation

`GET :6767/health` → 200 `{"status":"ok"}` before and after. No
`omni host`, no `~/.omnigent`, no other worktrees, no kills.

Evidence: `loop-fixes/evidence/hotfix4/` and `.../eval/`.
