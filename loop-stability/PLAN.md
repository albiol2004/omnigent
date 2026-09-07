# PLAN — iteration 1

status: complete
iteration: 1
mailbox: loop-stability

## Objective

Stop native Codex terminal start from dying on app-server -32600
"already has an active writer", serve Codex model options for the
session that owns the live thread after fork/resume, then fix
compact-on-fork (Claude→Codex), CLI view, and picture attachment.

## Diagnosed mechanism (items 1+2, log-verified)

Azure runner
`loop-stability/evidence/azure-runner-4ada6cb3-codex-start-failure.log`
(session `4ada6cb3…`, thread `01a07b94-6560-7623-af8b-ddfec31fee57`):

`_launch_native_terminal` → `_launch_codex` →
`_auto_create_codex_terminal` (preload at orchestration.py:4161) →
`preload_codex_thread_for_resume` (`codex_native_app_server.py:2674`) →
`CodexAppServerClient.request` (`:552`) raises

`RuntimeError: {'code': -32600, 'message': 'thread … already has an active writer'}`

Retry via `_ensure_native_terminal` hits the same raise. After that,
goal read logs `no bridge state` because `write_bridge_state` sits
*after* preload (`orchestration.py:4166`) so a failed resume leaves
the child unlabeled.

GOAL also records `Codex-native model options skipped … bridge
belongs to <other session>` from `runner/app.py:4086-4093`:
`_codex_native_bridge_state_for_session` refuses when
`state.session_id != conv_id` (fork/resume still pointing at the
parent bridge). Same ownership mismatch.

## Slices

```yaml
slices:
  - id: codex-writer-resume
    repo: .
    writes: [omnigent/codex_native_app_server.py, tests/test_codex_native.py]
    reads: [omnigent/runner/native/orchestration.py]
    gate: true
    status: complete
    iteration: 1
    accepts:
      - "preload treats -32600 active-writer as already-resumed, still closes the client"
      - "other app-server errors still raise"
      - "existing thread/resume param test still passes"
  - id: codex-bridge-owner
    repo: .
    writes: [omnigent/runner/app.py, tests/runner/test_app_sessions_native_events_lifecycle.py]
    reads: [omnigent/codex_native_bridge.py, omnigent/runner/native/orchestration.py]
    gate: true
    status: complete
    iteration: 1
    accepts:
      - "model options / settings / goal paths do not skip a session that inherited a parent bridge id after fork/resume"
      - "a truly foreign session still cannot use another session's bridge"
      - "unit test covers the skip log path and the allowed-owner path"
  - id: compact-on-fork-cross-harness
    repo: .
    writes: [omnigent/fork_compact.py, omnigent/codex_native.py, tests/server/routes/test_fork_compact.py, tests/test_codex_native.py]
    reads: [omnigent/claude_native.py, omnigent/runtime/compaction.py]
    gate: true
    status: complete
    iteration: 1
    accepts:
      - "scout-scoped files + failing-then-passing test or documented manual repro"
      - "Claude→Codex fork compact does not leave a dead Codex thread writer"
  - id: cli-view
    repo: .
    writes: [web/src/hooks/useTerminals.ts, web/src/hooks/useTerminals.test.ts, web/src/shell/AppShell.tsx, web/src/shell/AppShell.test.tsx, web/src/shell/MainTerminalView.tsx, web/src/shell/MainTerminalView.test.tsx]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts:
      - "scout-scoped web CLI/terminal view; web unit test or captured evidence"
  - id: image-attachment
    repo: .
    writes: [omnigent/server/routes/sessions/routes_resources.py, tests/server/routes/test_session_resources.py]
    reads: [omnigent/server/routes/_sessions/helpers.py]
    gate: false
    status: complete
    iteration: 1
    accepts:
      - "scout-scoped server attach path; test or captured evidence"
```

Wave 0 (parallel): scout `compact-on-fork-cross-harness` ∥ scout
`cli-view`+`image-attachment` ∥ builder `codex-writer-resume`.
Wave 1: builder `codex-bridge-owner` after writer lands (reads
orchestration; must not race writer).
Wave 2: builders for 5, then 3, then 4 using scout-filled `writes:`.

### codex-writer-resume — done when

- `preload_codex_thread_for_resume` does not raise on JSON-RPC
  `-32600` whose message contains `already has an active writer`.
- Client still `close()`s in `finally`.
- Unrelated errors (other codes / other messages) still raise.
- Test-first in `tests/test_codex_native.py` using
  `_FakeCodexAppServerClient`.
- Commands:
  `uv run pytest -q tests/test_codex_native.py -k preload_codex`

### codex-bridge-owner — done when

- Child session after fork/resume can read Codex model options
  when labels point at a bridge whose `state.session_id` is the
  parent *and* the child is the legitimate resume/fork target
  (smallest correct rule; do not drop all ownership checks).
- Test through `_codex_native_bridge_state_for_session` /
  `_codex_native_model_options` helpers, not a live Codex login.
- Commands:
  `uv run pytest -q tests/runner/test_app_sessions_native_events_lifecycle.py -k 'model_option or bridge'`

### compact-on-fork-cross-harness / cli-view / image-attachment

Writes filled from scout reports before a builder is dispatched.
If live Codex login is required: deterministic unit test around the
response path plus `loop-stability/evidence/iter1/<slice>/MANUAL.md`.

## Verification standard

mode: test-first for slices `codex-writer-resume`,
`codex-bridge-owner`, `compact-on-fork-cross-harness`;
implement-then-smoke for `cli-view` and `image-attachment`.

Evidence required (GOAL verification floor):

1. Failing-then-passing unit test for -32600 on `thread/resume`
   (no live Codex). Capture pytest output in
   `loop-stability/evidence/iter1/codex-writer-resume/`.
2. Unit test for bridge-owner skip vs allow. Capture pytest in
   `loop-stability/evidence/iter1/codex-bridge-owner/`.
3. Item 5: automated test or MANUAL.md + log under
   `loop-stability/evidence/iter1/compact-on-fork-cross-harness/`.
4. Items 3–4: web/server tests where they exist, else captured
   smoke in `loop-stability/evidence/iter1/<slice>/`.
5. Regression: `uv run pytest -q tests/test_codex_native.py
   tests/runner/test_app_sessions_native_events_lifecycle.py
   tests/runner/test_app_sessions_native_terminals_runtime.py -x`
   (narrowest relevant subset). Web: `cd web && npm test` only if
   slices 3/4 touch `web/`.

## Out of scope

- Upstream sync to omnigent-ai/omnigent v0.11.0 (note in REPORT
  if an item is already fixed there).
- Live Azure runner; live Codex login for unit tests.
- Amending `6ed9800e` or the mailbox init commit.
- Editing the 2.1 MB monolith in the Lead in-context; builders
  only, via diagnosed line ranges.
