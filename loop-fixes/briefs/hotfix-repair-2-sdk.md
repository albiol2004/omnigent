# Scoped repair — SDK replay guard must be fork-only

Repo `/home/alex/omnigent-fixes` (WORKTREE, branch `trio-v0.10.0-fixes`, HEAD 54b9ca859). HARD isolation: never touch ~/.omnigent, ~/.claude/projects, live :6767, `omni host`, /home/alex/omnigent (no git there). Read `loop-fixes/VERDICT-hotfix.md` first.

Allowed writes ONLY: `omnigent/inner/claude_sdk_executor.py`, `tests/inner/test_claude_sdk_fork_context_guard.py`, `loop-fixes/evidence/hotfix/repair2/`. Do NOT touch the native `guard=False` resume paths.

## Defect
`claude_sdk_executor.py:3130`: `_build_prompt(..., resume_session=False)` always calls `guard_fork_context(prompt)`. After a host restart `_clients` is empty, so an ordinary large SDK session (non-fork, or `pass_history=True`) replays its history as the first prompt and raises `ForkContextTooLarge` → 413 on a non-fork launch (Evaluator repro: 800,133 bytes).

## Change
Thread a fork decision into `_build_prompt` exactly as the native paths do (`grep -n 'guard=' omnigent/claude_native.py omnigent/runner/native/orchestration.py` for the pattern; fork = the conversation carries the fork labels `FORK_CARRY_HISTORY_LABEL_KEY` / fork-source labels, which the executor can read from the conversation/session labels it already has — find them with `grep -n 'label' omnigent/inner/claude_sdk_executor.py | head`; use `sed -n` ranges, NEVER read the whole file, it exceeds 1 MB). Non-fork oversized replay: log at INFO, do not raise. Fork replay: still raise. Tests: both cases in `tests/inner/test_claude_sdk_fork_context_guard.py`.

Run `uv run pytest -q tests/inner/test_claude_sdk_fork_context_guard.py tests/runner/test_fork_resume_oversize_guard.py tests/server/routes/test_fork_oversize_guard.py` and `PATH=.venv/bin:$PATH pre-commit run --files omnigent/inner/claude_sdk_executor.py tests/inner/test_claude_sdk_fork_context_guard.py`; save outputs under `loop-fixes/evidence/hotfix/repair2/`. Commit product+test files only as `slice(fork-oversize-guard): keep SDK history replay unguarded unless the session is a fork` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never amend/rebase/push/stash/reset. Print a compressed summary.
