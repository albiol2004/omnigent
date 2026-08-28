# Compact-on-fork evidence

## Files changed

- `omnigent/fork_compact.py`
- `omnigent/server/routes/sessions/routes_core.py`
- `omnigent/stores/conversation_store/__init__.py`
- `omnigent/stores/conversation_store/sqlalchemy_store.py`
- `tests/server/routes/test_sessions_fork.py`
- `tests/server/routes/test_fork_oversize_guard.py`
- `tests/server/routes/test_fork_compact.py`
- `tests/fork_context/test_fork_compact_model.py`

## Verification

- Repair 1 requested pytest suite: 8 passed, 1 warning.
- Requested pre-commit files: all applicable hooks passed.
- SQL store regressions: 210 passed, 1 skipped.
- Prior-slice output is in `pytest.txt`; repair output is in `PYTEST.txt`,
  `pre-commit.txt`, and `sql-store.txt`.
- `pre-commit` was not on `PATH`; the equivalent `uv run pre-commit`
  command passed.
- The unavailable bare invocation is recorded in `pre-commit-path.txt`.

## Resolved-model log format

`Fork compaction model resolved: source=<step> model=<model-id>`

The precedence steps are `env`, `source_override`, `target_spec`, and
`source_spec`.

Repair 1 throwaway evidence uses the real `compact_fork_items` and layered
`compact` path. Only `runtime.compaction.summarize_history` returns the fixed
summary text; the retained tail is compared with the synthetic source.
