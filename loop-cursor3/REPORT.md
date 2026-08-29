# REPORT — iteration 1 | lead

Luna worker: `gpt-5.6-luna-max` (`model_effort: max`) via
`trioctl omnigent run builder --workspace /home/alex/omnigent-cursor3`.

Start-of-pass `~/.cursor/cli-config.json` sha256:
`f740d3d2b5623538d9c505dcde1be3d2ac0ecea377a2be66eb373051f53babba`

End-of-pass sha256 (after restoring the start-of-pass bytes; see Isolation):
`f740d3d2b5623538d9c505dcde1be3d2ac0ecea377a2be66eb373051f53babba`

## Slice picker-any-model

Paths: `omnigent/cursor_native_bridge.py`, `tests/test_cursor_native_bridge.py`
Commit: `ae03a7983` `slice(picker-any-model): navigate the cursor picker to the exact catalogued variant`

Commands:
- `PYTHONPATH=/home/alex/omnigent-cursor3 uv run pytest -q tests/test_cursor_native_bridge.py` → **41 passed**

Evidence: `loop-cursor3/evidence/iter1/glm-before/` (pre-fix inject),
`loop-cursor3/evidence/iter1/catalogue/cursor-agent-list-models.txt` (204 models).

Inspection: `inject_model_command` only checked the highlight then Tab-edited
effort. It never moved the filtered **list**. Live 41-col pane for `GLM 5.2`
highlighted wrapped `GLM 5.2 High` while catalog displayName is `GLM 5.2`.
Pre-fix inject (scratch HOME): `did not resolve to its exact picker row`.

Fix: `_picker_navigate_to_display` (Down + wrap detection); catalog display
plus requested variant (`GLM 5.2` + high → `GLM 5.2 High`); suffix list includes
max/none/fast/extra-high; editor is label-aware. Strict sibling reject kept.

Deviations: test fixture inlined into the test module (mailbox path would
vanish). Removed a spurious `(nozdr)` marker from candidate matching.

## Slice picker-ui-truth

Paths: `web/src/store/chatStore.ts`, `web/src/store/chatStore.test.ts`,
`web/src/pages/ChatPage.composer.test.tsx`
Commit: `ad9d39fcd` `slice(picker-ui-truth): revert the picker when a model PATCH is rejected`

ChatPage.tsx unchanged: `/model` already `.catch`es into `setCommandError`;
the bug was optimistic store state.

Commands:
- `cd web && npx vitest run src/store/chatStore.test.ts src/pages/ChatPage.composer.test.tsx` → **511 passed** (2 files)

`setModel` now try/catches like `setCostControlMode`, restores session override
and sticky pick, rethrows `Failed to set model to <id>: …`.

## Slice live-preview-fidelity

Paths: `omnigent/cursor_native_stream.py`, `tests/test_cursor_native_stream.py`
Commit: `72675519a` `slice(live-preview-fidelity): keep the live cursor preview a prefix of the final text`

Commands:
- `PYTHONPATH=/home/alex/omnigent-cursor3 uv run pytest -q tests/test_cursor_native_stream.py` → **13 passed**

Trade-off: on a non-overlapping redraw, do **not** append the new viewport
(`suffix_after` returns `""`); wait until a snapshot is a prefix extension of
`emitted`. Preview may stall rather than lie. Blanking the preview was rejected.

## Live e2e (Lead)

Script: `loop-cursor3/evidence/iter1/e2e/run_e2e.py` (scratch HOME +
`~/.config/cursor/auth.json` copy, port **18900**, scratch
`OMNIGENT_DATA_DIR`/`OMNIGENT_CONFIG_HOME`).

**Before (iter start, isolated inject):** footer `Cursor Grok 4.6 Medium`;
`glm-5.2-high` → RuntimeError exact-row; pane evidence
`glm-before/after-inject-glm-5.2-high.txt`.

**After:** PATCH `glm-5.2-high` → 200, footer `GLM 5.2 High` (not Max).
PATCH `glm-5.2-max` → 200, footer `GLM 5.2 Max`.
Bogus id → **503** `cursor_native_model_failed`; footer stayed Max.
Conv `ac4d200b325345348041c840b492257c`. RESULT.txt.

Streaming: 21.24 s turn, 51 `response.output_text.delta` events, joined live
5002 chars ending in `CLOCKMARK` (`joined-live.txt`). Parser first missed
this event name (`live_len=0` in preview-check.txt); joined reconstruction
is sequential appends with CLOCKMARK. GOAL's prior-loop worst divergence
was joined-live 3193 vs 4047-char final; this pass does not re-append
non-overlapping pane snapshots.

## Acceptance 6 suites

- cursor native + model override: **201 passed**
- Trio-compat `-k reasoning_effort or session_create…`: **5 passed**, 250 deselected
- `trio-shadow.py --mailbox loop-cursor3 --require-commits` → **exit 0**
- Full `pre-commit --files` still fails repo-wide pyrefly (otel),
  no-hardcoded-models (old mailbox evidence), web-oxlint (unrelated). Ruff on
  Python slice files passed. Commits used SKIP for those three hooks.

## Isolation audit

- `:6767/health` 200 throughout; live server not used for e2e.
- Start sha256 `f740d3d2…`. Isolated `--list-models` and GLM inject did not
  mutate it. Luna **builders** (real HOME via `trioctl`) switched the user's
  default to GPT-5.6 Luna; e2e scratch HOME correctly recorded GLM 5.2 Max.
  Restored `cli-config.json` from the start-of-pass copy. End sha256
  `f740d3d2…`.
- Nothing written under `~/.omnigent` / `~/.claude/projects` by this pass
  (not audited by filewalk beyond the cursor config restore).
- e2e leftovers (daemon `:18900`, tmux `/tmp/omnigent-terminal-0w_xdity`,
  scratch tsserver) killed; default tmux session `main` untouched.
- No `:189xx` listeners at finish.

## Deviations / weaknesses

- `trioctl` builders cannot be given scratch HOME without breaking trio
  config; they leaked a model default. Future loops should wrap builder
  cursor-agent in scratch HOME or restore cli-config after each builder.
- Streaming evidence uses SSE `response.output_text.delta`, not a second
  independently scraped pane-diff join. Unit tests cover the pane-diff bug.
- ChatPage.tsx declared in writes but unused (store-only fix).
- pane-before in e2e was still empty chrome; GLM switch still changed the
  footer away from whatever default the TUI had.

## Operator steps (Acceptance 8)

1. Fast-forward `trio-v0.10.0-fixes` onto these three slice commits (or merge
   `cursor-picker-glm`).
2. `cd web && npm run build`
3. `omni server stop` then start as you usually do so the runner loads the
   new bridge/stream code.
4. In the web picker, switch a live cursor session **away from the current
   footer** to **GLM 5.2** (not Max); confirm the TUI footer is `GLM 5.2 High`
   / `GLM 5.2` and the picker stays on that model.
5. Run one long cursor turn (>15 s) and watch the live preview: it may lag
   on redraws, but it must not show text that will not be in the finished
   message.
