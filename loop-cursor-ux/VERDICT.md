VERDICT: SHIP

Independent Evaluator, iteration 1. Verdict formed from `git show` of
`238a64db4` / `39efcb7d5` / `9eb910285` (plus prettier `3a2ba6225` /
`d4935f9c0`), vitest/pytest, and a re-run e2e **before** reading REPORT.md.

## Adversarial: `byte_equal: false` (Lead 3193 vs 4047)

**Benign for the final transcript. Not permanent content loss. Not a
duplicated/interleaved handoff.**

Lead `SSE.jsonl` (conv `76b7c74…`): `response.completed` at t+1.57s (injection
idle), then **eight** `response.output_text.delta` on stable id
`cursor-live-76b7c74…` at t+43.4–44.6s (all after 15s), then
`session.input.consumed`, then `response.output_item.done` assistant
**4047** chars. Deltas are pane fragments: concatenating them yields 3193
chars with gaps (`🤖 Tmux is` + jump to `and organized.`). Walking each
delta as a substring of the completed item still reaches index 4047.

Store path (ranges from `git show` / targeted reads, not full-file ingest):

1. `tapLiveDeltas` applies those deltas because
   `isCursorLiveMessageId` skips the stale blacklist (`chatStore.ts:4452`).
2. `applyLiveDelta` **appends** fragments into one `live:<messageId>`
   `text_done` (`:4340-4366`). That preview is gappy/overlapping chrome,
   not the persisted essay.
3. `session.input.consumed` splices the user block before trailing live
   (`insertCommittedUserBeforeLiveTail`).
4. Native `text_done` with a real item id **removes** the live preview
   (`:4798-4815`) then appends the committed item. `isNativeWrapper`
   includes `cursor-native-ui`.

**What the user sees at rest:** `[user_message][assistant 4047 chars]`.
No live block remains; no second copy of the essay. During the last ~1s
of streaming they may see the gappy preview; it is superseded ~10ms after
`consumed`.

Evaluator re-run (`loop-cursor-ux/evidence/iter1/eval-e2e/`, port **18400**,
`uv run python`, wait 3s after `output_item.done`): TTFD **5.35s**, **111**
deltas (**62** after 15s), injection-complete **0.59s**, joined 11877 vs
complete **4834** (append of overlapping pane snapshots), `last_delta` is
inside complete, `user_before_assistant` true, `view_open_error_codes` [].
Same handoff order: consumed then assistant `output_item.done`.

GOAL “concatenated live text matches persisted item” is the wrong metric
for pane diffs. The authoritative `external_conversation_item` / 
`response.output_item.done` is what remains on screen.

Lead REPORT blamed an early harness stop. That is **wrong** for iter1
Lead SSE: every delta is **before** `output_item.done`. `run_e2e.py` is
otherwise sound (scratch dirs, stream capture, order, view-open GETs).
Must be launched with `uv run python` (system `python3` has no
sqlalchemy). Evaluator copy starts at port 18400 and does not stop at
the first assistant item.

## Slice 1 — stale exemption

Narrow: `isStaleCompletedResponse` itself unchanged; only
`tapLiveDeltas` adds `&& !isCursorLiveMessageId(ev.messageId)`.
Scheduled-wake test `still ignores stale scheduled-wake live deltas`
uses `wake-msg-1` (not `cursor-live-*`) and expects no preview — suite
already has it; no extra vitest written.

`ignored.add` runs only on that stale non-cursor branch, so a
`cursor-live-*` id is never blackholed for the rest of the turn. Claude
/ other native ids still blacklist. `LIVE_FLUSH_DEADLINE_MS = 100` and
`createRafScheduler` intact. `OMNIGENT_CURSOR_STREAM` still
`!= "0"` in `cursor_native_forwarder.py` (file not in this diff).

## Slice 2 — consume splice

Helper walks **only the trailing live run**. Both diagnosed sites plus
the third `eventContent` append (`git show 39efcb7d5`) use it.

