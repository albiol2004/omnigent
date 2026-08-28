# Hotfix — fork-oversize guard must never fire on a plain resume/restart

Repo `/home/alex/omnigent-fixes` (git WORKTREE, branch `trio-v0.10.0-fixes`). HARD isolation: never touch ~/.omnigent, ~/.claude/projects, the live :6767 server, `omni host`, or /home/alex/omnigent (shares .git; no git commands there). Never kill processes you did not start.

## Production failure (from the user's live runner log, after deploying this branch)
```
_ensure_native_terminal → _launch_claude → _auto_create_claude_terminal (orchestration.py:6312)
→ claude_native._ensure_local_claude_resume_transcript (claude_native.py:4250)
→ fork_context.guard_fork_context_bytes → ForkContextTooLarge
"Native Claude terminal start failed: Fork context too large: 1071085 bytes exceeds threshold 600000 bytes"
```
The session was an ordinary large claude-native session being resumed after a host restart — NOT a fork. Result: every big session refuses to start. The user had to revert the branch.

## Required change (smallest correct)
The oversize guard (slice eabf6b101) is only allowed on **fork launches** — i.e. when the launch carries the fork labels (`FORK_CARRY_HISTORY_LABEL_KEY` / `FORK_SOURCE_*`, see `orchestration.py` ~5907-5990, 6283-6420) or the server fork route (`routes_core.py` fork_session) / SDK fork-prompt replay (`claude_sdk_executor.py:3130` — only when the prompt is the fork "Conversation so far" replay). On a plain resume/rebuild (existing `external_session_id`, restart, cold resume, `_ensure_local_claude_resume_transcript` for the session's own history, and the analogous codex/pi/qwen rebuild paths at `codex_native.py:1821-1916`, `pi_native_resume.py:626`, `qwen_native_bridge.py`, `orchestration.py:1826,2445,3257`) the guard MUST be skipped (log at INFO if oversize, never raise). Prefer threading an explicit `is_fork: bool` / `guard: bool` parameter down from the launch metadata rather than sniffing globals. `guard_fork_context*` helpers may gain a no-op path but must not change their fork behavior.

## Tests
Add regression tests: (1) `_ensure_local_claude_resume_transcript` on a >threshold transcript for a NON-fork resume succeeds (no raise); (2) the same for a fork launch still raises `ForkContextTooLarge`; (3) analogous non-fork case for codex and pi rebuild helpers. Run `uv run pytest -q tests/runner/test_fork_context_guard.py tests/server/routes/test_fork_oversize_guard.py tests/server/routes/test_fork_compact.py tests/inner/test_claude_sdk_fork_context_guard.py tests/test_claude_native_bridge.py` plus any touched test files, the Trio-compat command (`uv run pytest -q tests/tools/builtins/test_spawn.py tests/runner/test_runner_dispatch.py tests/server/integration/test_sessions_child_sessions.py -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'`), and `PATH=.venv/bin:$PATH pre-commit run --files <changed>`. Save outputs to `loop-fixes/evidence/hotfix/`.

## Finish
Commit ONLY product+test files as `slice(fork-oversize-guard): apply the oversize guard to fork launches only, never to plain resume` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never amend/rebase/push/stash/reset. Print a compressed summary listing every call site you changed and how each now decides fork-vs-resume.
