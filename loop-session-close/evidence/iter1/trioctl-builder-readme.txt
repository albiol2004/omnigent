🤖 Done. README-only edit, no commit/push, `/home/coder/omnigent` untouched, Trio mailbox files untouched, unrelated edits preserved.

## Files changed
- `README.md` — section `## trio-v0.12.0-fixes (this worktree)` (lines 614–622)

## Exact new paragraph

```markdown
Stock `v0.12.0` plus a thin Trio keeper set. Live install
`/home/coder/omnigent` (`~/omnigent`) is on `trio-v0.12.0-fixes`.
This worktree branch `trio-v0.12.0-fixes-close` carries the
`sys_session_close` native teardown fix until it is adopted into
the live install. Keepers: kill-on-close leftover tmux SIGKILL,
registered `agent_id` native launch-arg derivation (`--yolo`),
and queue-aware Cursor yolo auto-accept; the close/teardown fix
covers Claude, Codex, and Cursor children. Do not treat this as
upstream `main`; several close/leak PRs landed after the 0.12.0 tag.
```

## Summary
Corrected the stale claim that live `~/omnigent` stays on `trio-v0.10.0-fixes`. The paragraph now states the live install (`/home/coder/omnigent` / `~/omnigent`) is on `trio-v0.12.0-fixes`, and that this worktree branch `trio-v0.12.0-fixes-close` carries the `sys_session_close` native teardown fix pending adoption into the live install. Existing keeper bullets (kill-on-close leftover tmux SIGKILL, registered `agent_id` `--yolo`, queue-aware Cursor yolo auto-accept) are preserved verbatim, with a short clause noting the close/teardown fix covers Claude, Codex, and Cursor children. The "do not treat as upstream `main`" caveat is retained. Heading left unchanged (minimal change). No CHANGELOG added, per the brief.

## Verification results
- `git diff README.md`: clean 6-line removal / 9-line addition, hunk confined to the `trio-v0.12.0-fixes (this worktree)` section (see diff above).
- Line-length check (`awk` on lines 614–622): all lines ≤ 68 chars, under the 88-char limit; wrapping (~57–68) matches the surrounding README style.
- `git status --short`: only `README.md` newly modified by this slice. `loop-session-close/STATE.md` (`M`) and the `loop-session-close/{PLAN.md,briefs/*,evidence/iter1/}` (`??`) entries were already present at conversation start — pre-existing, not touched.
- No pytest run: this slice is README-only and the brief specifies no test command (only "Return the exact new paragraph").

## Concerns
- The section heading remains `## trio-v0.12.0-fixes (this worktree)` even though the worktree branch is `trio-v0.12.0-fixes-close`. I left it untouched because the brief scoped the edit to the paragraph ("Return the exact new paragraph") and asked for the smallest complete change; the body now clarifies the branch name. Flagging in case the Lead wants the heading updated to `## trio-v0.12.0-fixes-close (this worktree)` in a follow-up.
- "if it still fits the short note" — I judged the close/teardown clause fits as a single semicolon-joined tail on the keepers sentence, keeping the note short.
