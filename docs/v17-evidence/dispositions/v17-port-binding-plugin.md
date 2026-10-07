# v17-port-binding-plugin — disposition notes

Re-port of the cursor chat-binding, plugin-dir/r17 groups and the v16 report onto v0.17.0
(18 v16 commits, `git cherry-pick -x`, original order, base a13bf28a6).

Conflicts (2), both resolved keeping upstream v0.17.0 and layering the fork change:
- `80eb3acbe` `cursor_native/permissions.py`: import block. Upstream (#8516 a16334f78 era) imports
  `_discover_store, _read_blob_rows`; kept and added `bound_store_path`. The fork's `env_truthy`
  import was dropped: its only user (`_YOLO_STALE_SURFACES_CARD`) does not exist on v0.17.0, so the
  import would be an unused F401.
- `5f71a8390` `cursor_native/status.py` `record_turn_end`: kept upstream's `hook_status`
  (completed/aborted/error) handling from #8516 and replaced the trailing `mkdir` with the fork's
  `ensure_private_dir(bridge_dir)`; `write_posted_count` took the fork `ensure_private_dir` over upstream's docstring.

`3add21910` (bridge MCP N11) and `62baa7157` (host/connect.py env passthrough) applied cleanly; upstream
Unix-socket MCP ingress (claude_native bridge) and host changes are untouched.

Pristine-proven failures (also fail on `v0.17.0`, excluded via `--deselect`; all in tests/host/test_connect.py,
pristine result `6 failed, 256 passed`): `test_handle_model_options_serves_the_claude_catalog`,
`test_run_host_process_announces_session_log_dir_on_start`,
`test_handle_model_options_serves_codex_probe_rows_and_caches`,
`test_handle_model_options_serves_claude_sdk_endpoint_listing`,
`test_handle_model_options_claude_sdk_rides_the_probe_when_endpoints_list_nothing`,
`test_model_options_frame_replies_off_the_receive_loop`.

Targeted check (with those deselects): `1425 passed, 6 deselected`. e2e files collect (11 tests, not run).

| v16 sha | fork sha | subject | disposition | new sha | notes |
|---|---|---|---|---|---|
| 8264557b8 | 354163318 | never bind a session to another workspace's chat store | ported | 9f7220a42 | |
| 80eb3acbe | e3778c9bf | pin each fresh launch to a pre-minted chat id | adapted | 24508959a | permissions.py import conflict |
| 2a6546fc9 | 041d74306 | bind a discovered chat only when this session's pane owns it | ported | 433df86ae | |
| 512d4d4a6 | 4032dde9d | warn when a launch overwrites a live sibling's hooks/MCP slot | ported | 197a2cb17 | |
| 8c4a4290c | n/a (v16-authored) | disposition notes for the chat-binding port | ported | b6962e4af | historical doc |
| f910eac65 | da6045a2e | opt-in per-launch --plugin-dir hooks/MCP config | ported | 3c7252f3a | |
| 62baa7157 | dd33637ec | let OMNIGENT_CURSOR_PLUGIN_DIR reach host-spawned runners | ported | a4269368c | host/connect.py |
| 523b64788 | d5bd4eb95 | never delete the project mcp.json when clearing a dead entry | ported | bab692622 | |
| a11446be3 | 93cbb7314 | refuse plugin-route launches cursor-agent would run without the plugin | ported | 10ce2b158 | |
| dfd54048c | b5d69a50c | plugin-route turn no longer fires a live sibling's project usage hook | ported | 1ee4c7d22 | |
| 5f71a8390 | 3dd01eab0 | owner-only bridge dir recreation; grace for mid-launch siblings | adapted | 4596497c7 | status.py conflict |
| d70bafafc | b9f3291bf | fix pyrefly errors in plugin-dir unit tests | ported | af4c6a098 | |
| fa967d38b | 1c1dcd7e2 | gate the plugin-dir real-CLI e2e; cover sibling-hook skip | ported | cec186bc5 | |
| 53901f3ec | ec2e5f2fc | cursor_project_key matches CLI directory mangling (r17 N16) | ported | 69b9e324d | |
| 3add21910 | e74900a77 | bridge MCP refuses a parent bound to another bridge (r17 N11) | ported | 7c66bd251 | claude_native/bridge.py upstream lines kept |
| 0a2b9b236 | 318264335 | receipt gate scans passthrough and installed plugin stop hooks (r17 N12) | ported | 66471010f | |
| 855d54cbd | n/a (v16-authored) | disposition notes for the plugin-dir/r17 port | ported | e64f72d1b | historical doc |
| cef9794cf | n/a (v16-authored) | v0.16.0 re-port report and after-port evidence | ported | 0cd5d45b4 | historical doc |
