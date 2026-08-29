VERDICT: SHIP

Independent re-eval after repair1 `f95026398`. Live picker now switches the
exact requested variant; bogus ids fail the web PATCH with 503 and do not
keep the bogus override.

## Live proof (evaluator, not builder)

Throwaway `127.0.0.1:18800`, conv `7481893be57440f392aa621efd1d204a`, pane
started by this eval (`evidence/iter1-eval-repair1/`). Switched **away**
from the current footer (not medium→medium):

- before: `GPT-5.6 Luna 272K Max`
- PATCH `cursor-grok-4.6-low` → **200**
- after: `Cursor Grok 4.6 Low` (sibling Medium not in footer)
- bogus `definitely-not-a-cursor-model-zzz` → **503**
  `runner_unavailable`, message names the model
- GET `model_override` after bogus = `null` (not the bogus id)

Builder `evidence/iter1/repair1/` (Medium→Low) is consistent with this.

## Matcher hole (closed)

`_picker_row_matches_display` is exact compact equality. Evaluated:

- `"Cursor Grok 4.6"` vs `"Cursor Grok 4.6 Medium"` → False
- `"Provider Mode"` vs `"Provider Model"` → False
- wrapped 41-col `"…Medi(Tab to\\n um  modify)"` vs Medium → True
  (`_picker_row_compact` strips the Tab hint and concatenates wrap)

## Fixture

`_IDLE` / `_REAL_PICKER_PANE` in `tests/test_cursor_native_bridge.py` are
verbatim 41-column `capture-pane -p` slices: composer
`→ Plan, search, build anything`, wrapped footer, wrapped picker row
`Medi(Tab to` / `um  modify)`. Matches live idle on this machine.

## PATCH honesty / other harnesses

`_surface_model_change_forward_failure` now rolls back then raises
`OmnigentError` (`RUNNER_UNAVAILABLE`). Still only called when
`_is_native_terminal_session`. Non-native
`test_patch_model_override_round_trips_through_snapshot` still 200s
(`claude-opus-4-7` persist). Residual: rollback unsets the column entirely,
so a failed attempt after a successful switch also clears the **previous**
good override (pane stays on Low; row becomes None). Acceptable vs lying
200; not a SHIP blocker.

## Prior SHIP slices

Parent of `f95026398` is `a4eda6797`. Diff `a4eda6797..f95026398` is only
the four scoped files. Untouched: `c24bed93f`, `a4eda6797`, `788c247fa`,
`479252e0d`, `bdc0fdb3a`, `9b83f39fb`.

## Acceptance 6

- vitest (4 render files): 675 passed
- pytest bridge + model_override: 45 passed
- pytest native/stream/forwarder/permissions + failed-payload: 161 passed
- Trio-compat `-k 'reasoning_effort or …'`: 5 passed, 250 deselected
- pre-commit on the four files: ruff/pyrefly/whitespace **pass**. The
  `no-hardcoded-models` hook still fails on pre-existing
  `loop-fork-real/evidence/**` (not in `f95026398`). Unrelated.

## Isolation

`:6767/health` 200. `~/.omnigent` / `~/.claude/projects` mtimes unchanged.
No `:187xx`/`:188xx` listeners after teardown. Eval tmux `kill-server`'d
on the throwaway socket only. User `:6767` panes not driven.

## Operator steps (unchanged)

Fast-forward `trio-v0.10.0-fixes`, `cd web && npm run build`,
`omni server stop`, then two prompts + a real picker switch on a
top-level cursor-native session.

commit: c24bed93f
commit: a4eda6797
commit: 788c247fa
commit: 479252e0d
commit: bdc0fdb3a
commit: 9b83f39fb
commit: f95026398
