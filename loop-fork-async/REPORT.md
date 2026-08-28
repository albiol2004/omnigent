# REPORT — iteration 1 (Lead resume after reboot)

Lead: Cursor Grok 4.6 in this session. Workspace
`/home/alex/omnigent-fixes`, branch `fork-async-preparing`.

## Passthrough cause

The Web UI's only fork entry point is "Fork from here", so it always
sends `up_to_response_id`. The native-clone predicate treated any
non-`None` value as "not a full clone" and compacted. Forking the last
response is still a full prefix. Evidence:
`loop-fork-async/evidence/iter1/passthrough-why/DECISION.md`.

## Slice passthrough-why — complete (`8c7318c50`)

- Paths: `omnigent/server/routes/sessions/routes_core.py`,
  `tests/server/routes/test_fork_passthrough_skip.py`
- Luna: prior builder; not re-run this resume
- Evidence: `loop-fork-async/evidence/iter1/passthrough-why/`
- Deviations: none this pass

## Slice passthrough-fix — complete (`901c9cf81`)

Verified the commit: a full prefix (`len(context_items) ==
len(source_items)`) treats `up_to_response_id` as `None` for the
passthrough predicate only. Truncated prefixes still skip.
`test_fork_oversize_guard.py` was listed in PLAN writes but the
commit only touched the skip tests + `routes_core.py` (existing
oversize tests still cover the negatives).
- Luna: `loop-fork-async/evidence/iter1/passthrough-fix/trioctl.out`
  (`gpt-5.6-luna-max` via `trioctl omnigent run builder`)
