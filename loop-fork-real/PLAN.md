# PLAN — fork-compact-real (iter 1)

## Objective
Make an oversize fork of a real claude-native session succeed with a
server-callable summary LLM, and make every compaction failure honest.
Pinned CLI aliases such as `fable` must never be sent to OpenAI.

## Verification standard
mode: test-first

Plus one real e2e (GOAL verification floor) on a throwaway server
port ≥ 17700. Evidence: `loop-fork-real/evidence/iter1/<slice>/`.
Failing tests first, then implementation, `pre-commit` on writes,
captured command output. Slice 3 records resolved provider/model,
bytes before/after, HTTP status, `--resume`, isolation audit.

## Reproduced root cause (do not re-guess)
`loop-fork-real/evidence/iter1/repro/repro.json` + `tracebacks.txt`.

`resolve_fork_compact_model` returns `fable` (`source_override`).
`_route_bare_model_for_compaction` (`workflow.py:2758-2788`) only
prefixes `databricks-*` and `claude-*`, so `fable` is unchanged.
`parse_model_string` defaults prefix-less ids to OpenAI, so the
generic client POSTs `model=fable` to
`https://api.openai.com/v1/responses`.

With claude-native `connection=None`: `httpx.HTTPStatusError` 401
Missing bearer (~297 ms here; live log 36 ms is the same path on a
warm connection). With the real OpenAI key from a read-only
`config.yaml` copy: 400 `The requested model 'fable' does not exist.`

`routes_core.py:2398-2400` then raises `OmnigentError(str(exc))` from
the original `ForkContextTooLarge`, discarding `compact_exc`. SSE
`in_progress` already fired at `2380`.

## Slices

### compact-model-routing
status: complete
writes: [omnigent/fork_compact.py, omnigent/fork_compact_routing.py, omnigent/model_fallbacks.py, tests/fork_context/test_fork_compact_model.py]

Done criteria:
- Resolve a **server-callable** `provider/model` + `connection`
  (api_key from `config.yaml` key-kind providers, never from
  `~/.omnigent` writes).
- Candidate order: env `OMNIGENT_FORK_COMPACT_MODEL`, source pin,
  target spec, source spec. For each candidate: if it is a native
  CLI alias (`omnigent.claude_model_vocabulary.CLAUDE_MODEL_ALIASES`
  plus Codex slugs in `omnigent.model_fallbacks._CODEX_MODELS`),
  map via a small table to `anthropic/<best claude-*>` when an
  anthropic **key** provider exists, or `openai/<codex slug>` when
  an openai **key** provider exists. Already-prefixed ids stay.
- First **callable** candidate wins. Uncallable pins (alias with no
  matching key, or OpenAI-defaulted bare alias) are skipped, not
  used. If none callable → raise before any summary call.
- INFO log the full chain tried and the final `provider/model`.
- Inject that connection into the LLMConfig used by `compact()`.
- Pass `conversation_id=None` into `compact()` so inner SSE is not
  emitted before the client is ready. Optional `on_llm_ready`
  callback after resolve, before `compact()`.
- Keep `fork_compact.py` focused; extract a tiny helper module if
  the file would exceed ~200 lines.
- Tests for: `fable` → anthropic callable when anthropic key exists;
  `fable` skipped then spec/env used; no callable → error; prefixed
  ids unchanged; Codex alias → openai; env override if callable.

### honest-failure
status: complete
writes: [omnigent/server/routes/sessions/routes_core.py, tests/server/routes/test_fork_compact.py]

Done criteria (edit ONLY `routes_core.py` ~2370-2405 via sed):
- Do not call `_publish_compaction_in_progress` until
  `on_llm_ready` / callable LLM is resolved.
- `except Exception as compact_exc:` log WARNING with traceback,
  including the model/provider that was tried when available.
- 413 body keeps the original oversize text **and** appends
  `; compaction failed: <reason>` from `compact_exc`.
- Publish failed/completed exactly once (failed on this path;
  do not also rely on `compact()` inner events).
- Tests: summary failure 413 includes `compaction failed:`;
  caplog WARNING + traceback; spy shows no `in_progress` when
  resolve raises before ready; `in_progress` once when compact
  is actually invoked.

### real-run-e2e
status: complete
writes: [loop-fork-real/evidence/iter1/e2e/]

Done criteria: GOAL verification floor. Scratch
`OMNIGENT_DATA_DIR` / `OMNIGENT_CONFIG_HOME`, copy
`~/.omnigent/config.yaml` read-only, copy only conversation
`e34847899b7d47b3ad322948d4ea6002` rows from
`~/.omnigent/chat.db` (`?mode=ro`). Throwaway port ≥ 17700,
torn down. POST /fork with pin `fable` → 201, record numbers.
Keys-removed 413 path. Fake-claude `--resume` on < 600 kB
transcript. Fix product code if the run reveals a gap.

## Out of scope
- Live :6767, ~/.omnigent writes, ~/.claude/projects, `omni host`,
  /home/alex/omnigent (no git). Killing foreign processes.
- Full-file reads of routes_core.py, helpers.py, orchestration.py,
  claude_native.py, workflow.py.
- Amending/rebasing/pushing. UI copy. chatStore.ts.

```yaml
slices:
  - id: compact-model-routing
    repo: .
    writes: [omnigent/fork_compact.py, omnigent/fork_compact_routing.py, omnigent/model_fallbacks.py, tests/fork_context/test_fork_compact_model.py]
    reads: [omnigent/claude_model_vocabulary.py, omnigent/model_fallbacks.py, omnigent/onboarding/provider_config.py, omnigent/llms/routing.py, omnigent/runtime/workflow.py]
    status: complete
    iteration: 1
  - id: honest-failure
    repo: .
    writes: [omnigent/server/routes/sessions/routes_core.py, tests/server/routes/test_fork_compact.py]
    reads: [omnigent/fork_compact.py, omnigent/server/routes/_sessions/helpers.py]
    status: complete
    iteration: 1
  - id: real-run-e2e
    repo: .
    writes: [loop-fork-real/evidence/iter1/e2e/, omnigent/llms/summarize.py, tests/llms/test_summarize.py]
    reads: [omnigent/fork_compact.py, omnigent/server/routes/sessions/routes_core.py]
    status: complete
    iteration: 1
```
