# PATHS — what each session-ending path kills

| Path | Code | Kills CLI? | Survivors |
|---|---|---|---|
| **sys_session_close** | `tool_dispatch.py:4934-5005` PATCH title+`omnigent.closed` only | **No** | tmux, claude/cursor-agent, MCP |
| **SSE disconnect** | `helpers.py:7498-7524` break + presence.disconnect | **No** | harness process tree |
| **Stop (claude-native)** | `interrupt.py:438-472` `kill_session` then terminal teardown | **Intended yes** via `tmux kill-session` | If `tmux.json` missing within 1s: 503, process left. Forwarder task **not** cancelled (unlike `_uniform_stop` at 396). No SIGKILL of `claude` if tmux kill fails (`claude_native_bridge.py:3139-3174`, `_run_tmux` 5s timeout, no escalation). |
| **Stop (uniform native)** | `interrupt.py:381-413` | kill_session + `_cancel_auto_forwarder_task` | same tmux.json 1s wait |
| **Delete session** | `routes_events.py:1931-1976` `_best_effort_stop` then records | Best-effort stop; if runner offline, skip (`1977-1990`) | CLI if stop failed |
| **Archive** | `_archive_stop` orchestration.py:640+ | stop + host runner teardown | |
| **Fork source** | `fork_session` copies; does not stop source | Source CLI stays | source tmux/claude |
| **UI tab close** | SSE disconnect path | **No** | same as SSE |
| **Runner restart** | `_entry.py:1283-1298` `reap_orphaned_terminals` | Reaps **tmux** from prior runner | claude/cursor if reparented outside those tmux servers |
| **Cancel mid-spawn** | interrupt/stop if spawn incomplete | `kill_session` may 503 if no `tmux.json` yet | half-started claude |
| **SDK stop** | `_force_close_client` `claude_sdk_executor.py:1888-1958` terminate_tree then kill_tree | Yes if transport._process known | grandchildren in other pgid if `killpg` hits then returns without walk (`_proc.py:227-228`) |

Scouted `_killpg` bail when pid shares our pgid: **Confirmed** `_proc.py:130-159`.
Native `claude` in this census **is** its own pgid — that fact is SDK/spawn specific.
`claude_sdk_executor.py` never calls `spawn_kwargs()`; CLI spawn is the SDK
transport (unconfirmed whether that sets `start_new_session`).
`kill_tree` returns after successful `killpg` with **no wait** (`211-228`).
