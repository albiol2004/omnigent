# PLAN — diagnose missed passthrough, then async fork preparing (iter 1)

status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, omnigent/server/routes/_host_launch.py, omnigent/runner/native/orchestration.py, omnigent/stores/conversation_store/__init__.py, omnigent/stores/conversation_store/sqlalchemy_store.py, web/src/shell/ForkSessionDialog.tsx, web/src/shell/ForkPreparingBanner.tsx, web/src/pages/ChatPage.tsx, web/src/store/chatStore.ts, tests/server/routes/test_fork_passthrough_skip.py, tests/server/routes/test_fork_oversize_guard.py, tests/server/routes/test_fork_async_preparing.py, web/src/shell/ForkSessionDialog.test.tsx, README.md]

## Objective

Same-family native forks that the Web UI submits (always with
`up_to_response_id`, including the last response) must passthrough
instead of compacting. Every other fork returns 201 immediately with
background compaction and a per-session preparing state — never a
modal that freezes the app.

## Probe decision (do not redo)

Cause: `fork passthrough skipped: up_to_response_id set`.
Full POST without that field: 201 in 134 ms. Web-style POST with the
last response id (covers every item): compact path. See
`loop-fork-async/evidence/iter1/passthrough-why/DECISION.md`.

## Verification standard

mode: test-first

Failing test first, then the smallest implementation, then the
commands below. Real e2e (a)/(b)/(c) is Lead-owned after builders.

`cd /home/alex/omnigent-fixes`
`PYTHONPATH=/home/alex/omnigent-fixes`
`PATH=/home/alex/omnigent/.venv/bin:$PATH` for pre-commit
`--workspace /home/alex/omnigent-fixes` on every `trioctl` run

Evidence: `loop-fork-async/evidence/iter1/<slice>/`

## Slices

### passthrough-why

status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, tests/server/routes/test_fork_passthrough_skip.py]

Done: structured INFO skip log; DECISION.md names `up_to_response_id set`.

### passthrough-fix

status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, tests/server/routes/test_fork_passthrough_skip.py, tests/server/routes/test_fork_oversize_guard.py]

Done: last-response / full-prefix native clone passthroughs; truncated
prefix, SDK, and cross-family still compact. Never widen passthrough.
Commit `901c9cf81`.

### async-fork-preparing-server

status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, omnigent/server/routes/_host_launch.py, omnigent/runner/native/orchestration.py, omnigent/stores/conversation_store/__init__.py, omnigent/stores/conversation_store/sqlalchemy_store.py, tests/server/routes/test_fork_async_preparing.py, tests/server/routes/test_fork_compact.py, tests/server/routes/test_sessions_fork.py, README.md]

Done: POST /fork 201 in < 1 s when compaction is needed; labels
`omnigent.fork.preparing=1` then clear; failure → `failed` + reason;
launch refused while preparing; `OMNIGENT_FORK_ASYNC=0` restores sync.
Commit `e3c3671f2`.

### async-fork-preparing-ui

status: complete
writes: [web/src/shell/ForkSessionDialog.tsx, web/src/shell/ForkSessionDialog.test.tsx, web/src/shell/ForkPreparingBanner.tsx, web/src/pages/ChatPage.tsx, web/src/pages/ChatPage.composer.test.tsx, web/src/store/chatStore.ts]

Done: dialog unmounts on 201; in-session preparing + disabled composer;
failure + retry refetch; no covering modal while preparing.
Commit `c9ba4be78`.

## Out of scope

Widening passthrough to cross-family, SDK, or truncated-prefix forks.
Live `:6767`, `omni host`, git in `/home/alex/omnigent`. Writes under
`~/.omnigent` or `~/.claude/projects`. Killing processes this loop did
not start. GOAL.md / VERDICT.md. Pi-native-only changes.

```yaml
slices:
  - id: passthrough-why
    repo: .
    writes: [omnigent/server/routes/sessions/routes_core.py, tests/server/routes/test_fork_passthrough_skip.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["skip-reason INFO log; DECISION.md names the reproduced condition"]
  - id: passthrough-fix
    repo: .
    writes: [omnigent/server/routes/sessions/routes_core.py, tests/server/routes/test_fork_passthrough_skip.py, tests/server/routes/test_fork_oversize_guard.py]
    reads: [loop-fork-async/evidence/iter1/passthrough-why/DECISION.md]
    gate: false
    status: complete
    iteration: 1
    accepts: ["last-response native clone passthroughs; truncated/SDK/cross-family still compact"]
  - id: async-fork-preparing-server
    repo: .
    writes: [omnigent/server/routes/sessions/routes_core.py, omnigent/server/routes/_host_launch.py, omnigent/runner/native/orchestration.py, omnigent/stores/conversation_store/__init__.py, omnigent/stores/conversation_store/sqlalchemy_store.py, tests/server/routes/test_fork_async_preparing.py, tests/server/routes/test_fork_compact.py, tests/server/routes/test_sessions_fork.py, README.md]
    reads: [omnigent/server/routes/_sessions/helpers.py]
    gate: false
    status: complete
    iteration: 1
    accepts: ["201 <1s with preparing labels; launch refused while preparing; OMNIGENT_FORK_ASYNC=0 sync"]
  - id: async-fork-preparing-ui
    repo: .
    writes: [web/src/shell/ForkSessionDialog.tsx, web/src/shell/ForkSessionDialog.test.tsx, web/src/shell/ForkPreparingBanner.tsx, web/src/pages/ChatPage.tsx, web/src/pages/ChatPage.composer.test.tsx, web/src/store/chatStore.ts]
    reads: [web/src/shell/ForkDialogContext.tsx]
    gate: false
    status: complete
    iteration: 1
    accepts: ["dialog closes on 201; preparing badge; composer disabled; no app-wide modal"]
```
