# FINDINGS — rc-kill

"Sometimes CLI sessions not killed" matches **label-only close** and
**disconnect-without-stop**, not a current zombie herd.

Now: four live Omnigent CLI trees under `omni host` 1270936; zero
dead-parent orphans. Do not reap them.

Highest-confidence code causes:
1. `sys_session_close` never stops the harness.
2. Browser/SSE disconnect never stops the harness.
3. Claude-native stop is weaker than other natives (no forwarder cancel;
   1s tmux.json wait; tmux kill only).
4. Delete/stop is best-effort; offline runner leaves processes.

Align with unmerged #4976 rather than a parallel teardown design.
