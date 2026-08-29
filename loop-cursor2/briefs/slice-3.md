# Builder brief — slice 3 (render-cache-check)

You are a Trio Luna builder (`gpt-5.6-luna-max`). Work ONLY in
`/home/alex/omnigent-cursor2`.

Do not commit. Do not git in `/home/alex/omnigent`. Do not touch :6767,
`omni host`, `~/.omnigent` (write), existing tmux/cursor-agent sessions.

## Writes ONLY

- `web/src/lib/renderItems.test.ts`
- `web/src/lib/renderItems.ts` **only if** the new test demonstrates a
  real failure

Do not edit ChatPage.tsx, chatStore.ts, or Python files.

Large file: `renderItems.ts` — use `sed -n` / `grep -n`, no full-file read.

## Hypothesis 5 (do not assume it is a bug)

`reusablePrefix` at `web/src/lib/renderItems.ts:584-660` validates the
cached prefix by **reference** (`:613-615` `blocks[j] !== cache.blocks[j]`).
`walkBubbles` at `:726` walks array order; grouping by `responseId`;
`user_message` breaks the group (`:775`, `:900`).

A mid-array splice (committed user inserted **before** a live preview,
as slice 1 does) may or may not poison the incremental cache.

## Test-first

Add a targeted test in `renderItems.test.ts`:

1. `const cache = createBubbleCache()`.
2. First `buildBubbles(blocksWithLivePreviewOnly, active, cache)` so the
   cache records `lastBubbleStart`.
3. Splice a `user_message` block into the **middle** (before the live
   `text_done`), keeping later block **object identity** for the live
   preview.
4. Second `buildBubbles(spliced, active, cache)`.
5. Assert bubble **order** is user then assistant, and assistant text is
   the live preview text (not dropped / duplicated / stuck on the old
   prefix).

If this PASSES without changing `renderItems.ts`, leave the implementation
alone and write a 5-line note at
`loop-cursor2/evidence/iter1/builders/slice-3-finding.md` (allowed extra
mailbox write).

If it FAILS, make the smallest cache invalidation fix (e.g. bail out of
reuse when length grew in the prefix region or when a user_message
appeared before `lastBubbleStart`) and keep the test.

`buildBubbles` is exported from `renderItems.ts:336`;
`createBubbleCache` at `:264`. Follow existing test factories in
`renderItems.test.ts` (do not full-read; grep for `text_done` helpers).

Comments: short scenario comments; no issue numbers.

## Command

```
cd /home/alex/omnigent-cursor2/web
npx vitest run src/lib/renderItems.test.ts
```

Print PASS/FAIL of the splice test and whether `renderItems.ts` changed.
