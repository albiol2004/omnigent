| fork sha | subject | disposition | new sha | notes / evidence |
| --- | --- | --- | --- | --- |
| 4de324dde | fix(cursor-native): no Backspace into an empty composer; stable readiness before the first paste | ported | c7000842a | Clean pick. |
| c5444087c | fix(cursor-native): never write a session stop hook into the user hooks.json | adapted | a9a2753b9 | Only conflict: import block in tests/runner/test_app_sessions_native_terminals_autocreate.py; kept upstream `import threading` and the fork's `import os` + `Callable`. |
| af775e159 | fix(cursor-native): never register a session MCP server in the user mcp.json | ported | 63ed06921 | Clean pick. |
| a04516b21 | fix(cursor-native): refuse Cursor launches whose project config is the user ~/.cursor | adapted | 5272f08cf | Conflict in `_native_terminal_start_error_payload` (orchestration.py): kept upstream's `TerminalExitedDuringLaunch` Codex branch and put the fork's `CursorSharedWorkspaceError` branch first in the same if/elif chain. Test adaptation (in the slice commit): `test_native_terminal_ensure_response_carries_cursor_refusal` calls `_native_terminal_start_error_response`, which v0.16.0 made require keyword-only `session_id`; the test now passes `session_id=` (same assertions). |
| 510511735 | fix(cursor-native): refuse Cursor launches from a repository subfolder | ported | 7d1acf15d | Clean pick. |
| 5a782783f | test(cursor-native): keep the repo-subfolder refusal test's bridge under the launch root | ported | 07be1ec88 | Clean pick. |

Environment notes (no test was weakened, deselected or skipped):

- This host has a stray empty `/tmp/.git` directory. Cursor's new refusal logic treats it as the project root for every workspace under `/tmp`, so the `tests/runner/test_app_sessions_native_terminals_autocreate.py` cursor tests fail with `workspace_not_project_root:/tmp` when pytest's tmp dir is under `/tmp`. They pass with `--basetemp=/dev/shm/...` (a path with no `.git` ancestor).
- `tests/server/integration/test_cursor_receipt_binding_e2e.py::test_owned_hooks_only_stays_capable` and `::test_shared_user_hook_from_another_session_cannot_close_a_running_turn` fail when pytest's basetemp is on `/dev/shm` (they also fail on the unmodified base a78169ed8 there) and pass under `/tmp` (verified on a78169ed8 and on this branch).
- `test_publish_native_terminal_start_error_emits_failed_status_only` fails only when TMPDIR is under `$HOME` (the log path is shown as `~/...`); passes otherwise.
- Combined result: autocreate file with `--basetemp=/dev/shm`, the other three files under default `/tmp`: all pass (see final report).
