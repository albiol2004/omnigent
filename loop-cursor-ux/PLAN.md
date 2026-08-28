# PLAN — iter 1: top-level cursor-native live render, order, re-pin

status: complete
iteration: 1
objective: A MAIN cursor-native session streams assistant text past the 15s stale window, commits the user bubble above that live block, and never paints a transcript error card for a model re-pin on view open.

HEAD reconnaissance (grep/sed only; ranges confirmed at c1dc1d9b5):

- Symptom 1: `supports_streaming` False at `omnigent/inner/cursor_native_executor.py:61-63`; inject then `TurnComplete(response=None)` at `:109-117`. Live id minted once at `omnigent/cursor_native_stream.py:163-165` (`cursor-live-<session><epoch>`). Client: `tapLiveDeltas` stale drop at `web/src/store/chatStore.ts:4427-4433`; `isStaleCompletedResponse` `:4495-4501`; `REVIVE_WINDOW_MS = 15_000` `:4489`; `finalizeCurrentActive` stamps `completedAt` `:6085-6095`. Idle post without `response_id` at `omnigent/cursor_native_forwarder.py:1281-1282` (local `_post_external_session_status` `:780-801`; contract at `omnigent/_native_post_delivery.py:189-196`).
- Symptom 2: pending held off blocks `:18`, `:244`. Consume commits by **tail append** `:5652-5662` and FIFO fallback `:5687-5697`. Live preview tail-appended `:4331-4335`. User mirror POST `:804-820`; poll post `:1157-1162`. `LIVE_ITEM_PREFIX` imported `:57` (`live:` in `web/src/lib/blocks.ts:536`). Helper `isLiveBlock` `:4249`.
- Symptom 3: SSE error code from `_surface_model_change_forward_failure` is `model_change_not_applied` (`omnigent/server/routes/_sessions/helpers.py:5109-5166`), not the runner body `cursor_native_model_failed` (`omnigent/runner/app.py:4436-4465`). Both are missing from `FAILURE_CODE_DESCRIPTIONS` (`web/src/components/blocks/StatusBlocks.tsx:61-71`) so `ErrorBanner` `:149` falls through to "Something went wrong". View-open evidence (GET snapshot/agent/terminals/child_sessions/items/stream then `model_change`) matches **bind-time sticky apply** `chatStore.ts:3097-3128` and delayed catalog handoff `:5058-5078` (`silent: true`), not modal Save. Modal re-pin remains a second trap: `ChatPage.tsx:6256-6259` (`rePinAfterRouting || modelChanged`). Picker `/model` `:4911-4921`. Inject mismatch `omnigent/cursor_native_bridge.py:884-892`.

## Iteration 1 slices

### cursor-live-deltas
Keep the stale-completed gate for scheduled-wake deltas. Do **not** drop `cursor-live-*` (LIVE_ITEM_PREFIX) deltas after injection-complete. Prefer binding pane status to a response id; acceptable: exempt those live ids in `tapLiveDeltas` only.

Done: vitest — delta >15s after `completed` on a cursor-native live id is applied; a scheduled-wake delta for a genuinely finished response is still ignored. No change to rAF/`LIVE_FLUSH_DEADLINE_MS` (e06c3d264) or `OMNIGENT_CURSOR_STREAM=0`.

### cursor-live-order
Same file as deltas — **one builder, two commits**, not parallel. When `session.input.consumed` promotes a user block, splice it **before** any trailing live (`LIVE_ITEM_PREFIX`) block instead of `...s.blocks, user`.

Done: vitest — with a live preview present, committed user lands above it; FIFO append without a live tail stays unchanged (prior-turn assistant item).

### cursor-model-repin
(a) Failed model re-pin is not a turn-error transcript block (picker/toast or log only). (b) View-open must not live-forward `/model` when the drafted/applied model is already the session override — fix the bind sticky / delayed handoff path the GET burst actually hit; also keep modal Save from re-pinning when routing is off and the draft equals applied. (c) Add `cursor_native_model_failed` **and** `model_change_not_applied` to `FAILURE_CODE_DESCRIPTIONS` and `describe_failure_code`. (d) Cheap look at `inject_model_command` picker-row mismatch for `cursor-grok-4.6`; fix only if small, else record follow-up.

Done: UI + python tests; genuine `session.status: failed` / executor errors still render.

## Verification standard

Mode: **test-first**.

Evidence:

1. Failing vitest (or python) written first, then the smallest fix, then green.
2. `cd /home/alex/omnigent-cursor/web && npx vitest run src/store/chatStore.test.ts`
3. Slice 3: `npx vitest run src/pages/ChatPage.composer.test.tsx src/components/blocks/StatusBlocks.test.tsx` plus any new store bind tests; `PYTHONPATH=/home/alex/omnigent-cursor uv run pytest -q` on touched python tests.
4. Lead-run real e2e: throwaway instance port ≥ 18300, scratch `OMNIGENT_DATA_DIR` / `OMNIGENT_CONFIG_HOME`, `OMNIGENT_PROCESS_LOG_FILE` unset; top-level cursor-native + real `cursor-agent`; prompt whose answer takes >15s; capture raw SSE; record TTFD, deltas after 15s, block order, view-open error items.
5. Acceptance 5 suites + pre-commit on changed files (`PATH=/home/alex/omnigent/.venv/bin:$PATH`).

## Out of scope

- Live `:6767`, `omni host`, git in `/home/alex/omnigent`, writes under `~/.omnigent` / `~/.claude/projects` / `~/.cursor`.
- Redesign of scheduled-wake stale gate; claude-native/codex streaming; cursor **sub-agent** path; disabling pane stream (`OMNIGENT_CURSOR_STREAM=0` must still work).
- Large `inject_model_command` picker rewrite unless a few-line match fix is obvious.

## Isolation

Throwaway servers port ≥ 18300; tear down; never kill processes we did not start. `cd /home/alex/omnigent-cursor` for every command.

```yaml
slices:
  - id: cursor-live-deltas
    repo: .
    writes: [web/src/store/chatStore.ts, web/src/store/chatStore.test.ts]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["cursor-live delta after 15s stale window is applied; scheduled-wake still ignored"]
  - id: cursor-live-order
    repo: .
    writes: [web/src/store/chatStore.ts, web/src/store/chatStore.test.ts]
    reads: [web/src/store/chatStore.ts]
    gate: false
    status: complete
    iteration: 1
    accepts: ["consumed user block splices before trailing live preview"]
  - id: cursor-model-repin
    repo: .
    writes: [web/src/pages/ChatPage.tsx, web/src/pages/ChatPage.composer.test.tsx, web/src/components/blocks/StatusBlocks.tsx, web/src/components/blocks/StatusBlocks.test.tsx, omnigent/runner/launch_failure.py, tests/runner/test_launch_failure.py, omnigent/server/routes/_sessions/helpers.py, omnigent/server/routes/sessions/routes_core.py, tests/server/integration/test_sessions_endpoints.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["view-open does not live-forward a no-op model re-pin; re-pin failure is not a transcript turn-error; failure codes have honest copy"]
```

Note: `cursor-live-deltas` and `cursor-live-order` share `chatStore.ts` — one Luna builder, two `slice(<id>):` commits. `cursor-model-repin` originally listed `chatStore.ts` for the bind sticky path; if that collides, Lead applies the store sticky skip sequentially after the live-store builder, or the re-pin builder stays in ChatPage/StatusBlocks/helpers/launch_failure and Lead patches sticky apply.
