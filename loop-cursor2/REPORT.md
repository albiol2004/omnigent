# REPORT — loop-cursor2 iteration 1 (Lead)

luna_model: gpt-5.6-luna-max
iteration: 1
HEAD after slices: 9b83f39fb
browser: **not used** (Omnigent `browser_*` tools target the live desktop
pane / :6767). Render assertions: vitest `buildBubbles` +
`mergePendingBubbles`, plus throwaway tmux `capture-pane` of a pane **this
loop started**.

## Isolation audit

- `:6767/health` → 200 throughout; no writes to live server or
  `/home/alex/omnigent` git.
- Scratch e2e: `OMNIGENT_DATA_DIR` / `OMNIGENT_CONFIG_HOME` under
  `/tmp/omnigent-cursor2-e2e-*`; `OMNIGENT_PROCESS_LOG_FILE` unset.
- Throwaway server bound `127.0.0.1:18500` (pid started by
  `run_e2e.py`); torn down in `finally`. After teardown: no `:185xx`
  listeners.
- Leftover e2e tmux `omnigent-terminal-xzycgs7_` (and earlier
  `6cud82kz`) **started by this loop** were `kill-server`'d after pane
  capture.
- User panes on :6767 (`52d47c71…`, grok-medium session) were not typed
  into, started, or killed.
- `~/.omnigent` / `~/.claude/projects` / `~/.cursor`: log **copies**
  only for mirror-gap.

## Slice 1 — live-delta-lifecycle

- **Paths:** `web/src/store/chatStore.ts`,
  `web/src/store/chatStore.test.ts`
- **Commit:** `c24bed93f` `slice(live-delta-lifecycle): …`
- **Builder:** `trioctl omnigent run builder` (`gpt-5.6-luna-max`);
  log `loop-cursor2/evidence/iter1/builders/slice-1-2.log`
- **Fix:** exempt `cursor-live-*` from `finalizedLiveMessageIds`; splice
  user at **first** live-provisional block; on `response_end` **promote**
  leftover `live:` itemIds to `promoted:` (Lead follow-up so turn 2 cannot
  concatenate onto turn 1).
- **Tests:** `npx vitest run src/pages/ChatPage.cursorRender.test.ts
  src/pages/ChatPage.test.ts src/lib/renderItems.test.ts
  src/store/chatStore.test.ts` → **675 passed**. Builder reported 533
  on a slightly smaller set before the promote tweak.
- **Before/after:** second-turn deltas for a reused `cursor-live-*` id
  were dropped (blacklist). After: they apply; after promote, a new
  `live:` block is created instead of appending onto the frozen text.
- **Weakness:** claude-native unreplaced previews are now promoted
  rather than deleted (tests updated). Spinner-on-idle risk is reduced
  by dropping the `live:` prefix.

## Slice 2 — pending-bubble-order

- **Paths:** `web/src/pages/ChatPage.tsx`,
  `web/src/pages/ChatPage.test.ts`,
  `web/src/pages/ChatPage.cursorRender.test.ts` (new)
- **Commit:** `788c247fa`
- **Fix:** `mergePendingBubbles` also walks back over
  `isLivePreviewBubble` (assistant items whose text `itemId`s are all
  `live:`). Completed assistant bubbles are not jumped.
- **Before/after:** pending user sat **below** the streaming preview.
  After: pending user is **above** a live-only trailing assistant
  bubble (`buildBubbles` then `mergePendingBubbles`).

## Slice 3 — render-cache-check

- **Paths:** `web/src/lib/renderItems.test.ts` only
  (`renderItems.ts` unchanged)
- **Commit:** `479252e0d`
- **Finding:** `loop-cursor2/evidence/iter1/builders/slice-3-finding.md`
  — mid-array splice **PASS** without a renderer change; prefix
  reference equality already forces a rebuild.
- **Builder log:** `slice-3.log` stayed empty (stdio buffer); test is
  in the commit.

## Slice 4 — picker-row-match

- **Paths:** `omnigent/cursor_native_bridge.py`,
  `tests/test_cursor_native_bridge.py`
- **Commit:** `40d61eb9f`
- **Commands:** `uv run pytest -q tests/test_cursor_native_bridge.py`
  → 21 passed (with slice 5, 44 when combined with
  `test_cursor_native.py` + failed-event tests).
- **Before/after:** first `→` was the composer (`Add a follow-up`);
  every switch 503'd. After: highlight is the `→` **below**
  `Models matching`; sibling effort prefixes rejected; fixtures include
  composer `→`.
- **Weakness:** runner still calls `inject_model_command(...,
  timeout_s=1.0)` for tmux settle; picker loop has its own budget.

## Slice 5 — picker-model-list

- **Paths:** `omnigent/cursor_native.py`, `tests/test_cursor_native.py`
- **Commit:** `bdc0fdb3a`
- **Commands:** `uv run pytest -q tests/test_cursor_native.py` → 21
  passed.
