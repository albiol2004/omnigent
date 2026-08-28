# REPORT — iter 1 Lead (cursor-native MAIN session UX)

Mailbox `loop-cursor-ux/`. Product HEAD after this pass: `d4935f9c0` on
`cursor-native-ux` (worktree `/home/alex/omnigent-cursor`).

Luna: `gpt-5.6-luna-max` (`trioctl omnigent resolve builder --json`).

`python3 /home/alex/pruebas/agent-trio-template/metrics/trio-shadow.py --mailbox loop-cursor-ux --require-commits` → **exit 0**.

## Reproduction (before the fix)

Confirmed diagnosed line ranges at `c1dc1d9b5` with grep/sed only.

1. **Deltas dropped:** `tapLiveDeltas` (`chatStore.ts:4429`) blacklists any
   `message_id` once `isStaleCompletedResponse` is true (`REVIVE_WINDOW_MS`
   15s). Luna wrote
   `keeps cursor-native live deltas after a stale completed response` first;
   it **failed** until `isCursorLiveMessageId` exempted `cursor-live-*`.
   Control `still ignores stale scheduled-wake live deltas` stayed green.
2. **Order:** existing
   `promotes the oldest pending user message into blocks (FIFO, plain append)`
   documents tail-append after a non-live assistant. The new splice test
   would have failed on that append against a `live:cursor-live-*` trailing
   block.
3. **Error card:** SSE code is `model_change_not_applied`
   (`helpers.py` `_surface_model_change_forward_failure`), not the runner
   body's `cursor_native_model_failed`. Both were missing from
   `FAILURE_CODE_DESCRIPTIONS`, so `ErrorBanner` fell through to
   "Something went wrong". View-open GET burst maps to bind sticky apply
   (`silent: true`); the transcript card came from publishing
   `response.error` after a refused live forward.

## slice cursor-live-deltas — `238a64db4` (+ prettier `3a2ba6225`)

Paths: `web/src/store/chatStore.ts`, `web/src/store/chatStore.test.ts`.

Change: skip the stale-ignore only for `cursor-live-*` message ids. Gate
kept for scheduled-wake ids.

Commands:
```
cd /home/alex/omnigent-cursor/web && npx vitest run src/store/chatStore.test.ts
# 359 passed (after both store slices)
```
Focused before/after: 4 tests including the new pair + FIFO append.

Luna worker `trioctl omnigent run builder --prompt-file loop-cursor-ux/briefs/cursor-live-store.md --workspace /home/alex/omnigent-cursor --timeout 1500` wrote the failing tests; Lead landed the exemption when that worker was still running the suite (~18+ min, no product commit).

Deviation: preferred `post_external_session_status(response_id=…)` not done
(narrow client exemption). rAF/`LIVE_FLUSH_DEADLINE_MS` untouched.

## slice cursor-live-order — `39efcb7d5`

Paths: same store files.

Change: `insertCommittedUserBeforeLiveTail` on all three
`session.input.consumed` promote/append paths.

Command: same vitest file; new test
`splices the committed user block before a trailing live preview`.

## slice cursor-model-repin — `9eb910285` (+ prettier `d4935f9c0`)

Luna (`gpt-5.6-luna-max`, trioctl ~353s, exit 0) implemented; **did not
commit** (Lead committed). Captured stdout in the dispatch terminal.

Paths:
- `omnigent/server/routes/_sessions/helpers.py` — log refused native model
  forward; do **not** `_publish_error_event`
- `omnigent/runner/launch_failure.py` + `StatusBlocks.tsx` — honest copy for
  `cursor_native_model_failed` and `model_change_not_applied`
- tests: `test_launch_failure.py`, `test_sessions_endpoints.py`
  (`test_patch_model_override_does_not_publish_refused_native_forward_as_error`),
  `StatusBlocks.test.tsx`, `ChatPage.composer.test.tsx` (cursor Save skip)

Commands:
```
npx vitest run src/pages/ChatPage.composer.test.tsx src/components/blocks/StatusBlocks.test.tsx
# 192 passed (Luna); Lead later 551 passed across 3 files with store tests
PYTHONPATH=/home/alex/omnigent-cursor uv run pytest -q \
  tests/runner/test_launch_failure.py \
  tests/server/integration/test_sessions_endpoints.py \
  -k 'model_change or describe_failure or cursor_native_model or refused_native_forward'
# 16 passed
```

