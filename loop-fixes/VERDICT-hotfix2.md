VERDICT: SHIP

Hotfix `47cbe1a31` stops an oversize same-host native clone from
killing fork launch. `ForkContextTooLarge` from the clone falls
through to rebuild-from-items with `guard=True`. Compacted fork
items resume; still-oversize items still 413. Generic clone errors
and non-oversize clones are unchanged.

## 1. Diff review

Claude (`orchestration.py:6364-6437`): clone `except ForkContextTooLarge`
sets `clone_context_too_large` and logs INFO; the rebuild `if` (was
`elif`) also opens when that flag is set. Rebuild still calls
`_ensure_local_claude_resume_transcript(..., guard=True)` on the
fork session id. Generic `Exception` does not set the flag, so
rebuild stays skipped and launch is fresh. Successful clone keeps
`clone_context_too_large=False` and `fork_source_external_id` set,
so rebuild does not run. Cold resume still requires
`session_external_id is not None` and uses `guard=False`.

Codex (`orchestration.py:3845-3927`): the rebuild `if` already ran
when clone left `external_session_id` unset. Catching oversize
(instead of re-raising) uses that path with `guard=True`. Codex
generic clone errors already rebuilt from items before this commit;
that is unchanged.

## 2. Repro

`loop-fixes/evidence/hotfix2/eval/RESULT.json`
(script: `verify_clone_fallback.py`; scratch
`/tmp/hotfix2-eval-00nvkgkz`; `_CLAUDE_PROJECTS_DIR` patched).

| Case | Result |
|---|---|
| 782 kB source jsonl + compact fork items | `--resume` new uuid; dest 701 B; rebuild `guard=True`; clone uuid unused |
| 782 kB clone + 1.1 MB fork items | 413 after rebuild (`actual_bytes=1100687`) |
| generic `RuntimeError` on clone | fresh launch; `rebuild_calls=[]` |
| 1.2 kB clone | `--resume` cloned uuid; `rebuild_calls=[]` |
| non-fork oversize resume | `--resume`; `guard=False`; clone not called |

## 3. Tests and pre-commit

Focused: 255 passed (`eval/focused-tests.log`).
Trio-compat: 5 passed (`eval/trio-compat.log`).
pre-commit on `9555d49e4..HEAD`: passed (`eval/precommit.log`).

No Codex clone-fallback unit test. Accepted: Codex control flow is
the pre-existing sequential rebuild `if`, only the oversize `except`
changed.

## 4. Isolation

- `GET http://127.0.0.1:6767/health` → `200`.
- No `:174xx` listeners.
- `/home/alex/.claude/projects` mtime unchanged (2026-08-27 20:48).
- No leftover throwaway servers; product files not edited in this eval.
