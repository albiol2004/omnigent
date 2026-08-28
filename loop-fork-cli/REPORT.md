# REPORT — iter 1 Lead (fork-compact-cli, redirected GOAL)

HEAD product: `77697270b`. Mailbox left uncommitted.

Luna builders: `gpt-5.6-luna-max` (`model_effort: max`).
`--workspace /home/alex/omnigent-fixes`.

| Slice | Command | Exit | Wall |
|---|---|---|---|
| native-fork-passthrough | `trioctl omnigent run builder --prompt-file loop-fork-cli/briefs/native-fork-passthrough.md --workspace /home/alex/omnigent-fixes --timeout 1800` | 0 | 535.68s |
| cli-summary-for-rebuild-paths | same, `cli-summary-for-rebuild-paths.md` | 0 | 513.05s |
| real-e2e | Lead throwaway `:17901` | n/a | native 110ms; rebuild 44468ms |

Captured: `loop-fork-cli/evidence/iter1/_trioctl/*.stdout`.

GOAL was redirected mid-flight (commit `1bd5cb21a`). Abandoned
headless-only design: `evidence/iter1/abandoned/`. First Luna wave
(`cli-summary-backend`) was SIGTERM'd (exit 143); product recovered
in the redirected slices.

## Probe

`evidence/iter1/probe/FACTS.md` + `DECISION.md`.

- Inherited `ANTHROPIC_API_KEY` → 401, wall 183s, `apiKeySource=ANTHROPIC_API_KEY`.
- Unset keys + `--safe-mode` + `{"mcpServers":{}}` → wall **2.27s**,
  `result=OK`, `apiKeySource=none`. JSON **array**, last `type=result`.
- `--bare` rejected (forces API key). `--mcp-config '{}'` invalid.
- Stdin `-p -` probe: wall 2.39s, `result=OK`.
- Clone vs `--fork-session`: keep clone + `--resume <clone-id>`.

## slice native-fork-passthrough — `3d26d9ecd`

Paths: `omnigent/claude_native.py`, `omnigent/codex_native.py`,
`omnigent/fork_context.py` (`OMNIGENT_FORK_NATIVE_GUARD`,
`OMNIGENT_CLAUDE_PROJECTS_DIR`), `routes_core.py` (~2348-2372
passthrough), tests for clone/oversize.

`PYTHONPATH=/home/alex/omnigent-fixes python -m pytest -q
tests/runner/test_fork_context_guard.py
tests/runner/test_fork_clone_fallback.py
tests/server/routes/test_fork_oversize_guard.py`
included in 55 passed below.

Luna: `gpt-5.6-luna-max`. Orchestration.py not edited (clone helper
no longer raises, so rebuild-on-size is unused).

## slice cli-summary-for-rebuild-paths — `77697270b`

Paths: `omnigent/fork_compact_cli.py`, `omnigent/fork_compact.py`,
`omnigent/fork_compact_routing.py`, CLI + model tests,
`tests/server/routes/test_fork_compact.py` (ALLOW_API for mocks).

Lead fixes after e2e: prompt on **stdin** (`-p -`) after
`[Errno 7] Argument list too long`; never set `CLAUDE_CONFIG_DIR`
to the scratch cwd (that dropped OAuth, exit 1).

```
PYTHONPATH=/home/alex/omnigent-fixes python -m pytest -q tests/fork_context
# 16 passed (with the rest of Acceptance 3: 55 passed)
```

Luna: `gpt-5.6-luna-max`.

## slice real-e2e — Lead, port 17901

Scratch `/tmp/fork-compact-cli-e2e`. Keys stripped. Process log
unset. `OMNIGENT_CLAUDE_PROJECTS_DIR` scratch. Source
`e34847899b7d47b3ad322948d4ea6002` (644 items). JSONL copied
read-only (1_328_243 B).

