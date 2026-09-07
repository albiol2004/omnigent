# compact-on-fork-cross-harness

- Capped fork `recent_window` to actual response groups so a
  one-turn oversized fork can still produce a summary marker.
- Codex rollout synthesizes replacement history from a summary-only
  compaction marker.
- Luna builder: gpt-5.6-luna-max.
- Lead re-ran `test_fork_compact.py` after review.
