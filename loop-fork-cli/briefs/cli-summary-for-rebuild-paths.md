# Builder brief — cli-summary-for-rebuild-paths

Workspace: `/home/alex/omnigent-fixes` (git WORKTREE, branch
`fork-compact-cli`). Mailbox: `loop-fork-cli/`. Slice id:
`cli-summary-for-rebuild-paths`. Luna model: `gpt-5.6-luna-max`.

You implement ONLY this slice. Do not git commit, push, stash,
reset, rebase, checkout, or amend. Lead will commit.
Do not edit routes_core / orchestration / claude_native /
codex_native (slice `native-fork-passthrough`).
Do not edit `omnigent/fork_compact_routing.py`.
Do not edit GOAL.md / VERDICT.md.

## HARD isolation

Never write `~/.omnigent` or `~/.claude/projects`. Never git
`/home/alex/omnigent`. Never live `:6767`, `omni host`. Never kill
foreign processes. CLI runs use a scratch cwd under `/tmp`.
`OMNIGENT_PROCESS_LOG_FILE` unset.

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
```

## NEVER read these files whole

`routes_core.py`, `helpers.py`, `orchestration.py`, `chat.py`,
`workflow.py`. `fork_compact.py` is small (~269 lines) — OK to
read whole.

## Diagnosed line ranges

- `omnigent/fork_compact.py` `_fork_compact_candidate_rows` **51-66**
  includes `openai_fallback` — REMOVE that row from the default
  list. Keep `_compact_with_resolved` **115-189** for ALLOW_API.
  `compact_fork_items` **192-243**: CLI-first path.
- `omnigent/inner/_proc.py:112-127` `spawn_kwargs()`.
- `omnigent/inner/kimi_executor.py:304-336` argv pattern only;
  do not edit.
- `omnigent/chat.py:2110-2193` is Omnigent SDK headless, NOT
  `claude -p`. Do not call it.
- `omnigent/llms/summarize.py:13-30` prompt; `:55-73` builder;
  `:110-136` input; `:139-156` `extract_summary_text`.
- `omnigent/runtime/compaction.py:402-428` Layer 2 call shape.

## Probe facts (must follow; do not redo)

Read `loop-fork-cli/evidence/iter1/probe/FACTS.md`.

Reuse parked WIP:
`loop-fork-cli/evidence/iter1/abandoned/fork_compact_cli.py`
(and the untracked `omnigent/fork_compact_cli.py` if present —
treat it as that parked copy). Adapt; do not invent a new argv.

Working argv (scratch cwd, keys unset):

```
claude -p --model fable --output-format json --safe-mode \
  --strict-mcp-config --mcp-config <{"mcpServers":{}}> \
  --no-session-persistence "<prompt>"
```

stdout is a JSON **array**. Last `type=result`. MUST unset
`ANTHROPIC_API_KEY`, `CLAUDE_API_KEY`, `ANTHROPIC_AUTH_TOKEN`.
NEVER `--bare`. NEVER `--mcp-config '{}'`.

Codex: `codex exec --model <slug> --ephemeral
--skip-git-repo-check --sandbox read-only -o <file> -- "<prompt>"`.
No `-q`. `-p` is `--profile`.

## Behavior

1. `omnigent/fork_compact_cli.py` (<200 lines):
   `resolve_cli_runner`, `run_cli_summary`, tiny
   `responses.create` adapter returning
   `output[].content[].text`. Popen `**spawn_kwargs()`.
   Timeout `OMNIGENT_FORK_COMPACT_CLI_TIMEOUT_S` default 300.
   Missing binary → `FileNotFoundError` whose str contains
   `claude CLI not found` or `codex CLI not found`.
   `on_started` AFTER Popen returns.
2. `compact_fork_items`: for each candidate (env, source pin,
   target spec, source spec — **no openai_fallback**), if it maps
   to a CLI runner and `shutil.which` finds the binary, CLI
   compact. Pass resolved `.model = "claude-cli/<pin>"`.
   Call `on_llm_ready` only after the process started.
   If no CLI works and `OMNIGENT_FORK_COMPACT_ALLOW_API=1`, keep
   today's API `list_fork_compact_candidates` loop.
   Else raise ValueError naming missing CLI / tried chain.
3. Comments short, scenario not PR numbers. `dict` not
   `typing.Dict`. Lines < 88 chars.

## Tests first (fake CLI)

`tests/fork_context/test_fork_compact_cli.py`:

- Fake `claude` on PATH writes argv+cwd+env to a file, prints a
  JSON array ending in
  `{"type":"result","is_error":false,"result":"SUM"}`.
  Assert `-p`, `--model`, `fable`, `--output-format`, `json`,
  `--safe-mode`; cwd under tempfile; `ANTHROPIC_API_KEY` absent;
  summary parsed.
- Timeout / non-zero / missing binary → error with CLI name.
- `compact_fork_items` with pin `fable` uses fake CLI and sets
  compaction model `claude-cli/fable`.

If `test_fork_compact_model.py` breaks because openai_fallback
was removed, adjust only the fallback assert(s) in that file.

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
uv run pytest -q tests/fork_context/test_fork_compact_cli.py \
  tests/fork_context/test_fork_compact_model.py \
  tests/llms/test_summarize.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/fork_compact.py omnigent/fork_compact_cli.py \
  tests/fork_context/test_fork_compact_cli.py \
  tests/fork_context/test_fork_compact_model.py
```

Write outputs under
`loop-fork-cli/evidence/iter1/cli-summary-for-rebuild-paths/`.
Print a compressed summary of files changed and test results.
