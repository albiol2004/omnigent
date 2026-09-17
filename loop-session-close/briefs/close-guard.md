# Builder: slice(close-guard)

You are a GLM 5.2 Trio builder. Workspace:
`/home/coder/omnigent-dev`. Implement this slice only.
Do not git commit or push. Do not touch `/home/coder/omnigent`.
Do not `uv tool install`, start/stop omni, or bind port 6767.
Do not modify Trio mailbox files except you may write nothing
there. Never ingest whole `tool_dispatch.py` or `app.py`.
Use `sed -n 'START,ENDp'` for the ranges below.

## Goal

Tree-scoped children (`parent_session_id` set, same
`root_conversation_id`) must close even when `title` does not
parse as `<agent>:<title>` (verbatim `sys_session_create`
titles). Keep rejecting true top-level sessions
(`parent_session_id` / `parent_conversation_id` None) with
`session_not_a_sub_agent`. Registration-anchor `config_path`
sessions with no parent stay non-closable.

## Edit ranges

- `omnigent/runner/tool_dispatch.py`
  `_parse_session_title` 4089-4113 (read)
  `_close_tree_scope_error` 5531-5579 (read; do not weaken)
  `_session_close_via_rest` 5582-5668 — **remove** the reject
  at 5630-5632 when parse fails after scope passed.
  Derive tombstone agent/title: if parse works, keep current
  `parsed.agent`/`parsed.title`. Else use snapshot fields like
  `sys_session_get_info` does at 4366-4391:
  `sub_agent_name` or `agent_name` or `agent_id` for agent;
  raw title (via `title_without_closed_marker`) or the
  conversation id for title. Sanitize so the tombstone still
  has the form `{agent}:{title}{_CLOSED_TITLE_INFIX}{id}`.
  Add a tiny helper next to `_session_close_via_rest` if
  needed. Lots of comments.
- `omnigent/tools/builtins/spawn.py`
  `_agent_title_from_conversation` 1194-1221 (do not make it
  silently succeed for peek if peek still relies on parse —
  only **close** must accept unparsable titles).
  Parent gate 1318-1334 stays.
  `SysSessionCloseTool` ~1693: if title has no colon, do not
  raise; tombstone from `resolution.child.agent_id` (or
  `"agent"`) and the raw title / id. Peek may still reject
  malformed titles via the existing helper.

## Tests (extend existing files)

- `tests/runner/test_runner_dispatch.py` after the close
  cases ~5850-6061: child with `title="Lead pass"` (no colon),
  `parent_session_id` set, same root → closed True, PATCH
  issued, stop event still posted. Top-level still rejected
  (existing test).
- `tests/tools/builtins/test_sys_session.py` after ~803-830:
  create a child with title `"Lead pass"` and parent set;
  close succeeds; parent/top-level still rejected.

## Verify

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/runner/test_runner_dispatch.py \
  tests/tools/builtins/test_sys_session.py
```

Return files changed, summary, exact pytest output, concerns.
