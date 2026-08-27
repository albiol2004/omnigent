# REPORT — iter 1–2 root-cause investigation

HEAD: `9926c9145` (product tree `ead098caf`). Investigation only. No
product diffs. Iter 2 adds problem 4 / **rc-freeze** only.

## Trioctl / Luna

Resolved scout/builder: **gpt-5.6-luna-max** (`model_effort: max`).

| Slice | Command | Exit | Notes |
|---|---|---|---|
| rc-fork | `trioctl omnigent run scout --prompt-file loop/briefs/rc-fork.md --workspace . --timeout 1800` | 0 | Captured `loop/evidence/iter1/_trioctl/rc-fork.stdout`. Ask mode blocked file writes; Lead persisted + re-measured. |
| rc-render | same, `rc-render.md` | 0 | `.../_trioctl/rc-render.stdout`. Ask mode blocked writes; Lead persisted + microbench. |
| rc-kill | same, `rc-kill.md` | **1** | Timed out 1800s, empty stdout (`rc-kill/SCOUT-STDERR.txt`). Lead completed census + path trace. |
| rc-freeze | `trioctl omnigent run scout --prompt-file loop/briefs/scout-rc-freeze.md` (coordinator, still writing `SCOUT.md`) | in-flight | Lead did not re-run it. Evidence from line-range reads + live logs. |

No builder product work. Iter 1 evidence under `loop/evidence/iter1/`.
Iter 2 under `loop/evidence/iter2/rc-freeze/`.

---

## Problem 1 — Fork loads the whole session into Claude Code context

### Confirmed causes (ranked)

1. **Unbounded history copy + full render on the first fork turn (high).**
   `fork_session` deep-copies items (`routes_core.py:1990-2172`).
   `fork_conversation` copies every `SqlConversationItem` (`sqlalchemy_store.py:3397`,
   item loop `3633-3666`). Native then clones JSONL (`claude_native.py:1780-1843`)
   or rebuilds it (`_ensure_local_claude_resume_transcript` `4125-4202`) for
   `claude --resume`. Fresh SDK serializes all prior turns as one prompt
   (`claude_sdk_executor.py:3052-3123`, `"Conversation so far:"` at `3094`).
   Cursor prepends a preamble (`cursor_native_executor.py:93-114`,
   `orchestration.py:5415-5443`).
   **Evidence:** `loop/evidence/iter1/rc-fork/MEASUREMENT.json` — 640 messages ×
   6k chars → **~3.85–3.93 MB** on SDK/cursor/JSONL paths. Scout analog
   ~4.06 MB JSONL (`SCOUT-STDOUT.md`). That is enough to trip Claude
   "Prompt is too long".

2. **No fork-time compaction (high).** Native rebuild compacts only when
   `compacted_messages` exists (scout snippet `claude_native.py:4333-4344`).
   Summary-only markers leave old records. Cursor ignores compaction items.
   SDK compaction is a warm-client feature; a fork is a **fresh** client.

3. **Resume/clone failure falls through to a blank or oversized launch (high).**
   Item fetch uses `limit: 1000` (`claude_native.py:4223`). Matches #5498.
   Missing source JSONL → `_clone_claude_transcript` returns `None` (`1818-1827`).

4. **Tool-result bloat / duplicate items (medium)** — #5180, #3469; not
   re-reproduced here.

5. **UI vs server fork_history mismatch (medium).** `forkHarness.ts:135-144`
   offers history-carrying forks; scout: `antigravity-native` advertised while
   plugin capability is `NONE`.

### Refuted scouted facts

- **SDK/cross-family fork uses `_ensure_local_claude_resume_transcript`.**
  That helper is **Claude-native JSONL rebuild**, not the SDK renderer.
  SDK uses copied conversation items + `_build_prompt` (`runner/app.py`
  per scout `3233-3237`, `5781-5783`).

### Unconfirmed

- Exact billed-token count / live `claude --print` "Prompt is too long"
  (avoided hitting user Claude + `~/.claude/projects`).
- Warm SDK size: Lead fixture returned 0 bytes; scout reported 6-byte
  latest message. Warm path **does** skip replay (`3080-3081`).

