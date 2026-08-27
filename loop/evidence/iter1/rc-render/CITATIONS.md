# CITATIONS — rc-render (HEAD 9926c9145)

| Scouted fact | Grade | file:line | Evidence |
|---|---|---|---|
| Forwarder poll 250 ms | Confirmed | `claude_native_forwarder.py:84` `_DEFAULT_POLL_INTERVAL_S = 0.25`; loops `864,900,921-928,1025` | SCOUT-STDOUT.md |
| One HTTP POST per delta 3962-3995 / 4041-4062 | Confirmed | `_post_external_output_text_delta` `3962-3984` sequential posts | scout 3998-4051 |
| UI store O(n) per token, no rAF 4292-4327 | **Split** | `applyLiveDelta` `4292-4307` is O(blocks) copy, **no rAF**. Generic stream **has** rAF `4201-4204`, `4504-4510`, `4736-4744`. Native live path `tapLiveDeltas` `4371-4393` calls `applyLiveDelta` synchronously. | SCOUT-STDOUT.md; Lead sed |
| SSE `routes_events.py:1893-1908` | Confirmed | `media_type="text/event-stream"` ~1908 | |
| session_stream maxsize 1024, drop on overflow | Confirmed | `session_stream.py:40`, enqueue `62-78`, queue `232-234`; overflow closes without `[DONE]` `helpers.py:7507-7515` | GOAL 63-79 ≈ 62-78 |
| Sidebar WS 4 s `common.py:474`, `routes_core.py:1213-1240` | Confirmed, line drift | `common.py:474`; sidebar `routes_core.py:1131-1150,1215-1237,1297-1305` | not on the chat token path |
| #3000 4 Hz poll | Confirmed open | GitHub | |
| #4589 Python hook ~1 s | Confirmed issue; **partially stale** | HEAD MessageDisplay is a shell appender `claude_native_bridge.py:1387-1400` | |
| #2702 tmux capture 5 Hz | Confirmed open | watcher `resource_registry.py:92-112`; `terminal.py:1628-1740` | scout: 0.2 s poll |

Lead microbench (Python analog, not React): see `scratch/microbench.txt`.
Poll quantum 250 ms dominates over O(n) copy (~0.4 ms/200 deltas in CPython).

## Cursor-native additions

| Fact | Grade | file:line | Evidence |
|---|---|---|---|
| Cursor uses the native terminal watcher | Confirmed | `runner/native/orchestration.py:2445-2458`; `runner/resource_registry.py:1151-1174` | `CURSOR-NATIVE.md` |
| Cursor watcher cadence | Confirmed | `runner/resource_registry.py:92-98,1338-1345`; `inner/terminal.py:1668-1679` | 0.2 s constant |
| `capture-pane` subprocess cost | Measured | `inner/terminal.py:1730-1740,1929-1949` | `capture-pane-benchmark.txt` |
| Permission polling is approval-only | Confirmed | `cursor_native_permissions.py:54-65,566-583,1013-1023` | `CURSOR-NATIVE.md` |
| Cursor transcript poll | Confirmed | `cursor_native_forwarder.py:58-62,1009-1011,1194` | 0.7 s constant |
| Complete item, not output delta | Confirmed | `cursor_native_forwarder.py:627-705,760-775` | one POST per item |
| Server persists before publishing | Confirmed | `server/routes/_sessions/orchestration.py:2143-2151`; `helpers.py:2482-2512` | `CURSOR-NATIVE.md` |
| Cursor uses generic client pump | Confirmed | `web/src/lib/sse.ts:431-432,1095-1103`; `web/src/store/chatStore.ts:4371-4409` | no Cursor `message_id` delta |
| First content bypasses rAF wait | Confirmed | `web/src/store/chatStore.ts:4504-4511,4736-4744` | generic pump |
| Cursor markdown is initially immediate | Confirmed | `web/src/hooks/useThrottledValue.ts:10-20,27-57` | 100 ms only for growth |

The full end-to-end qualification, unmeasured segments, comparison, and
candidate-fix assessment are in `CURSOR-NATIVE.md` and `REPORT.md`.
