# v21-port-isocompact — v17 "isolation + compact" group (#35-48) re-ported onto v0.21.0rc1

Method: `git cherry-pick -x` of v17 commits #35-48 in original order on top of v21-port-receipts. Taken over by the
Lead (the builder chain stopped at v21-port-receipts).

| # | v17 sha | subject | disposition | new sha | notes |
|---|---|---|---|---|---|
| 35 | cf7e01b4a | fix(cursor-native): no Backspace into an empty composer; stable readiness before the first paste | ported | 173de1e84 | clean |
| 36 | c34b373b0 | fix(cursor-native): never write a session stop hook into the user hooks.json | adapted | 0a60a0f50 | test import conflict |
| 37 | c91564c23 | fix(cursor-native): never register a session MCP server in the user mcp.json | ported | 2291b0b23 | clean |
| 38 | 4a5f7c704 | fix(cursor-native): refuse Cursor launches whose project config is the user ~/.cursor | adapted | 7039bb81c | start-error payload conflict |
| 39 | 1363b3692 | fix(cursor-native): refuse Cursor launches from a repository subfolder | ported | 61aab49ac | clean |
| 40 | e4877b51d | test(cursor-native): keep the repo-subfolder refusal test's bridge under the launch root | ported | c159ff675 | clean |
| 41 | fd369ae8c | slice(port-cursor-isolation): disposition notes; adapt ensure-response test to session_id kwarg | ported | a9b417e3f | clean |
| 42 | 913919d7f | slice(port-cursor-isolation): fix keep pytest tmp_path out of a stray .git ancestor | ported | 7d3d30ad3 | clean |
| 43 | f1676480c | fix(codex-native): compact via app-server thread/compact/start, not tmux keys | adapted | c9de4f254 | 3 conflicts, see below |
| 44 | c52ecff7b | fix(codex-native): keep the manual-compact guard until Codex reports an outcome | ported | fb268f6de | clean |
| 45 | d0a486bd2 | slice(port-cursor-isolation): fix disposition new-sha column to the trio/loop commits | ported | 01890d219 | historical evidence |
| 46 | 6fd4ca632 | slice(port-codex-compact): disposition notes for the app-server manual compact port | ported | bde75aed4 | historical evidence |
| 47 | 604ab387b | slice(v17-port-isolation-compact): move manual-compact tests to tests/harnesses/codex_native | ported | b4f61eb59 | clean |
| 48 | f5f90ca43 | slice(v17-port-isolation-compact): disposition notes | ported | f5df68e41 | historical evidence |

## Conflicts and how they were resolved (upstream v0.21.0rc1 kept, fork layered on top)

- **#36 `tests/runner/test_app_sessions_native_terminals_autocreate.py`** — import block only; kept upstream's imports
  (`tempfile`, `SimpleNamespace`, `cast`) plus the fork's `Callable`.
- **#38 `runner/native/orchestration.py::_native_terminal_start_error_payload`** — upstream generalized the
  terminal-exit branch to every runtime (`classify_terminal_failure` diagnosis, `_terminal_exit_summary`) and added
  `PiNativeCliOutdatedError`. Kept all of it; the fork's `CursorSharedWorkspaceError` branch is checked first (its
  `user_message()` is the refusal text), then upstream's generic `TerminalExitedDuringLaunch` branch.
- **#43 `runner/native_controls.py`** — upstream v0.21.0rc1 still compacts Codex by typing `/compact` into the TUI
  (`git grep 'thread/compact' v0.21.0rc1 -- omnigent` finds no RPC sender), so the fork patch is still needed. Upstream
  meanwhile factored the tmux injection into `_inject_codex_native_slash` / `_inject_codex_slash_command`, now also used
  by the new Codex `/clear` (`_handle_codex_native_clear`). Kept the injector and `/clear` handler; only
  `_handle_codex_native_compact` is replaced by the fork's app-server `thread/compact/start` handler plus
  `_await_codex_native_compact_completion`.
- **#43 `tests/runner/test_app_sessions_native_events_options.py`** — kept upstream's new
  `test_events_clear_on_codex_native_types_clear_into_the_tui`; the fork's compact tests replace upstream's tmux-based
  compact tests (`..._returns_503_when_no_terminal` etc.), as in v17.
- **#43 `tests/e2e_ui/sessions/test_codex_native_compact_takes_effect.py`** — docstring only; took the fork's
  (app-server RPC) description.

Follow-up commit: `f0813e6d6` — upstream's Codex forwarder now probes `client.is_subscribed_to_thread(thread_id)` before
`thread/resume`; the fork's `_ForwarderFakeClient` in `tests/harnesses/codex_native/test_codex_native_manual_compact.py`
gained that method (returns `False`: not subscribed before resume). Upstream fakes
(`tests/harnesses/codex_native/test_codex_native.py`) implement the same probe.

## Checks

`pytest -n 4 --basetemp=<private> tests/test_cursor_native_bridge.py tests/runner/test_app_sessions_native_terminals_autocreate.py
tests/runner/test_app_sessions_native_events_options.py tests/server/integration/test_sessions_compact.py
tests/server/integration/test_cursor_cold_start_prompt.py tests/harnesses/codex_native/test_codex_native_manual_compact.py`
→ `500 passed, 1 failed` before `f0813e6d6` (the fake-client probe); the manual-compact file alone → `26 passed` after.
(An earlier `-n 4` run without `--basetemp` errored 90 tests with `FileNotFoundError: .../pytest-3/popen-gw0`: a
concurrent pytest on the host rotated the shared `pytest-of-coder` basetemp; environment, not code.)

## Pristine-proven deselects

None (`docs/v21-evidence/deselects/v21-port-isocompact.args` is empty).
