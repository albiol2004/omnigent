# Builder brief — cli-summary-backend

Workspace: `/home/alex/omnigent-fixes` (git WORKTREE, branch
`fork-compact-cli`). Mailbox: `loop-fork-cli/`. Slice id:
`cli-summary-backend`. Luna model: `gpt-5.6-luna-max`.

You implement ONLY this slice. Do not git commit, push, stash,
reset, rebase, checkout, or amend. Lead will commit.
Do not edit `omnigent/fork_compact_routing.py` (slice
`no-api-by-default`). Do not edit GOAL.md / VERDICT.md.

## HARD isolation
Never write `~/.omnigent`. Never git `/home/alex/omnigent`.
Never live `:6767`, `omni host`. Never kill processes you did not
start. CLI runs use a scratch cwd under `/tmp`, never a user
workspace. `OMNIGENT_PROCESS_LOG_FILE` unset in any server you
start (you should not start a server in this slice).

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
```

## NEVER read these files whole
`routes_core.py`, `helpers.py`, `orchestration.py`, `chat.py`,
`workflow.py`. Use `sed -n` / grep ranges only.

## Diagnosed line ranges
- `omnigent/fork_compact.py` SMALL, whole file OK (~269 lines).
  `_fork_compact_candidate_rows` 51-66 includes `openai_fallback`
  — REMOVE that row from the default list.
  `_compact_with_resolved` 115-189 calls Layer-2 `compact()` via
  generic LLM client. Keep that path for ALLOW_API.
  `compact_fork_items` 192-243: add CLI-first path.
- `omnigent/inner/_proc.py:112-127` `spawn_kwargs()`.
- `omnigent/inner/kimi_executor.py:304-336` argv pattern
  (`--output-format` then `-p` last). Pattern only; do not edit.
- `omnigent/chat.py:2110-2193` is Omnigent SDK headless, NOT
  `claude -p`. Do not call it.
- `omnigent/llms/summarize.py:13-30` prompt; `:55-73` builder;
  `:110-136` input; `:139-156` `extract_summary_text` needs
  `resp.output[].content[].text`.
- `omnigent/runtime/compaction.py:402-428` Layer 2 call shape.
  `:559-184` `compact()` — reuse by injecting a tiny LLM client
  adapter rather than copying Layer 1/2.
- `omnigent/claude_model_vocabulary.py` `CLAUDE_MODEL_ALIASES`.
- `omnigent/model_fallbacks.py` `_CODEX_MODELS`.

## Probe facts (must follow)
Read `loop-fork-cli/evidence/iter1/probe/FACTS.md`.

Measured working argv (scratch cwd, keys unset):

```
claude -p --model fable --output-format json --safe-mode \
  --strict-mcp-config --mcp-config <file with {"mcpServers":{}}> \
  --no-session-persistence "<prompt>"
```

Wall ~2.27s. stdout is a JSON **array**. Last object:
`type=result`, `result` is the text, `is_error` bool.
Init object has `apiKeySource`.

MUST unset in the child env: `ANTHROPIC_API_KEY`,
`CLAUDE_API_KEY`, `ANTHROPIC_AUTH_TOKEN` (inherited invalid key
caused 401 + 183s retries). NEVER `--bare` (blocks OAuth).
NEVER `--mcp-config '{}'`.

Codex: `codex exec --model <slug> --ephemeral --skip-git-repo-check
--sandbox read-only -o <last-message-file> -- "<prompt>"`.
No `-q`. `-p` is `--profile`, not print.

## Behavior
1. Add `omnigent/fork_compact_cli.py` (<200 lines) with:
   - `resolve_cli_runner(candidate) -> (bin, argv_model, record_id)`
     claude-family alias / `claude-*` → `claude`, record
     `claude-cli/<alias>`. Codex slugs → `codex`, `codex-cli/<slug>`.
     Cursor-looking pins: if `cursor-agent` exists, try its `-p`
     print mode; else treat as claude default.
   - `run_cli_summary(prompt, *, runner, model, timeout_s) -> str`
     tempfile cwd + empty mcp json; Popen with `**spawn_kwargs()`;
     timeout env `OMNIGENT_FORK_COMPACT_CLI_TIMEOUT_S` default 300;
     shutil.which miss → `FileNotFoundError` / ValueError whose
     str contains `claude CLI not found` or `codex CLI not found`.
   - Parse result; non-zero, timeout, `is_error`, empty text →
     raise naming CLI + model.
2. Tiny adapter `responses.create` that flattens
   `instructions` + `input` into one prompt (system prompt then
   conversation text then trigger), calls `run_cli_summary`,
   returns an object `extract_summary_text` understands.
3. `compact_fork_items`: for each candidate in order (env, source
   pin, target spec, source spec — **no openai_fallback**), if it
   maps to a CLI runner and `shutil.which` finds the binary, use
   CLI compact (call `on_llm_ready` **after** Popen starts; pass a
   resolved object with `.model = "claude-cli/fable"` etc.).
   If no CLI works and `OMNIGENT_FORK_COMPACT_ALLOW_API=1`, keep
   today's API `list_fork_compact_candidates` loop. If no CLI and
   ALLOW_API unset → raise ValueError naming missing CLI / tried
   chain. Do not HTTP to api.openai.com / api.anthropic.com.
4. Keep `fork_compact.py` focused; CLI details live in the new
   module. Comments: short, scenario not PR numbers. `dict` not
   `typing.Dict`. Lines < 88 chars.

## Tests first (fake CLI)
`tests/fork_context/test_fork_compact_cli.py`:
- Fake `claude` on PATH writes argv+cwd+env to a file, prints a
  JSON array ending in `{"type":"result","is_error":false,"result":"SUM"}`.
  Assert argv contains `-p`, `--model`, `fable`, `--output-format`,
  `json`, `--safe-mode`; cwd is under tempfile; `ANTHROPIC_API_KEY`
  absent in child env; summary parsed.
- Timeout / non-zero / missing binary → error with CLI name.
- `compact_fork_items` with pin `fable` uses fake CLI and sets
  compaction model `claude-cli/fable` (mock `_load_spec` /
  `_prepare_messages` / `compact` as existing tests do, or run
  `run_cli_summary` unit-level plus a compact_fork_items test).

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
uv run pytest -q tests/fork_context/test_fork_compact_cli.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/fork_compact.py omnigent/fork_compact_cli.py \
  tests/fork_context/test_fork_compact_cli.py
```

Write outputs under `loop-fork-cli/evidence/iter1/cli-summary-backend/`.
If pytest of `tests/fork_context/test_fork_compact_model.py` breaks
because you removed openai_fallback, fix only `fork_compact.py`
candidate rows; do not rewrite routing.py — those tests belong to
slice 2 unless a one-line assert on fallback must change; then
adjust the fallback assert only.
