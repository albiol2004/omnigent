# Scout: rc-render (read-only product tree)

You are a Luna scout. Workspace: /home/alex/omnigent. HEAD product tree
ead098caf (commit 9926c9145). Investigation only.

## Writes (ONLY these)
`loop/evidence/iter1/rc-render/` — FINDINGS.md, CITATIONS.md, TIMING.md,
logs/copies. Pairwise-disjoint from other slices.

NEVER edit product files. NEVER add in-tree instrumentation. If you need
timing hooks, copy the relevant functions into
`loop/evidence/iter1/rc-render/scratch/` and measure those copies.
NEVER kill processes. NEVER touch real sessions.

## How to read code
Do NOT Read whole large files:
- web/src/store/chatStore.ts
- omnigent/claude_native_forwarder.py
- routes_core.py / routes_events.py if huge

Use `sed -n 'a,bp'` and `rg -n`.

Diagnosed ranges (GOAL + Lead grep — verify):
- poll 250 ms: omnigent/claude_native_forwarder.py:84
  (`_DEFAULT_POLL_INTERVAL_S = 0.25`); loops ~864/900/923-928/1025
  (GOAL; confirm with rg). HTTP POST per delta: search POST around
  3962-3995, 4041-4062 — numbers may have drifted; rg `httpx`/`POST`.
- UI store: web/src/store/chatStore.ts GOAL said O(n) per token at
  4292-4327 with no rAF. Lead grep at HEAD shows rAF comments at
  4201-4204, 4510, 4739-4747. Confirm or REFUTE "no rAF batching".
- SSE: omnigent/server/routes/sessions/routes_events.py:1893-1908
  (media_type text/event-stream ~1908)
- session_stream queue maxsize 1024:
  omnigent/runtime/session_stream.py:40 (`_SUBSCRIBER_QUEUE_MAX_EVENTS`),
  subscriber put ~63-79 GOAL — HEAD may use 233; confirm overflow drop.
- sidebar WS 4 s: omnigent/server/routes/_sessions/common.py:474;
  routes_core.py:1213-1240
- Upstream open: #3000 (4 Hz poll), #4589 (fresh python per hook ~1 s),
  #2702 (tmux capture 5 Hz)

Also grep: hook spawn, capture-pane, rAF, requestAnimationFrame,
scheduler, overflow, drop subscriber.

## Required outputs
1. CITATIONS.md: every scouted fact confirmed/refuted/unconfirmed with
   file:line at HEAD + evidence path.
2. TIMING.md: per-stage contribution for claude-native AND claude-sdk:
   hook spawn, 250 ms poll, per-delta POST, session_stream, SSE, store
   update, React render. Direct measurement preferred (copy+time in
   scratch, or parse existing logs). If a stage cannot be measured
   without a live UI, mark unconfirmed and give a lower-bound from
   constants (e.g. poll interval). Identify dominant stage(s).
3. Ranked causes.
4. Candidate fixes: size, files, risk, conflict with #4976 #5603 #5405
   #4913 #5081 #5544 and #3000 #4589 #2702.

Write FINDINGS.md last.
