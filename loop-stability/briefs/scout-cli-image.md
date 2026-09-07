# Scout brief — CLI view (item 3) + image attachment (item 4)

You are Trio Luna scout (`gpt-5.6-luna-max`, ask/read-only).
Workspace: `/home/alex/omnigent`. Mailbox `loop-stability/`.
Iteration 1.

Do NOT edit product files. Do NOT commit. Do NOT read whole large
files; grep + Read with offsets.

## Task

### Item 4 — picture attachment (server)

Scope:

- `omnigent/server/routes/sessions/routes_resources.py`
- `omnigent/server/routes/_sessions/helpers.py`

Grep `attach`, `image`, `picture`, `multipart`, `upload` in those
files and nearby tests under `tests/server/`.

### Item 3 — CLI view (web)

Grep `web/src` for the CLI/terminal view component (xterm, tmux,
terminal pane, cli view). Name the component file(s) and the
likely break (attach URL, session id, resource role, websocket).

## Return

You are read-only. Do NOT write files. Print a markdown report
with, for each item: files + line ranges, suspected cause,
existing tests, smallest fix, whether implement-then-smoke is
enough. Under ~150 lines total.
