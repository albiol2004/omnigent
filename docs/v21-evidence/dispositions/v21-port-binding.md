# v21-port-binding — v17 "chat binding + plugin-dir" group (#49-67) re-ported onto v0.21.0rc1

Method: `git cherry-pick -x` of v17 commits #49-67 in original order on top of v21-port-isocompact. Taken over by the
Lead.

| # | v17 sha | subject | disposition | new sha | notes |
|---|---|---|---|---|---|
| 49 | 9f7220a42 | fix(cursor-native): never bind a session to another workspace's chat store | ported | c8251c6e6 | clean |
| 50 | 24508959a | fix(cursor-native): pin each fresh launch to a pre-minted chat id | adapted | 78893d289 | permissions.py import+conftest |
| 51 | 433df86ae | fix(cursor-native): bind a discovered chat only when this session's pane owns it | adapted | 2dc5c82e1 | elicitation store resolver |
| 52 | 197a2cb17 | fix(cursor-native): warn when a launch overwrites a live sibling's hooks/MCP slot | ported | c9c439770 | clean |
| 53 | b6962e4af | slice(port-cursor-binding): disposition notes for the chat-binding port | ported | 47b2acb05 | historical evidence |
| 54 | 3c7252f3a | feat(cursor-native): opt-in per-launch --plugin-dir hooks/MCP config | ported | a99ce6d28 | clean |
| 55 | a4269368c | fix(cursor-native): let OMNIGENT_CURSOR_PLUGIN_DIR reach host-spawned runners | adapted | 975d358fd | runner env allowlist |
| 56 | bab692622 | fix(cursor-native): never delete the project mcp.json when clearing a dead entry | ported | 6dcba7ce0 | clean |
| 57 | 10ce2b158 | fix(cursor-native): refuse plugin-route launches cursor-agent would run without the plugin | adapted | 38fabe41f | start error payload import |
| 58 | 1ee4c7d22 | fix(cursor-native): a plugin-route turn no longer fires a live sibling's project usage hook | ported | 413f52e4e | clean |
| 59 | 4596497c7 | fix(cursor-native): owner-only bridge dir recreation; grace for mid-launch siblings | ported | a42a212a1 | clean |
| 60 | af4c6a098 | test(cursor-native): fix the pyrefly errors in the plugin-dir unit tests | ported | 9e468428a | clean |
| 61 | cec186bc5 | test(cursor-native): gate the plugin-dir real-CLI e2e; cover the sibling-hook skip | ported | 229bc198f | clean |
| 62 | 69b9e324d | fix(cursor-native): cursor_project_key matches the CLI's directory mangling (r17 N16) | ported | 39981432e | clean |
| 63 | 7c66bd251 | fix(cursor-native): bridge MCP refuses a parent bound to another bridge (r17 N11) | ported | e629e50d6 | clean |
| 64 | 66471010f | fix(cursor-native): receipt gate scans passthrough and installed plugin stop hooks (r17 N12) | ported | 1f3426fd3 | clean |
| 65 | e64f72d1b | slice(port-cursor-plugin-dir): disposition notes for the plugin-dir/r17 port | ported | 2656897c6 | historical evidence |
| 66 | 0cd5d45b4 | slice(v16-report): v0.16.0 re-port report and after-port evidence | ported | 978ba26b6 | historical evidence |
| 67 | 06aa68a25 | slice(v17-port-binding-plugin): disposition notes | ported | 31e97ccbb | historical evidence |

## Conflicts and how they were resolved (upstream v0.21.0rc1 kept, fork layered on top)

- **#50 `harnesses/cursor_native/permissions.py`** — upstream added `_resolve_elicitation_store` (prefers the bridge
  state's persisted/pre-seeded store on cold resume; imports `_read_state`). Kept it; the import block is the union
  (`_discover_store`, `_read_blob_rows`, `_read_state`, `bound_store_path`). The fork's per-poll
  `bound_store_path(bridge_dir)` follow runs first and only falls back to upstream's resolver while the forwarder has
  bound nothing.
- **#50 `tests/conftest.py`** — kept upstream's new `_no_workspace_probe` (autouse) and `frozen_recurrence_clock`
  fixtures and added the fork's autouse `_no_real_cursor_chat_minting` after them.
- **#51 `harnesses/cursor_native/permissions.py`** — the fork passes `held_stores=_pane_held_stores(bridge_dir)` to
  `_discover_store`; upstream's call site is now `_resolve_elicitation_store`, so that resolver gained a keyword-only
  `held_stores: frozenset[str] | None = None` it forwards to `_discover_store` (pane-ownership check kept on the
  discovery fallback; upstream's persisted-store preference unchanged).
- **#55 `host/connect.py`** — `_RUNNER_ENV_ALLOWLIST`: kept upstream's new `OMNIGENT_CLAUDE_CODE_ENTRYPOINT` /
  `OMNIGENT_BACKGROUND_TITLE_CLAUDE_MODEL` entries and added `OMNIGENT_CURSOR_PLUGIN_DIR` (upstream #9908's idle-timeout
  knobs untouched).
- **#57 `runner/native/orchestration.py`** — import block of `_native_terminal_start_error_payload`: union of the fork's
  `CursorPluginRouteError` / `CursorSharedWorkspaceError` and upstream's `PiNativeCliOutdatedError`.

## Checks

`pytest -n 4 --basetemp=<private> tests/test_cursor_native_plugin_dir.py tests/test_cursor_native.py tests/test_cursor_native_bridge.py
tests/test_cursor_native_forwarder.py tests/test_cursor_native_usage.py tests/test_cursor_native_permissions.py
tests/inner/test_cursor_native_executor.py tests/host/test_connect.py tests/runner/test_app_sessions_native_terminals_autocreate.py`
→ `TRIO_TEST: FAIL rc=1 passed=1107 failed=1`; the one failure is pristine (below).

## Pristine-proven deselects

- `tests/host/test_connect.py::test_run_host_process_announces_session_log_dir_on_start` — listed as
  `FAILED` in the pristine baseline `docs/v21-evidence/baseline-v0.21.0rc1.txt` (line 86, `== host ==` group, recorded at
  1b72ac3af, tree equal to v0.21.0rc1 outside `loop/`). Failure line on this branch (same):
  `E assert "This host's log: ~/.omnigent/logs/host/host-" in '...host started (pid …) … host exiting (clean) after 3.8s…'`
  (the host's structlog output in this environment carries no `This host's log:` line).
