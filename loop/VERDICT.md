VERDICT: SHIP

Independent rc-freeze pass (before REPORT): sqlite QueuePool
5/10/timeout 30 s is a **measured** cause of session-open stalls;
HTTP/1.1 6/host starvation is **unconfirmed** as the freeze
mechanism (transport facts confirmed). Problems 1–3 stand from
iter 1. Report is ready to retire.

## Independent rc-freeze (Evaluator)

Product tree `ead098caf`. `git status --porcelain` was loop/-only
before this verdict.

(a) Sqlite `create_engine` omits pool kwargs
`omnigent/db/utils.py:228-238`. Postgres sets `pool_size=200`,
`max_overflow=20`, `pool_timeout=10` (`:268-289`). SQLAlchemy
QueuePool defaults match live errors (`size 5 overflow 10`,
`timeout 30.00`). AnyIO limiter 200: `server/app.py:1141-1145`.

(b) `grep -c 'QueuePool limit of size 5'` on
`~/.omnigent/logs/server/server-20260827-162548-652214.log` =
**471** (string also appears inside tracebacks). Unhandled ERROR
lines = **156**, matching `LOG-PARSE.json`. Pairs 17:08:42 / 17:09:12
and 20:35:02 / 20:35:32 are 30.000 s apart. Last `routes_*.py`
frames are session-open / session-live paths: `list_child_sessions`
dominant, plus `_validate_session`, `stream_session`, `get_session`,
`list_session_items` (Lead also counted `session_updates`).

(c) `curl -sD- -o /dev/null http://127.0.0.1:6767/health` →
`HTTP/1.1 200` `server: uvicorn`. `--http2` still HTTP/1.1.

(d) SSE kept on `switchTo` (`chatStore.ts:1910-1913`). Abort on
dispose (`conversationRegistry.ts:275-279`). Serial cap 3
(`conversationRegistry.ts:74-77`; `streamSlots.ts:1-16`). Over-budget
open allowed (`chatStore.ts:2324-2347`). Bind hydrates
`getSessionSlim` + items in parallel (`chatStore.ts:3045-3052`).
Updates WS is app-lifetime (`SessionUpdatesProvider` /
`sessionUpdatesSocket.ts`). Child list:
`useChildSessions.ts:177-178`.

(e) Snapshot / items / updates DB via `asyncio.to_thread`, not the
loop: `_get_session_snapshot` `orchestration.py:9004-9020`;
`list_session_items` `routes_items.py:91-105`; `_fetch_watched_items`
`routes_core.py:1051-1084`; ticker 4 s `common.py:474`,
`routes_core.py:1297-1305`. Watch cap 500 (`common.py:480`).

**30 s × 2 ≈ 1 min:** confirmed as the **measured length of pool
saturation episodes** (two timeout waves). Not a stopwatch of one
UI `GET`. Sequential hydrate + `child_sessions` can stack waits;
that stacking is inferred, not timed on a real open.

**HTTP/1.1 6/host as freeze cause:** **unconfirmed**. Origin is
HTTP/1.1; 3 SSE + 1 updates WS + 2 hydrate GETs **can** fill ~6/host.
No live 6-SSE hold; idle fake-id GET 404 in 5.1 ms. Not refuted.

No Evaluator scout (`trioctl … scout`): line-range + log + curl
were enough. Ask mode cannot write.

## Acceptance

1. **Pass.** ≥1 confirmed cause per problem + artifact:
   - P1 fork: unbounded copy/replay; `MEASUREMENT.json` ~3.85–3.93 MB.
   - P2 render: cursor 0–700 ms poll + complete-item mirror;
     `CURSOR-NATIVE.md` / `TIMING.md`.
   - P3 kill: close/disconnect never stop CLI; `CENSUS.md` / `PATHS.md`.
   - P4 freeze: QueuePool 5+10 wait 30 s; `LOG-PARSE.json`,
     `EXCERPT-*`, `FINDINGS.md`.

2. **Pass.** GOAL scouted facts live in iter1 `CITATIONS.md` plus
   iter2 `CONSTANTS.md`/`TRANSPORT.md`/`DB.md` (confirmed / refuted /
   unconfirmed). None dropped: SDK `_ensure` refuted; global “no rAF”
   refuted; kill orphan-herd refuted; freeze event-loop sync sqlite
   refuted; 5 min h2 cap N/A locally; `database is locked` 0 today.

3. **Pass.** Candidate fixes have size / files / risk / listed
   upstream PRs (#4976, #5603, #5405, #4913, #5081, #5544). Fix order
   is coherent: freeze pool → kill/#4976 → fork after #5603/#5405 →
   cursor poll / Claude rAF.

4. **Pass.** No product path differs from `ead098caf`. Mailbox-only
   retirement commit.

## Discrepancies (non-blocking)

- REPORT ranks HTTP/1.1 6/host as confirmed cause #2. Architecture
  is confirmed; **starvation as the hang** is unconfirmed. Pool
  remains the only log-measured freeze cause. Does not fail
  Acceptance 1.
- Naive `grep -c 'QueuePool limit of size 5'` is 471, not 156.
- `HEAD` in REPORT (`9926c9145`) is the iter-1 product alias;
  mailbox `HEAD` before this commit was `53f9bcc33`; product tree
  is `ead098caf`.
- rc-freeze scout stdout was empty/in-flight; Lead + this Evaluator
  filled from HEAD + logs.

## Human check

None.

commit: none (investigation-only; no `slice(...)` product commits)
