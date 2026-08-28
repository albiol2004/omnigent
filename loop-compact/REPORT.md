# REPORT — iter 1 Lead (compact-on-fork)

HEAD product: `22793b2dd` (`slice(fork-compact-ui)`), `1c2a417e3`
(`slice(compact-on-fork)`). Mailbox left uncommitted.

Luna builders: `gpt-5.6-luna-max` (`model_effort: max`).

| Slice | Command | Exit |
|---|---|---|
| compact-on-fork | `trioctl omnigent run builder --prompt-file loop-compact/briefs/compact-on-fork.md --workspace /home/alex/omnigent-fixes --timeout 1800` | 0 (~958s) |
| fork-compact-ui | same, `fork-compact-ui.md` | 0 (~226s) |

Captured: `loop-compact/evidence/iter1/_trioctl/*.stdout`.

Lead reviewed `git diff` per file, published compaction SSE before
compact, and forced `resume_source_native_session=False` when
replacement items exist so the runner cannot clone the fat JSONL.

## slice compact-on-fork — `1c2a417e3`

Changed paths: `omnigent/fork_compact.py` (new),
`omnigent/server/routes/sessions/routes_core.py`,
`omnigent/stores/conversation_store/__init__.py`,
`omnigent/stores/conversation_store/sqlalchemy_store.py`,
`tests/server/routes/test_sessions_fork.py`,
`tests/server/routes/test_fork_oversize_guard.py`,
`tests/server/routes/test_fork_compact.py`,
`tests/fork_context/test_fork_compact_model.py`.

Commands:

```
uv run pytest -q tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_compact.py \
  tests/fork_context/test_fork_compact_model.py \
  tests/runner/test_fork_context_guard.py \
  tests/inner/test_claude_sdk_fork_context_guard.py
# 19 passed, 1 warning (prior slice verification)

uv run pytest -q tests/tools/builtins/test_spawn.py \
  tests/runner/test_runner_dispatch.py \
  tests/server/integration/test_sessions_child_sessions.py \
  -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'
# 5 passed, 250 deselected  (TRIO_COMPAT.txt)

uv run pre-commit run --files <slice writes>
# all applicable hooks passed  (pre-commit.txt)
```

Throwaway evidence (`loop-compact/evidence/iter1/compact-on-fork/THROWAWAY.json`):
uvicorn on `127.0.0.1:17110`, scratch `OMNIGENT_DATA_DIR`/`CONFIG_HOME`,
mock Layer-2 summary only, real layered compaction, synthetic 640×6k-char
session.

- bytes before: **3944621**
- bytes after: **55766**
- fork items: **10** (**1** compaction + **9** retained non-summary items)
- resolved model: **mock-compact-model** (`OMNIGENT_FORK_COMPACT_MODEL`, source `env`)
- compaction item: **`c5eb681d2e75407c963eb2c3831a5ab8`**; summary boundary:
  **`u315`**
- retained tail: **verbatim** (`a315`, then `u316`/`a316` through `u319`/`a319`)
- summary calls: **1**; HTTP 201; source items unchanged; server torn down
  (nothing on 17110).

Evidence dir: `loop-compact/evidence/iter1/compact-on-fork/`.

Repair 1 verification:

```
uv run pytest -q tests/server/routes/test_fork_compact.py \
  tests/server/routes/test_fork_oversize_guard.py
# 8 passed, 1 warning (PYTEST.txt)

uv run pre-commit run --files tests/server/routes/test_fork_compact.py
# all applicable hooks passed (pre-commit.txt)
```

Deviations from GOAL design:
- New `omnigent/fork_compact.py` instead of extending
  `fork_context.py` / editing `_run_compact_locked` in `helpers.py`.
  LLM/client wiring is imported from `omnigent.runtime.workflow`
  privates (`_prepare_messages`, `_get_llm_client`, runner client).
- Optional `replacement_items` on `fork_conversation` (additive;
  default None).
- Compaction SSE: `compact()` still publishes when `conversation_id`
  is set; Lead also publishes `in_progress` on the source before the
  call so mocked compact still signals the UI.
- Compacted forks skip native JSONL resume (not in GOAL text; required
  so the clone does not rehydrate 3.9 MB).

Weaknesses:
- Legacy short-summary and failure tests mock `omnigent.fork_compact.compact`;
  the retained-tail regression and throwaway mock only the Layer-2 summary
  call while running the real compaction path.
- Broad `except Exception` on the compact path maps every failure to
  the original 413.
- No SQL-store-specific replacement_items test (route stub + builder's
  210 store regressions).

Luna model: `gpt-5.6-luna-max`.

## slice fork-compact-ui — `22793b2dd`

Changed paths: `web/src/shell/ForkSessionDialog.tsx`,
`web/src/shell/ForkSessionDialog.test.tsx`. `sessionsApi.ts` unchanged
(`readJsonOrThrow` already keeps 413 text).

Commands:

```
cd web && npx vitest run src/shell/ForkSessionDialog.test.tsx
# 34 passed  (loop-compact/evidence/iter1/fork-compact-ui/vitest.txt)

uv run pre-commit run --files web/src/shell/ForkSessionDialog.tsx \
  web/src/shell/ForkSessionDialog.test.tsx
# prettier + tsc passed; web-oxlint fails on pre-existing
# ForkSessionDialog.tsx:329 and :343 (not the new progress block)
```

Evidence dir: `loop-compact/evidence/iter1/fork-compact-ui/`.

Deviations: progress copy is `Summarizing history…` (no N MB / model)
because the dialog does not have source byte size or pinned model.
No extra SSE subscription; `submitting` covers the blocking POST.
Server still emits compaction events on the source session id.

Weakness: coding and non-coding clones both show the summarizing line
while the POST is in flight, including small forks that skip compact.

Luna model: `gpt-5.6-luna-max`.

## Isolation self-audit

| Check | Baseline | After |
|---|---|---|
| `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6767/health` | 200 | **200** |
| `stat -c %Y /home/alex/omnigent-fixes-data/chat.db` | 1787905289 | **1787905289** |
| leftover throwaway (`:17110`) | n/a | **none** |

Did not touch `~/.omnigent`, `~/.claude/projects`, `:17067`,
`/home/alex/omnigent`, or kill foreign processes (`:6767` python
pid 1270937 left running).
The broad `ss ... | rg '171'` check still reports the unrelated
`kdeconnectd` listener on `*:1716`; no listener on the throwaway
`≥17100` range remains.

## Operator steps (GOAL Acceptance 5)

On the **test instance** (`:17067`, data dir
`/home/alex/omnigent-fixes-data`) — Lead did not restart it:

1. Rebuild web: `cd web && npm run build`.
2. Restart that test server/runner so it loads `1c2a417e3` +
   `22793b2dd`.
3. Fork a large session; expect summarizing progress then a clone
   under the byte cap. Fork a small session; items should match
   today's copy. Optional env: `OMNIGENT_FORK_COMPACT=0` refuse-only,
   `OMNIGENT_FORK_COMPACT_MODEL`, `OMNIGENT_FORK_COMPACT_TARGET_BYTES`.

Live deploy/rollback (same as `loop-fixes/REPORT.md`): deploy into
`/home/alex/omnigent` (or the running checkout), not this worktree;
rebuild web; restart server and runner. Rollback: check out the
previous live ref, rebuild web if needed, restart.
