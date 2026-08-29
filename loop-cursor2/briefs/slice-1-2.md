# Builder brief — slices 1+2 (live-delta-lifecycle + pending-bubble-order)

You are a Trio Luna builder (`gpt-5.6-luna-max`). Work ONLY in
`/home/alex/omnigent-cursor2` (git worktree, branch `cursor-render-picker`).

Do not commit. Do not amend/rebase/push/stash/reset/checkout. Do not run
git in `/home/alex/omnigent`. Do not touch the live server on :6767 or
`omni host`. `~/.omnigent`, `~/.claude/projects`, `~/.cursor` are
read-only. Do not type into, start, or kill EXISTING tmux/cursor-agent
sessions. Do not start long-lived servers.

## Isolation / commands

```
cd /home/alex/omnigent-cursor2
export PYTHONPATH=/home/alex/omnigent-cursor2
# pre-commit if you run it:
PATH=/home/alex/omnigent/.venv/bin:$PATH
```

Large files: **never full-file read** `chatStore.ts` or `ChatPage.tsx`.
Use `sed -n` / `grep -n` on the ranges below.

## Writes (disjoint — do not touch these other files)

ALLOWED:
- `web/src/store/chatStore.ts`
- `web/src/store/chatStore.test.ts`
- `web/src/pages/ChatPage.tsx`
- `web/src/pages/ChatPage.test.ts`
- NEW file `web/src/pages/ChatPage.cursorRender.test.ts` (preferred for
  the mandatory render-level tests)

FORBIDDEN: `web/src/lib/renderItems.ts`, `web/src/lib/renderItems.test.ts`,
`omnigent/cursor_native_bridge.py`, `omnigent/cursor_native.py`.

## Diagnosis (reproduce, do not re-derive)

Cause 4 (highest value): `finalizedLiveMessageIds` is a per-SSE-connection
blacklist. Gate `web/src/store/chatStore.ts:4349`
`if (finalizedLiveMessageIds.has(messageId)) continue;`. Set at 4577–4589,
populated 4718 / 4806 / bulk 4847, cleared only in `finally` at 4901.
Cursor live ids are `cursor-live-{session}{epoch}`
(`omnigent/cursor_native_stream.py:163-165`). Epoch advances only after a
user store row posts. Same id across turns → second-turn deltas dropped.
`isCursorLiveMessageId` already exists at 4259–4261 but is NOT used in
the gate (only around 4452 for stale-completed). **Exempt cursor-live ids
from the finalized gate** (or scope the set per turn). Do not weaken the
gate for non-cursor live ids (claude-native).

Cause 2: `insertCommittedUserBeforeLiveTail` 4264–4271 walks back only
while `isLiveProvisionalBlock` (4248–4250, `itemId` starts with `live:`).
A non-live block after the preview (reasoning, tool_group, response_end,
routing chip) stops the walk at `blocks.length` → user appended after the
assistant. Fix: splice the committed user at the **first**
live-provisional block in `blocks` (not only a contiguous trailing run).
Call sites ~5694, 5728, 5745.

Cause 3: `response_end` at 4847–4853 `filter`s out every
`isLiveProvisionalBlock`. Comment assumes a committed `text_done` already
replaced the preview. Cursor mirror often produces no replacement → the
only on-screen text is wiped. Fix: **promote** an unreplaced live preview
to a committed `text_done` (stable non-`live:` itemId, same text) OR only
drop previews whose messageId was replaced this turn. Must not resurrect
duplicates on SSE reconnect (promoted block should satisfy the same
dedup as a real committed item).

Cause 1 (ChatPage): `mergePendingBubbles` 516–525 lifts pending user
above trailing elicitation (`isStandaloneElicitationBubble` ~434–453)
and create-routing chips (`liftAboveCreateRoutingChips` 489–496) only.
A trailing live assistant preview is not in that list, so the pending
user renders **below** streaming text until `session.input.consumed`.
Extend the insert-position walk so a trailing assistant bubble whose
**items came only from a `live:` preview** (`LIVE_ITEM_PREFIX` =
`"live:"` in `web/src/lib/blocks.ts:536`; text `itemId` starts with
`live:`) is also lifted over. Guard: a normal completed assistant
bubble (non-live itemIds, or mixed tools) must **never** be jumped.
Existing tests in `ChatPage.test.ts` describe("mergePendingBubbles")
~518+ must stay green.

## Test-first (MANDATORY render path)

Every ordering/content assertion MUST go through `buildBubbles` +
`mergePendingBubbles` (import from `@/lib/renderItems` and `./ChatPage`).
Do **not** treat `handleSessionEvent` / store `blocks` order as proof of
UI order.

Write failing tests first in `web/src/pages/ChatPage.cursorRender.test.ts`:

1. Pending user + trailing live-preview assistant (blocks:
   live `text_done` only; pending via `buildPendingBubbles` or a user
   Bubble) → merged order is **user then assistant**, assistant text
   present.
2. Same after a committed user spliced before a live preview that is
   NOT last (live then `tool_group` or similar) → user still before
   assistant in `buildBubbles` output, and merge does not invert.
3. Second-turn: after first live id was finalized, further deltas for
   the **same** `cursor-live-*` id still appear in `buildBubbles` text
   (you may drive the store then `buildBubbles(blocks)` — the assertion
   is on bubbles, not on a raw findIndex).
4. `response_end` with no committed replacement: assistant text still
   in `buildBubbles` output (not wiped).
5. Regression: trailing completed assistant with real itemId is NOT
   jumped by a new pending user (extend ChatPage.test.ts merge suite).

Then implement the smallest fix.

Helpers: see `userBubble` / `assistantText` in `ChatPage.test.ts` ~469.
`buildBubbles(blocks, activeResponse, createBubbleCache())`.
`LIVE_ITEM_PREFIX` from `@/lib/blocks`. Look at
`web/src/store/chatStore.test.ts` around 8624+ for how native live
deltas are injected — reuse that to produce `blocks`, then ALWAYS
finish with `buildBubbles` + `mergePendingBubbles`.

Comments: short scenario comments only (CLAUDE.md); no issue numbers.

## Commands

```
cd /home/alex/omnigent-cursor2/web
npx vitest run src/pages/ChatPage.cursorRender.test.ts src/pages/ChatPage.test.ts src/store/chatStore.test.ts
```

If chatStore.test.ts is too slow, still run the new render file +
ChatPage.test.ts + the live-preview describe blocks you touched.

Do not start servers. Print a short DONE summary of files changed and
test output.