### Candidate fixes

| Fix | Size | Files | Risk | Upstream |
|---|---|---|---|---|
| Oversize preflight; refuse silent blank launch | S–M | `claude_native.py`, `orchestration.py`, runner app | UX needs compact/retry | Low vs #4976; **high** vs #5603/#5405 (route/store) |
| Fork-local or user-confirmed compact | M–L | route, store, renderers, UI | summary loss | **#5603 #5405 #5081 #4913** |
| Honor summary-only compaction on native+cursor | S–M | `claude_native.py`, `orchestration.py` | drops pre-summary turns | medium #5405 |
| Drive UI from server `fork_history` | S | `forkHarness.ts` | hides some targets | low–med #5081 |
| Pagination + rebuild when clone fails | S–M | `claude_native.py` | transcript divergence | #5498 |

**Do first:** measure+refuse oversize on fork, then compact-on-fork. Land
after or inside #5603/#5405, not as a conflicting third route rewrite.

---

## Problem 2 — UI slow to render CLI output

### Path qualification

There are two native render paths. Claude-native streams message deltas into a
live preview. Cursor-native does not stream assistant text through the
Omnigent executor: it polls Cursor's SQLite transcript and mirrors complete
items. The cursor trace, numbers, and comparison are in
`loop/evidence/iter1/rc-render/CURSOR-NATIVE.md`.

### Confirmed causes (ranked)

#### Cursor-native

1. **The Cursor transcript poll adds a 0–700 ms delivery quantum (high,
   bounded).** `_DEFAULT_POLL_INTERVAL_S = 0.7`, and the forwarder reads new
   rows before sleeping (`cursor_native_forwarder.py:58-62,1009-1011,1163-1194`).
   This is the largest known text-ingress wait in the three columns.
   **Evidence:** `CURSOR-NATIVE.md`; the complete poll budget is in
   `TIMING.md`.

2. **Cursor mirrors complete assistant records, so the web cannot paint partial
   assistant text (high, path-confirmed).** The executor explicitly has no
   streaming support (`inner/cursor_native_executor.py:41-61`), the forwarder
   converts a full assistant blob to one message
   (`cursor_native_forwarder.py:627-705`), and it emits no
   `external_output_text_delta`. The row's write/visibility time is
   **unmeasured**, but the absence of incremental web output is confirmed.

3. **Each complete item pays one sequential POST and server append before SSE
   publish (medium-high, path-confirmed).** The forwarder posts one item at a
   time (`cursor_native_forwarder.py:760-775`); the server appends before
   publishing `response.output_item.done`
   (`server/routes/_sessions/orchestration.py:2143-2151`,
   `server/routes/_sessions/helpers.py:2482-2512`). HTTP RTT, DB append, and
   SSE scheduling are **unmeasured** without a live cursor session.

4. **The 200 ms tmux watcher is a parallel status/activity path, not text
   delivery (medium for shared CPU, not a paint delay).** Cursor is in the
   status role set and uses the 0.2 s watcher
   (`runner/resource_registry.py:1151-1174,1338-1345`). The real-pane
   measurement found 1.203 ms mean, 1.467 ms p95, and 2.236 ms max for
   `capture-pane -p` (`capture-pane-benchmark.txt`). Its status edge can wait
   0–200 ms; it is excluded from the cursor text subtotal.

5. **Permission polling is approval-only (low for text rendering).**
   It polls every 300 ms and can add a 500 ms approval settle
   (`cursor_native_permissions.py:54-65,947-958,1013-1023`), but its
   pending-call scan is explicitly separate from the forwarder text path
   (`cursor_native_permissions.py:566-583`). Its direct assistant-text
   contribution is 0 ms; incidental contention is unmeasured.

#### Comparison and shared causes

6. **Claude-native live deltas bypass rAF and update the store synchronously
   per chunk (high for Claude-native).** `tapLiveDeltas` calls
   `applyLiveDelta` for a `message_id` delta
   (`web/src/store/chatStore.ts:4292-4307,4371-4393`). Cursor complete items
   do **not** take this branch; they use the generic pump.

