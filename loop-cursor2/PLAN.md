# PLAN — cursor-native rendered order, live content, model picker

status: in_progress
iteration: 1
writes: web/src/store/chatStore.ts, web/src/pages/ChatPage.tsx, web/src/lib/renderItems.ts, omnigent/cursor_native_bridge.py, omnigent/cursor_native.py, tests/, web/src/**/*.test.ts
luna_model: gpt-5.6-luna-max

## Objective

A top-level cursor-native session must render assistant text as it
streams, **below** the user's message, without wiping content at turn
end or on a second turn of the same SSE connection. The web model picker
must switch to the **exact** chosen variant (HTTP success + pane
evidence), fail honestly on a bogus id, and offer only ids that
`cursor-agent models` actually printed.

Last loop's store-reducer tests went green while the UI stayed broken:
rendered order is decided in `ChatPage.mergePendingBubbles` after
`buildBubbles`. Every ordering/content assertion in this loop goes
through `buildBubbles` + `mergePendingBubbles`.

HEAD bbac776ce confirmed the diagnosed ranges still match (helpers
`isCursorLiveMessageId` / `insertCommittedUserBeforeLiveTail` exist but
do not close causes 2–4).

## Verification standard

mode: test-first

Mandatory:

- Vitest for slices 1–3: assert **rendered** bubble order/text via
  `buildBubbles` then `mergePendingBubbles`. Reducer-only tests may
  exist as extras, never as the sole proof.
- Pytest for slices 4–5 (and 6 if a small server fix lands).
- Real two-turn cursor-native e2e on a throwaway instance (port ≥ 18500,
  scratch data/config): one SSE connection, two prompts, raw SSE
  captured; rendered transcript asserted (browser tools if they can
  reach the throwaway, else SSE replayed through `buildBubbles` +
  `mergePendingBubbles` — say so explicitly).
- Model-picker e2e: fully-qualified id → 200/204 **and** capture-pane
  shows that exact variant; bogus id → honest error.

## Slices

### 1. live-delta-lifecycle

writes: `web/src/store/chatStore.ts`, `web/src/store/chatStore.test.ts`
(plus a **new** render-level test file if needed; not `renderItems.ts`)

Diagnosed ranges (HEAD): `isLiveProvisionalBlock` 4248–4250;
`insertCommittedUserBeforeLiveTail` 4264–4271 (contiguous **trailing**
live run only); `applyLiveDelta` gate 4349; set 4577–4589; populate
4718 / 4806 / bulk 4847; `response_end` wipe 4847–4853; clear 4901;
insert call sites ~5694 / 5728 / 5745. `isCursorLiveMessageId` 4259–4261
exists but is **not** used in the finalized gate.

Done:

- Cursor-live ids are not permanently blacklisted for the SSE lifetime
  (exempt or scope the set per turn). Cause 4.
- Committed user splices at the **first** live-provisional block, not
  only a contiguous trailing run. Cause 2.
- `response_end` does not delete an unreplaced preview (promote or drop
  only genuinely replaced ids); no reconnect duplicates. Cause 3.
- Render-level tests: live preview below pending **and** committed user;
  second-turn deltas still render; preview text survives `response_end`
  when no committed replacement arrived.

### 2. pending-bubble-order

writes: `web/src/pages/ChatPage.tsx`, `web/src/pages/ChatPage.test.ts`

Diagnosed: `mergePendingBubbles` 516–525; lift only elicitation +
create-routing chips. Live preview is a trailing **assistant** bubble
with `live:` item ids (`LIVE_ITEM_PREFIX` in `web/src/lib/blocks.ts:536`).

Done:

- Pending user also lifts above a trailing assistant bubble whose items
  came **only** from a `live:` preview.
- A completed (non-live) assistant turn is never jumped.
- Tests through `mergePendingBubbles` (and `buildBubbles` when the
  bubble is produced from blocks). Combined with slice 1 in one builder.

### 3. render-cache-check

writes: `web/src/lib/renderItems.test.ts`; `web/src/lib/renderItems.ts`
only if a real failure is demonstrated

Diagnosed: `reusablePrefix` 584–660, reference equality 613–615;
`walkBubbles` 726 / grouping 775 / 900.

Done:

- Targeted `buildBubbles`(cache) test: mid-array splice (committed user
  inserted before a live preview). Record pass/fail in REPORT.
