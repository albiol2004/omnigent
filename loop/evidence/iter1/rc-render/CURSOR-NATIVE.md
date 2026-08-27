# Cursor-native render path

HEAD is `9926c9145` (product tree `ead098caf`). This is a static trace plus
one read-only local measurement. No cursor session was started, no session
state was changed, and no process was killed.

## Path conclusion

Cursor has two separate paths:

1. The embedded terminal uses a tmux pane. Its watcher publishes status and
   activity, not assistant text.
2. The chat transcript path reads Cursor's SQLite store, posts complete
   conversation items, and lets the normal SSE/client reducer render them.

`CursorNativeExecutor.supports_streaming()` returns `False` and says output is
shown by the terminal (`omnigent/inner/cursor_native_executor.py:41-61`).
The cursor forwarder instead describes the SQLite `store.db` as its source
(`omnigent/cursor_native_forwarder.py:1-20`).

## Stage 1 — tmux `capture-pane` watcher

- Cursor is launched with the `cursor-native` resource role
  (`omnigent/runner/native/orchestration.py:2445-2458`).
- That role is included in the status-watcher set
  (`omnigent/runner/resource_registry.py:1151-1174`).
- Status-enabled roles use `_CLAUDE_NATIVE_STATUS_POLL_INTERVAL_SECONDS =
  0.2` and pass it to the threaded watcher
  (`omnigent/runner/resource_registry.py:92-98,1330-1345`).
- Each tick waits for that interval, then runs `capture-pane`
  (`omnigent/inner/terminal.py:1668-1679,1730-1740`).

The measurement artifact is `capture-pane-benchmark.txt`. It ran 200 warm
samples after 20 warmups against the existing `main:0.0` pane, discarded
stdout, and only read the pane:

- `tmux capture-pane -p`: mean **1.203 ms**, p95 **1.467 ms**, max
  **2.236 ms**.
- The watcher form, `tmux capture-pane -p -e`: mean **1.192 ms**, p95
  **1.434 ms**, max **1.844 ms**.

The derived status/activity wait is **0–200 ms**, plus the measured subprocess
cost. A sample-level sum using the plain command is about **202.236 ms**;
2.236 ms is not a hard OS scheduling bound. This is **high confidence** for
the cadence and measured command cost, and **medium confidence** for the
combined delay because scheduler and tmux contention can vary.

This stage contributes **0 ms to Cursor assistant-text delivery by design**.
It can delay a status/activity edge by the above quantum, but the text
forwarder reads SQLite independently. This separation is confirmed by the
executor and forwarder citations above.

## Stage 2 — cursor permission polling

`cursor_native_permissions.py` sets `_POLL_INTERVAL_S = 0.3`
(`omnigent/cursor_native_permissions.py:54-65`) and sleeps at the end of each
approval-detection pass (`omnigent/cursor_native_permissions.py:1013-1023,
1155-1163`). A pending call must also remain pending for the default
**500 ms** settle window (`omnigent/cursor_native_permissions.py:947-958,
1075-1091`).

This is **approval-only**, not the assistant-text path. It scans pending tool
calls from the same SQLite store, explicitly describes itself as safe alongside
the forwarder, and does not publish conversation text
(`omnigent/cursor_native_permissions.py:566-583,589-621`). The runner starts
it alongside, but separately from, the transcript forwarder
(`omnigent/runner/native/orchestration.py:2528-2553`).

- Approval detection wait: **0–300 ms**, derived from the constant.
- Approval settle contribution: **0–500 ms**, derived from the constant.
- Assistant-text latency contribution: **0 ms in the text path**; any
  incidental CPU/SQLite contention is **unmeasured**.

Confidence is **high** for the interval, path classification, and settle
bound; it is **low** for incidental contention because no live cursor turn was
run.

## Stage 3 — Cursor store to server and SSE

The forwarder polls with `_DEFAULT_POLL_INTERVAL_S = 0.7`
(`omnigent/cursor_native_forwarder.py:58-62`). It reads new SQLite rows and
converts an assistant row into one complete `message` item
(`omnigent/cursor_native_forwarder.py:627-705`). The poll loop calls that
reader and sleeps after the pass (`omnigent/cursor_native_forwarder.py:1009-1011,
1163-1194`).

