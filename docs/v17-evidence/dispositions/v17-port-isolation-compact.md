# v17-port-isolation-compact — disposition notes

Ported the cursor-native isolation group and the codex manual-compact group from
`v16/trio-v0.16.0-fixes` onto v0.17.0 (after v17-port-receipts).

- **Conflict:** only `0b90fce3e` (codex compact via app-server). Its `runner/app.py` hunks
  edit `_handle_codex_native_compact` / `_inject_codex_compact`, which v0.17.0 moved into
  `omnigent/runner/native_controls.py`. `app.py` was left at v0.17.0 and the hunks were
  re-homed in `native_controls.py` (handler rewritten to use `thread/compact/start`,
  `_await_codex_native_compact_completion` added, tmux-based `_inject_codex_compact` removed).
  `test_app_sessions_native_events_options.py` conflicted in the compact tests; the fork's
  RPC-based tests replaced the old tmux-based ones (v0.17.0 helpers/imports unchanged).
- **Upstream kept:** codex #8745 (cold-resume MCP refresh), #9052, cursor_native #8516/#8523 —
  untouched; no upstream behaviour reverted.
- **Test move:** `tests/test_codex_native_manual_compact.py` (created by `0b90fce3e`/`da17fdc20`)
  moved to `tests/harnesses/codex_native/` (no import/fixture changes needed).
- `8920030c4` (tests/conftest.py tmp_path vs stray `.git` ancestor) applied cleanly.
- Targeted check: 398 passed; additionally `tests/harnesses/codex_native` 1484 passed.
  No pristine-proven deselects.

| v16 sha | fork sha | subject | ported/adapted/dropped | new sha | notes |
|---|---|---|---|---|---|
| 37c5ca35e | 4de324dde | cursor-native: no Backspace into empty composer; stable readiness before first paste | ported | cf7e01b4a | clean |
| cef70d04d | c5444087c | cursor-native: never write session stop hook into user hooks.json | ported | c34b373b0 | clean |
| c40055f88 | af775e159 | cursor-native: never register session MCP server in user mcp.json | ported | c91564c23 | clean |
| 09488293f | a04516b21 | cursor-native: refuse launches whose project config is user ~/.cursor | ported | 4a5f7c704 | clean |
| eef83cd9e | 510511735 | cursor-native: refuse launches from a repository subfolder | ported | 1363b3692 | clean |
| f62033d62 | 5a782783f | test(cursor-native): keep repo-subfolder refusal test's bridge under launch root | ported | e4877b51d | clean |
| 34315a4ff | (v16 slice commit) | port-cursor-isolation disposition notes; adapt ensure-response test to session_id kwarg | ported | fd369ae8c | clean; test adaptation applies on v0.17.0 |
| 8920030c4 | (v16 slice commit) | keep pytest tmp_path out of a stray .git ancestor | ported | 913919d7f | clean (tests/conftest.py) |
| 0b90fce3e | 0b2c6ce82 | codex-native: compact via app-server thread/compact/start, not tmux keys | adapted | f1676480c | app.py hunks re-homed into native_controls.py; events_options tests conflict resolved to fork RPC tests |
| da17fdc20 | 2a84483a5 | codex-native: keep manual-compact guard until Codex reports an outcome | ported | c52ecff7b | clean |
| ece706e7f | (v16 slice commit) | fix port-cursor-isolation disposition new-sha column | ported | d0a486bd2 | v16 notes doc only |
| 5aee0eee0 | (v16 slice commit) | port-codex-compact disposition notes | ported | 6fd4ca632 | v16 notes doc only |
| (adaptation) | — | move manual-compact tests to tests/harnesses/codex_native | adapted | 604ab387b | `git mv` from tests/ top level |
