# Iteration 1 notes
- Added coverage for an active Codex writer during thread preload.
- Added coverage proving unrelated resume errors still raise.
- Parsed RuntimeError dict representations with `ast.literal_eval`.
- Treated only JSON-RPC `-32600` active-writer errors as success.
- Preserved the existing `finally` close behavior.
- The pre-fix run failed 1 test and passed 2 tests.
- The final preload run passed 3 tests; output is in `pytest.txt`.