| Path | HTTP | Notes |
|---|---|---|
| (a) same-family native | **201** in 110 ms | 644 items, **no** compaction; rendered **1_028_488** B; clone **1_341_194** B; argv `claude --resume aaaaaaaa-…` |
| (c) PATH `/usr/bin:/bin` | **413** | `claude CLI not found`; no in_progress |
| (b) rebuild (no external id) | **201** in **44468** ms | 10 items, **19_789** B after, summary **7212** chars, model **`claude-cli/fable`** |

Source digest unchanged:
`644:c32a6a11e72b4bbcbda3af5d8786a7e815d45f792e82a93736f83960f4bef054`.

Evidence: `loop-fork-cli/evidence/iter1/e2e/` (`NATIVE.json`,
`REBUILD.json`, `FAIL413.json`, `E2E.json`). A second harness
`evidence/iter1/real-e2e/` on `:17911` recorded (a)+(c); its (b)
was 413 before the stdin/OAuth fixes.

## Isolation audit

| Check | Result |
|---|---|
| `http://127.0.0.1:6767/health` | **200** before and after |
| `~/.omnigent/config.yaml` mtime | unchanged |
| `~/.omnigent/chat.db` mtime | unchanged |
| leftover `:17901` | **none** |
| live source JSONL | not rewritten (mtime 21:05:34 still) |
| `OMNIGENT_PROCESS_LOG_FILE` | unset on throwaway server |

Did not git `/home/alex/omnigent`, did not kill `:6767`.
`claude -p` scratch cwd created
`~/.claude/projects/-tmp-fork-cli-probe-scratch` (GOAL-allowed).
Throwaway clones used `OMNIGENT_CLAUDE_PROJECTS_DIR`.

## Acceptance 3 suites

```
python -m pytest -q tests/server/routes/test_fork_compact.py \
  tests/server/routes/test_fork_oversize_guard.py tests/fork_context \
  tests/runner/test_fork_clone_fallback.py \
  tests/runner/test_fork_context_guard.py \
  tests/runner/test_fork_resume_oversize_guard.py \
  tests/llms/test_summarize.py
# 55 passed

python -m pytest -q tests/tools/builtins/test_spawn.py \
  tests/runner/test_runner_dispatch.py \
  tests/server/integration/test_sessions_child_sessions.py \
  -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'
# 5 passed, 250 deselected
```

`trio-shadow.py --mailbox loop-fork-cli --require-commits` → **exit 0**.
Tree dirty only with mailbox files. `tests/test_claude_native_bridge.py`
not re-run (GOAL listed it; not in the focused 55).

## Deviations / weaknesses

- First builder wave killed (143); GOAL redirect parked that design.
- Compaction prompt on argv hit E2BIG; stdin is required.
- `CLAUDE_CONFIG_DIR` on scratch cwd breaks subscription auth.
- Unresolved `file_id` still logs ERROR then continues; blobs copied.
- Items API `type` for compaction is numeric `6`; e2e parser missed
  `model` until the DB was read (REBUILD.json corrected).
- Luna `README.md` edit reverted (not in slice commits).
- Pre-commit `no-hardcoded-models` still flags `loop-fork-real/evidence`.

## Operator steps (Acceptance 5)

1. Fast-forward `trio-v0.10.0-fixes` onto this branch (or cherry-pick
   `3d26d9ecd` and `77697270b`).
2. `omni server stop`, then start the live server from that tree.
3. Re-fork conversation `e34847899b7d47b3ad322948d4ea6002` **same
   agent**: expect **201 immediately**, no compaction item, native
   `--resume` of the cloned transcript (even >600 kB).
4. Fork the same source **with an agent switch** (or any
   rebuild-from-items path): expect a summary whose compaction
   `model` is `claude-cli/fable` (subscription CLI, not API keys).
5. If `claude` is missing from PATH on a rebuild fork: 413 containing
   `claude CLI not found`, no Summarizing event.