- **Before/after:** dotted rewrite invented ids; `claude-4-sonnet`
  dropped; effort variants collapsed. After: printed CLI id + display
  name per row, grok variants distinct.

## Slice 6 — mirror-gap

- **Decision:** `loop-cursor2/evidence/iter1/mirror-gap/DECISION.md`
- **Scout:** `gpt-5.6-luna-max` ask mode (`slice-6.log`); Lead wrote
  DECISION.md (scout could not write).
- **Cause 7:** 42 POSTs all **202**. 33 were
  `external_output_text_delta` (no persist). 2 browser `message`s.
  **0** `external_conversation_item`. Forwarder **paused** because
  `store.db` was already mirrored by session `6511d339…` (shared cwd).
- **H6:** **CONFIRMED** (separate): incomplete `response.failed`
  500'd ASGI. **Commit:** `9b83f39fb` fills `id` / `model` /
  `created_at`. Test:
  `uv run pytest -q tests/runner/test_response_failed_payload.py` passed.
- **Not fixed here:** shared-store ownership / transfer.

## Real two-turn e2e (throwaway)

- Script: `loop-cursor2/evidence/iter1/e2e/run_e2e.py`
- Port **18500**, conv `07bf622576fb47fcbfece3b3073de9da`
- Raw SSE: `evidence/iter1/e2e/sse.raw` (18535 bytes)
- **18** `response.output_text.delta`, **2** `response.completed`
- Markers **ALPHAONE** and **BETATWO** both present in SSE (turn 2 on
  the **same** stream). Live message id stayed
  `cursor-live-07bf622576fb47fcbfece3b3073de9da` (epoch did not
  advance — no mirrored user rows; `pending_inputs` still queued).
  Cause 4 exemption is why turn-2 text was not dropped.
- Pane (this loop's tmux, then destroyed): user BETATWO prompt **above**
  `BETATWO. I am ready.` Footer still `GPT-5.6 Luna`.
- **No real browser.** Vitest render tests (slice 1–2) are the
  `buildBubbles` + `mergePendingBubbles` proof; SSE was inspected for
  markers/ids, not pumped through vitest in this pass.

### Model picker e2e (same throwaway)

- `GET /v1/sessions/{id}/cursor-model-options` on the **server** →
  `{"detail":"Not Found"}` (runner-only route; not proxied). Catalog
  arrived as `session.model_options` SSE without a models payload in
  the parsed stub.
- `PATCH` bogus id → **HTTP 200**, `model_override` stored
  (`definitely-not-a-cursor-model-zzz`) — **not** an honest 4xx/503.
- `PATCH cursor-grok-4.6-medium` → **HTTP 200**, override stored; pane
  footer still **GPT-5.6 Luna**; `session.model` SSE
  `model: gpt-5.6-luna`.
- Unit tests for causes 8–10 are green; **live inject was not proven**
  on this throwaway (wrong HTTP surface + PATCH does not wait on TUI
  inject). Follow-up: proxy `cursor-model-options`, fail PATCH when
  inject 503s, capture-pane after a successful runner-side
  `model_change`.

## Acceptance 6 suites

- Vitest focused: 675 passed (4 files).
- `tests/test_cursor_native_bridge.py` + `test_cursor_native.py` +
  failed-event: 44 passed.
- `test_cursor_native_forwarder.py` + `stream` + `permissions`: 138
  passed.
- Trio-compat `-k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'`:
  **5 passed**.
- `trio-shadow.py --mailbox loop-cursor2 --require-commits` → **exit 0**.
- Worktree `.venv` lacks `ruff`/`pyrefly`; hooks were run via
  `/home/alex/omnigent/.venv/bin` for the later commits. First
  live-delta commit was fast (hook env may have skipped ruff).

## Known weaknesses

1. Live picker e2e did not switch the pane or fail bogus ids honestly.
2. Real cursor-native still may not persist user/assistant items when
   the store is owned by another session (cause 7 follow-up).
3. Pane-diff deltas can rewrite the whole viewport into one live id;
   promote + exemption stop **drops**, not messy pane snapshots.
4. Slice 3 builder log empty; finding recorded by Lead.

## Operator steps (Acceptance 8)

1. Fast-forward `trio-v0.10.0-fixes` onto this branch (or cherry-pick
   the six `slice(*):` commits).
2. `cd web && npm run build`
3. `omni server stop` then start the usual server so it serves the new
   bundle.
4. Open a **top-level cursor-native** session, send **two** prompts on
   the same chat, confirm the user line stays above streaming text and
   the second answer still appears.
5. Use the web model picker with a **fully-qualified** id (e.g.
   `cursor-grok-4.6-medium`) and confirm the tmux footer matches that
   variant; try a bogus id and expect a visible error (if PATCH still
   200s, that remaining gap is still open).
