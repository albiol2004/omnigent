# Builder brief — probe-partial-text (slice 0)

Workspace: `/home/alex/omnigent-fixes` (git worktree, branch
`trio-v0.10.0-fixes`). Mailbox: `loop-cursor-stream/`. Slice id:
`probe-partial-text`. You MUST write evidence files.

You implement ONLY this probe. Do not change product code. Do not
`git commit`, `git push`, `git stash`, `git reset`, `git rebase`,
`git checkout`, or `git amend`.

## HARD isolation (non-negotiable)
Never touch `~/.omnigent`, `~/.claude/projects`, live server
`:6767`, `omni host`, the user's `:17067` test instance, data dir
`/home/alex/omnigent-fixes-data`, or repo `/home/alex/omnigent`
(shares `.git`; no git commands there). Never kill processes you
did not start. Stop only YOUR tmux session / cursor-agent.

Using the installed `cursor-agent` CLI from a throwaway workspace
is ALLOWED. Read `~/.cursor` store files READ-ONLY (sqlite
`mode=ro`). Never edit files under `~/.cursor`. Cursor creating a
new chat under `~/.cursor/chats/` is expected runtime, not your
edit.

Throwaway servers if any: port ≥ 17200 with scratch
`OMNIGENT_DATA_DIR` + `OMNIGENT_CONFIG_HOME`. This probe should
NOT need an Omnigent server — launch `cursor-agent` in your own
tmux.

## NEVER read these files whole
Forbidden full ingest: `chatStore.ts`, `claude_native_forwarder.py`,
`routes_core.py`, `helpers.py`, `orchestration.py`. Use `sed -n`.

## How Omnigent finds store.db (use this recipe)
File: `omnigent/cursor_native_forwarder.py`

- `_cursor_chats_root` ~387-389 → `Path.home() / ".cursor" / "chats"`
- `_workspace_hash` ~392-394 → `md5(workspace.encode("utf-8")).hexdigest()`
- `_discover_store` ~407-449 →
  `~/.cursor/chats/<md5(cwd)>/<chat-id>/store.db`
- Open WAL-aware READ-ONLY (never `immutable=1`):
  `_read_blob_rows` ~512-539, `_get_current_rowid` ~321-336.
  URI: `file:{store}?mode=ro` then plain-path fallback.

Locate the store for YOUR throwaway cwd:

```
python3 - <<'PY'
import hashlib, os
ws = os.path.realpath("<THROWAY_WS>")
print(hashlib.md5(ws.encode()).hexdigest())
print(ws)
PY
ls -lt ~/.cursor/chats/<hash>/*/store.db
```

Bind the newest chat dir created AFTER your launch. If the hash dir
is empty, wait — Cursor creates it lazily on first message.

## Concrete probe recipe
1. `WS=/tmp/omnigent-cursor-stream-probe-$(date +%s)`
   `mkdir -p "$WS"` — empty throwaway workspace, not under
   `/home/alex/omnigent*`.
2. `SESS=og-cstream-probe-$$`
   `tmux new-session -d -s "$SESS" -c "$WS"`
3. In that session start the TUI (not print/`-p` mode):
   `cursor-agent --force --trust`
   Wait until the pane looks ready (prompt visible).
4. Inject a long-answer prompt that should take many seconds, e.g.
   `Write 800 words explaining how a mechanical clock works, with
   no tools and no file edits.`
   Use tmux send-keys / bracketed paste + Enter. Do not use
   `cursor-agent -p` (that skips the TUI pane).
5. Record `T0` = generation start (Enter sent). Sample EVERY ~100 ms
   until the assistant message is clearly finished (pane idle and
   store blob length stable for ≥1 s, or cursor-agent returned to
   prompt). Cap at 180 s then stop sampling.
6. Each sample timestamped (monotonic + wall). Write JSONL.

### Store sample (read-only)
```
sqlite3 "file:${STORE}?mode=ro" \
  "SELECT MAX(rowid), COUNT(*) FROM blobs;"
# newest blob length:
sqlite3 "file:${STORE}?mode=ro" \
  "SELECT rowid, id, length(data) FROM blobs ORDER BY rowid DESC LIMIT 1;"
sqlite3 "file:${STORE}?mode=ro" "SELECT value FROM meta;"
# also stat store.db, store.db-wal, store.db-shm sizes
```
Decode the newest blob if JSON: role, content text length. Note
whether rowid is NEW early vs SAME rowid growing vs only appearing
at the end. Do not UPDATE/INSERT.

### Pane sample
```
tmux capture-pane -t "$SESS" -p -e
```
Record frame byte length and (optional) stripped-ANSI text length.

7. When done: stop YOUR tmux (`tmux kill-session -t "$SESS"`) only.
   Do not kill other tmux/cursor processes.

## Deliverables (MUST write)
All under
`loop-cursor-stream/evidence/iter1/probe/` :

- `store-timeline.jsonl` — one JSON object per sample
- `pane-timeline.jsonl` — one JSON object per sample
- `NOTES.md` — commands, pids, store path, isolation notes
- `DECISION.md` — required. Include:
  - time-to-first-partial-store vs time-to-first-pane-growth
    (ms after T0)
  - whether store blobs grow before completion (yes/no + numbers)
  - rowid behavior (new row early / in-place / complete-only)
  - pane: does assistant region grow before store completion
  - CHOICE: `store.db` OR `pane-diff` and WHY (GOAL: prefer
    store.db if partial blobs exist)
  - sample counts, cadence actually achieved
  - Luna model id you ran as

## Isolation self-check before exit
```
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:6767/health
stat -c %Y /home/alex/omnigent-fixes-data/chat.db
# must still be 1787905289
tmux has-session -t "$SESS" && echo STILL_ALIVE || echo session gone
```
Record results in NOTES.md.

cd /home/alex/omnigent-fixes for every command.
