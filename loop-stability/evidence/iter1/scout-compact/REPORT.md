# Scout compact-on-fork — captured from Luna scout (gpt-5.6-luna-max)

See trioctl scout stdout. Summary:

Writes for builder:
- `omnigent/fork_compact.py` ~160-206 (short-history protected window)
- `omnigent/codex_native.py` ~2081-2108 (summary-only CompactionData
  → Codex replacement_history)
- `tests/server/routes/test_fork_compact.py` ~170-211, 295-375
- `tests/test_codex_native.py` ~10163-10240
- optionally `tests/server/routes/test_sessions_fork.py` ~853-1015
  (claude-native → codex-native labels)
- optionally `routes_core.py` ~2534-2665 only if async failure race
  is confirmed

Do not touch `codex_native_app_server.py` (writer slice landed).
