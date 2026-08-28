# REPORT — iter 1 Lead (fork-compact-real)

HEAD product: `5113ebe59`. Mailbox left uncommitted.

Luna builders: `gpt-5.6-luna-max` (`model_effort: max`).

| Slice | Command | Exit |
|---|---|---|
| compact-model-routing | `trioctl omnigent run builder --prompt-file loop-fork-real/briefs/compact-model-routing.md --workspace /home/alex/omnigent-fixes --timeout 1800` | 0 (~452s) |
| honest-failure | same, `honest-failure.md` | 0 (~316s) |
| real-run-e2e | Lead throwaway server `:17701` + real Anthropic/OpenAI keys from a read-only config copy | 201 then keys-off 413 |

Captured: `loop-fork-real/evidence/iter1/_trioctl/*.stdout`.

## Reproduced root cause

`loop-fork-real/evidence/iter1/repro/`. Pin `fable` is not prefixed.
`parse_model_string("fable")` → OpenAI. Production-like
`connection=None`: `httpx.HTTPStatusError` 401 Missing bearer on
`https://api.openai.com/v1/responses` (~297 ms). With the OpenAI key:
400 `The requested model 'fable' does not exist.` Live 36 ms is this
reject on a warm socket, not a missing import.

## slice compact-model-routing — `e32f147da` + `9d249f209` + `f946532a4`

Changed paths: `omnigent/fork_compact.py`,
`omnigent/fork_compact_routing.py`, `omnigent/model_fallbacks.py`,
`tests/fork_context/test_fork_compact_model.py`.

`fable` → `anthropic/claude-fable-5` with the anthropic key-kind
connection. Origin `https://api.anthropic.com` (no `/v1`) is not
forwarded. `runner_client=None` (server-side). `conversation_id=None`
into `compact()`. `on_llm_ready` before the LLM call. If Anthropic
401s, retry `openai/gpt-4o-mini` from the fork_compact static fallback.

```
PYTHONPATH=/home/alex/omnigent-fixes python -m pytest -q \
  tests/fork_context/test_fork_compact_model.py
# 9 passed
```

Luna model: `gpt-5.6-luna-max`.

## slice honest-failure — `0cc255174`

Changed paths: `omnigent/server/routes/sessions/routes_core.py`
(fork compact try ~2370-2416 only), `tests/server/routes/test_fork_compact.py`.

413 body keeps the oversize text and appends
`; compaction failed: <reason>`. WARNING + traceback. SSE in_progress
only from `on_llm_ready`.

```
python -m pytest -q tests/server/routes/test_fork_compact.py \
  tests/server/routes/test_fork_oversize_guard.py
# included in 42 passed below
```

Luna model: `gpt-5.6-luna-max`.

## slice real-run-e2e — `5113ebe59` (payload sanitize) + Lead run

Throwaway `127.0.0.1:17701`, scratch
`/tmp/fork-compact-real-e2e`, copied conversation
`e34847899b7d47b3ad322948d4ea6002` (576 items) plus its agent/files
rows (needed to load the spec). Unset `OMNIGENT_PROCESS_LOG_FILE` so
logs stay under the scratch data dir.

Success (`evidence/iter1/e2e/E2E.json`, `success.server.log`):

| Field | Value |
|---|---|
| HTTP | **201** in 10474 ms |
| Pin | `fable` |
| Tried | `anthropic/claude-fable-5` → 401 (config anthropic key rejected) |
| Used | **`openai/gpt-4o-mini`** (`openai_fallback`) |
| Rendered bytes before | **939189** |
| Rendered bytes after | **16581** |
| Fork items | 13 (compaction + tail) |
| Summary length | 2379 chars |
| Fake `claude --resume` | transcript **16895** bytes (`< 600k`) |
| Fork id | `f8167b6aee254a59b1d2156ea3ef8d8c` |

Success log (`success.server.log`): pin `fable` tried as
`anthropic/claude-fable-5`, 401, then `openai/gpt-4o-mini`.

Keys stripped (`FAIL413.json`, `nokeys.server.log`): 413
`compaction failed: No callable model… fable -> anthropic/claude-fable-5 (no key)`;
WARNING + ValueError traceback in `nokeys.server.log`; no in_progress
publish. (An earlier FAIL413 `warning_traceback: false` was a grep of
the wrong log file.)

E2e also showed OpenAI 400 `Unknown parameter: input[].content[].filename`
on the real transcript; fixed in `omnigent/llms/summarize.py`.

## Isolation audit

| Check | Result |
|---|---|
| `http://127.0.0.1:6767/health` | **200** before and after |
| `~/.omnigent/config.yaml` mtime | unchanged |
| `~/.omnigent/chat.db` mtime | unchanged on the successful run |
| leftover `:17701` | **none** (`ss`) |
| First e2e inherited `OMNIGENT_PROCESS_LOG_FILE` and wrote `~/.omnigent/logs/runner/runner-e348…-200216-531672.log`; that file was deleted. Later runs log under scratch `OMNIGENT_DATA_DIR`. |

Did not git `/home/alex/omnigent`, did not touch `~/.claude/projects`,
did not kill `:6767`.

## Acceptance 3 suites

```
python -m pytest -q tests/server/routes/test_fork_compact.py \
  tests/server/routes/test_fork_oversize_guard.py tests/fork_context \
  tests/runner/test_fork_clone_fallback.py \
  tests/runner/test_fork_context_guard.py \
  tests/runner/test_fork_resume_oversize_guard.py \
  tests/llms/test_summarize.py
# 42 passed

python -m pytest -q tests/tools/builtins/test_spawn.py \
  tests/runner/test_runner_dispatch.py \
  tests/server/integration/test_sessions_child_sessions.py \
  -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'
# 5 passed, 250 deselected
```

Tree clean except mailbox. Slice commits present.

## Deviations

- Product commits used the requested prefix
  `slice(fork-compact-real):`. Trio-shadow `--require-commits` matches
  `slice(<slice-id>):`, so three empty marker commits were added
  (`slice(compact-model-routing):`, `slice(honest-failure):`,
  `slice(real-run-e2e):`) pointing at the already-landed SHAs. No
  amend/rebase.
- Copied `agents`, `users`, `session_permissions`, and `files` rows in
  addition to GOAL's conversation tables so fork could load the spec
  and attachments.
- Cleared `runner_id` / `external_session_id` on the copy so the
  throwaway server would not talk to the live runner or
  `~/.claude/projects`.
- Anthropic `kind: key` in this machine's config 401s on
  `api.anthropic.com`; summary used OpenAI `gpt-4o-mini` after that 401.
- `trioctl` workers import via the live editable venv; tests must set
  `PYTHONPATH=/home/alex/omnigent-fixes`.

## Weaknesses

- Attachment `file_id` still logs "unresolved" during render; summary
  proceeds with a filename placeholder.
- Anthropic pin still spends one 401 before the OpenAI fallback.
- Fake `--resume` argv is constructed from the compacted items, not a
  live `claude` binary.

## Operator steps (GOAL Acceptance 5)

On the live checkout (`/home/alex/omnigent`, currently
`trio-v0.10.0-fixes`):

1. Fast-forward to this worktree's product commits (or cherry-pick
   `e32f147da`..`5113ebe59`).
2. `omni server stop` (systemd restarts it).
3. Re-fork session `e34847899b7d47b3ad322948d4ea6002`. Expect a
   summarized fork (201), not a silent 413. If the Anthropic API key
   is still 401, the log should show fallback to `openai/gpt-4o-mini`.
4. Replace `providers.anthropic` with a Messages-API key if you want
   `fable` itself to summarize.
