# native-fork-passthrough

## Changes

- Native Claude/Codex forks with same-family captured history bypass the
  rendered-size preflight and server compaction.
- Source harness resolution prevents SDK or cross-family sources from using the
  passthrough.
- Native transcript clones accept an explicit guard override and default to the
  `OMNIGENT_FORK_NATIVE_GUARD` environment setting.
- Clone fallback tests cover passthrough, guarded rebuild, and compact-boundary
  trimming.

## Verification

- Focused pytest: 268 passed, 1 warning.
- Ruff format: passed.
- Ruff check: passed.
- Remaining pre-commit failures are repository-wide and unrelated: Pyrefly
  cannot import optional packages, and the hardcoded-model check reports
  existing `loop-fork-real` evidence files.

