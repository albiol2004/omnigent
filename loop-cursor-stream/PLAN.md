# PLAN — cursor-native streaming (iter 1)

## Objective
Stream cursor-native assistant text into the UI as transient
`response.output_text.delta` events while Cursor is still generating,
then replace that preview with today's complete
`external_conversation_item`. No duplicate/reordered text. No change
to persisted history. Reuse b0dc3bfaa adaptive poll + rAF live-delta
path. Env `OMNIGENT_CURSOR_STREAM` default on (`0` = today's
complete-item-only behavior).

## Verification standard
mode: test-first

Slice 0 is measurement-only (real `cursor-agent`, both sources).
Slice 1 writes failing unit tests first (fake store rows / fake pane
frames), then the implementation, then the same tests green.
Slice 2 is a real e2e on a throwaway Omnigent instance (port ≥ 17200,
scratch data/config dirs) with the actual `cursor-agent` CLI.

Evidence: `loop-cursor-stream/evidence/iter1/<slice>/`. Commands and
outputs captured there. Isolation audit in REPORT (GOAL Acceptance 4).

## Slices

### 0 probe-partial-text
status: complete
writes: []

Done criteria:
- Real `cursor-agent` turn in a throwaway workspace + own tmux.
- ~100 ms samples of store.db (`MAX(rowid)`, `COUNT(*)`, newest blob
  length, `SELECT value FROM meta`) AND `tmux capture-pane -p -e`.
- Timelines with timestamps for both sources.
- `DECISION.md` with measured numbers: prefer store.db if partial
  blobs exist (structured, no ANSI); else pane-diff.
- Read-only on `~/.cursor` (Cursor's own runtime writes are expected).
- No product-tree changes (no commit).

### 1 cursor-delta-source
status: complete
writes: [omnigent/cursor_native_forwarder.py, omnigent/cursor_native_stream.py, omnigent/_native_output_text_delta.py, omnigent/cursor_native_bridge.py, omnigent/inner/cursor_native_executor.py, omnigent/claude_native_forwarder.py, tests/test_cursor_native_forwarder.py, tests/test_claude_native_forwarder.py, tests/test_cursor_native_stream.py]

Done criteria:
- Chosen source polled at ~100–150 ms while a turn is active; idle
  backoff reuses b0dc3bfaa `_select_poll_interval` /
  `OMNIGENT_CURSOR_POLL_FAST_S` / `OMNIGENT_CURSOR_POLL_IDLE_S`.
- New suffix POSTed as `external_output_text_delta` with a stable
  `messageId` (same shape as claude-native 4013-4060). Factor the POST
  into a shared helper; do not duplicate the JSON body.
- Complete-item POST still supersedes the live preview via existing
  `tapLiveDeltas` / `isLiveProvisionalBlock` / `live:` splice
  (`chatStore.ts` ~4230-4648). Reuse; do not invent a second path.
- `OMNIGENT_CURSOR_STREAM` default on; `0` is a no-op (today).
- `CursorNativeExecutor.supports_streaming()` matches the gate.
- Unit tests: first delta, suffix growth, redraw/scroll if pane
  source, item-completion hand-off, env off.
- Tests written first, then implementation.

### 2 cursor-stream-e2e
status: complete
writes: [loop-cursor-stream/evidence/iter1/e2e/, omnigent/cursor_native_forwarder.py, omnigent/cursor_native_stream.py, tests/test_cursor_native_forwarder.py, tests/test_cursor_native_stream.py]

Done criteria:
- Throwaway instance port ≥ 17200, scratch `OMNIGENT_DATA_DIR` +
  `OMNIGENT_CONFIG_HOME`, torn down.
- Real cursor-native turn records: time-to-first-delta after
  generation starts, time-to-complete-item, delta count, concatenated
  deltas vs completed item byte-equality, no duplicate block after
  completion (GOAL Acceptance 2: TTFD < 1.5 s, ≥ 5 deltas for ~800
  words).
- Fix what the run reveals (smallest correct diff).

## Out of scope
- Live `:6767`, `~/.omnigent`, `~/.claude/projects`, `:17067`,
  `/home/alex/omnigent-fixes-data`, `/home/alex/omnigent`.
- Killing processes we did not start. Writing into `~/.cursor`.
- Amend/rebase/push/stash/reset/checkout.
- Full-file reads of `chatStore.ts` or `claude_native_forwarder.py`.
- Changing persisted history or the complete-item POST contract
  except the additive live-delta overlay.
- Upstream harness rewrite (#3000/#2702/#4589) beyond this overlay.

```yaml
slices:
  - id: probe-partial-text
    repo: .
    writes: []
    reads: [omnigent/cursor_native_forwarder.py]
    status: complete
    iteration: 1
  - id: cursor-delta-source
    repo: .
    writes: [omnigent/cursor_native_forwarder.py, omnigent/cursor_native_stream.py, omnigent/_native_output_text_delta.py, omnigent/cursor_native_bridge.py, omnigent/inner/cursor_native_executor.py, omnigent/claude_native_forwarder.py, tests/test_cursor_native_forwarder.py, tests/test_claude_native_forwarder.py, tests/test_cursor_native_stream.py]
    reads: [loop-cursor-stream/evidence/iter1/probe/DECISION.md]
    status: complete
    iteration: 1
  - id: cursor-stream-e2e
    repo: .
    writes: [loop-cursor-stream/evidence/iter1/e2e/, omnigent/cursor_native_forwarder.py, omnigent/cursor_native_stream.py, tests/test_cursor_native_forwarder.py, tests/test_cursor_native_stream.py]
    reads: [omnigent/cursor_native_forwarder.py, omnigent/cursor_native_stream.py]
    status: complete
    iteration: 1
```