- Commands: `PYTHONPATH=/home/alex/omnigent-fixes uv run pytest -q
  tests/server/routes/test_fork_passthrough_skip.py` (green in that
  builder's output, 21 passed with sibling suites)

## Slice async-fork-preparing-server — complete (`e3c3671f2`)

Reviewed the reboot-orphaned hunks and kept them after checks.

- Paths: `routes_core.py` (compaction branch only), `_host_launch.py`
  (launch refuse; PLAN had `hosts.py`), `orchestration.py` (native
  launch refuse), conversation store `replace_items` + preparing
  label keys, `test_fork_async_preparing.py`, fake-store helpers in
  `test_sessions_fork.py`, autouse `OMNIGENT_FORK_ASYNC=0` in
  `test_fork_compact.py`, root `README.md` (`OMNIGENT_FORK_ASYNC=0`)
- Contract: compaction required + env not `0` → copy items, stamp
  `omnigent.fork.preparing=1` + reason, 201, `asyncio.create_task`
  owned on `app.state._fork_compaction_tasks`, then
  `replace_items` + clear labels or `failed` + reason
- Commands:
  `PYTHONPATH=/home/alex/omnigent-fixes uv run pytest -q
  tests/server/routes/test_fork_async_preparing.py
  tests/server/routes/test_fork_compact.py
  tests/server/routes/test_fork_passthrough_skip.py
  tests/server/routes/test_sessions_fork.py
  tests/server/routes/test_fork_oversize_guard.py`
  → **49 passed**
- Luna: killed mid-flight before reboot; Lead finished in-session
  (no new `trioctl` builder this resume)
- Discarded: none of the server hunks; they matched the contract

## Slice async-fork-preparing-ui — complete (`c9ba4be78`)

- Paths: `ForkSessionDialog.tsx` (close+navigate on 201, Cancel
  stays enabled), `ForkPreparingBanner.tsx`, `ChatPage.tsx`
  (banner + composer lock), `chatStore.ts` (invalidate session on
  compaction SSE), tests
- Discarded: `web/README.md` UX prose (no new env var). Kept root
  `README.md` because it documents `OMNIGENT_FORK_ASYNC=0`.
- Commands: `cd web && npx vitest run
  src/shell/ForkSessionDialog.test.tsx
  src/pages/ChatPage.composer.test.tsx` → **184 passed**
- Luna: same as server (orphaned builder); Lead finished in-session
- Weakness: failure "Retry" only refetches the session; there is no
  compact-retry endpoint

## Real e2e (throwaway `:18117`, scratch `/tmp/fork-async-e2e-iter1`)

Script: `loop-fork-async/evidence/iter1/e2e/run_e2e.py`
Results: `loop-fork-async/evidence/iter1/e2e/E2E.json`

Read-only copy of conversation `e34847899b7d47b3ad322948d4ea6002`
(767 items) + jsonl into scratch `_CLAUDE_PROJECTS_DIR`. Key-kind
providers stripped from a 0o400 config copy.

| case | POST wall | 201 labels | background | notes |
| --- | --- | --- | --- | --- |
| (a) same-agent | **0.117 s** | no preparing | n/a | 767 items, no compaction item, clone **1 419 194 B**, `--resume` |
| (a2) Web UI last `up_to_response_id` `resp_claude_f5abd5a2…` | **0.195 s** | no preparing | n/a | 767 items, no skip log |
| (b) agent-switch Codex | **0.369 s** | preparing=1 | **48.688 s** then labels cleared | 10 items, rendered **64 138 B**, compaction present, no API key hits |
| (c) no `claude` on PATH | **0.140 s** | preparing=1 | **0.017 s** → failed | reason names CLI missing; DELETE **200** |

Access log (`server.access.log`): (a) 109.5 ms, (a2) 190.0 ms, (b)
364.4 ms with `fork passthrough skipped: resume_source_native_session
false` (expected for rebuild). (c) skip + compact failure, not stuck
at preparing=1.

Launch refuse while preparing: unit-tested (`resolve_host_launch` →
CONFLICT; `_pi_native_launch_config` RuntimeError). Throwaway had no
live host, so HTTP `POST /hosts/{id}/runners` was not exercised.

## Acceptance 5 suites

- `tests/fork_context` + fork compact/oversize/clone/resume/bridge +
  new async/passthrough tests: **294 passed**
- web vitest (touched): **184 passed**
- Trio-compat `-k 'reasoning_effort or session_create_spawns_child_under_caller
  or registered_native_agent_create_derives_launch_args_from_root_spec'`:
  **5 passed**, 250 deselected
- `pre-commit run --files` on UI slice: passed. On server Python
  files, `no-hardcoded-models` still flags **already-tracked**
  `loop-fork-real/evidence/**/*.json` (pass_filenames: false). Slice
  commits landed; worktree hook runtime is ~100 ms (hooks not
  installed on this worktree). Did not `--no-verify`.
- Commits present with `Co-Authored-By: Claude Fable 5
  <noreply@anthropic.com>`
- Tree clean except mailbox after this REPORT/PLAN/LOG update

## Isolation audit

- `GET :6767/health` → **200** before and after
- `~/.omnigent/config.yaml` and `chat.db` mtimes unchanged
- `~/.claude/projects` file count unchanged (1969)
- No `:18117` / `:180xx` listeners left
- No leftover `omnigent server` / e2e `claude` processes started here
- Did not git in `/home/alex/omnigent`, did not use `omni host`, did
  not kill foreign PIDs
- Transcript clone wrote only under `/tmp/fork-async-e2e-iter1/`

## Deviations

- Lead resume completed leftover slice 3 without a new Luna builder
  after reviewing killed-builder diffs.
- Launch gate lives in `_host_launch.py`, not `hosts.py`.
- (a) `--resume` verified via `_clone_claude_transcript` + constructed
  argv, not a bound fake-cli runner (no throwaway host).
- Retry affordance is refetch, not a server re-compact endpoint.

## Weaknesses

- Preparing UI retry cannot restart a failed compact.
- `asyncio.create_task` dies with the server process (acceptable per
  brief; not durable across restart).
- Compaction SSE plus the banner can both show "summarizing".

## Operator steps (Acceptance 7)

1. Fast-forward `trio-v0.10.0-fixes` onto these slice commits
   (`8c7318c50`, `901c9cf81`, `e3c3671f2`, `c9ba4be78`).
2. `cd web && npm run build` (web changed).
3. `omni server stop` (then start the live server as you usually do).
4. Fork the claude-native session from the Web UI ("Fork from here"
   on the last response). Expect the dialog to close immediately and
   the new session to open. Same-family native should not sit in
   preparing; rebuild/oversize forks should show in-session preparing
   with a disabled composer, not a blocking modal.
