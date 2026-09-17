VERDICT: SHIP

Pinned commit under review: `c45506dee` (clean). Evaluator
re-ran the GOAL focused set on that tree and independently
checked dropped-commit coverage on a pristine `v0.14.0`
scratch clone under `/tmp` (not a worktree). No product
edits this pass.

## Focused pytest vs `evidence/baseline-v0.14.0.txt`

| surface | baseline | eval at c45506dee |
|---------|----------|-------------------|
| `test_runner_dispatch.py` | 270 passed, 1 skipped | 274 passed, 1 skipped |
| `test_native_interrupt_runner.py` | 15 passed | 18 passed |
| `test_sys_session.py` | 44 passed | 45 passed |
| `tests/terminals` | 91 passed, 1 skipped | 100 passed, 1 skipped |
| `test_claude_native_bridge.py` | 392 passed | 393 passed |
| `test_codex_native_bridge.py` | 44 passed | 47 passed |
| `test_cursor_native_bridge.py` | 24 passed | 26 passed |
| `test_cursor_native_permissions.py` | 59 passed | 63 passed |

Zero new failures. Extra passes are keeper tests. Evidence:
`loop-v14-rebase/evidence/iter1/eval-pytest-*.txt`.

## Fake-transport close → kill + teardown

Existing tests, 9 passed
(`eval-pytest-fake-transport.txt`):

- Close (httpx.MockTransport): Claude
  `test_session_close_patches_tombstoned_title`; Cursor/Codex
  `test_session_close_routes_native_wrappers_to_stop_session`.
  All three POST `/events` `stop_session`.
- Stop (fake bridges): Cursor
  `test_uniform_stop_kills_tears_down_and_goes_idle`; Claude
  `test_claude_stop_cancels_forwarder_after_teardown`; Codex
  `test_codex_stop_kills_tears_down_and_goes_idle`. Each
  `kill_session` then teardown (Codex also app-server).
- Bridge `kill_session` tmux argv tests for all three
  harnesses.

Scout (`eval-trioctl-scout-yolo-close.txt`):
`_session_close_via_rest` routes those wrappers to
`stop_session`; `stop()` then `_claude_stop` /
`_codex_stop` / `_UNIFORM_STOP["cursor"]`.

## Dropped commits on pristine `v0.14.0` (`fc89a3ba3`)

Scratch clone `/tmp/omnigent-v014-eval` (removed after).
Import was `/tmp/omnigent-v014-eval/omnigent/__init__.py`.

- `c04442f16`: `test_native_subagent_yolo_args_derived_from_trusted_spec`
  **3 passed**, including `cursor-native` → `["--yolo"]`.
  `git show v0.14.0:...helpers.py` already has
  `_derive_terminal_launch_args_from_spec` cursor default
  `--yolo` (~9285 / 9376).
- `96b5639d8`:
  `test_claude_transcript_records_handles_native_compaction_messages`
  **1 passed**.
- `0c8082af2`: preload + `test_is_unreadable_thread_error`
  **15 passed** (active-writer still fails loud).

Evidence: `eval-dropped-commits-v0.14.0.txt`.

## Other floor checks

- `trioctl omnigent doctor` from this worktree:
  `omnigent:session-contract` **PASS**
  (`eval-trioctl-doctor.txt`). Alias
  `_resolve_agent_spec = _resolve_subagent_spec` in
  `omnigent/server/routes/sessions/__init__.py`.
- Old-import grep on `*.py`: empty. Residual dotted
  paths only in upstream docs/designs
  (`eval-old-import-grep.txt`).
- `git diff v0.14.0..c45506dee --stat`: keepers +
  `omnigent/native_tmux_kill.py` + restored
  `loop-session-close/` + README fork section. The
  `docs/cursor-native-elicitation.md` hunk is from the
  Cursor yolo cherry-picks, not a stray file.
- README heading `trio-v0.14.0-fixes (this worktree)`:
  stock v0.14.0 plus keepers; live install stays on
  `trio-v0.12.0-fixes` until adopt; #7498 leak rationale
  present.

## REPORT.md

Matches the tree. Fake-transport is the two-hop close→stop
plus stop→kill/teardown suite, which is the v0.14.0 shape.
Agree trioctl should later import `_resolve_subagent_spec`.

## Guidance for next iteration

None. Product HEAD is unchanged this eval.

commit: c45506dee912d0b495208f64ed13aad58b7b2894