7. **Claude-native's forwarder poll and per-delta POST remain separate bounded
   costs (high for Claude-native).** Its known poll quantum is 0–250 ms and
   its text path posts each delta sequentially
   (`claude_native_forwarder.py:84`, `3962-3995`).

8. **The shared `session_stream` queue can overflow during a burst (medium,
   not steady latency).** Its capacity is 1024 and overflow drops the backlog
   for snapshot reconnect (`runtime/session_stream.py:39-40,62-78`;
   `server/routes/_sessions/helpers.py:7507-7515`).

9. **The generic SDK and Cursor client pump is rAF-batched after first
   content.** The scheduler is `requestAnimationFrame`-backed and first content
   flushes synchronously (`web/src/store/chatStore.ts:4152-4183,4504-4511,
   4736-4744`). Cursor's known client-side subtotal is 0 ms for first content
   or at most one frame for later blocks; at 60 Hz that is 16.7 ms, derived
   rather than measured. React commit time is unmeasured.

### Refuted or qualified scouted facts

- **"No rAF batching" as a global UI fact.** False for `claude-sdk` and
  cursor-native complete items. True only for `message_id` live deltas.
- **"Primarily claude-native" as the render conclusion.** Not supported:
  Cursor-native has the largest known poll quantum and complete-item-only
  mirroring. Actual end-to-end ranking remains unmeasured.
- **#4589 Python hook ~1 s as current text-path evidence.** Partially stale:
  Cursor has no per-output hook, and HEAD's Claude MessageDisplay path is a
  shell appender (`claude_native_bridge.py:1387-1400`).
- **Sidebar WS 4 s as the chat render bottleneck.** The interval is confirmed
  (`common.py:474`), but that channel is not the token path.

### Unconfirmed

- Cursor store write-to-row visibility, POST RTT, server DB append, SSE
  scheduling, and browser React commit time.
- Actual live cursor end-to-end latency and whether it beats Claude-native in
  a particular network/browser environment.
- Production shell-hook startup cost and any incidental contention from the
  concurrent permission scanner.

### Candidate fixes

#### Cursor-native candidates

1. **Reduce or adapt the transcript poll.** Size **S–M**; files
   `omnigent/cursor_native_forwarder.py` plus tests. Risk: more SQLite load,
   store-discovery races, and power use; a too-large backoff worsens first
   output. This directly overlaps **#3000**. It is separate from **#2702**,
   **#4589**, **#4976**, **#5603**, **#5405**, **#4913**, and **#5081**;
   rebase shared route changes after **#5544**.

2. **Use a supported Cursor store notification or incremental output signal.**
   Size **M–L**; files `cursor_native_forwarder.py`, bridge/hook integration,
   and possibly the session event schema/routes plus tests. Risk: Cursor
   schema/API drift, partial-text ordering, deduplication, and lifecycle
   complexity. Direct coordination is needed with **#3000** and **#2702**;
   avoid a per-delta process design related to **#4589**. Any client/store
   changes should coordinate with **#5405**, **#5603**, and **#4913**;
   teardown should follow **#4976** and **#5544**; fork/recreate behavior
   should account for **#5081**.

3. **Batch complete Cursor item posts per poll.** Size **M–L**; files
   `cursor_native_forwarder.py`, session event schema/routes, and tests. Risk:
   delayed first item, new wire failure semantics, and ordering changes; it
   does not remove the 700 ms first-read quantum. This touches the route area
   changed by **#5544**; coordinate client/store implications with **#5405**,
   **#5603**, and **#4913**, and lifecycle with **#4976**. It is otherwise
   orthogonal to **#2702**, **#3000**, **#4589**, and fork/recreate **#5081**.

4. **Back off or replace the terminal `capture-pane` watcher.** Size **L**;
   files `omnigent/inner/terminal.py`, `omnigent/runner/resource_registry.py`,
   and tests. Risk: stale status/activity and terminal lifecycle regressions;
   it reduces CPU, not Cursor text latency. This directly addresses **#2702**,
   while **#3000** is the separate transcript-poll fix. **#4589**, **#4976**,
   **#5405**, **#5603**, **#4913**, **#5081**, and **#5544** are not direct
   conflicts unless shared lifecycle or UI files are changed.

