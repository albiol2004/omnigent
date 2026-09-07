# GOAL — Omnigent stability: Codex native terminal, stale Codex models, CLI view, image attachment, compact-on-fork

Target repo: /home/alex/omnigent (fork albiol2004/omnigent), branch trio-v0.10.0-fixes, baseline HEAD bd490d74f. Mailbox loop-stability/.
Codex CLI 0.153.4, tmux 3.4. Reproduces on the Azure workspace (Ubuntu container) and partially on Fedora.

## Mission
Find root causes and fix, with tests, five user-visible failures. Suspected common root: session/bridge ownership after fork/resume of native Codex sessions.

1. **Native Codex terminal fails to start** on session start. Evidence (Azure runner log
   runner-4ada6cb3c4b54f6d877f237a1daa4d82-20260907-111527-650211.log, copy in loop-stability/evidence/):
   `_launch_native_terminal` (omnigent/runner/native/orchestration.py ~7410) → `_launch_codex` (~7342) →
   `_auto_create_codex_terminal` (~3751, call at ~4161) → `preload_codex_thread_for_resume`
   (omnigent/codex_native_app_server.py ~2645) → `request` (~524) raises app-server error
   -32600 "thread 01a07b94-… already has an active writer". Retried by `_ensure_native_terminal` (~7523), same error.
2. **Stale/old Codex models shown** for a session. Evidence: omnigent/runner/app.py ~4088 logs
   "Codex-native model options skipped for <session>: bridge belongs to <other session>" right before (1).
3. **CLI view broken** (web UI) on both machines.
4. **Picture attachment broken** on both machines (server side candidates: omnigent/server/routes/sessions/routes_resources.py, routes/_sessions/helpers.py).
5. **Compact-on-fork fails** in some cases, e.g. forking a Claude session into Codex.

## Acceptance
- Each failure reproduced by an automated test (or, where a real harness is required, a documented manual repro with captured log) before the fix; test passes after.
- Root cause written in REPORT.md per item, with the ownership/bridge model explained.
- No regressions: existing native Claude/Codex session tests pass (`uv run pytest -q tests/runner tests/server -x` or the narrowest relevant subset, listed in REPORT).
- Web changes (3,4) covered by web unit tests where the repo has them (`cd web && npm test`).
- One commit per slice `slice(<id>): …`; clean tree at end.

## Verification floor
mode: test-first for 1, 2, 5; implement-then-smoke acceptable for 3, 4 with captured evidence in loop-stability/evidence/iter<N>/.

## Non-goals
Upstream sync (omnigent-ai/omnigent v0.11.0) is out of scope; note in REPORT if upstream already fixes an item.
