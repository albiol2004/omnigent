VERDICT: SHIP

Independent Evaluator, iteration 1 repair 1. Re-checked `7013a2f85`
(`git show`) plus prior `87482f1f8` / `9beb255aa`. Scratch cases, 77
pytest, Trio-compat, pre-commit, e2e artifacts, isolation — then this
file. Repair closes the post-completion replay gap that blocked SHIP.

## Repair 1 (`7013a2f85`)

Turn-epoch: `reset()` arms `_awaiting_new_turn` and stores
`_completed_region`; idle/completed panes emit nothing. A Working
(or Generating) edge with a new region, or `start_new_turn()` on a
mirrored user store row, calls `_start_new_epoch` and a fresh
`cursor-live-<session>[-N]` id (epoch 0 has no suffix). Last line-start
`🤖` ignores inline prompt emoji. `→` chrome is skipped, not a
cut, so later prose stays in the region.

Scratch (same cases as the prior ITERATE, against this code): all PASS
— no replay after reset (20 idle frames), user-text `🤖` →
`🤖 Hello world` only, two markers → `🤖 New text` with `-1` id,
`→` between paragraphs keeps both prose sides.

## Criterion evidence

### a. Probe timelines — PASS (unchanged)

231 paired JSONL samples with `elapsed_ms` / wall / monotonic. First
pane `🤖` 16300.059 ms; first store assistant 21700.056 ms, complete
rowid 11. Pane-diff still follows.

### b. Pane-diff correctness — PASS

Unit tests: first delta, suffix growth, overlap-scroll, redraw, ANSI,
wrap unwrap, rewind, reset/no-replay, new-epoch id, last marker, tool
chrome. Scratch matches. Remaining residual: a line-start `🤖` that
is the entire user prompt could still win `last`; not seen in e2e.

### c. Hand-off / persistence — PASS

Deltas stay `external_output_text_delta` (SSE only). Complete item
still store `external_conversation_item`. `tapLiveDeltas` /
`live:<messageId>` unchanged (`chatStore.ts` not in the diff). Repair
prevents a second live block after splice. E2E: 0 deltas for 10.009 s
after complete; second prompt used `cursor-live-<id>-1`.

### d. E2E — PASS

Repair rerun artifacts (`NUMBERS.json`, `REPLAY-CHECK.json`,
`DELTAS.txt`, `COMPLETE.txt`, `SSE.jsonl`):

- port 17200, scratch `/tmp/cursor-stream-e2e-kmmrisji`, conv
  `6c1e5743e96e4b639773f8c8065e0e37`
- 17 deltas, `byte_equal: true`, joined/complete lens 4979 (files are
  4980 chars with a trailing newline; in-memory equality holds)
- inject→first delta 57.375 s; complete 60.981 s (stream ~3.6 s).
  First-delta payload is a growing prefix, not a dump — model TTFT,
  not forwarder lag (same judgment as iter 1)
- `complete_event_observed: true`, `post_complete_delta_count: 0`,
  watch 10.009 s
- `second_delta_count: 1`, `second_message_id_is_new: true`, id
  `cursor-live-6c1e5743e96e4b639773f8c8065e0e37-1`
- SSE tail (80 of 98 events): 17 first-turn deltas + 1 second-turn
  delta after `output_item.done`

Initial 17201 run (26 deltas, 4901, 71 s TTFT) remains in NOTES as
the first passing stream; repair rerun supersedes the duplicate check.

### e. Env gate + cadence — PASS

`OMNIGENT_CURSOR_STREAM=0` still skips pane capture. One poll loop;
`_select_poll_interval` / `OMNIGENT_CURSOR_POLL_FAST_S` /
`_IDLE_S` unchanged by the repair.

### f. Prior commits unamended — PASS

Ancestors of HEAD: 480b6eea9, 780962a5d, ead098caf, b47adae25 …
3b045eaeb, b0dc3bfaa, 87482f1f8, 9beb255aa. Repair is a new commit
on top, not an amend.

### Tests / Trio-compat / pre-commit — PASS

```
uv run pytest -q tests/test_cursor_native_forwarder.py \
  tests/test_cursor_native_stream.py
# 77 passed
Trio-compat -k … : 5 passed, 250 deselected
uv run pre-commit run --files omnigent/cursor_native_stream.py \
  omnigent/cursor_native_forwarder.py \
  tests/test_cursor_native_forwarder.py \
  tests/test_cursor_native_stream.py
# Passed
```

No vitest (chatStore untouched).

### Isolation (Acceptance 4) — PASS

| Check | Result |
|---|---|
| `:6767/health` | 200 |
| testdb mtime | 1787905289 = baseline |
| `ss` `:172` | empty |
| cursor-agent outside host 1270936 | none (live tmux children in-tree) |
| `find ~/.cursor -newer GOAL.md` | runtime transcripts/logs/terminals |

Did not touch live host, `:17067` data, `/home/alex/omnigent`, or
`~/.omnigent`. Did not kill foreign processes.

### Acceptance 5

chatStore still unchanged → **no web rebuild**. Restart `:17067`
server + runner to pick up `87482f1f8` + `9beb255aa` + `7013a2f85`.
`OMNIGENT_CURSOR_STREAM=0` remains the behavior rollback.

commit: 87482f1f8
commit: 9beb255aa
commit: 7013a2f85
