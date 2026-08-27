# Transport (product tree ead098caf)

Local server: `omni host` → uvicorn on `http://127.0.0.1:6767`
(`sqlite:////home/alex/.omnigent/chat.db`).

## HTTP/1.1 vs h2

**Confirmed HTTP/1.1 only.** `curl --http2 http://127.0.0.1:6767/health`
still returned `HTTP/1.1 200` `server: uvicorn`. No h2/TLS in
`uvicorn.Config` (`omnigent/cli.py:4091-4116`). Default http impl is
h11. `conversationRegistry.ts:38-44` treats missing ALPN + `http:` as
**serial** (HTTP/1.1). Vite proxy (`web/vite.config.ts:32,276`) is also
HTTP/1.1.

## Long-lived connections per open session

| Channel | Count | Closed on session switch? |
|---|---|---|
| SSE `GET /v1/sessions/{id}/stream` | 1 per **live** conversation | **No.** `switchTo` keeps background pumps (`chatStore.ts:1910-1913`). Abort only on dispose/evict (`conversationRegistry.ts:275-279`). |
| Updates WS `/v1/sessions/updates` | **1 per tab** | Stays for app lifetime (`SessionUpdatesProvider` start/stop). |
| Terminal attach WS | 0–8 warm (`ChatPage.tsx:1633`) | LRU evict closes (`TerminalSession.ts:713-716`). Local often uses `ws://127.0.0.1:<runner>` (other port → other origin). Relay uses `:6767`. |
| Dictation WS | 0–1 while dictating | Closed on stop (`dictation.ts`). |

HTTP/1.1 live-SSE cap is **3** (`maxLiveConversations("serial")` =
`conversationRegistry.ts:74-77`; slots in `streamSlots.ts:1-16`).
Over-budget open is allowed when other tabs hold every lock
(`chatStore.ts:2324-2347`).

## Can the browser hit 6 connections to one host?

**Yes, on this HTTP/1.1 origin.** Typical tab: 3 SSE + 1 updates WS +
bind's parallel `getSessionSlim` + `items` (`chatStore.ts:3010,3045-3052`)
= **6**. Extra relay terminal WS or a second tab's over-budget SSE
queues ordinary fetches behind the Chrome ~6/host pool until a stream
stalls (`SSE_STALL_TIMEOUT_MS` 45s) or a WS watchdog fires (70s).

`ss` snapshot during this pass: 4 ESTAB + 19 CLOSE-WAIT to `:6767`
(not a 6-conn deadlock right now).

## SSE-hold reproduction

**Not run against production streams.** Holding N real
`/stream` GETs would occupy the user's server/pool. Bounded instead by
(1) HTTP/1.1 facts above, (2) live QueuePool logs, (3) a fake-id GET
that 404'd in 5.1 ms (`LOG-PARSE.json`) — pool was **not** exhausted
at probe time.