- Fix only if the test fails.

### 4. picker-row-match

writes: `omnigent/cursor_native_bridge.py`,
`tests/test_cursor_native_bridge.py`

Diagnosed: `inject_model_command` 790–889; settle `_MODEL_PICKER_SETTLE_S`
84 / `_PASTE_COMMIT_TIMEOUT_S` 80; `_picker_highlighted_row` 898–904
(first `→` wins — composer `→ Add a follow-up`);
`_picker_row_matches_display` 907–911 (prefix match). Fixture `_IDLE`
at `tests/test_cursor_native_bridge.py:174` has **no** composer `→`.
Port discrimination from `omnigent/claude_native_bridge.py:3750–3772`
(composer vs menu), cursor-shaped: only `→` below `Models matching`.

Done:

- Composer `→` never selected; exact row match (no sibling effort via
  prefix); re-check highlight across a widened budget; fixtures include
  a real composer `→` line; wrapping/truncation tolerated.

### 5. picker-model-list

writes: `omnigent/cursor_native.py`, `tests/test_cursor_native.py`

Diagnosed: `_cursor_base_model_id` / `_CURSOR_UNMAPPED_CLAUDE_RE` /
`parse_cursor_cli_model_options` 214–292. Dotted rewrite invents ids;
unmapped regex drops `claude-4-sonnet`. Existing tests **encode** that
wrong behavior and must be rewritten to the new contract.

Done:

- Options are ids `cursor-agent` printed (no invented rewrite).
- Injectable ids like `claude-4-sonnet` are kept.
- Effort variants are distinct picker rows (id + display of the variant
  the user will get).

### 6. mirror-gap

writes: `loop-cursor2/evidence/iter1/mirror-gap/DECISION.md` (and a
**small** product fix only if clearly in-scope)

Cause 7: conversation `52d47c71e54b4f61a2563bbaefe6ad34` — 42 event
POSTs, one persisted row (`pos=0 type=8`). Hypothesis 6: `response.failed`
without `id`/`model`/`created_at` → pydantic 500.

Done: DECISION.md with evidence, confirmed/refuted for H6, and either a
tiny fix or a precise follow-up.

## Out of scope

- Live `:6767` / `omni host` / git in `/home/alex/omnigent`
- Amending, rebasing, pushing, stashing, resetting, checking out
- Killing or typing into existing tmux/cursor-agent sessions
- Claude-native / Codex streaming redesign; rAF/deadline rewrite
- Cursor **sub-agent** sessions; disabling `OMNIGENT_CURSOR_STREAM=0`
  (must keep working)

## Wave plan

- Wave A (parallel, disjoint writes): builder **1+2**, builder **4**,
  builder **5**; Lead/scout **6** (read-only except DECISION.md).
- Wave B: builder **3** after 1+2 if `renderItems.ts` might change;
  otherwise 3 may run with A because it only owns `renderItems.ts` +
  `renderItems.test.ts`.

```yaml
slices:
  - id: live-delta-lifecycle
    repo: .
    writes: [web/src/store/chatStore.ts, web/src/store/chatStore.test.ts]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["cursor-live ids not blacklisted; user spliced before first live; unreplaced preview promoted"]
  - id: pending-bubble-order
    repo: .
    writes: [web/src/pages/ChatPage.tsx, web/src/pages/ChatPage.test.ts, web/src/pages/ChatPage.cursorRender.test.ts]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["pending user lifted above live-only assistant bubble via mergePendingBubbles"]
  - id: render-cache-check
    repo: .
    writes: [web/src/lib/renderItems.test.ts]
    reads: [web/src/lib/renderItems.ts]
    gate: false
    status: complete
    iteration: 1
    accepts: ["mid-array splice cache test; no renderer change needed"]
  - id: picker-row-match
    repo: .
    writes: [omnigent/cursor_native_bridge.py, tests/test_cursor_native_bridge.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["composer arrow ignored; exact variant match; highlight rechecked"]
  - id: picker-model-list
    repo: .
    writes: [omnigent/cursor_native.py, tests/test_cursor_native.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["picker ids are printed CLI ids including effort variants"]
  - id: mirror-gap
    repo: .
    writes: [omnigent/runner/app.py, tests/runner/test_response_failed_payload.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["response.failed has id/model/created_at; DECISION.md in mailbox"]
```
