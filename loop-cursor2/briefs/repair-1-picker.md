# Scoped repair — loop-cursor2 iteration 1, repair 1: make the model picker actually switch, and stop hiding failures

Read `loop-cursor2/VERDICT.md` first (sections "picker-row-match @40d61eb9f — ITERATE" and "Failure scope (repair)"), then `loop-cursor2/GOAL.md` findings 8-10. Repo `/home/alex/omnigent-cursor2`, branch `cursor-render-picker`.

HARD isolation: `~/.omnigent`, `~/.claude/projects`, `~/.cursor` READ-ONLY. Never touch the live :6767 server, `omni host`, or /home/alex/omnigent (no git commands there). **Never type into, start, or kill any EXISTING tmux/cursor-agent session — the user is actively working in them.** Only `capture-pane -p` on existing panes; any pane you DRIVE must be one your own throwaway started, and you must `kill-server` your own panes when done. Throwaway instance on port >= 18700, scratch `OMNIGENT_DATA_DIR`/`OMNIGENT_CONFIG_HOME`, `OMNIGENT_PROCESS_LOG_FILE` unset. Never kill processes you did not start.

Allowed writes ONLY: `omnigent/cursor_native_bridge.py`, `omnigent/server/routes/_sessions/helpers.py`, `tests/test_cursor_native_bridge.py`, any directly-affected server route test, and `loop-cursor2/evidence/iter1/repair1/`. Do NOT touch the shipped slices (`c24bed93f`, `a4eda6797`, `788c247fa`, `479252e0d`, `bdc0fdb3a`, `9b83f39fb`) or any web file. No re-planning.

## Defect 1 — the live `/model` inject still does not land the model
Evaluator live proof (throwaway :18600, a pane that loop started): the footer never changed; the runner logged `did not resolve to its exact picker row` for the real id `cursor-grok-4.6-medium` and `not available in the live catalog` for a bogus id. So the cause-8 path IS exercised and still fails on a real pane.
Two known holes:
- The test fixture is still SYNTHETIC: `_IDLE = "  → Add a follow-up"` in `tests/test_cursor_native_bridge.py`. The REAL idle composer line on this machine is `→ Plan, search, build anything`, the live pane is ~41 columns and WRAPS long rows, and `capture-pane` without `-S` only sees the viewport. Capture a real pane from your OWN throwaway cursor session (open the `/model` picker in it) and use that verbatim as the fixture, including the composer `→` line and at least one wrapped row.
- Remaining matcher hole in `_picker_highlighted_row` / `_picker_row_matches_display`: `normalized_display.startswith(normalized_row)` accepts a truncated or shorter highlighted row — e.g. it accepts a highlighted `Cursor Grok 4.6` when the request was `Cursor Grok 4.6 Medium`. Require the highlighted row to identify the EXACT requested variant; reject sibling variants (`… Low`, `… Fast`, `… High`) and truncated rows. Prefer typing a fully-qualified id so the picker filters to a single row, and tolerate wrapped/truncated display by reconstructing the logical row before comparing.
Also reconsider the timing budget (`_PASTE_COMMIT_TIMEOUT_S`, `_MODEL_PICKER_SETTLE_S`): re-check the highlight a few times rather than one fixed settle.

## Defect 2 — the web PATCH hides a runner 503
`omnigent/server/routes/_sessions/helpers.py` currently persists `model_override` and returns **200** even after the runner returns 503 for `model_change` on a native-terminal session. A bogus model id therefore reports success. A native-terminal runner 503 must fail the web PATCH (or roll the override back) so the UI shows an honest error naming the model. Keep the change additive and scoped to the native-terminal `model_change` path — do not alter model changes for SDK/other harnesses.

## Proof required (this is why the previous pass failed)
On your own throwaway, with a pane your throwaway started:
1. Read the current footer model via `capture-pane -p`.
2. PATCH to a model that is **clearly different** from it (do NOT re-PATCH the same model — the previous eval switched medium→medium so the footer could not move even on success).
3. `capture-pane -p` again and assert the footer now shows the EXACT requested variant.
4. PATCH a bogus id and assert the HTTP response is a failure (not 200) naming the model, and that `model_override` was not left persisted as a lie.
Save `pane-before.txt`, `pane-after.txt`, the HTTP bodies and the runner log excerpt under `loop-cursor2/evidence/iter1/repair1/`, plus a one-line `RESULT.txt` with the before/after footer strings and both HTTP statuses. Tear the throwaway down; `kill-server` only your own tmux socket.

## Finish
Run `PYTHONPATH=/home/alex/omnigent-cursor2 uv run pytest -q tests/test_cursor_native_bridge.py` plus any touched route test, and `PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files <changed files>`. Commit product+test files only as `slice(picker-row-match): land the exact cursor model variant and surface inject failures` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Never amend/rebase/push/stash/reset. Append `- iter 1 | lead | repair 1: <one line>` to `loop-cursor2/LOG.md`. Print a compressed summary including the before/after footer strings.
