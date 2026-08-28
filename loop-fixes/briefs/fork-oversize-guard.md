# Builder: fork-oversize-guard

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`.
Implement **only** this slice.

## HARD isolation (non-negotiable)
Never read/write `~/.omnigent`, `~/.claude/projects`, `~/.cursor`.
Never talk to `http://127.0.0.1:6767` or kill `omni host`. Never git
in `/home/alex/omnigent`. Work only in `/home/alex/omnigent-fixes`.
Throwaway: `OMNIGENT_DATA_DIR=<scratch>`, port ≥ 17000, tear down.
This slice should be unit/integration tests + helpers — **do not**
launch real Claude against user transcripts.

Do not edit GOAL.md/VERDICT.md. Do not touch sqlite-pool, kill-on-close,
or render-latency files.

## How to read code
These files are **>1 MB**. NEVER Read the whole file — transport
crashes. Use `sed -n 'start,endp'` only:

- Fork copy: `omnigent/server/routes/sessions/routes_core.py:1979-2200`
  (`async def fork_session` at 1990).
- Runner launch / clone: `omnigent/runner/native/orchestration.py:6283-6400`.
- JSONL clone: `omnigent/claude_native.py:1780-1843` `_clone_claude_transcript`.
- Rebuild: `omnigent/claude_native.py:4125-4202`
  `_ensure_local_claude_resume_transcript`.
- Item fetch `limit: 1000`: `omnigent/claude_native.py:4223` (paginate
  fully — loop already has `after`; raise page size and keep paging
  until empty).
- SDK full replay: `omnigent/inner/claude_sdk_executor.py:3052-3123`
  `_build_prompt` (`"Conversation so far:"` ~3094).
- Compaction honor on rebuild: scout cited `claude_native.py:4333-4344`
  `compacted_messages` — sed that band; honor **summary-only** markers
  (drop pre-summary records) when measuring/rebuilding.
- Measurement analog:
  `loop/evidence/iter1/rc-fork/scratch/measure_fork_bytes.py`
  (~3.9 MB synthetic). Do not read `helpers.py`.

## Task
Additive, env-overridable:

1. `OMNIGENT_FORK_MAX_CONTEXT_BYTES` default 600000 (~150k tokens).
2. Before launching a fork (route + runner native clone/rebuild + SDK
   first-prompt path), compute bytes the harness would receive.
3. If over threshold: honor existing summary-only compaction
   (drop pre-summary), re-measure; if still over, return a clear
   **4xx/error** naming actual size and threshold. Do not launch
   blind into "Prompt is too long".
4. Small sessions (< threshold) fork unchanged.
5. Paginate items fully (do not stop at one 1000-item page).

Keep changes rebase-friendly vs #5603/#5405: no route/store rewrite.
Prefer a small helper module if `routes_core.py` cannot take a large
insert — but do not create sprawling new packages.

## Tests / hooks
```
cd /home/alex/omnigent-fixes
uv run pytest -q tests/server/integration/test_sessions_child_sessions.py tests/runner tests/inner -k 'fork or oversize or compact or paginat' --maxfail=20
```
Add focused new tests under `tests/` (small files) for: threshold
refuse, compaction honoring, pagination, small-session unchanged.

Then:
```
pre-commit run --files <every file you changed>
```
Clean required.

## Evidence
`loop-fixes/evidence/iter1/fork-oversize-guard/`: run a unit/script
against the synthetic ~3.9 MB fixture (copy bytes logic; do not hit
production DB) showing refuse/compact + message with byte count.

## Finish
Do not commit. Print paths and results.
