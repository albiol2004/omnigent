# Scout brief — rc-freeze (read-only reconnaissance)

Repo /home/alex/omnigent, product tree ead098caf. Read `loop/GOAL.md` slice **rc-freeze** and problem 4. Investigation only: change nothing, kill nothing, never touch real sessions.

Answer with file:line evidence at HEAD (use `grep -n` / `sed -n 'a,bp'`; NEVER read whole files — several exceed 1 MB):
1. Transport: is the web UI served over HTTP/1.1 or HTTP/2 (uvicorn/hypercorn config, proxy, Electron)? How many long-lived connections does the UI hold per open session (SSE stream, updates WS, terminal/tunnel WS, dictation)? Are SSE streams/WS closed when switching sessions or navigating away (grep `EventSource`/`AbortController`/`close()` in web/src/store/chatStore.ts, web/src/lib/sse.ts, web/src/lib/sessionUpdatesSocket.ts, terminal attach)? Could 6+ open streams to one host starve new requests on HTTP/1.1?
2. Every constant near 60 s / 70 s / 30 s on the client (web/src/lib, web/src/store) and server (omnigent/server/routes) — reconnect backoff, watchdogs, heartbeats, request timeouts, keepalive. Which ones would produce "hangs ~1 min then works"?
3. Server side: does the updates-WS 4 s rescan (omnigent/server/routes/sessions/routes_core.py:1213-1240, common.py:474-480) or the session snapshot / `/items?limit=1000` path do blocking DB work on the event loop? Which DB (sqlite/postgres), lock mode, threadpool size? Any sync call in an async handler?
4. session_stream overflow (omnigent/runtime/session_stream.py:40,63-79): what does the client see when dropped, and how long until it reconnects?
5. Check recent server/runner logs on this machine (read-only; find them via `omnigent` config or ~/.omnigent, journalctl if permitted) for timeouts, "too many open files", pool exhaustion, slow-query warnings around session opens.

Output: ranked candidate causes (confidence, evidence, what measurement would confirm), plus for each a candidate fix with size/files/risk. Plain text; you cannot write files.
