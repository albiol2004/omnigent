| fork sha | subject | disposition | new sha | notes / evidence |
| --- | --- | --- | --- | --- |
| 0b2c6ce82 | fix(codex-native): compact via app-server thread/compact/start, not tmux keys | adapted | 0b90fce3e | Context-only conflicts: in `codex_native/forwarder.py` the `observe_codex_manual_compact_event(event)` hook sits after v0.16.0's `parent_thread_id=target.thread_id, event=event` block in the live-event loop (upstream #8271 resume/compaction mirroring kept intact; the hook runs on live events only, not resume replay); `routes_events.py` import block keeps upstream `import itertools` and adds the fork's `import json`. Runner `_handle_codex_native_compact` reuses v0.16.0's `_codex_native_bridge_state_for_session` and `_background_tasks`. |
| 2a84483a5 | fix(codex-native): keep the manual-compact guard until Codex reports an outcome | ported | da17fdc20 | Clean pick on top of 0b90fce3e. |

Lead take-over (the driver did not dispatch this slice because port-cursor-isolation had not integrated). Targeted check on `trio/loop`:
`uv run --frozen pytest -q -p no:cacheprovider tests/test_codex_native_manual_compact.py tests/server/integration/test_sessions_compact.py tests/runner/test_app_sessions_native_events_options.py` → `118 passed in 37.45s`; `ruff check` on codex_native, runner/app.py, routes_events.py and both test files → `All checks passed!`.
