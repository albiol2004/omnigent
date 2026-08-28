# PLAN — native fork passthrough + CLI summaries (iter 1)

status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, omnigent/claude_native.py, omnigent/codex_native.py, omnigent/fork_context.py, omnigent/fork_compact.py, omnigent/fork_compact_cli.py, omnigent/fork_compact_routing.py, tests/server/routes/test_fork_oversize_guard.py, tests/server/routes/test_fork_compact.py, tests/runner/test_fork_clone_fallback.py, tests/runner/test_fork_context_guard.py, tests/fork_context/test_fork_compact_cli.py, tests/fork_context/test_fork_compact_model.py]

## Objective

A same-host native claude/codex fork must launch as a plain CLI
resume of a cloned transcript: no byte guard, no server-side
summary. Guard + CLI-produced summary stay only for SDK,
cross-family, and rebuild-from-items forks. No API-key providers
unless `OMNIGENT_FORK_COMPACT_ALLOW_API=1`.

## Probe decision (do not redo)

Keep clone + `--resume <clone-id>`. Do not use `--fork-session` on
the source id. See `evidence/iter1/probe/DECISION.md` and
`evidence/iter1/probe/FACTS.md`.

## Verification standard

mode: test-first

Every product change lands behind a failing test, then the
implementation, then the exact commands below. Real e2e is slice 3,
not a substitute for unit tests.

`cd /home/alex/omnigent-fixes`
`PYTHONPATH=/home/alex/omnigent-fixes`
`PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files …`

Evidence: `loop-fork-cli/evidence/iter1/<slice>/`.

## Slices

### native-fork-passthrough

status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, omnigent/claude_native.py, omnigent/codex_native.py, omnigent/fork_context.py, tests/server/routes/test_fork_oversize_guard.py, tests/runner/test_fork_clone_fallback.py, tests/runner/test_fork_context_guard.py]

Done criteria: same-family native clone 201 with no compaction
item; `OMNIGENT_FORK_NATIVE_GUARD=1` restores the raise;
`OMNIGENT_CLAUDE_PROJECTS_DIR` for throwaway project roots.

### cli-summary-for-rebuild-paths

status: complete
writes: [omnigent/fork_compact.py, omnigent/fork_compact_cli.py, omnigent/fork_compact_routing.py, tests/fork_context/test_fork_compact_cli.py, tests/fork_context/test_fork_compact_model.py, tests/server/routes/test_fork_compact.py]

Done criteria: CLI summarizer; prompt on stdin (`-p -`);
ALLOW_API gate; missing CLI names `claude CLI not found`; model
`claude-cli/<pin>`.

### real-e2e

status: complete
writes: []

Done criteria: GOAL e2e (a)/(b)/(c). Evidence in
`loop-fork-cli/evidence/iter1/e2e/` (Lead run, port 17901). A
second harness under `evidence/iter1/real-e2e/` (port 17911) is
supplemental.

## Out of scope

`--fork-session` on the live source id. API-key summaries by
default. Live `:6767`, `omni host`, git in `/home/alex/omnigent`.
Writing `~/.omnigent`. Pi-native changes. GOAL.md / VERDICT.md.

```yaml
slices:
  - id: native-fork-passthrough
    repo: .
    writes: [omnigent/server/routes/sessions/routes_core.py, omnigent/claude_native.py, omnigent/codex_native.py, omnigent/fork_context.py, tests/server/routes/test_fork_oversize_guard.py, tests/runner/test_fork_clone_fallback.py, tests/runner/test_fork_context_guard.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["same-family native fork of a >600kB transcript returns 201 with no compaction item and --resume on the clone"]
  - id: cli-summary-for-rebuild-paths
    repo: .
    writes: [omnigent/fork_compact.py, omnigent/fork_compact_cli.py, omnigent/fork_compact_routing.py, tests/fork_context/test_fork_compact_cli.py, tests/fork_context/test_fork_compact_model.py, tests/server/routes/test_fork_compact.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts: ["rebuild-path compaction uses claude -p with keys unset; missing CLI names claude CLI not found; model records claude-cli/<pin>"]
  - id: real-e2e
    repo: .
    writes: []
    reads: [omnigent/server/routes/sessions/routes_core.py, omnigent/fork_compact.py, omnigent/fork_compact_cli.py, omnigent/claude_native.py]
    gate: false
    status: complete
    iteration: 1
    accepts: ["e2e (a) 201 no compaction; (b) CLI summary; (c) 413 claude CLI not found; isolation audit"]
```
