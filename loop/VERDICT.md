VERDICT: SHIP
# Verdict — iteration 1
attempt: 2c376deddaf84b97845c07adb216e236
evaluated: c813e0b825b803b70350bad650cd024c7e2b121e

## What changed since last verdict
First verdict of this loop. Iteration 1 does the whole GOAL: 58 v16 product commits re-ported onto v0.17.0 (12b5f67d2): 43 ported, 12 adapted, 3 dropped with upstream evidence, plus 8 merge/loop-only commits not ported. It also adds the v17 focused-suite runner with a pristine baseline, the refreshed child-reasoning-effort patch, the overlap check, and docs/v17-report.md. I graded a detached worktree at the pin c813e0b82 (HEAD of trio/loop, clean tree). I used a repo-local `uv sync --frozen --offline` venv, and all suites ran with `TMPDIR=/var/tmp/pytest-of-coder/ev1`.

## Criteria results
| # | criterion | result | evidence | command | key output |
|---|---|---|---|---|---|
| D1 | every v16 product commit ported/adapted with `-x` or dropped with upstream evidence; table in docs/v17-report.md | PASS | re-run + probe | own trailer diff over `git rev-list --no-merges v0.16.0..v16/trio-v0.16.0-fixes` vs `git log --format=%B b52507b70..HEAD`; `loop/probes/iter-1/table_trailers.py` | 58 product commits; 55 have exactly one trailer, 0 duplicates; the 3 without one (39e45d8d4, d69671640, de03a352c) are the report's 3 dropped rows. Table: `66 {'not ported': 8, 'adapted': 12, 'ported': 43, 'dropped': 3} bad= []` |
| D1b | drops really superseded | PASS (with observation 1) | probe | grafted the 4 tests that de03a352c/d69671640 add onto a scratch copy of the tip | `queue_all_accept_in_turn_zero_cards` (batched tools, 3 accepts, 0 cards) PASSES on upstream #8516 code. The other 3 fail only on fork-only knobs (`_YOLO_ACCEPT_MAX_ATTEMPTS`, `_YOLO_ACCEPT_STALE_CEILING_S`, `OMNIGENT_CURSOR_YOLO_STALE_SURFACES_CARD`) that #8516 replaced with a time-based retry and a no-prompt SKIP. 39e45d8d4: `_resolve_agent_spec = _resolve_subagent_spec` is present via 669e05bfd |
| D2 | upstream overlaps kept (#9048 #9008 #9005 #8672 #8572 #8745 #8761 #8516 #8523 …) | PASS | re-run + probe | `bash scripts/v17_overlap_check.sh`; second path `loop/probes/iter-1/overlap_removed.py` | script: every PR 0 absent except #8516 (6 absent, 1 "moved"). My probe: only #8516 has added lines removed by the port (all in cursor_native/forwarder.py). Reading forwarder.py:1900-1966: `read_turn_outcome`, the damaged-marker failure path, `turn_outcome=outcome` and `write_posted_count` are all still present, re-shaped around the receipt post |
| D3 | focused suites vs pristine baseline: no new failure ids | PASS | re-run | `TMPDIR=/var/tmp/pytest-of-coder/ev1 bash scripts/v17_focused_suite.sh …/v17-full.txt` (full_check) | SUITE_DONE, 0 TIMEOUT. dispatch 284p/1s; interrupt 24p; runner-native 7F/583p; sys-session 45p; terminals 109p/2s; claude-native 4F/1545p; codex-native 1484p; cursor-native 556p; inner-proc 40p/8s; host 6F/257p; sessions-routes 64p. Every failing id is in the baseline or fails on pristine (next two rows) |
| D3a | failing ids pre-exist on pristine | PASS | re-run (second path) | pristine v0.17.0 scratch copy: `pytest tests/runner/test_app_sessions_native_events_lifecycle.py tests/harnesses/claude_native/test_claude_native_status_file.py` | `18 failed, 68 passed`. Includes all 7 runner-native tip failures and all 3 status_file timing tests |
| D3b | the 1 id not in the baseline: `test_claude_native_bridge.py::test_http_ingress_advertises_absolute_socket_path` | PASS (environment) | re-run | same test, tip and pristine, varying TMPDIR depth | tip with TMPDIR=ev1 → `1 failed`; tip with a deeper TMPDIR → `1 passed`; pristine with the same depth geometry → `1 failed`. The test's `../`×N relative path climbs to `/` when tmp_path is no deeper than cwd (my eval worktree is 11 levels deep). Upstream test, unchanged by the port, so not a regression |
| D4 | behaviour checks: receipt gate/plugin-dir/foreign stop hook/N12, cursor isolation, input fence, stop-routing + kill escalation, codex manual compact, claude hook bridge | PASS | re-run + probe (fault injection) | goal_probe pytest set; cursor-native/terminals/interrupt/codex/claude groups above; 2 injected faults | goal_probe: `1 failed, 204 passed` on the first run (flake, observation 2), then 1/5 and 1/12 fail rates in isolation; groups green. Fault 1: repo-subfolder refusal disabled → `3 failed` (`test_repo_subfolder_is_refused[1,3]`, `test_alias_to_a_repo_subfolder_is_refused`). Fault 2: `input_fence.admit_input` no-op → `test_verified_fence_rejects_every_input_api_and_persists` FAILED |
| D5 | patch applies to pristine v0.17.0 and to the tip | PASS | re-run | `git apply --check` on a pristine `git archive v0.17.0` copy and on the tip; applied + `pytest tests/tools/builtins/test_child_reasoning_effort.py` on both | `pristine_check=0`, `tip_check=0`, reverse-check on tip=1 (not already applied); `10 passed` on pristine+patch, `10 passed` on tip+patch (imports resolved to each tree). Nothing written to ~/.local/share/trio-agent-loop |
| D6 | report lists migrations since v0.16.0 and since 318264335, risks, unverifiable list, install/rollback with DB restore | PASS | probe | `git diff --name-status v0.16.0 HEAD` / `318264335 HEAD -- omnigent/db/migrations/versions` vs report grep | since v0.16.0: only mm1a2b3c4d5e; since 318264335: 10 revisions, all 10 in the report. Report §7 is the unverifiable list; §8.2/8.4 back up with `sqlite3 .backup` and restore chat.db before the switch-back |
| T | test-integrity audit | PASS | probe | removed `-` lines of `git diff -M v0.17.0 HEAD -- tests` compared with v16's `v0.16.0..v16tip` removals | 9 removed upstream test functions, all also removed in the v16 port (fork stop-routing/compact/discovery changes). Only 3 v17-specific removed lines, all in the replaced tmux-compact tests. No new skip/xfail |
| L | lint/type | PASS | re-run | `ruff check`/`ruff format --check` on 59 changed .py; `pyrefly check` | `All checks passed!`, `59 files already formatted`, `0 errors` |
| G | LOG.md Lead entry | PASS | re-run | grep `- iter 1 | lead |` | present (line 14) |

attacks:
- Grafted the fork's dropped yolo tests (de03a352c/d69671640) onto the tip → the batched-tool behaviour passes on upstream code; the remaining 3 need fork-only knobs (observation 1).
- Disabled the repo-subfolder refusal in a scratch copy (`reason = None if True …`, bridge.py:1435) → 3 refusal tests fail: the suite catches a lost isolation guard.
- Turned `input_fence.admit_input` into a no-op → the fence integration test fails: the fence is enforced, not just declared.
- Ran the suite from a deeper cwd and a different TMPDIR than the Lead → exposed one upstream path-depth test artifact (D3b) and one flaky fork test (observation 2); neither is a product regression.
- Overlap counted a second way (lines removed by the port vs lines added by each PR) → only #8516 is affected, and the code was re-shaped, not lost.

## Independent probe
probe: PASS v17 patch applies to pristine and tip; goal_probe behaviour tests pass; DoD-1/2 probes clean
probe_cmd: git archive v0.17.0 | tar -x -C $S/pristine && (cd $S/pristine && git init -q && git apply --check $PIN/patches/child-reasoning-effort.v0.17.0.patch); git -C $PIN apply --check patches/child-reasoning-effort.v0.17.0.patch; TMPDIR=/var/tmp/pytest-of-coder/ev1 uv run --frozen pytest -q -p no:cacheprovider tests/test_cursor_native_completion_receipt.py tests/test_cursor_native_plugin_dir.py tests/server/integration/test_input_fence.py tests/harnesses/codex_native/test_codex_native_manual_compact.py tests/terminals/test_pane_reaper.py; python3 loop/probes/iter-1/table_trailers.py; python3 loop/probes/iter-1/overlap_removed.py
probe_src: loop/probes/iter-1/ (table_trailers.py, overlap_removed.py, NOTES.md)
expected: both apply checks exit 0; pytest N passed / 0 failed; every ported/adapted row has its -x trailer; no upstream overlap line lost
observed: pristine_check=0 tip_check=0; `1 failed, 204 passed` on the first run, where the failure was the known flaky `test_fence_close_linearizes_against_concurrent_injections` (close beats all 8 writers → no inject file); re-runs pass 4/5 and 11/12; `66 {'not ported': 8, 'adapted': 12, 'ported': 43, 'dropped': 3} bad= []`; overlap: only `#8516 a16334f78: lines=595 removed_by_port=26`, re-shaped not lost (forwarder.py:1900-1966)

## Blocking issues
(none)

## Non-blocking observations
1. The drop of d69671640 loses the fork env override `OMNIGENT_CURSOR_YOLO_STALE_SURFACES_CARD`, and the drop of de03a352c loses the attempts-budget / stale wall-clock ceiling knobs. The default behaviour (no phantom cards, batched gates accepted in turn) is delivered by #8516. But report §1.3 says #8516 "already delivers both behaviours" without saying the opt-out knob is gone. Add one line to the report so nobody sets that env var expecting an effect.
2. `tests/test_cursor_native_completion_receipt.py::test_fence_close_linearizes_against_concurrent_injections` is flaky. It fails about 1 run in 5–12 when the fence close beats every writer: `admitted == 0`, `cursor_inject.jsonl` never created, so `read_text()` raises FileNotFoundError. The linearization assertions themselves pass. The test is identical to v16 and the fence code is unchanged from v16, so this is a test weakness, not a port regression. Fix: treat a missing file as an empty record list.
3. A new v17 interaction in cursor_native/forwarder.py: a receipt re-post (`receipt_update_due`, opt-in receipts only) sends `status="idle"` with no `turn_outcome`, even when the turn's first post was `failed`. The server then treats that idle as `completed` for a cursor child (`native_subagent_terminal_status`) and publishes `idle` over `failed`. Subagent "returned" edges are deduplicated per turn, which limits the damage, but no test covers re-post after a failed outcome. Worth a test, and probably reusing the original outcome on re-post.
4. `tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_advertises_absolute_socket_path` (upstream) fails whenever pytest's tmp_path is no deeper than the cwd. Record this next to the AF_UNIX TMPDIR quirk in the evidence method.
5. trio-shadow reports c813e0b82 (slice v17-afterport) editing docs/v17-report.md, a v17-report write. This is bookkeeping only; the Lead disclosed it.

## Guidance for next iteration
None needed: SHIP. Suggested commit message for the landed branch: "port: re-port Omnigent fork (v16 patch set) onto upstream v0.17.0 — 43 ported, 12 adapted, 3 superseded by #8516/v0.17.0; v17 suite/baseline, overlap check, child-reasoning-effort.v0.17.0.patch, docs/v17-report.md". All product work is already committed as `slice(<id>): …` commits on trio/loop; the retirement commit covers only the mailbox.
Follow-ups for a new GOAL: (a) observations 1–3; (b) the live steps below.

## Remaining real-world steps
- Install on the live editable /home/coder/omnigent and migrate chat.db ll1a2b3c4d5e → mm1a2b3c4d5e. Follow report §8 (back up the DB first; rollback restores the backup). Human only; GOAL forbids touching the live install or server.
- Real cursor-agent / codex app-server / claude CLI runs (gated e2e tests, report §7), and `trioctl omnigent doctor` importing `_resolve_agent_spec`.
- Ship patches/child-reasoning-effort.v0.17.0.patch into the next trio release.

## Human check
Not required for this verdict (no `verify: human` criteria). The live steps above are post-SHIP operator actions.

commit: c813e0b825b803b70350bad650cd024c7e2b121e
evaluated: c813e0b825b803b70350bad650cd024c7e2b121e
