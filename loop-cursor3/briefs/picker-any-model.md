# Builder brief — slice picker-any-model

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent-cursor3`. Mailbox `loop-cursor3/`. Iteration 1.

Do NOT read whole large files. Use grep/sed on the ranges below.
Do NOT touch `~/.cursor`, `:6767`, `/home/alex/omnigent` git, tmux session
`main`, or any pane you did not start. Do NOT run a live cursor-agent
model switch (Lead already reproduced). Do NOT commit unless the tests
below are green — then commit exactly:

```
slice(picker-any-model): navigate the cursor picker to the exact catalogued variant

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

No amend/rebase/push/stash/reset/checkout. PATH for pre-commit:
`PATH=/home/alex/omnigent/.venv/bin:$PATH`. Tests:
`cd /home/alex/omnigent-cursor3 && PYTHONPATH=/home/alex/omnigent-cursor3 uv run pytest -q tests/test_cursor_native_bridge.py`

## Writes (only)

- `omnigent/cursor_native_bridge.py`
- `tests/test_cursor_native_bridge.py`

## Line ranges (HEAD a4d9746ae)

- `inject_model_command` 797–950
- `_picker_filter_queries` / `_PICKER_QUERY_VARIANT_SUFFIXES` 953–972
- `_PICKER_EFFORT_INDEX` / `_picker_variant_settings` 980–998
- `_picker_set_variant` 1020–1055 (effort editor only; no list navigation)
- `_picker_highlighted_row` 1075–1096
- `_picker_row_matches_display` 1110–1114

## Verified failure (use as fixture, do not re-capture)

File:
`loop-cursor3/evidence/iter1/glm-before/glm-5.2-query-pane.txt`

The highlighted row is wrapped `GLM 5.2` + `High`, composer has `→ /model GLM 5.2`.
`--list-models` display for `glm-5.2-high` is **`GLM 5.2`** (no High). Strict
equality therefore fails. Live inject raised:
`cursor model 'glm-5.2-high' did not resolve to its exact picker row`.

`inject_model_command` never sends Up/Down on the **model list** — only Tab
into the effort editor. Confirm in code; then add list navigation.

## Catalogue suffixes that must be stripped/indexed

high, low, medium, xhigh, extra-high, max, none, fast, and *-fast
combinations. GLM ladder is high/max. Grok is low/medium/high/xhigh(+fast).
Do not special-case only GLM.

## Required behavior

1. After filter, if highlight is not the exact requested row, send Down/Up
   (with wrap detection) until `_picker_row_matches_display` succeeds or the
   list cycles.
2. Match catalog display `GLM 5.2` to picker `GLM 5.2 High` when the
   requested id's variant is high — the effort column is part of the row,
   not a different model. Still reject `GLM 5.2 Max` for `glm-5.2-high`.
3. Keep strict matching: never accept a sibling or truncated wrap
   (`Hig` without completing `High` unless the wrap continuation is joined
   the way `_picker_highlighted_row` already joins).
4. `_picker_set_variant` must understand `max` (and other non-grok editor
   labels if the editor uses them). If the highlight already is the exact
   variant, Enter without forcing the grok four-rung editor.
5. Tests: load the real captured pane; assert highlight parse; assert
   inject sends Down when a sibling is highlighted and Enter on the exact
   row; assert glm-5.2-high vs glm-5.2-max disambiguation; assert bogus id
   still Escape + RuntimeError; keep existing grok family-query tests.

Repo comments: short scenario comments, no issue numbers.

After tests: `PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files`
on the two files, then commit with the message above.
