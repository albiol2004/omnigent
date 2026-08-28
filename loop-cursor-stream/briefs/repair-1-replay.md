# Scoped repair — loop-cursor-stream iteration 1, repair 1

Read `loop-cursor-stream/VERDICT.md` first (the "Why not SHIP" and "Repair scope" sections), then `loop-cursor-stream/GOAL.md` (HARD isolation: never touch ~/.omnigent, ~/.claude/projects, :6767, `omni host` 1270936 or its children, /home/alex/omnigent-fixes-data, /home/alex/omnigent; throwaway only on port ≥ 17200; cursor-agent allowed from a throwaway workspace; ~/.cursor read-only; never kill processes you did not start). Repo `/home/alex/omnigent-fixes`, branch `trio-v0.10.0-fixes`.

Allowed writes ONLY: `omnigent/cursor_native_stream.py`, `omnigent/cursor_native_forwarder.py`, `tests/test_cursor_native_forwarder.py`, the stream test file (find it: `grep -ln cursor_native_stream tests/`), `loop-cursor-stream/evidence/iter1/e2e/`, `loop-cursor-stream/REPORT.md`, `loop-cursor-stream/LOG.md`. No re-planning, smallest correct change.

## Defects (from VERDICT)
1. After the complete `external_conversation_item` is posted, `live_stream.reset()` + the next pane poll re-emits the finished answer under `cursor-live-<session>` → a second live preview beside the persisted message.
2. The first-🤖 marker matches user-typed text containing 🤖.
3. `→` tool chrome lines cut later prose.

## Task
- Suppress delta emission after a completed turn until a NEW generation is observed (a new Working/generating frame, or the user's next inject) — track a "turn epoch"; the pane region already emitted for a completed turn is never re-emitted. Use a fresh `message_id` per turn epoch.
- Anchor the assistant region to the LAST 🤖 marker that appears after the most recent user prompt line (not the first in the pane), so quoted 🤖 in user text is ignored.
- Treat `→` tool-chrome lines as interleaved non-prose: skip them without truncating subsequent prose (continue diffing after them).
- Tests: reset/replay after completion (no re-emit), new turn after completion (emits with new message_id), 🤖 in user text, `→` lines between prose paragraphs, plus the existing suite. Run `uv run pytest -q tests/test_cursor_native_forwarder.py <stream test file>` and `pre-commit run --files <changed>` — clean.
- Extend the e2e evidence: rerun the throwaway (port ≥ 17200, torn down; `ss -ltnp | grep ':172'` empty after) and keep watching ≥ 10 s AFTER the complete item lands; record that zero deltas were emitted after completion, and that a second prompt produces deltas again under a new message_id. Save under `loop-cursor-stream/evidence/iter1/e2e/` (e.g. `REPLAY-CHECK.json`).
- Commit as `slice(cursor-delta-source): no replay after completion; robust marker and tool-chrome handling` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` — product + test files only; leave mailbox files uncommitted. Never amend/rebase/push/stash/reset.
- Update REPORT.md numbers; append `- iter 1 | lead | repair 1: <one line>` to LOG.md. Print a compressed summary.
