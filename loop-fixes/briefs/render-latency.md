# Builder: render-latency

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`.
Implement **only** this slice.

## HARD isolation (non-negotiable)
Never read/write `~/.omnigent`, `~/.claude/projects`, `~/.cursor`.
Never talk to `http://127.0.0.1:6767` or kill `omni host`. Never git
in `/home/alex/omnigent`. Work only in `/home/alex/omnigent-fixes`.
No live cursor/claude sessions. Evidence = unit tests + a timing
microbench on constants/backoff, not the user's TUI.

Do not edit GOAL.md/VERDICT.md. Do not touch sqlite-pool,
kill-on-close, or fork files.

## How to read code
`chatStore.ts` is huge — NEVER Read the whole file. `sed -n` only:

- Cursor poll: `omnigent/cursor_native_forwarder.py:58-62`
  `_DEFAULT_POLL_INTERVAL_S = 0.7`; loop sleep
  `:1009-1011`, `:1163-1194` (sed those bands).
- Claude poll: `omnigent/claude_native_forwarder.py:84`
  `_DEFAULT_POLL_INTERVAL_S = 0.25`.
- Per-delta POST: `omnigent/claude_native_forwarder.py:3962-3995`
  `_post_external_output_text_delta`; loop `:4041-4062`
  `_forward_available_deltas` posts one HTTP call per delta.
- UI live path (no rAF): `web/src/store/chatStore.ts:4292-4327`
  `applyLiveDelta`; `:4371-4393` `tapLiveDeltas` calls it
  synchronously.
- Generic rAF pump to copy: `web/src/store/chatStore.ts:4152-4183`
  `createRafScheduler`.
- Baseline: `loop/evidence/iter1/rc-render/TIMING.md`.
- Tests: `tests/test_cursor_native_forwarder.py`,
  `web/src/store/chatStore.test.ts`. Find claude forwarder tests via
  `rg -l claude_native_forwarder tests`.

Do not Read `helpers.py`, `routes_core.py`, `orchestration.py`.

## Task
(a) cursor-native: adaptive poll — ~0.15 s while new output is
arriving, back off to 0.7 s when idle. Env-overridable (e.g.
`OMNIGENT_CURSOR_POLL_FAST_S` / `..._IDLE_S` or one interval +
multiplier). Keep existing post-one-item semantics unless a tiny
local batch is already easy; GOAL asks poll adaptivity first.

(b) claude-native: default poll 0.25 → 0.1 s with the same idle
backoff idea. Batch the per-delta POSTs into **one POST per poll
tick**, preserving order (concatenate deltas or a list payload the
server already accepts — grep `external_output_text_delta` handlers
with `rg -n` in `omnigent/server/routes` **small files only**; if the
API is strictly one delta per event, post sequentially but **without
awaiting each before queueing** is NOT OK — either one batched
event type already in the schema, or concatenate text for the same
`message_id` in-order into one POST per tick). Do not change
persistence semantics.

(c) UI: coalesce `tapLiveDeltas`/`applyLiveDelta` per animation
frame like the generic pump so Claude-native live text does not
setState every chunk.

## Tests / hooks
```
cd /home/alex/omnigent-fixes
uv run pytest -q tests/test_cursor_native_forwarder.py tests/test_claude_native_forwarder.py tests/test_qwen_native_forwarder.py
cd /home/alex/omnigent-fixes/web && npm test -- --run src/store/chatStore.test.ts
cd /home/alex/omnigent-fixes
pre-commit run --files omnigent/cursor_native_forwarder.py omnigent/claude_native_forwarder.py web/src/store/chatStore.ts web/src/store/chatStore.test.ts
```
Include any new test files in pre-commit. If claude forwarder test
module has another name, run that instead. Fix until clean.

## Evidence
`loop-fixes/evidence/iter1/render-latency/`: save pytest/vitest
output and a short note comparing new fast/idle constants vs
`loop/evidence/iter1/rc-render/TIMING.md` (0.7 s / 0.25 s quanta).

## Finish
Do not commit. Print paths and results.
