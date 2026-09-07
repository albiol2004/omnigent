# Cursor-native Elicitation — Transcript-based Surfacing

**Status:** implemented
**Supersedes:** [`cursor-native-tui-mirror-plan.md`](./cursor-native-tui-mirror-plan.md) (pane-scrape design)
**Code:** `omnigent/cursor_native_permissions.py`, the `cursor-permission-request` hook in
`omnigent/server/routes/sessions.py`, runner wiring in
`omnigent/runner/native/orchestration.py`, `web/.../ApprovalCard.tsx`.

## Goal / behavior

Surface an Omnigent **elicitation card whenever the `cursor-agent` TUI gates a tool call or
asks a question**, answerable from the web **or** the embedded TUI. Cursor's own native gate
stays the source of truth — Omnigent never modifies cursor's JS bundle and never suppresses
the TUI prompt. The failure mode is benign: if detection ever breaks, the embedded TUI prompt
still works and the user answers there.

One exception: a session the *caller* launched with `--yolo` / `--force` / `-f` has already
declared it wants no approvals, and a card mirrored to a piloted parent is a stall nobody can
click. Those sessions answer lingering gates in the pane instead — see
[Yolo sessions](#yolo-sessions-run-everything) below.

Two interaction kinds are surfaced (both ride cursor's per-call "pending" mechanism):

1. **Tool-approval gates** — shell commands, file edit/create (`ApplyPatch`), `Delete`, MCP
   tools, etc. Rendered as an approve/reject card; answered with a keystroke.
2. **`AskQuestion`** — cursor's structured multiple-choice tool. Rendered as the existing
   `AskUserQuestion` form; answered by driving the TUI picker.

## Approach: detect in the transcript, deliver via the pane

```
cursor chat store.db (~/.cursor/chats/<md5(cwd)>/<chat-id>/store.db)
   │  pending tool call written as an assistant `tool-call` content part with
   │  providerOptions.cursor.pendingToolCallStartedAtMs and no matching tool-result
   ▼
[runner] supervise_cursor_transcript_elicitations  (tails the SAME store the forwarder mirrors)
   │  read_cursor_pending_tool_calls → settle-debounce → POST /hooks/cursor-permission-request
   ▼
[server] publish response.elicitation_request → PARK   (_publish_and_wait_for_harness_elicitation)
   ▼
[web]    ApprovalCard / AskUserQuestionForm renders → user answers
   ▼
[server] return the verdict to the parked POST
   ▼
[runner] send tmux keystrokes into the pane:
            approval → `y` / `Escape`(+`Enter` to submit the rejection reason)
            question → picker navigation (Down × index, Space, Enter), or type into "Other"
```

If the pending call vanishes from the store while still parked (the user answered in the TUI,
or it executed), the runner POSTs `external_elicitation_resolved` to clear the card.

### Detection signal (the key fact)

Each `toolCallId` is classified by how its `tool-call` part appears in the store:

- **pending** — appears in an object **with** `providerOptions.cursor.pendingToolCallStartedAtMs`
  (cursor is blocking on it),
- **committed** — appears **without** the marker (cursor finalized it to run — auto-approved,
  or approved and now executing),
- **resolved** — has a `tool-result`.

> **active elicitation = pending AND NOT committed AND NOT resolved.**

The committed exclusion is the structural discriminator that removes the auto-approve flash
*without a timing guess*: empirically a call genuinely blocked on the human appears **only**
with the marker until answered (verified — a pending `Delete`: marker-only, zero no-marker
appearances), while an auto-approved/committed call appears without it. The pending call lives
**only inside cursor's binary protobuf checkpoint frames** — not as a plain-JSON `blobs` row —
so the reader (`read_cursor_pending_tool_calls`) byte-scans each blob for embedded JSON objects
rather than `json.loads`-ing the whole row.

### Settle / debounce (small backstop)

With the committed-exclusion above doing the real work, the settle window is just a short
backstop (`_ELICITATION_SETTLE_S` = 0.5s) for the sub-poll race where cursor's marker frame is
observed a tick before its committed frame. It is intentionally short so a genuinely-gated
prompt that resolves quickly — e.g. a cursor **Auto-review retry** — still surfaces a card
rather than being suppressed. (An earlier 1.5s window suppressed exactly such a retry; the
discriminator is what let it shrink safely.)

### Keystroke delivery

The pane is still used to *deliver* the verdict. Two gotchas, both handled in
`_send_cursor_keys`:

- **Send keys one at a time** with a short gap and a longer settle before `Enter` — the cursor
  TUI re-renders between keys and **drops a back-to-back burst** sent in one `tmux send-keys`
  call. (Single-key approvals were unaffected, which is why this only surfaced with the
  multi-key `AskQuestion` picker.)
- **Reject is a two-step.** Cursor's tool-reject doesn't dismiss on the decline key alone — it
  opens a *"Reason for rejection (Enter to submit, Esc to cancel)"* sub-prompt. The approval
  decline path sends the decline key **then `Enter`** to submit an empty reason, so the TUI
  doesn't park at the reason input. (The `AskQuestion` picker's "Esc to skip" dismisses
  cleanly, so the question decline is a single key.)

### Yolo sessions (Run Everything)

A session launched with `--yolo` / `--force` / `-f` (`cursor_launch_args_enable_yolo`) still
occasionally leaves a pending marker behind. Mirroring that as a card stalls a piloted parent
that has no human to click it, so the supervisor answers it in the pane instead — with the
opposite default of the rest of this design, so the accept is deliberately fail-closed:

- **Only while cursor is asking.** `capture_cursor_pane` must show cursor's parenthesised
  accept hint (`→ Run (once) (y)`). A stale marker with no gate rendered gets no keystroke —
  `tmux send-keys y` would type a literal `y` into the composer, which then prepends itself to
  whatever the user types next in the embedded terminal.
- **Bounded, with two independent budgets.** `_YOLO_ACCEPT_MAX_ATTEMPTS` tries, paced by
  `_YOLO_ACCEPT_RETRY_S`, cover a prompt that IS on screen but that the accept key isn't
  clearing (at most one keystroke per poll, since cursor renders one prompt at a time). A
  *separate*, far more generous `_YOLO_ACCEPT_STALE_CEILING_S` wall-clock ceiling (default 60s,
  measured from when the call was first seen pending) covers the other failure mode — no prompt
  ever renders at all, e.g. a stale marker cursor already resolved that store.db hasn't caught
  up to. Keeping these separate matters: without it, a call still queued behind an earlier one
  would burn its "no prompt yet" polls against the small attempts budget and could be surfaced
  before cursor even started showing it.
- **Queue-aware: only the head of the queue spends budget.** Cursor's TUI can only ever be
  showing ONE of a session's pending calls at a time, so when several tool calls go pending
  together, the supervisor sorts them by first-seen time and evaluates *only* the oldest
  (the "head") each pass — every other pending call is skipped for free, with its own budget
  left untouched, until it becomes head in turn (the current head either clears or exhausts to
  a card). This is what fixes a batch of tool calls emitted in one turn racing each other's
  attempts down to zero before cursor ever rendered most of them.
- **A prompt visibly stuck falls back to the card; a stale marker with no prompt does not.**
  A dead pane, a send tmux rejects, or the head's attempts budget exhausting *with a prompt
  visible* — those surface the ordinary ApprovalCard for that one call (a human keystroke really
  is needed and typing isn't landing), and the queue proceeds to the next. But the head's
  stale-ceiling exhausting with **no prompt ever rendered** is a different situation: cursor's
  Run Everything mode already executed the call — its own status line reads `… Run Everything`
  with no accept hint anywhere on screen — and store.db's pending marker just hasn't caught up.
  Nobody is being asked anything there, so surfacing a card would park a piloted parent on a
  phantom. That case is instead resolved locally as auto-allowed/stale: logged at WARN
  (`stale pending marker under yolo; treating as already executed; no card`, including whether
  the pane's `Run Everything` status-line marker was present as corroboration) and marked handled
  in the supervisor's `active` bookkeeping — the same map a parked card uses — so later polls skip
  it outright instead of re-evaluating it every pass. No card was ever parked for it, so there is
  nothing to resolve server-side (contrast `external_elicitation_resolved`, which releases a card
  that *was* parked once the TUI answers it directly). Set
  `OMNIGENT_CURSOR_YOLO_STALE_SURFACES_CARD=1` to restore the pre-existing behaviour (surface the
  card at the stale ceiling) if an operator needs that fail-safe back. Either way, the worst case
  stays today's visible stall for one call, never a keystroke loop or an indefinitely blocked
  queue.
- **`AskQuestion` is excluded** — a question is human input, not a gate `y` can answer, and it
  does not occupy (or wait behind) the accept-budget queue.
- Because a gate answered this way is never seen by a human, the accept logs the tool name and
  an argument preview at INFO: that line is the only record Omnigent approved the call. Whenever
  a card is surfaced instead, the WARN log includes the pane's last ~3 lines (truncated to 200
  chars) so a failure shows the actual prompt wording that didn't clear.
- **Env overrides.** `OMNIGENT_CURSOR_YOLO_ACCEPT_ATTEMPTS` (default 5) and
  `OMNIGENT_CURSOR_YOLO_ACCEPT_RETRY_S` (default 2.0) override `_YOLO_ACCEPT_MAX_ATTEMPTS` /
  `_YOLO_ACCEPT_RETRY_S` for an operator who needs to trade off latency-to-card against
  tolerance for a slow-rendering TUI without a code change. A malformed value is logged and
  ignored in favor of the default. `OMNIGENT_CURSOR_YOLO_STALE_SURFACES_CARD` (any truthy value,
  default off) restores the pre-existing behaviour of surfacing a card when the stale ceiling
  fires instead of dropping the call locally.

The attempt counters are in-memory, so a runner restart re-tries a call that is still pending.

### AskQuestion specifics

- Rendered via the existing web form: the runner stamps the full questions as the **structured
  `ask_user_question` hook field** (uncapped), with an `AskUserQuestion(...)` `content_preview`
  as the ≤1024-char legacy fallback. cursor's `prompt`/`label` are mapped to the web's
  `question`/`label`; each question `id` is preserved.
- Answered by translating the chosen option labels (keyed by question `id`) into picker
  keystrokes; a value matching no option targets the trailing "Other (type to answer)" row.

## Why this replaced the pane-scrape plan

The original plan (`cursor-native-tui-mirror-plan.md`) chose to **scrape the rendered TUI pane**
and answer with keystrokes. Its central justification:

> "The transcript JSONL and the chat `store.db` contain only the user message while an approval
> is pending (the decision lives in memory), so a clean file-tail channel is not available —
> scraping the pane is required."

**That premise was incorrect — and it was an investigation gap, not a cursor-version change.**
Empirically, cursor chat stores from **June 18–19** (the same `2026.06.19` era the plan was
written against) already contain `pendingToolCallStartedAtMs` — the exact signal this design
keys on. The pending decision *is* persisted; it just lives inside the **binary protobuf
checkpoint frames**, which don't decode as a plain-JSON blob. An inspection that reads the
store the way the forwarder does (`_blob_to_item` → `json.loads`, skipping binary blobs as
"Merkle-tree node, not a message") sees only the user message and concludes the decision is
in-memory. Byte-scanning the frames for embedded JSON reveals the pending tool call.

### What the transcript channel wins over pane-scraping

- **No prompt-wording allowlist.** Pane-scraping recognized prompts by verb regex
  (`run|allow|approve|…`), so it silently missed prompts whose accept verb fell outside it —
  e.g. the file-deletion gate *"Delete this file? → Delete (y) / Keep (n)"* (the bug that
  motivated this rewrite). The transcript path captures **every** gated tool kind uniformly.
- **Solves the plan's "tricky part" (dedup).** The plan flagged identity for identical
  consecutive commands as the hard problem and pointed at a "hook-assisted hybrid" to borrow a
  stable `tool_use_id`. The transcript gives us cursor's stable `toolCallId` directly — used as
  the dedup key and to mint the elicitation id — so that edge case disappears.
- **Structured data** (`toolName` + `args`) instead of regex-parsed pane text.

### What we kept from the plan

- Cursor's native gate remains authoritative; no bundle modification; benign failure mode.
- The pane is still the delivery channel for the verdict keystroke.
- The server hook, parking machinery (`_publish_and_wait_for_harness_elicitation`),
  `external_elicitation_resolved`, and the web `ApprovalCard` are reused unchanged (the
  `AskQuestion` form reuses Claude's `AskUserQuestion` renderer).

## Known gaps / follow-ups

- **Duplicate cursor sessions in one cwd.** The forwarder arbitrates a single owner
  (`_chat_claimed_by_other`); the elicitation detector does not, so two same-cwd sessions could
  double-surface. Low likelihood; not yet addressed.
- **Store schema is private and version-sensitive.** Confirmed against cursor-agent 2026.06.24
  (and the marker present back to 2026.06.18). Failure stays benign (TUI gate authoritative).
- **Why a `--yolo` session gates at all is unconfirmed.** cursor documents `--force` as "force
  allow commands unless explicitly denied", so a surviving gate may be one cursor deliberately
  held back (a user deny rule, or a server-side classifier). The auto-accept above answers it
  anyway, which is what the flag asks for; the pane check is what keeps that from becoming a
  blind keystroke.
- **Keystroke delivery assumes the pane still shows the prompt** and the picker's key bindings
  (`Down`/`Space`/`Enter`, highlight resets per question). Verified live; re-check on cursor
  upgrades.
- **Workspace-trust modal** (first-run) is not a tool call, so it isn't surfaced — answerable
  only in the TUI.
