# Evaluator iter-1 probes (pin c813e0b82)
- overlap_removed.py: second-path DoD-2 check (only #8516 forwarder lines, re-shaped not lost; verified by reading forwarder.py:1900-1966).
- table_trailers.py: DoD-1 table vs -x trailers -> 66 rows, bad=[].
- v16 yolo graft: the 4 tests de03a352c/d69671640 added (from v16 tests/test_cursor_native_permissions.py) were grafted onto a
  scratch copy of the tip: queue_all_accept_in_turn_zero_cards PASSES; the other 3 depend on fork-only
  _YOLO_ACCEPT_MAX_ATTEMPTS/_YOLO_ACCEPT_STALE_CEILING_S/OMNIGENT_CURSOR_YOLO_STALE_SURFACES_CARD, which upstream #8516 replaced.
- Fault injection (scratch copy, reverted): repo-subfolder refusal disabled -> 3 bridge tests fail; admit_input no-op -> input-fence test fails.
