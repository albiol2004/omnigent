# Scoped repair — loop-compact iteration 1, repair 1

Read `loop-compact/VERDICT.md` first, then `loop-compact/GOAL.md` (HARD isolation: never touch ~/.omnigent, ~/.claude/projects, :6767, `omni host`, the user's :17067 instance / /home/alex/omnigent-fixes-data, or /home/alex/omnigent; throwaway servers only on port ≥ 17100 with a scratch data dir, torn down by you; never kill processes you did not start). Repo `/home/alex/omnigent-fixes`, branch `trio-v0.10.0-fixes`.

Allowed writes ONLY: `tests/server/routes/test_fork_compact.py`, `loop-compact/evidence/iter1/compact-on-fork/` (script + outputs), `loop-compact/REPORT.md` (evidence numbers), `loop-compact/LOG.md`. No product code changes, no re-planning.

## Defect
`throwaway_fork.py` stubbed `compact_fork_items` entirely with a single marker whose `last_item_id` was the last source row, so the recorded fork had 1 item / 272 bytes and proved nothing. Production compaction keeps the last five assistant groups verbatim after the summary.

## Task
1. Rewrite the throwaway evidence so ONLY the LLM summary call is mocked (return a fixed summary string), while the real `compact_fork_items` / layered `compact` runs. Fork the ~3.9 MB synthetic session on a throwaway server (port ≥ 17100). Record in `THROWAWAY.json`: bytes before, bytes after, `fork_item_count`, count of retained non-summary items, the id of the compaction/summary item, the resolved model, and assert bytes-after < `OMNIGENT_FORK_MAX_CONTEXT_BYTES` and retained tail non-empty (last 5 assistant groups + their user turns present verbatim — compare text against the source).
2. Extend `tests/server/routes/test_fork_compact.py` with a test that asserts the compacted fork item set = one compaction item + the retained recent tail (non-empty, verbatim), mocking only the summary call.
3. Run `uv run pytest -q tests/server/routes/test_fork_compact.py tests/server/routes/test_fork_oversize_guard.py` and `pre-commit run --files tests/server/routes/test_fork_compact.py` — both clean. Tear down the throwaway server; `ss -ltnp | grep 171` must be empty afterwards.
4. Commit the test change as `slice(compact-on-fork): evidence and retained-tail test` with trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (product-only paths: the test file). Leave mailbox files uncommitted. Never amend/rebase/push/stash/reset.
5. Update the numbers in `loop-compact/REPORT.md`; append `- iter 1 | lead | repair 1: honest compaction evidence (<before>→<after> bytes, N retained)` to `loop-compact/LOG.md`. Print a compressed summary.
