# DB / event loop (ead098caf)

## Engine

This machine: **sqlite**
`sqlite:////home/alex/.omnigent/chat.db` (~1.65 GiB + ~29 MiB WAL).
WAL + `busy_timeout=20s` (`db/utils.py:247-256`).

Sqlite `create_engine` does **not** set `pool_size` (`:228-238`).
With `check_same_thread=False`, SQLAlchemy uses QueuePool defaults:
**size 5, overflow 10, timeout 30 s** — identical to live errors.

Non-sqlite engines get `pool_size=200`, `max_overflow=20`,
`pool_timeout=10` (`:268-289`). AnyIO thread limiter is **200**
(`server/app.py:1141-1145`). Up to 200 `to_thread` workers can wait
on 15 sqlite connections.

## Blocking on the event loop?

Updates WS and snapshot/`items` use **`await asyncio.to_thread(...)`**
— sync DB off the loop:

- `_fetch_watched_items`: `to_thread` for perms +
  `get_conversations` (`routes_core.py:1051-1084,1209-1221`).
- Ticker every **4 s** (`common.py:474`; `routes_core.py:1297-1305`).
- `get_session` → `_get_session_snapshot` (`routes_core.py:708-767`,
  `orchestration.py:9004-9020`).
- `list_session_items` `to_thread(list_items)` (`routes_items.py:63-105`).
- `list_child_sessions` `to_thread(get_conversation)` (`:176` in
  traceback).

Not a sync sqlite call *on* the asyncio thread in these handlers.
Saturation is **pool checkout**, which still stalls the request until
`pool_timeout`.

Watch set cap 500 (`common.py:480`). A 4 s rescan of a large watch-set
on a 1.65 GiB sqlite file can occupy all 15 connections; other GETs
wait 30 s.

## Log measurement

`LOG-PARSE.json`: 156 QueuePool unhandled errors today; **0**
`database is locked`; **0** slow-query; **0** EMFILE.

Traceback endpoints (last `routes_*.py` frame):
`list_child_sessions` 120, `_validate_session` 26, `session_updates` 3,
`stream_session` 3, `get_session` 1, `list_session_items` 1.
