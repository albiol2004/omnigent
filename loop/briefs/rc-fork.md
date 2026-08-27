# Scout: rc-fork (read-only product tree)

You are a Luna scout. Workspace: /home/alex/omnigent. HEAD product tree
ead098caf (commit 9926c9145 = that tree + mailbox). Investigation only.

## Writes (ONLY these)
`loop/evidence/iter1/rc-fork/` — FINDINGS.md, CITATIONS.md, MEASUREMENT.md,
any scripts/logs you generate. Pairwise-disjoint from other slices.

NEVER edit files outside loop/. NEVER kill processes. NEVER touch
~/.claude/projects or real sessions. Use a temp data dir under /tmp or
loop/evidence/iter1/rc-fork/scratch/.

## How to read code
Do NOT Read whole large files. They crash the transport:
- omnigent/inner/claude_sdk_executor.py (>1 MB)
- web/src/store/chatStore.ts
- omnigent/server/routes/sessions/routes_core.py

Use `sed -n 'a,bp' FILE` and `rg -n 'symbol' FILE` only.

Diagnosed ranges (GOAL + Lead grep at HEAD — verify, do not assume):
- fork route: omnigent/server/routes/sessions/routes_core.py:1979-2200
  (`fork_session` ~1990)
- DB copy: omnigent/stores/conversation_store/sqlalchemy_store.py:3397-3520
  (`fork_conversation` 3397)
- runner fork labels: omnigent/runner/native/orchestration.py:5907-5990,
  6233, 6283-6400, 6265-6362 (`_ensure_local_claude_resume_transcript`,
  `_clone_claude_transcript`)
- claude-sdk replay: omnigent/inner/claude_sdk_executor.py:3062-3123
  (`Conversation so far:` at 3094; helpers 372, 477)
- cursor-native preamble: omnigent/inner/cursor_native_executor.py:93-114
- UI: web/src/lib/forkHarness.ts (small file OK; exports 25,67,135,156)

Also grep: compaction, resume, jsonl, --resume, prompt too long.

## Required outputs
1. Confirm/refute EVERY scouted fact below with `file:line` verified at
   HEAD. Table in CITATIONS.md: fact | confirmed/refuted/unconfirmed |
   file:line | evidence path.
2. Reproduction: build a synthetic LARGE conversation in a temp data dir
   (not the user's store). Measure the prompt/transcript BYTES that would
   reach `claude` on fork for (a) claude-native resume jsonl clone,
   (b) SDK `_ensure_local_claude_resume_transcript` rebuild,
   (c) claude-sdk "Conversation so far:" single-prompt replay,
   (d) cursor-native preamble. Prefer calling/importing the actual
   renderer functions in a throwaway Python snippet; do not spawn a real
   billed Claude session if avoidable. If you must invoke `claude`, use
   `--print` against a dummy and stop on "Prompt is too long". Record
   sizes, message counts, and whether compaction exists on that path.
3. Ranked causes (confidence + why).
4. Candidate fixes: change size, files, risk, conflict with upstream
   PRs #4976 #5603 #5405 #4913 #5081 #5544 (and related #5498 #5180
   #2967 #3469). Use `gh pr view` if needed.

## Scouted facts to grade
- Fork server route copies session at routes_core.py:1979-2200.
- DB copy sqlalchemy_store.py:3397-3520.
- Runner consumes fork labels at orchestration.py:5907-5990, 6233,
  6283-6400; native Claude clones ~/.claude/projects/<ws>/<sid>.jsonl +
  `claude --resume`; SDK/cross-family rebuilds JSONL via
  `_ensure_local_claude_resume_transcript`.
- claude-sdk harness replays whole history as one prompt
  ("Conversation so far:") at claude_sdk_executor.py:3062-3123.
- Cursor-native preamble cursor_native_executor.py:93-114.
- UI predicates web/src/lib/forkHarness.ts.
- Related upstream: #5498, #5180, #2967 (no harness-path compaction),
  #3469.

Write FINDINGS.md last. Be specific. Quote 5-15 line snippets with
line numbers from sed, not whole files.
