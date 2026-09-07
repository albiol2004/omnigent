# REPORT — loop-stability iteration 1 (Lead)

Lead: Cursor Grok 4.6 (`cursor-grok-4.6-medium`).
Luna workers: `gpt-5.6-luna-max` / `max` via
`trioctl omnigent run builder|scout` (no `--allow-fallback`).
Workspace `/home/alex/omnigent`, branch `trio-v0.10.0-fixes`.

## Root causes

### 1. Native Codex terminal fails to start

`preload_codex_thread_for_resume` (`codex_native_app_server.py:2645`)
calls `thread/resume`. On Azure session `4ada6cb3…` the app-server
returned JSON-RPC `-32600` “thread … already has an active writer”.
`CodexAppServerClient.request` raised `RuntimeError(str(error))`.
That abort sits *before* `write_bridge_state` in
`_auto_create_codex_terminal` (`orchestration.py:4161` then `:4166`),
so `_ensure_native_terminal` retries the same preload and still
fails. The thread is already loaded by another writer; resume is
redundant.

Fix: treat only `-32600` + “already has an active writer” as success
in preload; still `close()` the client. Other errors still raise.

### 2. Stale Codex models

`_codex_native_bridge_state_for_session` (`runner/app.py:4086`)
skipped when `state.session_id != conv_id`. After fork/resume
rotation the child label still names the live bridge, but state
lists the parent as owner. Model options then 503 / skip and the UI
keeps an old catalog.

Fix: **read-only** `action == "model options"` returns the labeled
live state even on session mismatch. Mutating actions still skip.

### 3. CLI view

Scout: `useTerminals` treated any terminal (including a user shell)
as “CLI ready”, then `AppShell` / `MainTerminalView` fell back to
`terminals[0]` and hid the Chat/Terminal pill.

Fix: identify the agent pane by resource id; do not substitute a
user shell; keep reconciling until the agent pane exists.

### 4. Picture attachment

Upload stored MIME; download used `mimetypes.guess_type(filename)`
and forced `Content-Disposition: attachment`. Extensionless images
became `application/octet-stream`; `<img>` could not preview.

Fix: prefer stored `content_type`; inline only png/jpeg/gif/webp;
HTML/SVG/text/unknown stay attachment + `nosniff`.
`helpers.py` unchanged.

### 5. Compact-on-fork (Claude→Codex)

Scout: (a) default five-response window protects a short history so
fork compact raises “did not produce a valid summary”; (b) server
`CompactionData` with summary and empty `compacted_messages` made
Codex `replacement_history=[]` (Claude has a synthetic summary
fallback). Cross-family labels already skip the source external
session.

Fix: cap fork `recent_window` to actual response groups; synthesize
Codex replacement messages from the summary string.

Live Codex login was not required; unit tests cover the response
paths. MANUAL for a full Claude→Codex TUI is in the scout report
(`loop-stability/evidence/iter1/scout-compact/REPORT.md`).

Upstream v0.11.0 was not compared (non-goal).

## Tests (Lead-run)

```
uv run pytest -q tests/test_codex_native.py -k 'preload_codex or rollout_records_summary'
# 4 passed

uv run pytest -q tests/server/routes/test_fork_compact.py
# 9 passed

uv run pytest -q tests/server/routes/test_session_resources.py -k 'image or upload or content or png or html or svg'
# 13 passed

uv run pytest -q tests/runner/test_app_sessions_native_events_lifecycle.py \
  -k 'interrupt_on_codex_native or stop_session_on_codex_native or stop_on_codex_native_cancels or interrupt_on_codex_native_with_turn or settings_change_uses_thread or follow_labeled_foreign'
# 10 passed  (Lead re-seeded bridge state after session create so a
# logged-in local Codex auto-create cannot wipe fixtures)

cd web && npm test -- --run src/hooks/useTerminals.test.ts \
  src/shell/MainTerminalView.test.tsx src/shell/AppShell.test.tsx
# 161 passed
```

Full `tests/runner/test_app_sessions_native_terminals_runtime.py`
was not re-run to completion in this pass (narrow subset above).

## Captured trioctl results

| role | model | prompt-file | outcome |
|---|---|---|---|
| builder | gpt-5.6-luna-max | briefs/codex-writer-resume.md | 3 preload tests pass; no commit |
| scout | gpt-5.6-luna-max | briefs/scout-compact-fork.md | compact seams report |
| scout | gpt-5.6-luna-max | briefs/scout-cli-image.md | CLI + MIME report |
| builder | gpt-5.6-luna-max | briefs/codex-bridge-owner.md | 3 model-options tests pass |
| builder | gpt-5.6-luna-max | briefs/compact-on-fork-cross-harness.md | 30 focused pass |
| builder | gpt-5.6-luna-max | briefs/cli-view.md | 59 + 102 vitest pass |
| builder | gpt-5.6-luna-max | briefs/image-attachment.md | 12 focused + 150 resource pass |

Evidence: `loop-stability/evidence/iter1/<slice>/`.

## Weaknesses

- Active-writer is treated as success; if the writer is a *stuck*
  lock, start still proceeds (same as Azure’s desired outcome).
- Model options may list the parent thread’s catalog during
  rotation; mutations stay owner-bound.
- CLI/image: implement-then-smoke; no live browser session in this
  Lead pass (header + vitest coverage instead).
- Async fork-compact failure label vs runner `"1"` check was
  scouted, not changed.
