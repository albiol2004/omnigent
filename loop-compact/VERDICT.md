VERDICT: SHIP

Independent Evaluator re-check after repair 1 (`3b045eaeb`). Isolation
held. Product files were not edited in this pass.

## Repair (a) — retained recent window

**Pass.** `throwaway_fork.py` does not assign or patch
`compact_fork_items`. The only mock is
`omnigent.runtime.compaction.summarize_history` (Layer-2 LLM).
`compact()` / `_replacement_items` stay on the real path.

`THROWAWAY.json`: HTTP 201; **3,944,621 → 55,766** bytes (under
600,000); **640 → 10** fork items; `summary_last_item_id=u315`;
retained ids `a315,u316,a316,u317,a317,u318,a318,u319,a319`;
`retained_tail_verbatim=true`; `source_unchanged=true`;
`resolved_model=mock-compact-model`; `summary_call_count=1`; port
17110; scratch torn down.

Independent spot-check of `_synthetic_items()`: `items[-9:]` ids match
JSON; texts are `A315`/`U316`/…/`A319` plus the 6000-char body, same
as source rows. Boundary `u315` is the user turn before the protected
window (default 5 assistant groups).

`test_oversized_fork_keeps_recent_assistant_tail_verbatim` mocks only
`summarize_history`, asserts compaction + 9 verbatim messages,
`last_item_id == items[-10].id`, source snapshot unchanged.

Evaluator pytest:
`tests/server/routes/test_fork_compact.py`
`tests/server/routes/test_fork_oversize_guard.py` — **8 passed**.

## (b) Source unmodified

**Pass.** Route tests and throwaway `source_unchanged`.

## (c) Small fork equality

**Pass.** `test_fork_keeps_small_history_unchanged`:
`replacement_items is None`, fork items `== [item]`.

## (d) Model order + log

**Pass.** Unchanged `resolve_fork_compact_model` tests (env → pin →
target spec → source spec). Compact path logs resolved model. Throwaway
uses `OMNIGENT_FORK_COMPACT_MODEL`; compaction item model
`mock-compact-model`.

## (e) Native resume

**Pass.** Compacted forks still set
`resume_source_native_session` false when `replacement_items` is set
(`1c2a417e3`). No JSONL clone of the fat source.

## (f) 409 running; compact=0 → 413

**Pass.** Existing tests still in the 8-passed run.

## (g) Prior SHAs unamended

**Pass.** Ancestors of HEAD: `480b6eea9`, `780962a5d`, `ead098caf`,
`b47adae25`, `4f8f6f673`, `eabf6b101`, `b0dc3bfaa`, plus
`1c2a417e3`, `22793b2dd`. Repair is a **new** `3b045eaeb`, not an
amend.

## Isolation

- `:6767/health` → **200**
- testdb mtime **1787905289** = baseline
- `ss -ltnp | grep 171`: `kdeconnectd *:1716` only; no ≥17100 leftover

## UI / pre-commit (unchanged from iter 1)

Progress copy remains `Summarizing history…`. `uv run pre-commit` on
web files still hits pre-existing oxlint; not a ship blocker.

## Acceptance 5

REPORT still has operator steps: rebuild web, restart `:17067`, live
deploy/rollback via `loop-fixes/REPORT.md`. Expect a **summary + recent
turns**, not a one-item 272-byte fork.

commit: 1c2a417e3
commit: 22793b2dd
commit: 3b045eaeb
