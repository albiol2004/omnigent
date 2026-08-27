# CITATIONS — rc-kill (HEAD 9926c9145)

Luna scout **timed out** (1800s, empty stdout). Lead filled this slice.

| Scouted fact | Grade | file:line |
|---|---|---|
| sys_session_close only PATCH, never stops harness | **Confirmed** | `tool_dispatch.py:4934-5005` (GOAL 4968-5005 drifted; PATCH at 4988-4993) |
| No kill on SSE/WS disconnect helpers 7415-7420 | **Confirmed, line drift** | disconnect loop `helpers.py:7498-7524` — no process kill |
| claude-sdk child not own pgid so `_killpg` bails | **Partial** | `_killpg` refuses own pgid `_proc.py:130-159`. Native claude **is** own pgid (census). SDK spawn does not use `spawn_kwargs()` (unconfirmed SDK flags). |
| psutil walk misses re-parented grandchildren | **Plausible / unconfirmed live** | `kill_tree` returns after `killpg` `_proc.py:227-228` without walking |
| tmux kill-session 1s, no SIGKILL, no orphan sweep | **Confirmed with nuance** | `interrupt.py:447` `timeout_s=1.0` waits for tmux.json; `_run_tmux` 5s; no SIGKILL; runner boot sweep only `_entry.py:1283-1298` |
| kill_tree no wait | **Confirmed** | `_proc.py:211-236` |
| `_claude_stop` does not cancel forwarder | **Confirmed** | `_claude_stop` `438-472` vs `_uniform_stop` `396` |
| #4930 / PR #4976 | Open P1 teardown (scout render `gh`) | |
| #5544 merged post-v0.11 | Confirmed merged; this tree is v0.10.0+local | |
