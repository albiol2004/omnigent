# Builder brief — slice 5 (picker-model-list)

You are a Trio Luna builder (`gpt-5.6-luna-max`). Work ONLY in
`/home/alex/omnigent-cursor2`.

Do not commit. Do not git in `/home/alex/omnigent`. Do not touch :6767,
`omni host`, write `~/.omnigent`. No live tmux.

## Writes ONLY

- `omnigent/cursor_native.py`
- `tests/test_cursor_native.py`

Do not edit `omnigent/cursor_native_bridge.py` (slice 4).

Ranges: `_CURSOR_UNMAPPED_CLAUDE_RE` / `_CURSOR_DOTTED_CLAUDE_RE` /
`_cursor_base_model_id` / `parse_cursor_cli_model_options` at
`omnigent/cursor_native.py:214-292`. Use `sed -n`; no full-file read
of huge files.

## Diagnosis (cause 10)

`parse_cursor_cli_model_options` collapses variants via
`_CURSOR_VARIANT_SUFFIX_RE` and rewrites dotted Claude ids
(`claude-4.6-sonnet-medium` → `claude-sonnet-4-6`) which **never**
appear in `cursor-agent models`. `_CURSOR_UNMAPPED_CLAUDE_RE` **drops**
real injectable ids such as `claude-4-sonnet`.

The web picker types the `id` into `/model <id>`. Invented ids →
genuine "No matches". Collapsed effort → wrong variant after slice 4
starts matching rows.

Ground truth: `cursor-agent models` includes
`cursor-grok-4.6-low/-medium/-high/-xhigh` (± `-fast`);
`cursor-grok-4.6-high` displays as "Cursor Grok 4.6".

## Required contract

- Build options **only** from ids the CLI actually printed (the `id`
  field of each parsed line). Drop or stop applying the dotted rewrite
  that synthesises non-existent ids.
- Stop dropping injectable ids like `claude-4-sonnet`.
- Expose the **variant the user will get**: do not collapse
  `-low/-medium/-high/-xhigh/-fast` into an ambiguous base for the
  picker. Each CLI line → one option (`id` = printed id, `displayName`
  = printed name, keeping effort words that distinguish variants).
- `isDefault` / `isCurrent` still work from tags on those exact ids.

## Tests

`tests/test_cursor_native.py` currently **encodes the old wrong
behavior**:
- `test_parse_cursor_cli_model_options_normalizes_base_ids` (~177)
  expects collapsed ids (`gpt-5.3-codex`, `claude-opus-4-6`) and
  **omits** `claude-4-sonnet`.
- `test_parse_cursor_cli_model_options_logs_unmapped_claude_ids` (~223)
  asserts `claude-4-sonnet` is absent.

Rewrite these to the new contract (test-first: change tests to expect
printed ids + `claude-4-sonnet` present, then implement). Keep empty
catalog rejection. Add a case with grok effort variants all present as
distinct rows (`cursor-grok-4.6-medium` vs `-high`).

If other tests in this file depend on collapsed ids, update only those
assertions (do not drive-by refactor).

Comments: short scenario comments; no issue numbers.

## Commands

```
cd /home/alex/omnigent-cursor2
export PYTHONPATH=/home/alex/omnigent-cursor2
uv run pytest -q tests/test_cursor_native.py
```

Print DONE + test output.
