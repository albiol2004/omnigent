VERDICT: SHIP

Independent eval on `/home/alex/omnigent-fixes` (`fork-async-preparing`).
Product range `746ffd3bf..HEAD`. Verdict formed from `git show` + targeted
sed before reading `REPORT.md`. Evidence:
`loop-fork-async/evidence/iter1/eval-e2e/`.

## Passthrough scope (`901c9cf81`)

The "covers everything" test is **count on one snapshot**:
`len(context_items) == len(source_items)` after `_items_through_response`.
That helper returns `items[:last_index_of(response_id)+1]` or `None` if the
id is missing. A prefix is always a head slice of the same list, so equal
length means the cut is the last item. A genuinely truncated prefix cannot
match counts.

| case | why it cannot passthrough |
| --- | --- |
| Truncated / early message | shorter prefix; skip reason `up_to_response_id set` |
| Unknown `up_to_response_id` | `context_items is None` → full-prefix false |
| SDK source | existing `test_sdk_source_external_id_keeps_preflight_guard` still 413; skip reasons still require native target / carry-history |
| Cross-family | `resume_source_native_session` / carry-history stay false; rebuild compact |

Race between `_items_through_response` and clone: both see the listed
snapshot for the predicate; `fork_conversation` then cuts the **current**
rows at `body.up_to_response_id`. Concurrent **appends after** that id are
not in the prefix. Concurrent **rewrites that keep the same length** are
not modeled (item store is append-style). Native JSONL clone for a last-
response passthrough copies the live transcript file; that is the intended
full-session clone, not a truncated-prefix leak.

Eval e2e (a3): early `up_to_response_id` → 201 in **0.461 s** with
`preparing=1`, skip log `up_to_response_id set`, compact 779 → 11 items.
(The first non-last `response_id` in SQLite was the conversation hex; it
was still a truncated head.)

## Async contract (`e3c3671f2`)

- POST 201 in < 1 s on every eval path (a 0.154 s, a2 0.251 s, a3 0.461 s,
  b 0.339 s, c 0.178 s).
- Compaction path stamps `omnigent.fork.preparing=1` + reason, then clears
  both labels once on success; failure sets `failed` + reason (c).
- `OMNIGENT_FORK_ASYNC=0` restored in `test_sync_fork_waits_for_compaction`
  and via autouse in `test_fork_compact.py`.
- Launch refuse: `resolve_host_launch` CONFLICT; native
  `_launch_native_terminal` / launch-config helpers. Throwaway had no host,
  so HTTP runner bind was not re-hit (same gap Lead noted).
- **Restart:** `_finish_async_compaction` is `asyncio.create_task` on
  `app.state`. If the server dies mid-compact, labels stay `preparing=1`,
  launch stays refused, and nothing recovers the job. The session remains
  **deletable**. Named residual, not a SHIP blocker: operator deletes and
  re-forks. No durable queue.

## UI (`c9ba4be78`)

- `ForkSessionDialog` test: dialog unmounts on 201; Cancel stays enabled
  while the POST is in flight.
- Banner + composer lock from labels; failed state shows reason.
  "Retry fork preparation" only invalidates the session query (Lead
  agrees). Copy tells the user to re-clone from source.
- `chatStore.ts` only adds session invalidation on compaction SSE.
  `createRafScheduler` / `LIVE_FLUSH_DEADLINE_MS` from `e06c3d264` is
  intact (`e06c3d264` still an ancestor).

## Scope creep

Root `README.md` documents `OMNIGENT_FORK_ASYNC=0` only. No `web/README.md`
hunk. PLAN listed `test_fork_oversize_guard.py` for passthrough-fix; that
file was not touched (existing SDK/oversize tests still cover negatives).

## Prior commits

Unamended ancestors: `480b6eea9`, `780962a5d`, `ead098caf`, `c48533487`,
`3d26d9ecd`, `77697270b`, `e06c3d264`.

## Eval e2e (re-run, port **18241**, scratch `/tmp/fork-async-eval-iter1`)

Read-only copy of `e34847899b7d47b3ad322948d4ea6002` + JSONL mode 0444
into scratch `_CLAUDE_PROJECTS_DIR`. Key-kind providers stripped.

| case | POST wall | result |
| --- | --- | --- |
| (a) same-agent, no fork point | 0.154 s | 201, no preparing, 779 items, clone 1 470 505 B, `--resume` argv |
| (a2) last `up_to_response_id` | 0.251 s | 201, no preparing, 779 items, no skip log |
| (a3) early `up_to_response_id` | 0.461 s | 201 + preparing, skip `up_to_response_id set`, then 11 items |
| (b) Codex agent-switch | 0.339 s | preparing=1; bg **54.506 s** then labels cleared; 36 395 B |
| (c) no `claude` on PATH | 0.178 s | failed + CLI-missing reason; DELETE 200 |

## Suites

- Acceptance 5 + new tests: **319 passed**
- Trio-compat selector: **5 passed**, 250 deselected
- `npx vitest run` ForkSessionDialog + ChatPage.composer: **184 passed**
- `pre-commit --files` on `746ffd3bf..HEAD` product paths: ruff/pyrefly/web
  hooks pass. `no-hardcoded-models` still flags **already-tracked**
  `loop-fork-real/evidence/**/*.json` (`pass_filenames: false`). Not
  introduced by these four slices.

## Isolation

- `:6767/health` 200 before and after
- Eval e2e: `config_mtime` and `chat_db_mtime` unchanged at
  `1787949839.0583587`; `projects_count` 1969
- No leftover `:18241` / `:181xx` listeners; no eval-started `claude`
- Did not git in `/home/alex/omnigent`, did not touch live `:6767` / `omni host`

## vs REPORT.md

Agrees on cause, shas, operator steps (must rebuild web), retry=refetch,
and in-process compaction task. Lead e2e used `:18117` (below the ≥18200
floor) and omitted (a3); this eval filled both. Lead pytest count 294 vs
this 319 is suite-list width, not a product mismatch. Restart durability
is the same residual both named.

## Operator steps (Acceptance 7)

1. Fast-forward `trio-v0.10.0-fixes` onto `8c7318c50`, `901c9cf81`,
   `e3c3671f2`, `c9ba4be78`.
2. `cd web && npm run build` (web changed).
3. `omni server stop`, then start the live server as usual.
4. Fork the claude-native session from the Web UI on the last response:
   dialog should close immediately; same-family native should not sit in
   preparing.

commit: 8c7318c50fd8c3c3f01aba45e1a69f4bab60fac9
commit: 901c9cf816757cea61469510dc9093ac947f6da5
commit: e3c3671f22c02d6e280cb17f46c70626275a957b
commit: c9ba4be78e5fc2b9c3535b85066224f882f3dba5
