# Builder brief — cursor-model-repin

You are GPT-5.6 Luna (`gpt-5.6-luna-max`, effort max). Workspace: `/home/alex/omnigent-cursor`. `cd /home/alex/omnigent-cursor` for every command. Tests: `PYTHONPATH=/home/alex/omnigent-cursor`. Pre-commit: `PATH=/home/alex/omnigent/.venv/bin:$PATH`. No amend/rebase/push/stash/reset/checkout. Never touch `/home/alex/omnigent`, :6767, `omni host`, `~/.omnigent`, `~/.claude/projects`, `~/.cursor`. Never kill foreign processes. No full-file reads of `ChatPage.tsx` / `chatStore.ts` / `runner/app.py` — `grep -n` / `sed -n`. Do not edit GOAL.md/VERDICT.md.

**Conflict:** another builder owns `web/src/store/chatStore.ts` for live-delta/order. Prefer fixing view-open **without** editing `chatStore.ts` if possible. If you must skip a no-op sticky PATCH, wait — if git says the file is dirty/changed by the other worker, **stop and report**; Lead will apply the store skip. Safe exclusive writes: ChatPage, StatusBlocks, launch_failure, helpers.py, tests.

## Isolation
Unit tests only unless you need a tiny python test. No live server. If you start a process, port ≥ 18300, scratch dirs, tear down.

## Diagnosed ranges

- Runner 503: `omnigent/runner/app.py:4436-4465` → `inject_model_command` `omnigent/cursor_native_bridge.py:884-892`.
- Transcript card: `_surface_model_change_forward_failure` `omnigent/server/routes/_sessions/helpers.py:5109-5166` publishes `model_change_not_applied` (THIS is the SSE `error.code`; runner JSON `cursor_native_model_failed` is only in the 503 body). `ErrorBanner` `web/src/components/blocks/StatusBlocks.tsx:61-71`, `:149`.
- View-open (live log: GETs then `model_change`): bind sticky `chatStore.ts:3097-3128` and delayed `:5058-5078` (`silent: true` should skip `live_forward` in `omnigent/server/routes/sessions/routes_core.py:2035-2054`). If a silent PATCH still forwards, that is a server bug — fix `live_forward`. Also skip applying sticky when `session.modelOverride` already equals the sticky (no PATCH).
- Modal trap: `ChatPage.tsx:6256-6259` `rePinAfterRouting || modelChanged`. Existing test `ChatPage.composer.test.tsx` "skips unchanged knobs on Save" (~1992) must stay green. Keep "re-pins when turning Smart Routing off" (~2010).
- `/model` slash: `ChatPage.tsx:4911-4921` — do not break explicit model changes.
- Twin table: `omnigent/runner/launch_failure.py:183-194`; tests `tests/runner/test_launch_failure.py:113-127`.

## Test-first

1. StatusBlocks: `cursor_native_model_failed` and `model_change_not_applied` headlines are honest (not "Something went wrong").
2. Composer: Save with routing off + draft === applied still does not `setModel` (already exists; add cursor `modelPickerKind: "cursor"` variant if missing).
3. Python: `describe_failure_code` includes both new codes. Integration around `test_sessions_endpoints.py` model_change_not_applied (~6457): a failed re-pin must **not** persist/publish a turn-error item **or** the web must not treat it as a transcript ErrorBanner — pick server-side: stop `_publish_error_event` for model re-pin (session-config, not a turn). Explicit user `/model` failure may still need a **non-transcript** indication; do not leave users with a silent failed switch — toast/log/picker error is OK; transcript ErrorBlock is not.
4. (d) Read `inject_model_command` / `_picker_row_matches_display` with sed. If `cursor-grok-4.6` fails because the picker row is a display name vs id mismatch and a ≤15-line fix is obvious, do it with a unit test. Else record "follow-up" in your return text; do not rewrite the picker.

## No-regression
claude-native/codex model inject still forwards on **explicit** setModel. Genuine turn failures still render ErrorBanner. Cursor sub-agents have no picker — unchanged.

## Commands
```
cd /home/alex/omnigent-cursor/web && npx vitest run src/pages/ChatPage.composer.test.tsx src/components/blocks/StatusBlocks.test.tsx
cd /home/alex/omnigent-cursor && PYTHONPATH=/home/alex/omnigent-cursor uv run pytest -q tests/runner/test_launch_failure.py tests/server/integration/test_sessions_endpoints.py -k 'model_change or describe_failure or cursor_native_model'
```

## Commit
```
slice(cursor-model-repin): stop treating cursor model re-pin as a turn error

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

Do not commit mailbox files.