The Cursor path should not receive the Claude-native rAF fix: its complete
items already use the generic frame scheduler. Recommended first render
change is the small poll reduction/backoff experiment, followed by a live
cursor measurement before attempting a new incremental wire contract.

---

## Problem 3 — CLI sessions sometimes not killed

### Confirmed causes (ranked)

1. **`sys_session_close` is a tombstone, not a stop (high).**
   PATCH title + `omnigent.closed` (`tool_dispatch.py:4934-5005`). No
   harness teardown.

2. **SSE/tab disconnect does not stop the harness (high).**
   `helpers.py:7498-7524` — break stream, drop presence, no kill.

3. **Claude-native stop is incomplete vs other natives (high).**
   `_claude_stop` (`interrupt.py:438-472`): `kill_session(..., timeout_s=1.0)`
   then terminals; **does not** `_cancel_auto_forwarder_task` (uniform stop
   does at `396`). `kill_session` is `tmux kill-session` only
   (`claude_native_bridge.py:3139-3174`); 5s `_run_tmux` timeout; **no
   SIGKILL**. Missing `tmux.json` within 1s → 503, process left.
   `remain-on-exit on` on live tmux servers (census command lines).

4. **Delete stop is best-effort (medium-high).**
   `_best_effort_stop` (`orchestration.py:573-632`); offline runner skips
   runner cleanup (`routes_events.py:1977-1990`).

5. **`kill_tree` may skip descendant walk (medium).**
   Successful `_killpg` returns immediately (`_proc.py:227-228`). `_killpg`
   refuses shared pgid (`130-159`). SDK executor does not call
   `spawn_kwargs()`.

### Refuted / qualified

- **Machine currently full of orphans.** Census
  `loop/evidence/iter1/rc-kill/CENSUS.md`: **zero dead-parent orphans**.
  Four live Omnigent CLI trees under `omni host` 1270936. Not killed.
- **Native claude lacks its own pgid.** Census: `pid==pgid==sid` for
  live `claude`. The pgid bug is the **SDK/shared-group** case.

### Unconfirmed

- Whether `claude-agent-sdk` SubprocessCLITransport sets
  `start_new_session` (no `spawn_kwargs` in executor).
- Live reproduction of a close-without-stop leftover (would require
  stopping a user session — forbidden).
- Mid-spawn cancel leaving a half-started CLI.

### Candidate fixes

| Fix | Size | Files | Risk | Upstream |
|---|---|---|---|---|
| Close/disconnect → same stop as UI Stop | M | `tool_dispatch.py`, SSE helpers, runner stop | must not kill sibling sessions | **#4976** (prefer merge/rebase, don't fork the design); #5544 already merged upstream |
| `_claude_stop` = `_uniform_stop` (cancel forwarder) | S | `interrupt.py` | low | #4976 |
| SIGKILL escalation + wait after tmux kill | S–M | `claude_native_bridge.py`, `_proc.py` | killing wrong pgid | #4976 #4930 |
| Periodic orphan sweep beyond runner boot | M | `_entry.py` / host | false-positive kills | #5544 |

**Do first:** wire close/disconnect to existing stop; make `_claude_stop`
cancel the forwarder; track #4976 instead of a competing teardown.

---

## Problem 4 — Session open hangs ~1 min then self-heals

Evidence: `loop/evidence/iter2/rc-freeze/` (`FINDINGS.md`,
`TRANSPORT.md`, `CONSTANTS.md`, `DB.md`, `LOG-PARSE.json`).

### Confirmed causes (ranked)

1. **Sqlite QueuePool exhausted: 5 + overflow 10, wait 30 s (high).**
   Local AP uses sqlite (`~/.omnigent/chat.db` ~1.65 GiB). Sqlite
   `create_engine` does not set pool kwargs (`db/utils.py:228-238`);
   SQLAlchemy defaults match the live error *exactly* (`size 5
   overflow 10 … timeout 30.00`). Postgres engines get pool 200 /
   timeout 10 (`:268-289`). AnyIO allows 200 `to_thread` workers
   (`server/app.py:1141-1145`). Today's server log: **156** unhandled
   QueuePool errors; paired bursts **30 s apart** (17:08:42→17:09:12,
   20:35:02→20:35:32) — two waits ≈ the user's “about a minute”.
   Stacks include `list_child_sessions`, `_validate_session`,
   `session_updates`, `stream_session`, `get_session`,
   `list_session_items` (`LOG-PARSE.json`). Bind hydrates via
   `getSessionSlim` + items (`chatStore.ts:3045-3052`) and the UI also
   hits `child_sessions` (`useChildSessions.ts:178`).

