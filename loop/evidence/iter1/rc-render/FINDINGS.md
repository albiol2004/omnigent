# FINDINGS — rc-render

"UI slow to render CLI output" has two different native paths. Cursor-native
has the largest known ingress quantum: its SQLite forwarder polls every
700 ms and mirrors complete assistant items. Claude-native has a separate
live-preview path that can bypass rAF. The generic SDK stream is rAF-batched.

GOAL "no rAF batching" is **false for claude-sdk and cursor-native complete
items** and **true for native `message_id` live deltas**.

The cursor-native trace and measurement are in `CURSOR-NATIVE.md`. The
cursor-specific top confirmed cause is the **0–700 ms transcript-poll
quantum plus complete-item-only mirroring**. Store-write, transport, and
React commit costs remain unmeasured without a live cursor session.

Recommended fix order: reduce or adapt the cursor transcript poll, then
investigate a supported incremental Cursor output signal. Batch
`tapLiveDeltas` through the existing rAF scheduler only for the
claude-native path. Coordinate shared UI work with #3000, #5405, and #5603.
