# Builder brief — cursor-delta-source (slice 1)

Workspace: `/home/alex/omnigent-fixes`. Mailbox:
`loop-cursor-stream/`. Slice id: `cursor-delta-source`.

Do NOT `git commit` / push / stash / reset / rebase / checkout /
amend. Lead commits. TEST-FIRST.

## HARD isolation
Never touch `~/.omnigent`, `~/.claude/projects`, `:6767`, `omni host`,
`:17067`, `/home/alex/omnigent-fixes-data`, `/home/alex/omnigent`.
Never kill foreign processes. No Omnigent server needed for this
slice. `~/.cursor` read-only.

## NEVER read whole
`chatStore.ts`, `claude_native_forwarder.py` — use `sed -n` / the
ranges below. Full ingest crashes the transport.

## Probe decision (measured — obey it)
`loop-cursor-stream/evidence/iter1/probe/DECISION.md`:
**CHOICE = pane-diff**. Store blobs are complete-only (assistant
rowid 11 at 21631 bytes appeared at 21700 ms). Pane showed growing
assistant text from 16300 ms (`🤖 A mechanical clock is` …). Do NOT
implement store-blob streaming.

## Diagnosed ranges (`grep -n` then `sed -n`)
- Cursor poll: `omnigent/cursor_native_forwarder.py` 58-92
  `_DEFAULT_FAST_POLL_INTERVAL_S` 0.15 / idle 0.7,
  `_select_poll_interval`. Loop sleep 1231-1236.
  `_read_blob_rows` 512-539. `_post_conversation_item` 791-806.
  Poll body ~1027-1236. Keep complete-item POST unchanged.
  `forward_cursor_store_to_session` starts ~904.
- Tmux: `omnigent/cursor_native_bridge.py` `read_tmux_info` 491-509;
  `_capture_pane` 541-553 (add `-e` for this path, or a sibling
  capture; do not break existing callers that omit `-e`).
- Claude delta POST: `omnigent/claude_native_forwarder.py`
  4013-4046 `_post_external_output_text_delta`. Dataclass
  `ClaudeMessageDelta` is `omnigent/claude_native_bridge.py` 600-623.
  Factor POST JSON into `omnigent/_native_output_text_delta.py`
  (<200 lines). Claude wrapper must keep the same payload; update
  `tests/test_claude_native_forwarder.py` ~5872-5894 if the import
  moves.
- UI hand-off (READ ONLY unless a proven gap):
  `web/src/store/chatStore.ts` `applyLiveDelta` 4296-4317,
  `tapLiveDeltas` 4383-4426, `isLiveProvisionalBlock` 4230-4233,
  `makeLiveTextBlock` 4258+, splice 4624-4648. Tests
  `chatStore.test.ts` ~9047-9115. Prefer ZERO chatStore edits:
  posting `message_id` on `external_output_text_delta` already
  accumulates `live:<id>` and complete `text_done` removes it.
- Executor: `omnigent/inner/cursor_native_executor.py` 59-61.
  KEEP `supports_streaming() -> False` like claude-native (76-77:
  output comes from the forwarder, not the executor). Update the
  docstring to mention pane live-deltas. Tests
  `tests/inner/test_cursor_native_executor.py` ~90 stay False.

## Behavior
1. `OMNIGENT_CURSOR_STREAM` default ON (unset or `1`). `0` skips
   pane sampling and delta POSTs; store mirror unchanged.
2. While a turn is active, capture pane ~fast poll (reuse
   `_select_poll_interval`; treat a new suffix as `has_new_output`).
   Idle backoff when no suffix.
3. New module `omnigent/cursor_native_stream.py` (<200 lines):
   - strip ANSI
   - extract assistant region: text after `🤖` until the
     `Working` / footer / composer (`→ `) chrome. Match probe
     frames in DECISION.md.
   - `suffix_after(emitted: str, viewport: str) -> str`:
     if `viewport` starts with `emitted` (or emitted is prefix),
     return the extra tail; if viewport scrolled (viewport is a
     later window of the same message), find the longest suffix of
     `emitted` that is a prefix of `viewport` and return the rest;
     empty on shrink/redraw with no new text; never reorder.
   - stable `message_id` per in-flight assistant message (e.g.
     `cursor-live-<session>` until the complete blob lands, then
     reset). UI keys `live:<messageId>`.
   - POST suffix via shared helper (`delta`, `message_id`,
     `index` increment, `final` False). Optional `final` True
     when the complete assistant item is about to POST — not
     required if the item splice already drops `live:*`.
4. Do not persist deltas. Do not change `_post_conversation_item`.
5. Files stay focused (<200 lines for new modules). Short comments.

## Tests FIRST (fail), then impl (pass)
`tests/test_cursor_native_stream.py`:
- first viewport → first delta
- growing viewport → suffix only
- scrolled viewport (head of message gone, tail new) → new suffix,
  no duplicate prefix
- redraw with same text → empty
- ANSI stripped
`tests/test_cursor_native_forwarder.py`:
- env `OMNIGENT_CURSOR_STREAM=0` never POSTs
  `external_output_text_delta` (fake pane frames)
- env on: fake frames cause delta POSTs then complete item POST
  still happens
Keep existing cursor/claude tests green.

## Commands
```
cd /home/alex/omnigent-fixes
uv run pytest -q tests/test_cursor_native_stream.py \
  tests/test_cursor_native_forwarder.py \
  tests/test_claude_native_forwarder.py \
  tests/inner/test_cursor_native_executor.py
# if you touch chatStore:
cd web && npx vitest run src/store/chatStore.test.ts
pre-commit run --files <touched>
```
Capture outputs under
`loop-cursor-stream/evidence/iter1/cursor-delta-source/`.
Write `NOTES.md` with Luna model id and any deviations.
