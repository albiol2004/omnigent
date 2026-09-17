# Builder: slice(readme)

You are a GLM 5.2 Trio builder. Workspace:
`/home/coder/omnigent-dev`. README only. No commit/push.
Never touch `/home/coder/omnigent`.

## Edit

`README.md` section `## trio-v0.12.0-fixes (this worktree)`
around lines 612-618 currently says live `~/omnigent`
stays on `trio-v0.10.0-fixes`. Correct it:

- Live install `/home/coder/omnigent` (or `~/omnigent`) is
  on `trio-v0.12.0-fixes`.
- This worktree branch `trio-v0.12.0-fixes-close` carries
  the sys_session_close native teardown fix until that
  branch is adopted into the live install.
- Keep the existing keeper bullets (kill-on-close leftover
  SIGKILL, registered agent_id `--yolo`, queue-aware Cursor
  yolo auto-accept) and mention close/teardown for Claude,
  Codex, and Cursor children if it still fits the short
  note.

No CHANGELOG: recent fork commits did not add one.

Return the exact new paragraph.
