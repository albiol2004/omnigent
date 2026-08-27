# FINDINGS — rc-fork

Fork is an unbounded deep copy plus target-specific full-history render.
That is why a large source session breaks Claude Code (`Prompt is too long`
or equivalent) on the **first** fork turn.

## Ranked causes
1. Store copies every item (`fork_conversation` / `3633-3666`); no token cap.
2. Fresh SDK replay serializes all prior turns into one prompt
   (`_build_prompt`, `resume_session=False`).
3. Native clone/`_ensure` writes the full JSONL for `--resume` (no compact
   unless a compaction snapshot exists). Resume fetch pages `limit=1000`.
4. Cursor injects the same history as one preamble on first message.
5. Silent fallback to a blank launch when clone/`_ensure` fails (#5498).

## Fixes (see REPORT)
Smallest: fail closed on oversize + honor compaction snapshots everywhere.
Do not silently launch empty. Coordinate with #5603/#5405 on route/store.
