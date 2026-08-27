VERDICT: ITERATE

## Why not SHIP

GOAL now has problem 4 / slice **rc-freeze** (session open hangs ~1 min,
then self-heals). The Lead has not investigated it. There is no
`loop/evidence/iter*/rc-freeze/` artifact, and `loop/REPORT.md` has no
problem-4 section. Acceptance 1 requires a confirmed root cause plus
evidence for **all four** problems. Iteration 2 should address only
rc-freeze.

## Problems 1–3 (pass)

Independent re-check of the cursor-native repair and the iter-1
artifacts. Spot-checks at HEAD (`ead098caf` / `9926c9145`):

- **700 ms SQLite transcript poll:**
  `omnigent/cursor_native_forwarder.py:61`
  `_DEFAULT_POLL_INTERVAL_S = 0.7`; loop sleeps
  `poll_interval_s` at `:1194`.
- **Complete-item-only mirroring:** assistant blob → one
  `item_type="message"` with full `output_text`
  (`:668-682`); one `external_conversation_item` POST
  (`_post_conversation_item` `:760-775`). No
  `external_output_text_delta`.
- **capture-pane benchmark:** `capture-pane-benchmark.txt`
  `plain: mean_ms=1.203` (p95 1.467, max 2.236). Off the
  assistant-text path; 0.2 s watcher is status only.
- **rAF path:** `tapLiveDeltas` only diverts
  `text_delta` + `messageId` (`chatStore.ts` ~4351–4409).
  Cursor complete items use the generic pump; first content
  flushes sync, later blocks `scheduler.schedule` (rAF)
  (`:4504–4511`, `:4736–4744`).
- **"Primarily claude-native"** is gone from FINDINGS/TIMING
  as a conclusion. REPORT qualifies it as **not supported**;
  cursor-native has the largest known ingress quantum.

### Problem 1 — fork
Pass. Ranked causes; `MEASUREMENT.json` / `MEASUREMENT.md`
(~3.85–3.93 MB synthetic); scouted SDK-`_ensure` fact
refuted; fixes with size/files/risk/upstream PRs.

### Problem 2 — render
Pass after repair 1. Cursor-native column in `TIMING.md`;
`CURSOR-NATIVE.md` stage budget; permissions poll 0.3 s
classified as approval-only (`cursor_native_permissions.py:54`).
Live Cursor E2E still unmeasured and correctly listed as
unconfirmed, not mixed into confirmed causes.

### Problem 3 — kill
Pass. Ranked causes; `CENSUS.md` / `PATHS.md` (list-only);
scouted orphan-herd claim refuted (live trees, not
dead-parent zombies); fixes track #4976.

## Do not investigate in this verdict

Problem 4 starting points in GOAL (HTTP/1.1 connection
limits, SSE/WS hold, 4 s updates scan, DB lock, 60 s
timeouts) stay for iteration 2. This Evaluator did not
probe them.

## Human check

None. `verify: human` is not the blocker; rc-freeze
evidence is.
