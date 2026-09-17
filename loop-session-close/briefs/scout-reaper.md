# Scout: pane-reaper vs process_manager.release

You are the Trio Scout. Read-only. Do not edit, commit, or
push. Workspace: `/home/coder/omnigent-dev`. Never touch
`/home/coder/omnigent`. Never bind port 6767. Never
`uv tool install`. Never start/stop omni.

Do **not** ingest whole `omnigent/runner/app.py` or
`omnigent/runner/tool_dispatch.py`. Use `sed -n 'START,ENDp'`.

## Question

Hypothesis: `HarnessProcessManager.release` (~1040-1109 in
`omnigent/runtime/harnesses/process_manager.py`) drops state
that `NativePaneReaper` listing (`native_panes()` in
`omnigent/terminals/registry.py` ~355) or busy-check depends
on, so after the ~1h idle harness reaper
(`_idle_reaper_loop` ~1420-1455) fires, native tmux panes
are never pane-reaped.

## Read exactly

1. `omnigent/runtime/harnesses/process_manager.py`
   `has_active_turn` ~980-990, `clear_in_flight` ~1025-1038,
   `release` ~1040-1109, `_close_entry` ~1334-1375,
   `_idle_reaper_loop` ~1420-1463. Does `release` pop
   `_in_flight_response_ids`? Does `_close_entry` touch
   terminals?
2. `omnigent/terminals/registry.py` `native_panes()` ~355-377.
   Does it consult process_manager?
3. `omnigent/runner/app.py` **only**:
   `_native_pane_status` init ~2460-2461
   pop on `delete_session` ~3870-3890
   pane-reaper wiring `_native_panes_for_reaper`,
   `_native_pane_is_busy`, `_reap_native_pane` ~10617-10686
   Who writes `_native_pane_status` (~2538)? Can it stay
   `"running"` after harness `release` with the pane still
   listed?
4. `omnigent/terminals/pane_reaper.py` classify/reap loop
   (whole module is small; OK to read).
5. Optional read-only grep of
   `/home/coder/.omnigent/logs/runner/runner-13839e479047419e8d446c50a2cca38f-20260915-140650-755225.log`
   for `reaping idle harness subprocess` vs pane-reaper
   lines for conv ids 6b7c939e, 55913c8a, cbd5aeac,
   1c0a0a25, 393b95d8 (never pane-reaped) vs 492e2359,
   b3dbfcd8 (were). Do not dump huge log chunks.

## Return

- Confirmed, disproved, or mixed — with file:line evidence.
- The smallest fix site if confirmed or the actual cause if
  not.
- How to write a unit test without the live server (fake
  process_manager + list_native_panes + is_busy).
