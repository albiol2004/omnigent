# v21 behaviour map (GOAL DoD 4)

Node ids verified with `pytest --collect-only -q <id>` on this tree. Source:
`docs/v17-report.md` §4, updated for v0.21.0rc1 class names and the #10251
interaction test.

| behaviour | covering node ids | notes |
|---|---|---|
| cursor receipt gate | `tests/test_cursor_native_completion_receipt.py::test_receipt_binds_prompt_hash_and_counts`, `::test_turn_end_is_stamped_with_the_store_position`, `::test_matching_stops_bind_a_clean_turn_and_queued_turns`, `::test_skip_is_persisted_before_the_cursor_passes_it`; `tests/server/integration/test_input_fence.py::test_reserved_labels_cannot_be_forged`, `::test_receipt_binding_is_stored_in_its_own_label`, `::test_receipt_persisted_for_owner_and_monotonic`; `tests/server/integration/test_cursor_receipt_binding_e2e.py::test_queued_repost_verifies_only_after_both_copies_end`, `::test_single_late_turn_verifies_once_it_ends`, `::test_restart_mid_pass_keeps_the_lost_row_unacked` | completion receipts + reserved labels |
| cursor isolation | `tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_user_mcp_has_omnigent_server`, `::test_project_file_aliasing_the_user_file_is_never_written`, `::test_account_home_is_never_written`; `::TestHooksConfig::test_write_hooks_config_preserves_existing_hooks`; `::TestCompletionReceiptHookGate::test_write_hooks_config_skips_home_workspace`, `::test_write_hooks_config_skips_account_home`, `::test_arm_refused_drops_stale_epoch_and_keeps_user_hooks`, `::test_workspace_that_is_home_refuses_receipts`, `::test_account_home_is_refused_even_when_home_env_differs`; `::TestCursorLaunchAdmission::test_home_workspace_is_refused`, `::test_repo_subfolder_is_refused`, `::test_alias_to_a_repo_subfolder_is_refused`, `::test_folder_inside_home_repo_is_refused`, `::test_own_repo_inside_home_repo_is_admitted`; `tests/server/integration/test_cursor_receipt_binding_e2e.py::test_workspace_that_is_home_holds` | never write user `~/.cursor` hooks/mcp.json; refuse home workspace / repo subfolder |
| input fence | `tests/server/integration/test_input_fence.py::test_verified_fence_rejects_every_input_api_and_persists`, `::test_new_input_racing_a_close_is_refused`, `::test_open_is_runner_first_and_fails_closed`, `::test_injection_after_receipt_fails_verification`, `::test_crash_mid_close_reconciles_on_retry`; `tests/test_cursor_native_completion_receipt.py::test_fenced_pane_refuses_injection_before_touching_tmux`, `::test_fence_close_linearizes_against_concurrent_injections` | runner-first fence |
| stop-routing + kill escalation (#10251) | `tests/server/test_v21_shared_runner_kill_on_close.py::test_stop_subagent_child_kills_native_harness_without_stopping_shared_host_runner`, `::test_stop_top_level_host_session_stops_owned_host_runner`; `tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_codex_native_hard_stops_without_marker`, `::test_events_stop_session_on_native_kills_tmux_and_publishes_idle`, `::test_events_stop_session_on_native_returns_503_when_kill_fails`; `tests/runner/test_native_interrupt_runner.py::test_uniform_stop_kills_tears_down_and_goes_idle`, `::test_uniform_stop_kill_failure_returns_503_without_idle`; `tests/tools/builtins/test_sys_session.py::test_close_accepts_child_with_unparsable_title`, `::test_close_marks_closed_and_tombstones_internal_title`; `tests/test_cursor_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill`; `tests/harnesses/codex_native/test_codex_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill`; `tests/harnesses/claude_native/test_claude_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill` | child native kill requested; shared host runner left up |
| Codex manual compact | `tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_sends_thread_compact_start_and_reports_accepted_not_completed`, `::test_completion_event_resolves_completed`, `::test_missing_completion_times_out_uncertain_without_resend`, `::test_active_turn_is_busy_and_sends_nothing`, `::test_forwarder_live_stream_settles_manual_compact_and_still_mirrors`; `tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_sends_thread_compact_start`, `::test_events_compact_on_codex_native_409_while_turn_active`, `::test_codex_native_compact_failure_clears_spinner_without_completion` | app-server `thread/compact/start` |
| claude_native hook bridge + hook TMPDIR | `tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_always_registered_hook_commands_match_hook_cli_parser`, `::test_injected_optional_hook_commands_match_hook_cli_parser`; `tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_defaults_to_unix_socket`, `::test_http_ingress_refuses_symlinked_socket_root`, `::test_http_ingress_reaps_sockets_of_dead_owners`, `::test_generated_claude_subprocesses_pin_runner_tmpdir`, `::test_augment_claude_args_injects_mcp_and_hooks` | `env TMPDIR=` + `-m omnigent.harnesses.claude_native.hook` + `--bridge-dir` |

<!-- ids:start -->
# cursor receipt gate
tests/test_cursor_native_completion_receipt.py::test_receipt_binds_prompt_hash_and_counts
tests/test_cursor_native_completion_receipt.py::test_turn_end_is_stamped_with_the_store_position
tests/test_cursor_native_completion_receipt.py::test_matching_stops_bind_a_clean_turn_and_queued_turns
tests/test_cursor_native_completion_receipt.py::test_skip_is_persisted_before_the_cursor_passes_it
tests/server/integration/test_input_fence.py::test_reserved_labels_cannot_be_forged
tests/server/integration/test_input_fence.py::test_receipt_binding_is_stored_in_its_own_label
tests/server/integration/test_input_fence.py::test_receipt_persisted_for_owner_and_monotonic
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_queued_repost_verifies_only_after_both_copies_end
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_single_late_turn_verifies_once_it_ends
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_restart_mid_pass_keeps_the_lost_row_unacked
# cursor isolation
tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_user_mcp_has_omnigent_server
tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_project_file_aliasing_the_user_file_is_never_written
tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_account_home_is_never_written
tests/test_cursor_native_bridge.py::TestHooksConfig::test_write_hooks_config_preserves_existing_hooks
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_write_hooks_config_skips_home_workspace
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_write_hooks_config_skips_account_home
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_arm_refused_drops_stale_epoch_and_keeps_user_hooks
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_workspace_that_is_home_refuses_receipts
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_account_home_is_refused_even_when_home_env_differs
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_home_workspace_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_repo_subfolder_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_alias_to_a_repo_subfolder_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_folder_inside_home_repo_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_own_repo_inside_home_repo_is_admitted
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_workspace_that_is_home_holds
# input fence
tests/server/integration/test_input_fence.py::test_verified_fence_rejects_every_input_api_and_persists
tests/server/integration/test_input_fence.py::test_new_input_racing_a_close_is_refused
tests/server/integration/test_input_fence.py::test_open_is_runner_first_and_fails_closed
tests/server/integration/test_input_fence.py::test_injection_after_receipt_fails_verification
tests/server/integration/test_input_fence.py::test_crash_mid_close_reconciles_on_retry
tests/test_cursor_native_completion_receipt.py::test_fenced_pane_refuses_injection_before_touching_tmux
tests/test_cursor_native_completion_receipt.py::test_fence_close_linearizes_against_concurrent_injections
# stop-routing + kill escalation (#10251)
tests/server/test_v21_shared_runner_kill_on_close.py::test_stop_subagent_child_kills_native_harness_without_stopping_shared_host_runner
tests/server/test_v21_shared_runner_kill_on_close.py::test_stop_top_level_host_session_stops_owned_host_runner
tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_codex_native_hard_stops_without_marker
tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_native_kills_tmux_and_publishes_idle
tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_native_returns_503_when_kill_fails
tests/runner/test_native_interrupt_runner.py::test_uniform_stop_kills_tears_down_and_goes_idle
tests/runner/test_native_interrupt_runner.py::test_uniform_stop_kill_failure_returns_503_without_idle
tests/tools/builtins/test_sys_session.py::test_close_accepts_child_with_unparsable_title
tests/tools/builtins/test_sys_session.py::test_close_marks_closed_and_tombstones_internal_title
tests/test_cursor_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill
tests/harnesses/codex_native/test_codex_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill
tests/harnesses/claude_native/test_claude_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill
# Codex manual compact
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_sends_thread_compact_start_and_reports_accepted_not_completed
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_completion_event_resolves_completed
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_missing_completion_times_out_uncertain_without_resend
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_active_turn_is_busy_and_sends_nothing
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_forwarder_live_stream_settles_manual_compact_and_still_mirrors
tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_sends_thread_compact_start
tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_409_while_turn_active
tests/runner/test_app_sessions_native_events_options.py::test_codex_native_compact_failure_clears_spinner_without_completion
# claude_native hook bridge + hook TMPDIR
tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_always_registered_hook_commands_match_hook_cli_parser
tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_injected_optional_hook_commands_match_hook_cli_parser
tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_defaults_to_unix_socket
tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_refuses_symlinked_socket_root
tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_reaps_sockets_of_dead_owners
tests/harnesses/claude_native/test_claude_native_bridge.py::test_generated_claude_subprocesses_pin_runner_tmpdir
tests/harnesses/claude_native/test_claude_native_bridge.py::test_augment_claude_args_injects_mcp_and_hooks
<!-- ids:end -->

## Excluded id (cwd-depth environment artifact)

`tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_advertises_absolute_socket_path`
(upstream test) is deliberately not in the id list: it builds a socket root
with `os.path.relpath` from the cwd, so it fails from checkouts nested deeper
than the pytest tmp dir (e.g. `.claude/worktrees/...`) on pristine rc1 too
(Evaluator it1 evidence; `docs/v21-evidence/env-artifacts.txt`). The claude
hook bridge + TMPDIR behaviour keeps 7 depth-independent ids.

## Revert-sanity (re-checked by the Lead in the it2 review call)

Each mutation was applied to `omnigent/server/routes/_sessions/helpers.py`,
the test file run, and the file restored with `git checkout`; never committed.

1. `_owns_host_runner` returns `True` for every session (as if #10251 were
   reverted): `test_stop_subagent_child_kills_native_harness_without_stopping_shared_host_runner`
   fails (`host_stop.assert_not_awaited()` — the shared host runner would be
   stopped) → `1 failed, 1 passed`.
2. `_stop_session_via_runner_impl` returns `True` without POSTing
   `stop_session` (fork kill-on-close forward removed): both tests fail (no
   `/v1/sessions/<id>/events` `stop_session` recorded) → `2 failed`.
3. (builder) `_owns_host_runner` returns `False`:
   `test_stop_top_level_host_session_stops_owned_host_runner` fails
   (`host_stop.assert_awaited()`).

No product defect: #10251 and kill-on-close still coexist. No `omnigent/` fix.
