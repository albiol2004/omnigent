# v17-port-receipts — cursor completion receipts / input fence

Ported `v0.16.0..v16/trio-v0.16.0-fixes` cursor-receipt group onto v0.17.0, in original order, with
`git cherry-pick -x`. Evidence for the v16 side: `docs/v16-evidence/dispositions/port-cursor-receipts.md`.

## Conflicts and how they were resolved (all in 5f21ceaf5 unless noted)

- `cursor_native/forwarder.py` — upstream #8516 (a16334f78) posts one `external_session_status` per
  stop marker with a `turn_outcome` (completed/cancelled/failed; damaged markers retried then
  reported failed) via `pending_turn_end`. **Kept.** Fork layer: the same post also carries the opt-in
  `turn_end` receipt (`_post_external_session_status(..., turn_outcome=None, turn_end=None)`, both
  optional, `turn_end` passed only when a receipt exists), receipt-only refresh posts (delayed
  transcript flush) go out as `idle` with no `turn_outcome`, and the receipt snapshot is taken at the
  start of each poll as before.
- `cursor_native/status.py` — upstream's leading-blank-line marker + retained hook `status` kept for
  both the legacy (no-epoch) marker and the receipt marker; the epoch path adds the fork's
  epoch/turn_seq/inject-count fields. Docstring merged again in 4b580b109.
- `runner/app.py` — v0.17.0 split the native control handlers into `runner/native_controls.py`. The
  fork's `_handle_cursor_native_input_fence` lives there now (new `NativeControls` field
  `handle_cursor_native_input_fence`); `app.py` only binds it and routes `body_type == "input_fence"`.
- `server/routes/_sessions/helpers.py` — `_reject_server_reserved_label_seed` keeps upstream's
  `WORKTREE_ROOT_LABEL_KEY` check and adds the fork's `SERVER_RESERVED_LABELS` check.
- `server/routes/sessions/routes_events.py` — upstream's codex side-chat fork-lost guard kept; the
  fork's `input_fence` event branch follows it.
- 4b580b109 — docstring-only conflict in `status.record_turn_end`.

## Test adaptations (separate commits)

- `auth_client` moved to `tests/server/conftest.py` upstream (#8628); fork e2e tests import only
  `auth_app`/helpers from `test_sessions_permissions` (its strict `auth_app` override still feeds the
  conftest `auth_client`).
- Legacy stop markers now start with a blank line and keep `status`: the fork's legacy-marker test
  filters blank lines and expects `{ts, generation_id, status}`; marker readers in the e2e tests skip blanks.
- The receipt test's status recorder accepts upstream's `turn_outcome` kwarg.
- Forwarder passes `turn_end=` only when a receipt exists so upstream's `test_cursor_native_status.py`
  recorder (no `turn_end` kwarg) keeps working.

## Pristine-proven deselects

None.

| v16 sha | fork sha | subject | ported/adapted/dropped | new sha | notes |
|---|---|---|---|---|---|
| 5f21ceaf5 | 99d8a5884 | feat(cursor-native): opt-in completion receipts and durable input fence | adapted | b110581d4 | conflicts in forwarder, status, app.py (→ native_controls.py), helpers, routes_events; test adaptations in cdff1f729, 68355aa71 |
| 1cff84c5b | – (v16-only) | slice(baseline-suite): focused-suite runner and pristine v0.16.0 baseline | ported | 0a0489d45 | historical docs/script, as-is |
| 1ecb111fc | 6bc9c6923 | fix(cursor-native): bind receipt turn ends to prompts; durable skipped rows | ported | 6dfb7d57c | clean; test fixes in cdff1f729 |
| 2ed704fc8 | 0944602eb | test(cursor-native): serialize mixed binding reasons in e2e evidence dumps | ported | 966a8e8ee | clean |
| 61812adf7 | 3b45e5573 | fix(cursor-native): withhold completion receipts when a foreign stop hook is configured | ported | e0849ba33 | clean |
| 4b580b109 | fa16a055d | fix(cursor-native): bind receipt stops to this chat; scope owned stop hooks | adapted | e90741969 | docstring conflict in status.record_turn_end |
| d0db96552 | fb085ca12 | fix(cursor-native): abort launch when a stale receipt epoch cannot be removed | ported | c2d486a61 | clean |
| b19f3fbf2 | – (v16-only) | slice(port-cursor-receipts): disposition notes | ported | f824ffc1d | historical, as-is |
| f51c5e01f | – (v16-only) | slice(patch-refresh): child-reasoning-effort patch for v0.16.0 | ported | 74ee1aa8b | historical patch, as-is |

Adaptation commits: cdff1f729 (tests for v0.17.0 APIs), 68355aa71 (forwarder post call shape).
