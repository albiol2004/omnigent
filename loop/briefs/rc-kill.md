# Scout: rc-kill (read-only product tree)

You are a Luna scout. Workspace: /home/alex/omnigent. HEAD product tree
ead098caf (commit 9926c9145). Investigation only.

## Writes (ONLY these)
`loop/evidence/iter1/rc-kill/` — FINDINGS.md, CITATIONS.md, CENSUS.md,
PATHS.md. Pairwise-disjoint from other slices.

NEVER edit product files. NEVER kill any process you did not start.
List orphans; do not reap them. NEVER touch ~/.claude/projects or real
sessions.

## How to read code
Do NOT Read whole large files (tool_dispatch.py, helpers.py, interrupt.py
if huge). Use `sed -n` and `rg -n`.

Diagnosed ranges (GOAL + Lead grep — verify; line numbers drifted):
- sys_session_close: GOAL tool_dispatch.py:4968-5005. HEAD:
  dispatch ~3763, `_session_close_via_rest` 4934. Confirm it only
  PATCHes a label and does not stop the harness.
- no kill on SSE/WS disconnect: search helpers.py around 7415-7420
  (`rg -n disconnect|on_disconnect|websocket` in
  omnigent/server and omnigent/runner).
- claude-sdk CLI child pgid: omnigent/inner/_proc.py:130-159 `_killpg`;
  spawn flags 116-126; `kill_tree` 211-236. Confirm whether children
  get start_new_session and whether _killpg bails when pid!=pgid.
- tmux kill-session 1 s timeout: runner/native/interrupt.py:437-470
  (HEAD ~385, 439-447, timeout_s=1.0). Confirm no SIGKILL escalation
  and no orphan sweep.
- `_claude_stop` vs forwarder task cancel: rg `_claude_stop` and
  forwarder cancel.

Session-ending paths to trace (code + what process actually dies):
stop, close, delete, fork-source, UI tab close, runner restart,
sys_session_close, cancel mid-spawn.

Upstream: #4930 (P1, open; fix PR #4976 unmerged), #2421, #5544
(merged post-v0.11, delete cleanup), #5254, #4014. Also check
#4976 #5603 #5405 #4913 #5081 #5544 for conflict.

## Required outputs
1. CENSUS.md: `ps -ef` / `pgrep -af 'claude|cursor-agent|tmux|mcp'`
   NOW. Classify likely-orphan vs likely-live. Do not kill anything.
2. PATHS.md: for each session-ending path, what the code kills (file:line)
   vs what can survive (claude, tmux, MCP, cursor-agent).
3. CITATIONS.md: every scouted kill fact confirmed/refuted/unconfirmed.
4. Ranked causes + candidate fixes (size/files/risk/PR conflict).

Write FINDINGS.md last. Quote short sed snippets only.
