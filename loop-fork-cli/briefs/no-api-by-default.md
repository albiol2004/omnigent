# Builder brief — no-api-by-default

Workspace: `/home/alex/omnigent-fixes` (git WORKTREE, branch
`fork-compact-cli`). Mailbox: `loop-fork-cli/`. Slice id:
`no-api-by-default`. Luna model: `gpt-5.6-luna-max`.

You implement ONLY this slice. Do not git commit, push, stash,
reset, rebase, checkout, or amend. Lead will commit.
Do not edit `omnigent/fork_compact.py` or add
`fork_compact_cli.py` (slice `cli-summary-backend`).
Do not edit GOAL.md / VERDICT.md.

## HARD isolation
Never write `~/.omnigent`. Never git `/home/alex/omnigent`.
Never live `:6767`, `omni host`. Never kill foreign processes.

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
```

## NEVER read these files whole
`routes_core.py`, `helpers.py`, `orchestration.py`, `chat.py`,
`workflow.py`. Routing module is small; read it whole.

## Diagnosed line ranges
- `omnigent/fork_compact_routing.py` whole (~178 lines).
  `ResolvedForkCompactModel` 22-29 requires `connection: dict`.
  `_key_connection` 52-81.
  `_route_candidate` 84-111 maps `fable` → `anthropic/claude-fable-5`.
  `list_fork_compact_candidates` 126-170 skips when `connection is
  None` (`no key`) then may still return later key candidates
  including openai fallback supplied by the caller.
- Tests: `tests/fork_context/test_fork_compact_model.py` whole.

## Probe / product constraint
API-key providers are OFF for fork compaction unless
`OMNIGENT_FORK_COMPACT_ALLOW_API=1`. The anthropic key is invalid;
the openai key must not be used silently. CLI execution is the
other slice; you only change **who is considered callable**.

## Behavior
1. If `OMNIGENT_FORK_COMPACT_ALLOW_API` is not exactly `1`,
   `list_fork_compact_candidates` must not append any
   `ResolvedForkCompactModel` that carries a key-kind
   `connection`. Skip those with
   `skipped (api disabled)` in the chain log.
2. With ALLOW_API=1, keep today's key routing (fable →
   anthropic/claude-fable-5 when key exists, origin URL handling,
   openai-prefixed ids, Codex slug → openai when key exists).
3. When ALLOW_API is unset and every candidate was skipped as
   api-disabled / empty / unsupported, raise ValueError whose
   message includes the chain and makes clear API keys were not
   used. Do not mention a successful openai fallback.
4. `ResolvedForkCompactModel.connection` may stay a dict for the
   ALLOW_API path. Do not invent a CLI runner here.
5. Comments short; no issue numbers; `dict` not `typing.Dict`.

## Tests first
Rewrite `tests/fork_context/test_fork_compact_model.py` for the
new default:
- Keys present, ALLOW_API unset: `resolve_fork_compact_model`
  with pin `fable` raises (or returns nothing callable) — must
  NOT return `anthropic/claude-fable-5` or `openai/...`.
- ALLOW_API=1: existing fable→anthropic+key, origin URL, prefixed
  id, Codex→openai, env override still pass.
- ALLOW_API=1 and fable with only openai key: skip fable, fall
  through to callable spec (today's test).
- No keys, ALLOW_API unset: still no callable API model.

```
cd /home/alex/omnigent-fixes
export PYTHONPATH=/home/alex/omnigent-fixes
export PATH=/home/alex/omnigent/.venv/bin:$PATH
uv run pytest -q tests/fork_context/test_fork_compact_model.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/fork_compact_routing.py \
  tests/fork_context/test_fork_compact_model.py
```

Write outputs under `loop-fork-cli/evidence/iter1/no-api-by-default/`.
If `compact_fork_items` tests in the same file still assume API
`connection` without ALLOW_API, set the env in that one test or
gate with monkeypatch — do not edit `fork_compact.py`.
