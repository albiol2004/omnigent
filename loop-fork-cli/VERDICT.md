VERDICT: SHIP

Independent Evaluator, iteration 1. Formed before reading REPORT.md.
Evidence: `loop-fork-cli/evidence/iter1/eval-e2e/` (re-run, port 17951)
plus Lead `evidence/iter1/e2e/` (port 17901). Product HEAD `77697270b`.

## Verdict

SHIP. Same-host native clones skip the byte guard and compaction.
Rebuild / cross-family / SDK forks still guard and summarize through
the subscription CLI. API-key providers stay off unless
`OMNIGENT_FORK_COMPACT_ALLOW_API=1`. Prior Trio patches
`480b6eea9` / `780962a5d` / `ead098caf` and every slice through
`94c7921a6` are unamended ancestors.

## a. Passthrough scoping (code)

Skip fires only when **all** of these hold
(`routes_core.py` ~2348–2372, `git show 3d26d9ecd`):

1. `OMNIGENT_FORK_NATIVE_GUARD` is not `1`
2. source `external_session_id` is a nonempty string
3. `resume_source_native_session` — same agent, or agent switch in
   the same provider family, and the target is not cursor
4. `up_to_response_id` is None
5. `carry_history_into_native` (target rebuilds a native transcript)
6. target harness in `{claude-native, codex-native}`
7. source harness in `{claude-native, codex-native}`

Cross-family: (3) is false, so compaction still runs (eval e2e b).
SDK source with a leftover external id: (7) fails
(`test_sdk_source_external_id_keeps_preflight_guard` → 413).
Rebuild-from-items (no external id): (2) fails (Lead e2e b).
`up_to_response_id` truncation still measures. Clone helper defaults
`guard` to `fork_native_guard_enabled()`; tests show `=1` restores
`ForkContextTooLarge`. Plain non-fork resume still calls
`_ensure_local_claude_resume_transcript(..., guard=False)`.

If a same-family skip later fails to find the JSONL, the runner
rebuilds with `guard=True` (413 at launch), not an unguarded SDK
replay. That is the missing-transcript case, not the original
same-host oversize clone.

## b. Real e2e (Evaluator)

Throwaway `127.0.0.1:17951`, scratch `/tmp/fork-cli-eval-iter1`,
`PYTHONPATH=/home/alex/omnigent-fixes`, process log unset, keys
stripped from scratch config, `ANTHROPIC_API_KEY` unset in the
server env. Live `~/.omnigent/chat.db` opened `?mode=ro`. JSONL
copied read-only into scratch `_CLAUDE_PROJECTS_DIR`.

| Path | Result |
|---|---|
| (a) same-family | **201** in 0.096 s, fork `322aa289…`, **661** items, **0** compaction rows; `_auto_create_claude_terminal` with fake launch → `--resume 2de717d4-…` on **1_115_733** B clone; no 413 |
| (b) agent switch to `16a06503` (codex-native) | **201** in 65.078 s, 10 items, compaction `model=claude-cli/opus`, summary **11392** chars; server log `Fork compaction model resolved: … claude-cli/opus`; **no** `api.openai.com` / `api.anthropic.com` lines |
| (c) PATH without `claude` | **413** naming `claude CLI not found`; `c_in_progress=false`; no Summarizing SSE |

Source scratch digest unchanged
`661:0244796633ba99918d73893d1b866158e340ddccf96a205e561c62c3d5240f3d`.
Live JSONL sha/mtime unchanged (1_106_086 B). Live source session
pin is now `opus` (not `fable`); CLI record id follows the pin.

Lead `evidence/iter1/e2e/` matches (a)/(c) and a rebuild-from-items
(b) at 201 / `claude-cli/fable` / 7212 chars / 44 s.
`evidence/iter1/real-e2e/E2E.json` (b) is the pre-stdin **E2BIG**
413; REPORT already marks that harness stale.

## c. No API by default

`openai/gpt-4o-mini` fallback row removed from
`_fork_compact_candidate_rows`. `ALLOW_API` unset raises before
`load_providers`. Eval (b) used `CliSummaryClient` only.

## d. `claude -p` child env

`run_cli_summary`: pops `ANTHROPIC_API_KEY` / `CLAUDE_API_KEY` /
`ANTHROPIC_AUTH_TOKEN`; scratch cwd under `omnigent-fork-compact-`;
empty MCP; timeout `OMNIGENT_FORK_COMPACT_CLI_TIMEOUT_S` default 300;
prompt on stdin (`-`). Non-zero → `RuntimeError`; timeout →
`TimeoutError`; missing binary → `FileNotFoundError` surfaced in the
413 body (not a silent oversize-only 413). Tests in
`tests/fork_context/test_fork_compact_cli.py`.

## e. Prior commits

`git merge-base --is-ancestor` for `94c7921a6`, `480b6eea9`,
`780962a5d`, `ead098caf` → yes. Range `1bd5cb21a..HEAD` is only
`3d26d9ecd` and `77697270b`.

## Acceptance 3 suites (Evaluator)

```
uv run pytest -q tests/fork_context tests/server/routes/test_fork_compact.py
  tests/server/routes/test_fork_oversize_guard.py
  tests/runner/test_fork_clone_fallback.py
  tests/runner/test_fork_context_guard.py
  tests/runner/test_fork_resume_oversize_guard.py
  tests/llms/test_summarize.py tests/test_claude_native_bridge.py
# 288 passed
Trio-compat -k: 5 passed, 250 deselected
```

Ruff on the product/test files in the range: clean.
Pre-commit `pyrefly` fails on this worktree's incomplete `.venv`
(optional deps) and `no-hardcoded-models` still flags committed
`loop-fork-real/evidence` JSON. Same pre-existing noise Lead recorded.
Not a product regression.

## Isolation audit

| Check | Result |
|---|---|
| `:6767/health` | 200 before and after |
| `~/.omnigent/config.yaml` mtime | unchanged |
| `~/.omnigent/chat.db` mtime | unchanged during this run (1787949345) |
| `~/.claude/projects` count | **1958** before and after |
| live JSONL | sha unchanged |
| leftover `:17951` / `:179xx` | none |
| leftover eval `claude` | none (did not kill live `:6767` resume) |

`~/.claude/projects/-tmp-fork-cli-probe-scratch` is probe residue
from Lead (REPORT); this eval used `OMNIGENT_CLAUDE_PROJECTS_DIR`.

## REPORT.md after verdict

Agrees on product SHAs, stdin/`CLAUDE_CONFIG_DIR` pitfalls, and
stale `:17911` (b). Gaps Lead called out that this eval closed:
`tests/test_claude_native_bridge.py` was run (included in 288);
agent-switch (b) was re-run, not only null-external-id. Operator
step 4 hardcodes `claude-cli/fable`; live pin is `opus` → expect
`claude-cli/<source pin>`.

## Operator steps (Acceptance 5)

1. Fast-forward `trio-v0.10.0-fixes` onto `3d26d9ecd` + `77697270b`.
2. `omni server stop`, start the live server from that tree.
3. Re-fork `e34847899b7d47b3ad322948d4ea6002` same agent: immediate
   201, no compaction item, `--resume` of the clone even if >600 kB.
4. Fork with an agent switch: CLI summary, compaction `model`
   `claude-cli/<pin>` (currently `opus` on the live session).
5. Rebuild fork with `claude` missing: 413 names `claude CLI not found`,
   no Summarizing event.

commit: 3d26d9ecdf24bd571daa784d682ae1657ed7139c
commit: 77697270bee81dba36e2cab9f5f2051c96f62266
