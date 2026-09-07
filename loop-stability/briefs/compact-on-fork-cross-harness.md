# Builder brief — slice compact-on-fork-cross-harness

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent`. Mailbox `loop-stability/`. Iteration 1.

Do NOT read whole large files. Do NOT commit. No live Codex login.
Do NOT edit `codex_native_app_server.py`, `runner/app.py`, or
`runner/native/orchestration.py`.

PATH: `PATH=/home/alex/omnigent/.venv/bin:$PATH`

Scout (read-only) found two deterministic seams:

1. `omnigent/fork_compact.py` ~160-206: short histories cannot
   compact because the default five-response window protects
   everything → `Compaction did not produce a valid summary`.
2. `omnigent/codex_native.py` ~2081-2108: server `CompactionData`
   with `summary` but empty `compacted_messages` emits
   `replacement_history=[]`. Claude has a synthetic summary
   fallback (`claude_native.py` ~4420-4444); Codex does not.

## Writes (only)

- `omnigent/fork_compact.py`
- `omnigent/codex_native.py`
- `tests/server/routes/test_fork_compact.py`
- `tests/test_codex_native.py` (append near ~10163 only; do not
  rewrite the preload tests at ~460-589)

Optional extra test only (no extra product files unless the test
proves a bug):
- `tests/server/routes/test_sessions_fork.py` claude-native →
  codex-native label gating (~853-1015)

## Test-first

1. Real one-turn oversized fork with mocked summary LLM; expect a
   compaction marker (fail first if the protected window blocks).
2. `_codex_rollout_records_from_session_items` with summary-only
   marker; Codex replacement history must contain the summary
   (not empty).
3. Run tests, then implement the smallest fix:
   - fork-specific smaller protected window so a summary boundary
     exists on short histories
   - Codex: synthesize replacement history from `summary` when
     `compacted_messages` is empty (mirror Claude)

```
cd /home/alex/omnigent && uv run pytest -q \
  tests/server/routes/test_fork_compact.py \
  tests/test_codex_native.py -k 'fork_compact or compaction or rollout'
```

Narrow if needed. Capture
`loop-stability/evidence/iter1/compact-on-fork-cross-harness/pytest.txt`
and NOTES.md + MANUAL.md only if live Codex is still required.
Lines < 88 chars.