2. **HTTP/1.1 origin + long-lived SSE/WS (medium-high locally).**
   Uvicorn serves **HTTP/1.1** (`cli.py:4091-4116`; curl `--http2`
   still HTTP/1.1). Cap 3 live SSE on serial
   (`conversationRegistry.ts:74-77`); **switch does not close** SSE
   (`chatStore.ts:1910-1913`). One updates WS per tab + bind's two
   GETs can fill Chrome's ~6/host pool. Over-budget SSE is allowed
   (`chatStore.ts:2324-2347`). Client 45 s stall / 70 s WS watchdog
   can look like a ~1 min thaw. Secondary to (1) in *this* log.

3. **Updates-WS 4 s rescan of ≤500 ids on a huge sqlite file (medium).**
   `common.py:474-480`; `_fetch_watched_items` via `to_thread`
   (`routes_core.py:1051-1084,1297-1305`). Occupies the tiny pool; does
   **not** run sync DB on the event loop.

### Refuted / unconfirmed

- Sync sqlite **on** the asyncio thread in snapshot/updates/`items` —
  refuted (`asyncio.to_thread`).
- `database is locked`, slow-query, EMFILE — **0** hits today.
- SSE reconnect backoff as the 60 s clock — max 5 s
  (`chatStore.ts:1056-1057`).
- Overflow as a 60 s hang — reconnect instant; slow only if snapshot
  then waits on the pool (`session_stream.py:40,296-300`;
  `helpers.py:7507-7511`).
- Holding N real SSE streams then timing `GET /v1/sessions/{real id}` —
  **unreproduced** (would touch production). Fake-id GET 404 in 5.1 ms
  while the pool was idle.

### Candidate fixes

| Fix | Size | Files | Risk | Upstream |
|---|---|---|---|---|
| Give sqlite the same explicit pool as Postgres (or NullPool + short checkout); never default 5/10/30 | S | `omnigent/db/utils.py` | too-large QueuePool vs sqlite writer; prefer modest size + WAL | Low vs #4976/#5603/#5405/#4913/#5081/#5544 |
| Bound/cache updates-WS rescan; don't checkout 15 conns every 4 s | M | `routes_core.py` `_fetch_watched_items`, ticker | stale sidebar | Low–med #5544 if shared session routes |
| Defer SSE open until after snapshot+items; serialize hydrate GETs | S–M | `chatStore.ts` `bindStream` | slower first token | Low; coordinate #5405/#4913 if store changes |
| HTTP/2 (or TLS h2) on local server so 6/host does not apply | M | `cli.py` uvicorn Config / proxy | certs, h2c browser support | Orthogonal to listed PRs |
| Coalesce `child_sessions` on open (dominant stack) | S | `routes_items.py` / `useChildSessions.ts` | stale child rail | Low vs #4976 |

**Do first:** explicit sqlite pool (or NullPool) so session-open GETs
cannot sit 30+30 s. Then hydrate/SSE ordering for HTTP/1.1.

---

## Recommended fix order

1. **Freeze:** sqlite engine pool (stop 30 s checkouts) — matches
   production logs; then HTTP/1.1 hydrate/SSE ordering.
2. **Kill:** close/disconnect → stop; `_claude_stop` forwarder cancel (#4976).
3. **Fork:** oversize preflight + compact-on-fork (after #5603/#5405 awareness).
4. **Render:** reduce the cursor transcript poll; then Claude-native rAF
   batching and forwarder backoff (#3000).

## Out of scope / hygiene

`git status` loop/-only. No `slice(...)` commits (no product slices).
Gate: `trio-shadow.py --mailbox loop --require-commits` expected 0.
