# v21-port-receipts — v17 "receipts" group (#23-34) re-ported onto v0.21.0rc1

Method: `git cherry-pick -x` of v17 commits #23-34 in original order on top of v21-port-stop. Taken over by the Lead
(the builder's harness denied the cherry-pick of #26; nothing from the builder was integrated).

| # | v17 sha | subject | disposition | new sha | notes |
|---|---|---|---|---|---|
| 23 | b110581d4 | feat(cursor-native): opt-in completion receipts and durable input fence | adapted | f43bf418e | 4 conflicts, see below |
| 24 | 0a0489d45 | slice(baseline-suite): focused-suite runner and pristine v0.16.0 baseline | ported | db3580761 | historical evidence |
| 25 | 6dfb7d57c | fix(cursor-native): bind receipt turn ends to prompts; durable skipped rows | adapted | e89407bd7 | 1 conflict, see below |
| 26 | 966a8e8ee | test(cursor-native): serialize mixed binding reasons in e2e evidence dumps | ported | 05774790e | clean |
| 27 | e0849ba33 | fix(cursor-native): withhold completion receipts when a foreign stop hook is configured | ported | 4b2b72d26 | clean |
| 28 | e90741969 | fix(cursor-native): bind receipt stops to this chat; scope owned stop hooks | ported | cf37c9605 | clean |
| 29 | c2d486a61 | fix(cursor-native): abort launch when a stale receipt epoch cannot be removed | ported | b0ec78f26 | clean |
| 30 | f824ffc1d | slice(port-cursor-receipts): disposition notes | ported | c41d695ba | historical evidence |
| 31 | 74ee1aa8b | slice(patch-refresh): child-reasoning-effort patch for v0.16.0 | ported | b6850163c | historical patch |
| 32 | cdff1f729 | slice(v17-port-receipts): adapt receipt tests to v0.17.0 APIs | ported | d2e81b624 | clean |
| 33 | 68355aa71 | slice(v17-port-receipts): post receipt kwarg only when a receipt exists | ported | 6b9bf6bf1 | clean |
| 34 | 5ce00dcde | slice(v17-port-receipts): disposition notes | ported | 610e8fa07 | historical evidence |

## Conflicts and how they were resolved (upstream v0.21.0rc1 kept, fork layered on top)

- **#23 `runner/native/orchestration.py`** — upstream added `native_usage_baseline` to the shared Pi/Cursor launch config
  (`_PiNativeLaunchConfig`, also used by cursor-native); kept it and added the fork's `completion_receipts` field and
  constructor argument next to it.
- **#23 `server/routes/_sessions/common.py`** — upstream split `_ALLOWED_EVENT_TYPES` into
  `CLIENT_SESSION_EVENT_TYPES` (client-posted, advertised by `/v1/info`) and `_RUNNER_SESSION_EVENT_TYPES` (hosts and
  forwarders only). `input_fence` is an owner-posted client event (trio driver), so it is added to
  `CLIENT_SESSION_EVENT_TYPES` only; upstream's split is kept as is.
- **#23 `server/routes/_sessions/helpers.py`** — `_reject_server_reserved_label_seed`: kept upstream's new sandbox
  profile / MCP selection / scheduled-task / created-by / side-chat label guards and added the fork's
  `SERVER_RESERVED_LABELS` (input-fence receipt labels) guard after them.
- **#23 `server/routes/sessions/routes_events.py`** — upstream now tracks `in_flight` for `message` and
  `session_message`; kept that and added the fork's `admission=in_flight` argument to both dispatch call sites. In
  `_post_session_event_inner` upstream rewrote the authorization block (external-transcript auth, peer
  `session_message` orchestration source, native-shell owner check, native-mode-change owner check); all kept, and the
  fork's `_input_fence.admit_input(...)` admission gate runs after it (before `in_flight` is marked), so a fenced
  session still refuses input only after the caller is authorized.
- **#25 `server/routes/_sessions/orchestration.py`** — `_dispatch_session_event_to_runner`: upstream added the
  MCP-registry support check, `disconnect_outcome.note_user_turn` and the generalized Codex side-chat thread check; kept
  all and put the fork's `_input_fence.refuse_if_fenced(...)` first (server-internal dispatches bypass the route gate).

## Checks

- `pytest -n 4 tests/test_cursor_native_completion_receipt.py tests/test_cursor_native_bridge.py
  tests/server/integration/test_input_fence.py tests/server/integration/test_cursor_receipt_binding_e2e.py
  tests/server/integration/test_cursor_receipt_epoch_clear_e2e.py tests/runner/test_app_sessions_native_terminals_autocreate.py`
  → `TRIO_TEST: PASS rc=0 passed=326 failed=0` (after #34).
- ruff: the remaining format/RUF100 findings in `tests/test_cursor_native_completion_receipt.py` /
  `tests/server/integration/test_input_fence.py` are the ones v17 fixed later in #72 (`8001e9de9`), picked in order in
  v21-port-tail.

## Pristine-proven deselects

None (`docs/v21-evidence/deselects/v21-port-receipts.args` is empty).
