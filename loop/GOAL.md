# Goal
profile: software
Re-port the user's Omnigent fork patches onto upstream stable v0.17.0 so the trio stack can run on 0.17.0 with every fork behaviour intact.

## Context
- This clone: /home/coder/omnigent-v17, branch `trio-v0.17.0-fixes`, created from upstream tag `v0.17.0` (12b5f67d2, omnigent-ai/omnigent, released 2026-10-05; 254 commits after v0.16.0).
- Port SOURCE (preferred): ref `v16/trio-v0.16.0-fixes` (tip 3dd44be0f). It is the fork already re-ported and verified on v0.16.0 (SHIP 2026-10-06). The patch range is `git log v0.16.0..v16/trio-v0.16.0-fixes`, excluding commits that only touch `loop/` or `loop-archive-*` (mailbox bookkeeping, NOT ported). Its `docs/v16-report.md` has the 60-row disposition table and `docs/v16-evidence/` the per-slice notes, baseline method and `scripts/v16_focused_suite.sh`: reuse the method, update for v0.17.0.
- Original fork: ref `fork/release/omnigent-2a84483a` (tip 318264335), only for reference when a v16 adaptation is unclear.
- A trial `git merge-tree` of the v16 port onto v0.17.0 conflicts in 18 files; 6 are version/lock/pyproject noise (keep upstream's). Real hotspots: harnesses/cursor_native/{bridge,forwarder,permissions,status}.py, runner/app.py, server/routes/_sessions/helpers.py, server/routes/sessions/routes_events.py, docs/cursor-native-elicitation.md, tests/runner/test_app_sessions_native_events_{lifecycle,options}.py, tests/runner/test_native_interrupt_runner.py, tests/test_cursor_native_permissions.py.
- v0.17.0 reorganised many test files (claude-native/codex-native tests split by ownership, #8788/#8789/#8805): fork tests may need to move to the new file layout rather than recreating old files.
- Known env quirk from the v16 port: the driver's long TMPDIR pushes tmux socket paths past the 108-byte AF_UNIX limit; run tmux-using suites with `TMPDIR=/var/tmp/pytest-of-coder` (or similar short path) and record that in the evidence.

## Definition of done
1. Every fork code commit from the v16 port is cherry-picked (`-x`, original order) with conflicts resolved, adapted, or explicitly dropped as superseded by v0.17.0 with evidence (the upstream commit/test that covers it). Disposition table in `docs/v17-report.md` (v16 commit → original fork commit → ported/adapted/dropped + reason).
2. Upstream v0.17.0 changes are kept where they overlap fork patches (e.g. claude_native transient-outage/turn-failure/shutdown evidence #9048/#9008/#9005, in-process subagent StopFailure #8672, hook TMPDIR #8572, codex cold-resume MCP refresh #8745, cursor_native permissions/status/elicitation, Harnesses settings page #8761); fork behaviour is layered on top, not reverted. Verify with a line-presence check like v16's.
3. Focused suites (same groups as v16: runner native dispatch/interrupt/orchestration, sys_session, terminals incl. pane reaper, cursor_native, claude_native, codex_native, inner-proc, host, sessions routes) pass, compared against a pristine-v0.17.0 baseline run; pre-existing upstream failures are listed separately and not counted as regressions.
4. Behaviour checks covered by tests or scripted probes: cursor receipt gate (labels, plugin-dir, foreign stop-hook refusal, passthrough scan r17 N12); cursor isolation (no session MCP in user mcp.json, refuse user ~/.cursor / repo subfolder); input fence; stop-routing and kill escalation; Codex manual compact via app-server; claude_native hook bridge with the Unix-socket MCP and hook TMPDIR.
5. Refreshed trio patch `patches/child-reasoning-effort.v0.17.0.patch` that applies cleanly to pristine v0.17.0 and to the final tip (start from the v16 repo's `patches/child-reasoning-effort.v0.16.0.patch`; do NOT write into ~/.local/share/trio-agent-loop).
6. `docs/v17-report.md` also lists: new risks/breaking changes in v0.17.0 (DB migrations added since v0.16.0 AND since the fork tip 318264335, config/preference changes, removed APIs the trio driver or fork used), what could not be verified without a live server, and exact install/rollback steps for the live editable install at /home/coder/omnigent (installed via `uv tool install --editable /home/coder/omnigent`; rollback must restore the pre-upgrade DB because of migrations).

## Constraints
- Work only inside this repo/its worktrees. Never modify /home/coder/omnigent (LIVE editable install backing the running Omnigent server), /home/coder/omnigent-v16, ~/omnigent-dev, ~/.omnigent, ~/omnigent-backups, ~/.claude settings, or the installed trio release.
- Never start, stop or restart the Omnigent server or services; never pkill/killall by pattern. Tests needing a server use isolated temp ports/dirs.
- No push to any remote. No `uv tool install`/pip install into the user's tool envs; use a repo-local venv (`uv sync --frozen --extra all --group dev` / `uv run`) for tests.
- Base is exactly v0.17.0; do not track upstream main.
- Never use bypassPermissions / --dangerously-skip-permissions.
