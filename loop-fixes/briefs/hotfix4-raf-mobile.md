# Hotfix 4 — chat pane freezes on mobile: rAF-gated live deltas never flush when rAF is throttled

Repo `/home/alex/omnigent-ui-fix` (git WORKTREE, branch `hotfix-raf-mobile`, based on trio-v0.10.0-fixes). Work ONLY under `web/`. Never touch ~/.omnigent, live :6767, /home/alex/omnigent or /home/alex/omnigent-fixes.

## Defect (from scouting; regression introduced by b0dc3bfaa)
`web/src/store/chatStore.ts`: `createRafScheduler()` (~4158-4182) falls back to setTimeout only when rAF is *absent*; on iOS/WKWebView rAF exists but stops firing when the page is backgrounded, screen dims, Low Power Mode, etc. Since b0dc3bfaa, `queueLiveDelta()`/`scheduleFrame()` (~4585-4596) AND committed blocks after first paint (~4787-4792) all wait on that frame, so the chat pane freezes until stream end (drains at ~4801/4811) — while `tool_output_delta` (~4413-4417) applies synchronously, so the terminal tab keeps updating. Also latent: `flush()` calls `cancelFrame()` (~4544) without draining `liveBuffer` (stranded tail); and `applyLiveDelta` recreates a live block when `at === -1` (~4291-4296) after cleanup (~4768-4771), a ghost-duplicate hazard.

## Required change (smallest correct)
1. Scheduler: race rAF against a `setTimeout` deadline (~100 ms, env/const `LIVE_FLUSH_DEADLINE_MS`) so a batch always applies even when rAF is stalled; whichever fires first runs the flush and cancels the other. Add a `visibilitychange` (and `pageshow`) listener that flushes pending work immediately when the document becomes visible. Keep coalescing behavior on desktop unchanged (one apply per frame while rAF is healthy).
2. `cancelFrame()`/`flush()` must drain `liveBuffer` (never strand deltas).
3. Guard `applyLiveDelta` against resurrecting a live block for a messageId that was already finalized/cleaned up in this stream (small set of finalized ids, cleared on stream end).
4. Tests in `web/src/store/chatStore.test.ts`: (a) with a fake rAF that never fires, queued deltas still apply within the deadline; (b) visibilitychange flushes; (c) flush drains the buffer, no stranded tail; (d) delta after cleanup does not recreate a block; (e) existing coalescing/order tests still pass. Run `cd web && npx vitest run src/store/chatStore.test.ts` and `npx tsc --noEmit -p tsconfig.app.json` (or the project's lint/typecheck script), `PATH=../.venv/bin:$PATH pre-commit run --files web/src/store/chatStore.ts web/src/store/chatStore.test.ts`. Save outputs to `loop-fixes/evidence/hotfix4/`.

## Finish
Commit only the two web files: `slice(render-latency): always flush live deltas within a deadline when rAF is throttled` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never amend/rebase/push/stash/reset. Print a compressed summary.
