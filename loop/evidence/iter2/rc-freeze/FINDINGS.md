# rc-freeze FINDINGS

## Ranked confirmed causes

1. **Sqlite QueuePool exhaustion (size 5 + overflow 10, wait 30 s)** —
   high. Matches “doesn't load ~1 min then works”: paired bursts 30 s
   apart (17:08:42 / 17:09:12, 20:35:02 / 20:35:32). Session-open
   paths (`get_session`, `list_session_items`, `list_child_sessions`,
   `stream_session`, `session_updates`) wait on the same pool.
   Evidence: `LOG-PARSE.json`, log excerpt, `db/utils.py:228-238`.

2. **HTTP/1.1 + long-lived SSE/WS (browser ~6/host)** — medium-high
   locally. Uvicorn is HTTP/1.1; UI keeps ≤3 SSE + 1 updates WS +
   hydrate fetches. Can queue `GET /v1/sessions/{id}` until a 45 s
   stall or 70 s WS watchdog. Evidence: `TRANSPORT.md`. Not the
   dominant *server* signal today (pool errors).

3. **Updates-WS 4 s bulk sqlite reads on a 1.65 GiB DB** — medium.
   Occupies pool; does not block the event loop (uses `to_thread`).
   Evidence: `DB.md`.

## Refuted / unconfirmed

- **Event-loop sync sqlite in snapshot/updates handlers** — refuted
  (`to_thread`).
- **`database is locked` / EMFILE / slow-query warnings** — none in
  today's server log.
- **SSE reconnect backoff as the 60 s timer** — max 5 s
  (`STREAM_RECONNECT_MAX_MS`).
- **session_stream overflow as a 60 s hang** — reconnect is instant;
  only slow if snapshot then hits the pool.
- **Live 6-SSE hold reproducing delayed GET** — not run on production
  streams (forbidden). Fake session GET 404 in 5.1 ms (pool idle).

## Scout

`loop/evidence/iter2/rc-freeze/SCOUT.md` was still empty (in-flight
`trioctl … scout`) while Lead measured. Not re-run.
