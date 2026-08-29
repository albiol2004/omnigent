# Builder brief — slice 4 (picker-row-match)

You are a Trio Luna builder (`gpt-5.6-luna-max`). Work ONLY in
`/home/alex/omnigent-cursor2`.

Do not commit. Do not git in `/home/alex/omnigent`. Do not touch :6767,
`omni host`, write `~/.omnigent`. Do not type into, start, or kill
EXISTING tmux/cursor-agent sessions. You may use **mocked** tmux in
unit tests only (see existing `tests/test_cursor_native_bridge.py`).

## Writes ONLY

- `omnigent/cursor_native_bridge.py`
- `tests/test_cursor_native_bridge.py`

Do not edit `omnigent/cursor_native.py` (slice 5) or web files.

Large file: `cursor_native_bridge.py` — `sed -n` / `grep -n` only around
the ranges below. Read `omnigent/claude_native_bridge.py:3750-3772` and
`:144-157` for the discrimination pattern (do not port Claude glyphs
blindly).

## Diagnosis

Cause 8: `_picker_highlighted_row` at
`omnigent/cursor_native_bridge.py:898-904` returns the FIRST top-down
line starting with `→`. cursor-agent uses `→` as the **composer** glyph
(`  → Add a follow-up` sits **above** the model list). So the matcher
always sees the composer line, `_picker_row_matches_display` fails, and
the runner 503s "did not resolve to its exact picker row". Harness-wide.

Cause 9: `_picker_row_matches_display` `:907-911` allows
`normalized_row.startswith(f"{display} ")` so "Cursor Grok 4.6 Low/Fast/
Extra High" all match a display of "Cursor Grok 4.6".

Timing: `_MODEL_PICKER_SETTLE_S = 1.5` at `:84`; one sleep then one
highlight check in `inject_model_command` `:790-889`. Widen: re-check
the highlight a few times instead of one fixed settle.

Fixture `_IDLE = "Add a follow-up"` at
`tests/test_cursor_native_bridge.py:174` has **no** `→` — that is why
the unit suite shipped green. Update fixtures to a REAL captured pane
shape, e.g.:

```
  → Add a follow-up
Models matching "cursor-grok-4.6-medium"
 →  Cursor Grok 4.6 Medium
    Cursor Grok 4.6 High
```

(composer `→` first, picker `→` below `Models matching`).

Port Claude's idea: only treat a `→` as the picker highlight if it is
part of the picker list (below `_PICKER_MATCH_MARKER = "Models matching"`
at `:90`), never the composer input line. Tolerate wrap/truncation of
long display names (live pane ~41 cols): exact match **or** row is a
prefix of display / display is a prefix of concatenated wrapped lines
in the picker section — but do **not** accept a different effort
variant (reject if another variant's extra suffix is present unless
that is the expected display).

Prefer: match the highlighted picker row to `expected_display_name`
with equality after whitespace-normalize, plus a wrap-tolerant compare
that does not use `startswith(display + " ")` for variant siblings.

Callers type `/model {id}` at `:847`. Slice 5 will expose fully-qualified
ids; you should still reject a highlight that is clearly a different
variant than `expected_display_name`.

Test-first: add tests with the composer `→` line that **fail** on current
code, then fix.

Also keep: "No matches" still Escape + RuntimeError; successful match
still Enter; missing catalog still clean error.

Comments: short scenario comments; no issue numbers.

## Commands

```
cd /home/alex/omnigent-cursor2
export PYTHONPATH=/home/alex/omnigent-cursor2
uv run pytest -q tests/test_cursor_native_bridge.py
```

Print test counts and a DONE summary.
