# CENSUS — 2026-08-27T21:30+02 (list only, nothing killed)

Raw: `pgrep-now.txt`. Host `omni host` pid 1270936 is alive (5h).

| Class | PIDs | Verdict |
|---|---|---|
| User tmux `main` | 1427076 | Not an Omnigent CLI session |
| `cswap auto` | 1831 | Tool daemon, not a session |
| Trio dashboard | 1680606 | Unrelated |
| claude-native syngenta `/c/a29ac066…` | tmux 2831182, claude 2831183, mcp 2831324 | **Live** (ppid=host, ~59 min) |
| claude-native omnigent `/c/e34847899…` | tmux 2853093, claude 2853094, mcp 2853250 | **Live** (this Lead session) |
| cursor-native omnigent `/c/42f6959b…` | tmux 2878438, cursor-agent 2878439, mcp 2878907 | **Live** (this Cursor role) |
| cursor-native syngenta `/c/c5506d9a…` | tmux 2983523, cursor-agent 2983524, mcp 2984005 | **Live** (~1 min) |

**No dead-parent orphans observed.** `claude` pid==pgid==sid (own session).
tmux launched with `remain-on-exit on` — servers can outlive a dead pane.

This census does not prove the user bug is absent; it proves the failure is
path-dependent (close/stop/disconnect), not "the machine is full of zombies
right now".
