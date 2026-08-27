🤖 I verified HEAD as `9926c9145ee1067405baf50b64369a55d6f7ce1d`.
Product files remain untouched; only pre-existing `loop/` changes are present.

The key correction is that “no rAF batching” is only true for the
`claude-native` live-preview branch. Generic streaming, including
`claude-sdk`, is rAF-batched. No direct timing was performed because Ask mode
forbids creating scratch/log files or running live sessions.

## CITATIONS

| Fact | Result | HEAD evidence |
|---|---|---|
| Native forwarder default poll | Confirmed: `0.25s` | `omnigent/claude_native_forwarder.py:84,723-724,803-805,1025` |
| Poll loop locations | Confirmed | `omnigent/claude_native_forwarder.py:864,900,921-928,1025` |
| One HTTP POST per native text delta | Confirmed; posts are sequential | `omnigent/claude_native_forwarder.py:3962-3995,3998-4051` |
| Native MessageDisplay hook | Shell command, not Python; still incurs command-process overhead | `omnigent/claude_native_bridge.py:1387-1400` |
| Python hook benchmark | Confirmed, but does not model current production MessageDisplay | `dev/benchmarks/omnigent/journeys.py:881-931` |
| Native live store update | O(block count) search/copy plus growing-text work per delta | `web/src/store/chatStore.ts:4292-4307` |
| Native live rAF batching | Not present: `tapLiveDeltas` calls `applyLiveDelta` synchronously | `web/src/store/chatStore.ts:4371-4393` |
| Generic stream rAF batching | Confirmed | `web/src/store/chatStore.ts:4152-4183,4504-4510,4736-4744` |
| SSE endpoint | Confirmed `text/event-stream` | `omnigent/server/routes/sessions/routes_events.py:1724-1750,1893-1908` |
| SSE validation/serialization | Per-event validation and formatting occur before yield | `omnigent/server/routes/_sessions/helpers.py:7391-7506` |
| Session queue size | Confirmed: `1024` events | `omnigent/runtime/session_stream.py:39-40,232-234` |
| Overflow behavior | Confirmed: backlog is drained and replaced by `_OVERFLOW` | `omnigent/runtime/session_stream.py:62-78,294-309` |
| Overflow response | Route closes without `[DONE]`, forcing reconnect/reconciliation | `omnigent/server/routes/_sessions/helpers.py:7507-7515` |
| Sidebar WS rescan | Confirmed: `4.0s` | `omnigent/server/routes/_sessions/common.py:474`; `routes_core.py:1297-1305` |
| Sidebar scope | Separate sidebar channel, not the chat token stream | `omnigent/server/routes/sessions/routes_core.py:1131-1150,1215-1237` |
| Native tmux polling | Confirmed: native status watcher polls every `0.2s` | `omnigent/runner/resource_registry.py:92-112,1338-1345` |
| `capture-pane` subprocess | Confirmed per watcher tick | `omnigent/inner/terminal.py:1628-1740,1929-1949` |
| Markdown throttling | Confirmed: `100ms` trailing throttle | `web/src/components/blocks/ChatMarkdown.tsx:254-259,359-389` |
| Bubble caching | Confirmed: finalized prefixes are reused, active region rebuilt | `web/src/lib/renderItems.ts:336-437,568-659` |
| SDK event path | SDK emits `TextChunk`; adapter emits directly to runner SSE queue | `omnigent/inner/claude_sdk_executor.py:2671-2687`; `omnigent/runtime/harnesses/_executor_adapter.py:615-623` |
| SDK runner stream | Confirmed persistent client per session and streamed queue | `omnigent/inner/claude_sdk_executor.py:1674-1782`; `omnigent/runtime/harnesses/_scaffold.py:1284-1365` |
| SDK server relay | Runner SSE is parsed, then published to `session_stream` | `omnigent/server/routes/_sessions/orchestration.py:5757-5781,5890-5900,6168` |

Upstream evidence was collected with `gh issue view` / `gh pr view`:

