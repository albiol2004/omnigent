# Builder brief — compact-model-routing

Workspace: `/home/alex/omnigent-fixes` (git WORKTREE, branch
`fork-compact-real`). Mailbox: `loop-fork-real/`. Slice id:
`compact-model-routing`. Luna model: `gpt-5.6-luna-max`.

You implement ONLY this slice. Do not `git commit`, `git push`,
`git stash`, `git reset`, `git rebase`, `git checkout`, or amend.
Lead will commit. Do not edit `routes_core.py` (slice 2).

## HARD isolation
Never write `~/.omnigent`. Copy config/rows out only. Never
`~/.claude/projects`, live `:6767`, `omni host`, or git in
`/home/alex/omnigent`. Never kill processes you did not start.
Throwaway ports ≥ 17700 only, torn down.

The live tree's venv is editable to `/home/alex/omnigent`. **Every
python/pytest must see the worktree first:**

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
```

`PATH=.venv/bin:$PATH` is equivalent if `.venv` is that interpreter.

## NEVER read these files whole
`routes_core.py`, `helpers.py`, `orchestration.py`,
`claude_native.py`, `workflow.py` (>1 MB / huge). Use sed ranges.

## Diagnosed line ranges
- `omnigent/fork_compact.py` — SMALL, read whole.
  `resolve_fork_compact_model` 49-65 (string pick only; no alias
  map). `_llm_config_for_model` 80-85. `compact_fork_items` 88-171:
  logs `model=fable` then `_route_bare_model_for_compaction` then
  `compact(..., conversation_id=source_id)`.
- `omnigent/runtime/workflow.py:2758-2788` `_route_bare_model_for_compaction`
  (`sed -n '2758,2788p'`) — does not handle `fable`.
- `omnigent/llms/routing.py:51-75` `parse_model_string` — bare id
  → OpenAI.
- `omnigent/claude_model_vocabulary.py:37-45` `CLAUDE_MODEL_ALIASES`
  / `ALIAS_MODEL_ENV_VARS`.
- `omnigent/model_fallbacks.py:20-34` `_CLAUDE_SUBSCRIPTION_MODELS`
  and `_CODEX_MODELS`.
- `omnigent/onboarding/provider_config.py:936` `load_providers`;
  `1125` `get_default_provider`; `1155` `first_available_provider`;
  `ProviderEntry.family()` 354-376 for `api_key`.
- Tests: `tests/fork_context/test_fork_compact_model.py` (whole).

## Reproduced exception (ground truth)
`loop-fork-real/evidence/iter1/repro/ROOT_CAUSE.md`.
`fable` + no spec connection → POST OpenAI `/v1/responses` →
`httpx.HTTPStatusError` 401 Missing bearer. With OpenAI key:
400 `The requested model 'fable' does not exist.`

## Behavior
1. Candidates in order: env `OMNIGENT_FORK_COMPACT_MODEL`, source
   pin, target spec, source spec.
2. For each candidate, try to produce a **callable**
   `provider/model` + connection dict:
   - If `/` already in the id, keep it (still need a key for that
     provider).
   - If alias in `CLAUDE_MODEL_ALIASES`, map to
     `anthropic/<first matching _CLAUDE_SUBSCRIPTION_MODELS id>`
     when a **key-kind** anthropic family has `api_key`.
   - If candidate is in `_CODEX_MODELS` (or a known Codex CLI
     alias), map to `openai/<slug>` when openai key-kind exists.
   - Bare `claude-*` → `anthropic/...` as today, with anthropic key.
   - Skip candidates that would still route to OpenAI as a CLI alias.
3. First callable wins. Log INFO the full skipped/tried chain and
   `provider/model`. If none: raise a clear
   `ValueError`/`OmnigentError` (no LLM call).
4. Put `api_key` (and `base_url` if set) on `LLMConfig.connection`.
   Do not use subscription CLI login as the generic client auth.
5. `compact(..., conversation_id=None)`. Add optional
   `on_llm_ready: Callable[[ResolvedForkCompactModel], None] | None = None`
   invoked after resolve, before `compact()`, so slice 2 can publish
   SSE only then.
6. Comments: short, scenario not PR numbers. No `typing.Dict`.

## Tests first
Extend `tests/fork_context/test_fork_compact_model.py`. Mock
`load_global_config` / `load_providers` (do not read live
`~/.omnigent` in tests). Cover fable→anthropic+key, fable with no
key falls through, no callable raises, env callable override,
codex alias→openai.

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
uv run pytest -q tests/fork_context/test_fork_compact_model.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/fork_compact.py tests/fork_context/test_fork_compact_model.py
```

Write outputs under `loop-fork-real/evidence/iter1/compact-model-routing/`.
If you add a tiny helper module, include it in `pre-commit --files`.
