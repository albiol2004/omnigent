# Builder: kill-on-close

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`
(branch `trio-v0.10.0-fixes`). Implement **only** this slice.

## HARD isolation (non-negotiable)
This is the user's production machine. Never read/write `~/.omnigent`,
`~/.claude/projects`, `~/.cursor`. Never talk to
`http://127.0.0.1:6767`. Never restart/kill `omni host` (PID 1270936),
the runner, or any process you did not start. Never run git in
`/home/alex/omnigent`. Work ONLY under `/home/alex/omnigent-fixes`.
Throwaway servers only: `OMNIGENT_DATA_DIR=<scratch>`, port ≥ 17000,
torn down by you. Prefer **fakes** — no live claude/tmux of the user.

Do not edit `loop-fixes/GOAL.md` or `loop-fixes/VERDICT.md`. Do not
touch sqlite-pool / fork / render files.

Do **NOT** add kill-on-SSE-disconnect (`helpers.py` stream break).
That is deferred.

## How to read code
NEVER ingest whole files (`tool_dispatch.py`, `claude_native_bridge.py`
are huge). Use `sed -n` / `rg -n` on these ranges only:

- Close is tombstone-only: `omnigent/runner/tool_dispatch.py:4934-5005`
  `_session_close_via_rest` (PATCH title + `omnigent.closed`).
- Existing stop POST to reuse: `omnigent/runner/tool_dispatch.py:7076-7087`
  `_cancel_subagent_task` posts
  `{"type": event_type, "data": {}}` to `/v1/sessions/{id}/events`
  with `stop_session` for claude-native else `interrupt`.
- `_claude_stop` missing forwarder cancel:
  `omnigent/runner/native/interrupt.py:438-472`
  vs `_uniform_stop` cancel at `:396`
  (`await _cancel_auto_forwarder_task(conv_id)`). Import already at
  `interrupt.py:44`.
- `kill_session` is tmux-only:
  `omnigent/claude_native_bridge.py:3139-3174`.
- `_killpg` refuses own pgid: `omnigent/inner/_proc.py:130-159`;
  `kill_tree` `:211-236`; `_wait_gone` `:239-241`; `process_alive`
  `:244+`.
- Existing close tests: `tests/runner/test_runner_dispatch.py:5409-5472`
  (`test_session_close_patches_tombstoned_title`) — extend so a stop
  event is POSTed for the **target** only, not siblings.
- Existing kill_session test:
  `tests/test_claude_native_bridge.py:3784-3828`.
- Proc tests: `tests/inner/test_proc_and_platform.py`.
- Native stop tests: `tests/runner/test_native_interrupt_runner.py`.

`list-panes -F #{pane_pid}` exists in `omnigent/inner/terminal.py:1782`
— use that pattern after `kill-session` if you need to see leftover
pane pids; do not Read that whole file.

## Task
(a) In `_session_close_via_rest`, after tree-scope checks succeed and
before/with the PATCH, POST the same stop as UI Stop / cancel-task
for the **target** session id only. Best-effort: a failed/404 stop
must still tombstone (close should succeed). Must not POST stop for
the caller or siblings. Reuse the event JSON shape above; prefer
`stop_session` when you can know claude-native, else `interrupt` is
OK if labels are not on the snapshot — document the choice. Do not
kill other sessions.

(b) `_claude_stop`: after successful `kill_session` / teardown, call
`await _cancel_auto_forwarder_task(conv_id)` like `_uniform_stop`.

(c) After `_run_tmux(..., "kill-session", ...)` in `kill_session`,
verify the pane/process group is gone (list-panes / `process_alive`).
If still alive, SIGKILL recorded pgid/pids using `_proc.py` helpers
(`kill_tree` / `_killpg`) with a **bounded** wait. Never pass our own
pgid. If tmux.json has no pid, capture pane_pid before kill when
cheap, or list-panes; keep the change small. Escalate only the
session's recorded pids.

Keep comments short (CLAUDE.md): scenario, not PR numbers.

## Tests / hooks you must run
```
cd /home/alex/omnigent-fixes
uv run pytest -q tests/runner/test_runner_dispatch.py tests/runner/test_native_interrupt_runner.py tests/test_claude_native_bridge.py tests/inner/test_proc_and_platform.py tests/tools/builtins/test_sys_session.py
pre-commit run --files omnigent/runner/tool_dispatch.py omnigent/runner/native/interrupt.py omnigent/claude_native_bridge.py omnigent/inner/_proc.py tests/runner/test_runner_dispatch.py tests/runner/test_native_interrupt_runner.py tests/test_claude_native_bridge.py tests/inner/test_proc_and_platform.py
```
Add any new test files to `--files`. Fix until clean.

Also keep Trio-compat in mind (Lead will re-run):
`uv run pytest -q tests/tools/builtins/test_spawn.py tests/runner/test_runner_dispatch.py tests/server/integration/test_sessions_child_sessions.py -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'`

## Evidence
`loop-fixes/evidence/iter1/kill-on-close/`: pytest log + a tiny fake
subprocess/tmux script showing SIGKILL escalation when kill-session
leaves a pid, and that `_killpg` still refuses own pgid. No live
user sessions.

## Finish
Do not commit. Print changed paths and test results.
