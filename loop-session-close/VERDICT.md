VERDICT: SHIP

Evaluator independently re-ran the Lead suite at HEAD `254714d8d`
(product tip `ec696c5fc`) and exercised the close/stop/reaper/advertise
paths with unit and fake-transport tests. No live server, port 6767, or
`/home/coder/omnigent` was touched.

## Pytest (a)

Command:

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/runner tests/tools/builtins tests/terminals \
  tests/test_claude_native_bridge.py \
  tests/test_cursor_native_bridge.py \
  tests/test_codex_native_bridge.py
```

Saved: `evidence/iter1/pytest-evaluator.txt`.

Result: `5 failed, 2726 passed, 2 skipped, 4 xfailed, 7 warnings
in 2516.11s (0:41:56)` — same five names and counts as
`evidence/iter1/pytest-final.txt`.

Accepted pre-existing failures, checked on this tree and on base
`96b5639d8` at
`/tmp/claude-1000/-home-coder-personal-agent-platform/88164f66-cf3f-402a-97cb-fb9f6f3cb4eb/scratchpad/od-base`
(`uv run --project <od-base> pytest -q <those five>`):

- `tests/runner/test_uc_function.py` four cases:
  `ModuleNotFoundError: No module named 'databricks'` (env/optional extra).
- `test_codex_native_model_options_follow_labeled_foreign_bridge`:
  GET options 200; `model_change` on an owner-bound parent bridge
  returns 503 (`Codex-native settings update requires a loaded Codex
  bridge`) vs asserted 204. Identical assertion on the base commit
  (failure at lifecycle.py:1140 there; :1186 here after the auto-create
  stub). Out of this mission's close/teardown scope.

No other failures. `ruff check` on touched product/test files: all
checks passed. Commit gate:
`python3 .../trio-shadow.py --mailbox loop-session-close --require-commits`
→ PASS.

## Acceptance (b)

Fake-transport `sys_session_close` (httpx.MockTransport; evidence
`evidence/iter1/fake-transport-close-wrappers.txt`) plus existing
unit tests:

- Tree-scoped child with unparsable title `"Lead pass"` closes for
  Claude, Codex and Cursor wrapper labels and POSTs `stop_session`
  (not `interrupt`). Tombstone from snapshot `sub_agent_name`.
- True top-level (`parent_session_id` None) still
  `session_not_a_sub_agent` with no PATCH. In-process path uses the
  same parent gate (`spawn.py` `_resolve_session_call`); a
  `config_path` registration anchor with no parent is that top-level
  case and stays non-closable.
- Codex `NativeInterruptRunner.stop`:
  `test_codex_stop_kills_tears_down_and_goes_idle` asserts kill_session
  → `_teardown_session_terminals` → `teardown_codex_native_app_server`.
  Cursor uniform stop kills via `cursor_native_bridge.kill_session`.
- Shared leftover SIGKILL: `omnigent/native_tmux_kill.py`
  `kill_session_with_escalation` is the only leftover helper; Claude,
  Codex and Cursor `kill_session` all call it. Escalation unit tests
  exist in all three bridge test files.
- Reaper: scout disproved listing-drop; actual cause is stale
  `"running"` + TUI `window_activity` after `release`.
  `test_busy_orphaned_stale_running_fresh_activity_no_clients_is_reapable`
  reproduces that orphaning (busy is False → reapable) and passes with
  `_pane_is_busy_after_harness`. Live harness still busy; attached
  client still busy. `process_manager.py` correctly untouched.
- `codex-advertise-guard` is a real fix: after stop-routing advertised
  `tmux.json`, `resource_registry.terminal_registry` AttributeError
  aborted Codex auto-create *after* a successful launch and tore down
  the app-server. `getattr(..., None)` skips advertise when missing.
  Lifecycle/options stubs keep tests that seed bridge state from
  running auto-create (they are not testing launch); that is fixture
  isolation, not silencing the getattr bug. Remaining labeled-bridge
  503 is pre-existing on `96b5639d8`.

## Diff risk (c) `git diff 6220807f3..HEAD -- omnigent`

Intended behaviour for all native close users (not Trio-only):
unparsable in-tree children close; Cursor/Codex close POSTs
`stop_session`; Codex stop hard-kills tmux + terminals + app-server;
orphaned native panes after harness `release` are reapable unless a
tmux client is attached. Failed stop still tombstones. Missing Codex
`tmux.json` is best-effort.

Error handling stays fail-closed on tree/top-level gates; stop POST
is `suppress(Exception)`. New module `native_tmux_kill.py` is 147
lines. Undeclared PLAN touches (`orchestration.py` advertise,
`native_tmux_kill.py`) are the stop/kill slices, with tests. No
unrelated harness files without tests. `sys_cancel_task` still
interrupts Codex (close-only scope; noted in REPORT).

## REPORT vs tree (d)

REPORT slice SHAs match `git log`. Reaper hypothesis text matches the
code and scout log. Evidence `sk-test` / `auth_token_factory=None`
strings are pytest fixtures and traceback fields, not live
credentials. No private keys.

## Guidance for next iteration

None. Product commits already on `trio-v0.12.0-fixes-close`. Adoption
into `/home/coder/omnigent` is the user's decision.

commit: cc40d1513cef1cd39356310e78d0996a4f163e46
commit: 97d84a2fc62b20c1a219ed9babe91ce245bd966b
commit: 208aada58dae06da503e766dca0297549d85ff86
commit: eea0c68622f0d7569e8b1998c965ae074d75fea2
commit: d18393174929f7c19455ec63bdb30a48f82a7b15
commit: ec696c5fc9e9024e83e6f4334f4cd4eec2ad38a8
