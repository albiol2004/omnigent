# CITATIONS — rc-fork (HEAD 9926c9145 / product ead098caf)

| Scouted fact | Grade | file:line | Evidence |
|---|---|---|---|
| Fork route copies session | Confirmed | `omnigent/server/routes/sessions/routes_core.py:1990-2172` | SCOUT-STDOUT.md; sed 1998-2006 |
| DB copy 3397-3520 | Confirmed, range short | `sqlalchemy_store.py:3397` def; item copy `3633-3666` | SCOUT-STDOUT.md |
| Runner fork labels 5907-5990, 6233, 6283-6400 | Confirmed | `orchestration.py:5907-5925`, `6233-6276`, `6283-6409` | SCOUT-STDOUT.md |
| Native clones `~/.claude/projects/...jsonl` + `--resume` | Confirmed | `claude_native.py:1780-1843` | clone writes dest jsonl then resume |
| SDK/cross-family uses `_ensure_local_claude_resume_transcript` | **Refuted as SDK target** | `_ensure` is Claude-native rebuild `claude_native.py:4125-4202`; used from `orchestration.py:6265-6276` | SDK fork uses copied items + `_build_prompt` |
| claude-sdk replays whole history `"Conversation so far:"` | Confirmed, **fresh client only** | `claude_sdk_executor.py:3052-3123` (`3094`) | warm/`resume_session` skips replay (`3080-3081`) |
| Cursor-native preamble 93-114 | Confirmed | `cursor_native_executor.py:93-114`; render `orchestration.py:5415-5443` | wrap `cursor_native_bridge.py:212-241` |
| UI `forkHarness.ts` | Confirmed | `web/src/lib/forkHarness.ts:135-158` | |
| #5498 #5180 #2967 #3469 | Confirmed as issues (not PRs) | GitHub | scout `gh issue view` |

Lead cross-check: `_fetch_all_session_items_for_claude_resume` uses `limit: 1000` at `claude_native.py:4223`.