- No live tail: `at = length` → same as FIFO append (existing test).
- Multiple trailing live blocks: user lands before the whole trailing
  live run.
- Live from a *previous* turn that is **not** trailing (completed
  content after it): user still appends after that completed content.
- Live from a previous turn that **is** trailing (uncleared preview):
  user splices before it — same as current-turn live; pre-existing
  preview leak, not a jump over older completed items.

Vitest covers the single trailing live case only; the helper’s while
loop is enough for the other shapes.

## Slice 3 — model re-pin

`_surface_model_change_forward_failure` logs and does **not** publish
`response.error`. Integration test asserts no `response.error` and no
persisted `error` item; PATCH still stores `model_override`. Genuine
executor/`session.status` failed paths were not removed.

`FAILURE_CODE_DESCRIPTIONS` and `_FAILURE_CODE_DESCRIPTIONS` both add
the same two strings for `cursor_native_model_failed` and
`model_change_not_applied`.

`ChatPage.tsx` / bind sticky **unchanged**. Delayed handoff already
skips PATCH when `alreadyApplied`. Composer Save skip extended to the
cursor picker; **picker** `setModel` on an explicit choice is untouched,
so a user pick still re-pins. `inject_model_command` picker-row mismatch
for `cursor-grok-4.6` is recorded follow-up (agrees with REPORT).

## No regressions / prior SHAs

Product diff vs `c1dc1d9b5` is the nine listed files only. No
forwarder/executor/sub-agent edits. Ancestors intact: `a15b8c3e9`,
`480b6eea9`, `780962a5d`, `ead098caf`, `e06c3d264`. No amend/rebase.

## Suites

- `npx vitest run` store + composer + StatusBlocks: **551 passed**
- `uv run pytest` cursor forwarder/stream/permissions: **138 passed**
- Trio-compat selector: **5 passed**, 250 deselected
- Touched launch_failure + sessions model tests: green
- Web prettier/oxlint/tsc via pre-commit: **passed**
- Worktree `.venv` has **no ruff**; parent venv `ruff check` clean.
  `ruff format --check` would collapse two list-comps in
  `test_sessions_endpoints.py` (style only; not treated as product
  failure). `no-hardcoded-models` is `pass_filenames: false` and flags
  unrelated `loop-fork-real/` evidence.

## Isolation

`:6767/health` **200**. No `:183xx`/`:184xx` listeners after teardown.
Eval server pid 291793 gone; eval tmux socket killed (started by this
pass). Live `:6767` cursor/tmux **not** touched.

Throwaway used scratch `OMNIGENT_DATA_DIR`/`CONFIG_HOME`; process log
unset. Real `cursor-agent` still wrote
`~/.cursor/projects/tmp-cursor-ux-eval-e2e-hyzv01g6-pwd/` (CLI
transcript home). Live `~/.omnigent` logs/db continued from `:6767`,
not the throwaway. `~/.claude/projects` unchanged.

## REPORT.md discrepancies (read after verdict)

- `byte_equal` cause: **not** early stop in Lead SSE.
- Isolation “~/.cursor read-only” is aspirational; `cursor-agent`
  always persists under `~/.cursor/projects/…`.
- Ruff “pass” did not include format on the new sessions test asserts.

Operator steps in REPORT match Acceptance 7 (rebuild web bundle).

## Human check

N/A (not NEEDS_HUMAN). Operator still must `cd web && npm run build`
on the live checkout after fast-forward — agents cannot do that on
`:6767`.

commit: 238a64db4 slice(cursor-live-deltas): keep cursor-live deltas after injection-complete
commit: 39efcb7d5 slice(cursor-live-order): splice consumed user block before live preview
commit: 9eb910285 slice(cursor-model-repin): stop treating cursor model re-pin as a turn error
commit: 3a2ba6225 slice(cursor-live-deltas): prettier on live-delta tests
commit: d4935f9c0 slice(cursor-model-repin): prettier on failure-code headline test
commit: mailbox loop-cursor-ux iteration 1 SHIP (this commit)
