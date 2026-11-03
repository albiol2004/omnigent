# v17-port-close — v14 "close" group re-ported onto v0.17.0

Conflicts and how they were resolved:

- **48d792284 kill-on-close** — `claude_native/bridge.py` import block (upstream `kiro_bridge` import kept; the
  fork's `from omnigent.inner import _proc` added beside it; upstream #9005/#9008/#8672/#8572 untouched) and
  `tests/runner/test_native_interrupt_runner.py` (upstream's no-optimistic-`cancelled` assertion kept; the fork's
  new `test_claude_stop_cancels_forwarder_after_teardown` appended, pointed at
  `omnigent.harnesses.claude_native.bridge`).
- **de03a352c / d69671640 (cursor queue-aware yolo, stale markers)** — dropped: upstream #8516 (a16334f78)
  rewrote the same yolo accept path and already delivers both behaviours (see rows).
- **39e45d8d4** — dropped: v0.17.0 has no `_resolve_agent_spec` in `_sessions/helpers.py` (so the re-export would
  be an ImportError) and d4f6816bf's alias is the net result anyway. Upstream's removal of the
  `_reset_runner_resources_after_switch_impl` re-export was kept when d4f6816bf conflicted.
- **d8aa8058d** — hunk still belongs in the nested `_codex_native_bridge_state_for_session` in `runner/app.py`
  (v0.17.0's `native_controls.py` only calls it with `action="model options"`); no move needed. Only a ruff-format
  adaptation commit was added (also reflows two `tool_dispatch.py` hunks from cfeb9ee10).
- Disposition notes `a902a5ddc` (v16 notes file + alias moved below imports, lifecycle-test v0.16 assertion
  tweaks) applied cleanly.

Pre-existing failures (same node ids fail on pristine v0.17.0, detached worktree, `15 failed, 50 passed` for
`tests/runner/test_app_sessions_native_events_lifecycle.py`); deselected from the targeted check:

- `::test_events_codex_native_settings_change_uses_thread_settings_update[model_change|effort_change|plan_mode_change]`
  (pristine: `codex-native model_change must return 204; got 503 codex_native_settings_update_failed`)
- `::test_claude_native_model_options_use_session_launch_catalog[False]`
- `::test_claude_native_model_options_serves_probe_rows_after_pending`
- `::test_events_interrupt_on_codex_native_uses_turn_interrupt_without_marker`
- `::test_events_interrupt_codex_side_chat_leaves_parent_turn_running[running|idle|newer_turn|missing_turn|rpc_failure]`
- `::test_events_stop_session_on_codex_native_uses_turn_interrupt_without_marker`
- `::test_events_stop_on_codex_native_cancels_mcp_startup_without_active_turn[interrupt|stop_session]`
- `::test_events_interrupt_on_codex_native_with_turn_and_mcp_stops_both`

| v16 sha | fork sha | subject | ported/adapted/dropped | new sha | notes |
| --- | --- | --- | --- | --- | --- |
| 48d792284 | 5837d559d | kill-on-close: stop the target harness on sys_session_close | adapted | 8f7f924c2 | Conflicts in bridge.py imports and test_native_interrupt_runner.py, resolved as above. |
| 1da2e0ee1 | (v16 follow-up) | adapt kill-on-close pick (wrapper label import, bridge module path) | ported | fb38228b0 | Clean; still needed on v0.17.0 (tool_dispatch import). |
| de03a352c | 49da161cd | cursor-native: queue-aware yolo auto-accept for batched tools | dropped | - | Superseded by upstream a16334f78 (#8516): `auto_accept_available`/`approval_waiting` gate allows one accept per poll and non-visible gates never spend retry budget. Covered by `tests/test_cursor_native_permissions.py::test_supervise_transcript_yolo_waits_through_stale_pending_burst[prompt\|transcript\|backoff]`. |
| d69671640 | a60a600d7 | cursor-native: drop phantom cards for stale yolo markers | dropped | - | Superseded by a16334f78: pending marker with no visible accept hint -> no key, no card. Covered by `::test_supervise_transcript_yolo_never_types_when_no_prompt_on_screen` and the burst test above. |
| d8aa8058d | 3444f699f | codex-bridge-owner: serve Codex model options from a labeled live bridge | adapted | 033e6837e | Clean pick; hunk verified in the function that still owns it (`app.py`), format fixed in 2f74c179a. Test `test_codex_native_model_options_follow_labeled_foreign_bridge` passes. |
| ff86cbba7 | 4dfbe128d | compact-on-fork-cross-harness: replay summary-only Codex compaction markers | ported | 561681c55 | Clean; test landed in `tests/harnesses/codex_native/test_codex_native.py`. |
| 39e45d8d4 | 69db59457 | sessions: re-export _resolve_agent_spec | dropped | - | Name no longer exists in helpers on v0.17.0; superseded by the alias added by d4f6816bf. |
| d4f6816bf | 70d652bbc | session-contract: alias _resolve_agent_spec to _resolve_subagent_spec | adapted | 669e05bfd | Conflict on the helpers re-export block; upstream's removal of `_reset_runner_resources_after_switch_impl` kept. |
| cfeb9ee10 | c7a454a78 | close-guard: close tree-scoped children with unparsable titles | ported | ab9d2c7cb | Clean. |
| a902a5ddc | (v16 only) | disposition notes for v14 close slice | ported | 2eed26a21 | Clean; adds the v16 notes file and moves the alias below imports. |
| - | - | ruff-format fork hunks in runner/app.py and tool_dispatch.py | adapted | 2f74c179a | Adaptation commit (formatting only). |
