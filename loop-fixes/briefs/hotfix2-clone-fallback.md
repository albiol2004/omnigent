# Hotfix 2 — oversize native transcript clone must fall back to the compacted rebuild, not 413

Repo `/home/alex/omnigent-fixes` (git WORKTREE, branch `hotfix-clone-fallback`, based on trio-v0.10.0-fixes). HARD isolation: never touch ~/.omnigent, ~/.claude/projects, live :6767, `omni host`, /home/alex/omnigent (no git there). Throwaway only (port ≥ 17400, scratch OMNIGENT_DATA_DIR/OMNIGENT_CONFIG_HOME). Never kill processes you did not start.

## Production failure (live runner log, forking a native Claude session on the same host)
```
_auto_create_claude_terminal (orchestration.py:6354) → claude_native._clone_claude_transcript (claude_native.py:1890)
→ guard_fork_context_bytes → ForkContextTooLarge: 782357 bytes exceeds threshold 600000
```
`POST /fork` succeeded (server-side compact-on-fork produced a compacted item set in the DB), but the runner's same-host native path IGNORES those items: it clones the source's raw `~/.claude/projects/<ws>/<sid>.jsonl`, and `_compact_cloned_transcript` only helps when Claude's own `compact_boundary` exists. So the user's fork still 413s at launch.

## Required change (smallest correct)
In `_auto_create_claude_terminal` (`orchestration.py` ~6340-6420, use `sed -n`; the file is >1 MB — NEVER read it whole): when `_clone_claude_transcript` raises `ForkContextTooLarge` (and only then), do NOT re-raise. Log at INFO ("source transcript N bytes > threshold; rebuilding from compacted items") and fall through to the existing "no native transcript" branch that calls `_ensure_local_claude_resume_transcript` from the fork's own Omnigent items (which compact-on-fork already compacted). That rebuild keeps its fork guard (`guard=True`) so a still-oversize result still 413s with the real message. Codex path (`codex_native.py:1821-1916` analogous clone) — apply the same fallback if an equivalent rebuild exists; otherwise leave and note it.

## Tests
`tests/runner/test_fork_context_guard.py` / a new test: fork launch where the clone is oversize but the rebuilt-from-items transcript is under threshold → launches with `--resume`, no raise, rebuild path taken; clone oversize AND rebuild oversize → 413. Run `uv run pytest -q tests/runner/test_fork_context_guard.py tests/runner/test_fork_resume_oversize_guard.py tests/server/routes/test_fork_compact.py tests/server/routes/test_fork_oversize_guard.py tests/test_claude_native_bridge.py`, Trio-compat (`uv run pytest -q tests/tools/builtins/test_spawn.py tests/runner/test_runner_dispatch.py tests/server/integration/test_sessions_child_sessions.py -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'`), `PATH=.venv/bin:$PATH pre-commit run --files <changed>`. Outputs → `loop-fixes/evidence/hotfix2/`.

## Finish
Commit product+test files only: `slice(compact-on-fork): rebuild oversize native clones from compacted items instead of refusing` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never amend/rebase/push/stash/reset. Print a compressed summary.