- [#3000](https://github.com/omnigent-ai/omnigent/issues/3000) — open,
  native forwarder polls at 4 Hz and lacks idle backoff.
- [#4589](https://github.com/omnigent-ai/omnigent/issues/4589) — open,
  fresh Python hook-process overhead; partially stale for current
  MessageDisplay because HEAD uses a shell appender.
- [#2702](https://github.com/omnigent-ai/omnigent/issues/2702) — open,
  `tmux capture-pane` fork/exec at 5 Hz per native terminal.
- [#4976](https://github.com/omnigent-ai/omnigent/pull/4976) — open,
  process-tree teardown.
- [#5603](https://github.com/omnigent-ai/omnigent/pull/5603) — open,
  fork run configuration.
- [#5405](https://github.com/omnigent-ai/omnigent/pull/5405) — open,
  permission inheritance.
- [#4913](https://github.com/omnigent-ai/omnigent/pull/4913) — open,
  fork-from-user-message rendering/API changes.
- [#5081](https://github.com/omnigent-ai/omnigent/pull/5081) — open,
  deleted-worktree recreation.
- [#5544](https://github.com/omnigent-ai/omnigent/pull/5544) — merged,
  full session teardown and cache-generation guard; local HEAD predates it.

## TIMING

All values below are static code-derived budgets, not measurements.

| Stage | `claude-native` | `claude-sdk` |
|---|---|---|
| Hook spawn | Per-chunk shell command; runtime unconfirmed. The Python benchmark is not representative. | N/A per delta. SDK CLI connects once per cached session client. |
| Poll | Arrival waits `0–250ms`; nominal average is `~125ms` only under a uniform-arrival assumption. | N/A. |
| Per-delta POST | One sequential `httpx` POST per delta; latency unconfirmed and network-dependent. | N/A per delta. |
| `session_stream` | Local publish plus `call_soon_threadsafe` queue delivery; no fixed delay. | Same publish path, reached through the runner relay. |
| SSE | One server SSE hop to the browser; per-event validation/JSON formatting. | Runner SSE + relay parsing, then server SSE to browser. |
| Store update | Native `message_id` path updates synchronously per delta; `findIndex`, array copy, string append, and `includes`. | Reducer coalesces text at a 30-character/newline threshold and flushes via rAF. |
| React render | Store update invalidates `ChatPage`; bubble cache helps, but active bubble is rebuilt per delta. | At most one normal store flush per animation frame after first content. |
| Markdown | Heavy markdown work throttled to at most roughly every `100ms`. | Same. |

The queue’s `1024` capacity is a burst limit, not a latency bound. Overflow
drops the backlog and causes reconnect, so it indicates the consumer has fallen
behind rather than adding a predictable delay.

### Ranked causes

1. Native live previews bypass the rAF scheduler and perform synchronous
   store/render work for every delta.
2. Native forwarder polling contributes a known `0–250ms` delivery quantum.
3. Native output also pays one sequential HTTP request per delta.
4. Native terminal watchers can consume substantial CPU through repeated
   `capture-pane` subprocesses, especially with many terminals.
5. Shell hook startup remains overhead, but the current MessageDisplay path
   already avoids the much heavier Python import path.
6. SSE validation, serialization, and queue delivery are plausible secondary
   costs but have no direct timing evidence here.
7. The 4-second sidebar WS rescan is not a chat-token rendering bottleneck.

## Candidate fixes

| Fix | Size / files | Risk | Upstream interaction |
|---|---|---|---|
| Batch native live-delta store updates per animation frame | Medium; `chatStore.ts`, store tests | Medium/high: preserve ordering, reconnect, and final-item reconciliation | Directly overlaps #5405/#5603 `chatStore` work; semantically near #4913 `renderItems`/`ChatPage` changes |
| Add adaptive native forwarder backoff or mtime gating | Medium; `claude_native_forwarder.py`, tests | Medium: can delay status, `/clear`, and first-token delivery | Directly coordinate with open #3000 |
| Batch native deltas into one HTTP request per poll | Medium/large; forwarder, session event schema/routes, tests | Medium/high: new wire contract and failure semantics | May touch `routes_events.py`, so rebase after merged #5544; independent of #2702 |
| Replace repeated `capture-pane` with control mode or adaptive polling | Large; `inner/terminal.py`, `runner/resource_registry.py`, tests | High: terminal lifecycle and cross-platform behavior | Directly addresses #2702 |
| Correct `native_hook_spawn` benchmark to measure the production shell hook | Small; benchmark journey/README/tests | Low | Clarifies, but does not duplicate, #4589 |
| Add a fast-path for transient text-delta SSE serialization | Small/medium; session route/helpers/schema | Medium: risks bypassing wire validation | `routes_events.py` overlap with merged #5544; no direct fork-UI overlap |
| Virtualize finalized chat bubbles | Large; `ChatPage.tsx`, render components/tests | High UX/scroll correctness risk | Strong overlap with #4913 and render portions of #5405/#5603 |
| Persistent native forwarder connection/daemon | Large; forwarder, bridge, lifecycle, tests | High lifecycle and teardown risk | Coordinate with #4976 and #5544 process/session teardown work |

No `loop/evidence/iter1/rc-render/` files were created because Ask mode
prohibits writes. The evidence paths above are the read-only product sources.

For a follow-up measurement, the existing hook benchmark can be run with:

```bash
uv run --no-sync dev/benchmarks/omnigent/run.py \
  --journeys native_hook_spawn --iterations 20 --runs 3 --warmup 3
```

That measures the Python benchmark path, not the current production shell
MessageDisplay command.
