# Probe notes

- Slice: `probe-partial-text`; iteration: 1.
- Run date: 2026-08-28.
- Throwaway workspace:
  `/tmp/omnigent-cursor-stream-probe-1787919978-1841716`.
- Workspace hash:
  `a09d3066e00e78d72374f5fe8c6d9a1f`.
- Own tmux session: `og-cstream-probe-1841716`.
- Launcher shell PID encoded in the session name: `1841716`.
- The tmux-server and cursor-agent child PIDs were not captured separately.
- Cursor CLI: `v2026.08.25-3e8eec8`.
- Model id from Cursor metadata: `gpt-5.6-luna`.
- Model label rendered in the pane: `GPT-5.6 Luna 272K Max`.
- Prompt:
  `Write 800 words explaining how a mechanical clock works, with no tools
  and no file edits.`
- T0 wall time: `2026-08-28T12:28:15.523+00:00`.
- T0 was measured around the `tmux send-keys Enter` call.
- Bound store:
  `/home/alex/.cursor/chats/a09d3066e00e78d72374f5fe8c6d9a1f/f0d89441-3224-42da-bd26-eb79fe2c6763/store.db`.
- The hash-directory store listing was empty before the prompt was sent.
- SQLite reads used the WAL-aware URI
  `file:<store>?mode=ro`; no `immutable=1` URI was used.
- The sampler ran 231 paired store/pane samples.
- Sampling elapsed from 1.361 ms through 23000.054 ms after T0.
- Intervals: minimum 98.698 ms, median 100.001 ms, mean 99.994 ms,
  maximum 100.046 ms.
- Stop reason: pane and store signatures stable for 1.2 seconds after
  activity.
- The sampler attempted `tmux kill-session` only for the own session.

## Commands and queries

The run was launched from `/home/alex/omnigent-fixes` with:

```text
WS=/tmp/omnigent-cursor-stream-probe-1787919978-1841716
SESS=og-cstream-probe-1841716
mkdir -p "$WS"
tmux new-session -d -s "$SESS" -c "$WS" cursor-agent --force --trust
tmux capture-pane -t "$SESS" -p -e
tmux send-keys -t "$SESS" -l -- "$PROMPT"
tmux send-keys -t "$SESS" Enter
tmux kill-session -t "$SESS"
```

The sampler executed these read-only SQL queries through Python's
`sqlite3` module:

```sql
SELECT MAX(rowid), COUNT(*) FROM blobs;
SELECT rowid, id, length(data), data
FROM blobs ORDER BY rowid DESC LIMIT 1;
SELECT value FROM meta;
```

It also sampled `store.db`, `store.db-wal`, and `store.db-shm` sizes,
decoded JSON blob data when possible, and recorded ANSI-stripped pane
snapshots with frame byte lengths.

## Isolation self-check

The required checks were run after the probe:

```text
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:6767/health
200

stat -c %Y /home/alex/omnigent-fixes-data/chat.db
1787905289

tmux has-session -t og-cstream-probe-1841716
can't find session: og-cstream-probe-1841716
session gone
```

No Omnigent server was started. No port at or above 17200 was used. The
health request and data-directory stat were read-only checks. The probe
did not touch `~/.omnigent`, `~/.claude/projects`, `:17067`,
`/home/alex/omnigent-fixes-data`, `/home/alex/omnigent`, or mailbox files.
The only repository outputs are the four files in this probe directory.

The `meta.value` query was performed, but its encoded preview was redacted
from the evidence because it contains Cursor metadata including an
encryption-key field. Its type and length remain recorded in the timeline.
