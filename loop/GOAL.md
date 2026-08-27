# GOAL — Root-cause investigation (NO CODE CHANGES): fork context overload, slow CLI-output rendering, unkilled CLI sessions

Target repo: /home/alex/omnigent. Mailbox loop/. Baseline: branch trio-v0.10.0 HEAD ead098caf (v0.10.0 + 3 local commits). Upstream: omnigent-ai/omnigent, latest v0.11.0.

## Mission
Produce a rigorous, evidence-backed root-cause report for three production problems in the user's main work setup, enumerating ALL plausible causes ranked by confidence, each with file:line evidence and a concrete reproduction, plus candidate fixes with risk assessment — without modifying any product code.

## Verification floor
Every cause claimed must be backed by (a) file:line citations verified against HEAD ead098caf and (b) a reproduction or direct measurement (log excerpt, timing, process listing, transcript size) captured under loop/evidence/iter<N>/. Claims that cannot be reproduced are listed separately as "unconfirmed hypotheses", never mixed with confirmed causes.

## The three problems (user's words)
1. "the fork function is broken as it loads all the session into context so breaks ClaudeCode"
2. "the UI being very slow to render what the CLI produced"
3. "sometimes CLI sessions not being killed"

## Scouted facts (starting points — verify, do not trust blindly)
- Fork server route: omnigent/server/routes/sessions/routes_core.py:1979-2200; DB copy omnigent/stores/conversation_store/sqlalchemy_store.py:3397-3520. Runner consumes fork labels at omnigent/runner/native/orchestration.py:5907-5990, 6233, 6283-6400 (native Claude: clone ~/.claude/projects/<ws>/<sid>.jsonl + `claude --resume`; SDK/cross-family: rebuild JSONL via _ensure_local_claude_resume_transcript). claude-sdk harness replays whole history as one prompt: omnigent/inner/claude_sdk_executor.py:3062-3123 ("Conversation so far:"). Cursor-native: preamble in omnigent/inner/cursor_native_executor.py:93-114. UI predicates web/src/lib/forkHarness.ts. Upstream related: #5498, #5180, #2967 (no harness-path compaction), #3469.
- Rendering: claude-native forwarder polls files at 250 ms (omnigent/claude_native_forwarder.py:84, loops 864/900/923-928/1025), one HTTP POST per delta (:3962-3995, :4041-4062); UI store O(n) per token (web/src/store/chatStore.ts:4292-4327), no rAF batching; SSE at routes_events.py:1893-1908; session_stream queue maxsize 1024 drops subscriber on overflow (omnigent/runtime/session_stream.py:40,63-79); sidebar WS 4 s rescan (omnigent/server/routes/_sessions/common.py:474, routes_core.py:1213-1240). Upstream open: #3000 (4 Hz poll), #4589 (fresh python per hook ~1 s), #2702 (tmux capture 5 Hz).
- Kill: sys_session_close only PATCHes a label, never stops the harness (omnigent/runner/tool_dispatch.py:4968-5005); no kill on SSE/WS disconnect (helpers.py:7415-7420); claude-sdk CLI child not in own pgid so _killpg bails (omnigent/inner/_proc.py:130-159), psutil walk misses re-parented grandchildren; tmux kill-session 1 s timeout, no SIGKILL escalation, no orphan sweep (omnigent/runner/native/interrupt.py:437-470); kill_tree no wait (_proc.py:211-236); _claude_stop does not cancel the forwarder task. Upstream: #4930 (P1, open; fix PR #4976 unmerged), #2421, #5544 (merged post-v0.11, delete cleanup), #5254, #4014.

## Slices (in order; all are investigation slices — writes: only under loop/)
1. **rc-fork** — Determine exactly which harness/path the user's fork goes through (claude-sdk vs claude-native vs cursor), measure what lands in the Claude Code context on fork (prompt size / transcript size / token estimate), reproduce the failure ("Prompt is too long" or equivalent) on a synthetic large session, and enumerate causes + fixes.
2. **rc-render** — Instrument end-to-end latency CLI output → SSE → DOM for claude-native and claude-sdk; measure per-stage contribution (hook spawn, 250 ms poll, per-delta POST, session_stream, SSE, store update, React render); identify the dominant stage(s); enumerate causes + fixes.
3. **rc-kill** — Enumerate every session-ending path (stop, close, delete, fork-source, UI tab close, runner restart, sys_session_close, cancel mid-spawn) and for each determine by actual process listing whether claude/tmux/MCP children survive; find orphans on this machine now (`ps -ef` for claude/cursor-agent/tmux/mcp) as evidence; enumerate causes + fixes.
4. **rc-report** — Consolidate into loop/REPORT.md: per problem, confirmed causes (ranked, with evidence links), unconfirmed hypotheses, candidate fixes with risk (blast radius, upstream-rebase conflict likelihood, reversibility), and a recommended fix order.

## Constraints
- ABSOLUTELY NO modifications to files outside loop/. No git commits except mailbox commits (`loop: …`). No `git checkout`, stash, or reset. Reproductions run in the scratch/temp dirs or against throwaway sessions only; never touch the user's real sessions/agents/~/.claude/projects.
- Do not kill any process you did not start. List orphans; do not reap them.
- Reproductions that need a running Omnigent server must use a separate temporary data dir / port, or clearly documented read-only probes against the running one.
- No code-changing slices → the commit gate has nothing to require; the Evaluator's SHIP retirement commit covers the mailbox only.

## Acceptance
1. loop/REPORT.md lists, per problem, ≥1 confirmed root cause with file:line verified at ead098caf and a reproduction artifact under loop/evidence/.
2. Every claim from "Scouted facts" is either confirmed (with evidence), refuted (with evidence), or marked unconfirmed — none silently dropped.
3. Each candidate fix has: change size estimate, files touched, risk, and whether it conflicts with any open upstream PR (#4976, #5603, #5405, #4913, #5081, #5544).
4. No file outside loop/ differs from ead098caf (`git status --porcelain` shows only loop/).
