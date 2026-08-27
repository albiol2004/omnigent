# ~30 / 60 / 70 s constants (ead098caf)

Which ones can look like “hang ~1 min then works”?

| Value | Where | ~1 min? |
|---|---|---|
| **SQLAlchemy sqlite QueuePool `timeout 30.00`**, size 5 overflow 10 | Live logs; sqlite `create_engine` omits pool kwargs so SQLAlchemy defaults apply (`db/utils.py:228-238`). Postgres path sets `pool_size=200`, `pool_timeout=10` (`:268-289`). | **Yes.** Two consecutive 30 s waits = ~60 s. Clusters at 17:08:42 then 17:09:12 and 20:35:02 then 20:35:32. |
| SQLite `busy_timeout=20000` (20 s) + connect `timeout: 20.0` | `db/utils.py:237,252` | 20 s, not 60. **0** `database is locked` in today's server log. |
| Updates heartbeat 30 s / client watchdog **70 s** | `common.py:478`; `sessionUpdatesSocket.ts:50` `HEARTBEAT_WATCHDOG_MS = 70_000` | Sidebar liveness, not transcript hydrate. Close to “a minute”. |
| SSE stall **45 s** | `sse.ts:89` `SSE_STALL_TIMEOUT_MS = 45_000` | Reconnect + snapshot; can add a second wait. |
| SSE reconnect cap **5 s** | `chatStore.ts:1056-1057` `STREAM_RECONNECT_MAX_MS` | Too short alone. |
| Background reconnect jitter **3 s** | `chatStore.ts:4134` | Too short. |
| Presence idle **30 s** | `presenceIdle.ts:12` | Recycles SSE with `?idle=`; not a 60 s block. |
| SSE heartbeat **15 s** | `common.py:386` | Keeps stream alive. |
| Updates rescan **4 s** | `common.py:474` | Load, not a 60 s timer. |
| Uvicorn WS ping 30 s / pong **90 s** | `cli.py:4114-4115`; `limits.py:27-28` | Tunnel half-open, longer than 1 min. |
| Runner forward read **60 s** | `common.py:395` `_RUNNER_FORWARD_TIMEOUT` | Runner proxy, not session open GET. |
| Background title timeout **70 s** | `background_session_titles.py:102` | One 504 in log; not session open. |
| Client 404 retry comment “~10-60s restart” | `chatStore.ts:1058-1060` | Restart window, not pool. |
| Apps ~5 min h2 stream cap | comments in `chatStore.ts:1051-1052`, `routes_events.py:1917` | N/A locally (HTTP/1.1). |

## Overflow reconnect

Queue 1024 (`session_stream.py:40,63-79,296-300`). Overflow raises;
SSE helper logs and **does not** yield `[DONE]` (`helpers.py:7507-7511`).
Client treats drop as reconnectable; healthy reconnect is instant
(`chatStore.ts:3969-3971`). Slow only if the follow-up snapshot hits
the pool.