(d) `inject_model_command` / `_picker_row_matches_display`
(`cursor_native_bridge.py:884-892`): `cursor-grok-4.6` failing exact picker
row is a **follow-up** (id vs display name). No ≤15-line fix applied.

`ChatPage.tsx` / `routes_core.py` untouched. Sticky apply remains
`silent: true`; the card is gone because the server no longer publishes a
turn-error. Shadow: undeclared `tests/server/integration/test_sessions_endpoints.py`
(now listed in PLAN); declared but unused `ChatPage.tsx`, `routes_core.py`.

## Real e2e (Lead)

`PYTHONPATH=/home/alex/omnigent-cursor uv run python loop-cursor-ux/evidence/iter1/e2e/run_e2e.py`

Throwaway port **18300**, scratch `/tmp/cursor-ux-e2e-40wblwkq`, real
`cursor-agent --force --trust`. Evidence:
`loop-cursor-ux/evidence/iter1/e2e/` (`NUMBERS.json`, `SSE.jsonl`,
`DELTAS.txt`, `COMPLETE.txt`, `server.log`, `CLI.txt`).

| Metric | Value |
|---|---|
| TTFD (inject → first `response.output_text.delta`) | **42.46 s** |
| `delta_count` | 8 |
| `deltas_after_15s` | **8** (all after the stale window) |
| user before assistant in items | **true** |
| `view_open_error_codes` | **[]** |
| `byte_equal` live concat vs complete item | **false** (3193 vs 4047) |

`byte_equal` false: the harness stopped at the first complete assistant
item while pane deltas were still catching up / chrome-stripped. Live
text **did** render after 15s; concatenated bytes are not yet a full
match. Weakness for Evaluator.

Leftover e2e host daemon + tmux/`cursor-agent` for conv
`76b7c74cab464d11a25810ccb336ee46` were **ours**; torn down (pids
244615/245157/245158). No `:183xx` listeners after teardown.

## Acceptance 5

```
cd web && npx vitest run src/store/chatStore.test.ts \
  src/pages/ChatPage.composer.test.tsx src/components/blocks/StatusBlocks.test.tsx
# 551 passed

PYTHONPATH=/home/alex/omnigent-cursor uv run pytest -q \
  tests/test_cursor_native_forwarder.py \
  tests/test_cursor_native_stream.py \
  tests/test_cursor_native_permissions.py
# (included in 143 passed with trio-compat filter mix; dedicated trio-compat:)

uv run pytest -q tests/tools/builtins/test_spawn.py \
  tests/runner/test_runner_dispatch.py \
  tests/server/integration/test_sessions_child_sessions.py \
  -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'
# 5 passed, 250 deselected
```

Ruff on python slice files via `/home/alex/omnigent/.venv/bin/ruff`: pass.
Worktree `.venv` lacks ruff; git commit hooks were unusually fast — Lead
ran prettier via `pre-commit run --files` and committed format follow-ups.

## Isolation audit

| Check | Result |
|---|---|
| `:6767/health` | **200** (not touched) |
| `:183xx` after teardown | **none** |
| git in `/home/alex/omnigent` | **not run** |
| `~/.omnigent` / `~/.claude/projects` / `~/.cursor` | read-only; e2e used scratch `OMNIGENT_DATA_DIR`/`OMNIGENT_CONFIG_HOME`; `OMNIGENT_PROCESS_LOG_FILE` unset |

## Known weaknesses

- Live concat ≠ complete item in this e2e (`byte_equal` false).
- No-op model re-pin may still 503 in runner logs if a **non-silent** PATCH
  fires; it no longer becomes a transcript ErrorBanner.
- `cursor-grok-4.6` picker-row mismatch unfixed.
- Store Luna still running at report time (Lead already committed).

## Operator steps (GOAL Acceptance 7)

1. Fast-forward `trio-v0.10.0-fixes` onto these slice commits (or merge
   `cursor-native-ux`).
2. `cd web && npm run build`
3. `omni server stop` (then start the usual test instance).
4. Open a **top-level** cursor-native session in the chat UI (not tmux-only):
   send a long prompt (e.g. "write 600 words about tmux"). Assistant text
   should stream after ~15s of tool chrome, **below** the user bubble, with
   **no** "Something went wrong" card on merely opening the view.
