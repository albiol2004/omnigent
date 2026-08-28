# cli-summary-for-rebuild-paths

## Files

- `omnigent/fork_compact.py`
- `omnigent/fork_compact_cli.py`
- `tests/fork_context/test_fork_compact_cli.py`
- `tests/fork_context/test_fork_compact_model.py` was pre-existing worktree
  state and was included in verification without edits here.

## Verification

- Focused pytest: `20 passed in 0.16s`.
- Ruff format and ruff check: passed for all four requested files.
- `fork_compact_cli.py`: 199 lines.
- Focused pre-commit: ruff passed; pyrefly failed on 33 existing missing optional
  dependencies; hardcoded-model check failed on existing `loop-fork-real/evidence`
  JSON artifacts.

## Result

CLI-first fork compaction uses isolated subscription CLIs, strips Anthropic
credential variables, reports CLI failures, and keeps API fallback opt-in.