The forwarder does **not** emit `external_output_text_delta`. It makes one
sequential `external_conversation_item` POST for each complete item
(`omnigent/cursor_native_forwarder.py:760-775`). The server dispatches that
event (`omnigent/server/routes/sessions/routes_events.py:947-959`), appends
the item before publishing it (`omnigent/server/routes/_sessions/orchestration.py:2143-2151`),
and publishes it as `response.output_item.done`
(`omnigent/server/routes/_sessions/helpers.py:2482-2512`).

The known Cursor-specific wait is therefore **0–700 ms** per newly visible
store row. There are **0 per-token POSTs** and **1 POST per complete item**.
Cursor store-write-to-row visibility, HTTP round-trip, server DB append, and
publish scheduling have no source constant and were not measured without a
live cursor session; they are **bounded by constant, unmeasured** rather than
guessed.

There is no per-output hook process comparable to the Claude hook concern.
Cursor's installed hook is a `stop` hook for one usage record per completed
turn (`omnigent/cursor_native_bridge.py:344-371`), not a text-delta hook.
Its process cost is therefore **unmeasured but off the incremental text path**.
Confidence is **high** for the poll and POST shape, and **medium** for the
latency ranking because the transport and DB portions lack live measurements.

## Stage 4 — SSE to client store and DOM

The server's `session_stream.publish` hands each event to subscriber queues
through `call_soon_threadsafe`; it has no fixed delay constant
(`omnigent/runtime/session_stream.py:81-119`). The SSE route validates and
serializes each event before yielding it
(`omnigent/server/routes/_sessions/helpers.py:7391-7406,7497-7506`).
Those queue, validation, network, and browser-read costs are **unmeasured**.

Cursor's complete item is parsed as `response.output_item.done`, then as
`message_done` (`web/src/lib/sse.ts:431-432,1095-1103`). The generic
`BlockStream` turns that complete content into `text_done`
(`web/src/lib/blockStream.ts:688-740`). `pumpStreamEvents` runs every event
through `tapLiveDeltas`, but that tap only diverts a `text_delta` carrying a
`messageId` (`web/src/store/chatStore.ts:4351-4409`). Since the Cursor
forwarder sends no such event, Cursor text **does not take the no-rAF live
delta path**.

The complete item follows the generic frame scheduler: the first content
flushes immediately, and later blocks schedule one rAF flush
(`web/src/store/chatStore.ts:4147-4183,4504-4511,4736-4744`). That is
**0 ms scheduler wait for first content**, or **at most one browser frame**
for later content; **16.7 ms at 60 Hz** is a derived example, not a measured
React timing. The React commit itself is **unmeasured**.

The live markdown throttle is configured at **100 ms**
(`web/src/components/blocks/ChatMarkdown.tsx:254-259`). The hook emits its
initial value immediately and only trails repeated changes
(`web/src/hooks/useThrottledValue.ts:10-20,27-57`). A Cursor assistant item
arrives complete, so its initial markdown render adds **0 ms by design**;
the **0–100 ms** throttle is relevant to a growing text block, which Cursor
does not send on this path. The DOM hands assistant text to that component at
`web/src/components/blocks/BlockRenderer.tsx:738-756`.

Confidence is **high** for the event-path and rAF classification, **medium**
for the derived frame bound, and **low** for actual React commit time.

## Known end-to-end budget and comparison

For Cursor's assistant text, the known scheduling components are:

```
store-poll quantum       0–700.0 ms
first-content scheduler      0.0 ms
later-content scheduler   <=16.7 ms at 60 Hz (derived)
initial markdown throttle    0.0 ms
```

So the known quantum subtotal is **0–700.0 ms for first text**, or
**0–716.7 ms for a later block at 60 Hz**. This is not a hard end-to-end
upper bound: Cursor store write, POST/DB/SSE, and React commit remain
**unmeasured**. The separate tmux status path adds **0–200 ms** to status
edges, but is not part of this subtotal. Permission polling adds **0 ms** to
assistant text.

Compared with the existing columns:

- **claude-native:** known forwarder wait **0–250 ms**, one POST per live
  delta, synchronous no-rAF live-delta store work, and a 100 ms growing-markdown
  throttle.
- **claude-sdk:** no transcript poll; it uses the generic streamed relay and
  rAF batching, with no fixed transport or React timing.
- **cursor-native:** the largest known ingress quantum is **0–700 ms**, and
  the browser cannot paint partial assistant text because it receives one
  complete item.

This supports a cursor-native top cause of **700 ms transcript polling plus
complete-item-only mirroring**, while not proving an actual environment-wide
slowest ranking without a live end-to-end sample.
