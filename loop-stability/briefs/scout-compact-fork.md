# Scout brief — compact-on-fork (item 5)

You are Trio Luna scout (`gpt-5.6-luna-max`, ask/read-only).
Workspace: `/home/alex/omnigent`. Mailbox `loop-stability/`.
Iteration 1.

Do NOT edit product files. Do NOT commit. Do NOT read whole large
files; grep + Read with offsets.

## Task

Scope why compact-on-fork fails in some cases, especially forking a
Claude session into Codex. Search `compact` and `fork` in:

- `omnigent/runner/native/`
- `omnigent/server/routes/_sessions/orchestration.py`

Also grep `omnigent/fork_compact.py`,
`omnigent/server/routes/sessions/routes_core.py`,
`tests/server/routes/test_fork_compact.py`,
`tests/fork_context/`.

## Return

You are read-only. Do NOT write files. Print a markdown report with:

1. Exact files + line ranges a builder should touch (writes/reads).
2. Suspected root cause in plain English (Claude→Codex thread /
   bridge / writer / compact model routing).
3. Existing tests that almost cover it.
4. Smallest test-first plan (deterministic, no live Codex if possible).
5. If live Codex is required: MANUAL.md steps.

Keep it under ~120 lines.
