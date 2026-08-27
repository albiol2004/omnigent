# Scoped repair — iteration 1, repair 1: measure the cursor-native render path

Read `loop/VERDICT.md` first, then `loop/GOAL.md` (investigation-only; nothing outside `loop/` may change; never kill processes; never touch real sessions or `~/.claude/projects`). Repo `/home/alex/omnigent`, product tree = commit ead098caf.

Allowed writes: `loop/REPORT.md`, `loop/evidence/iter1/rc-render/` ONLY. No re-planning, no touching other slices, no product code. Smallest correct addition.

## Task
Fill the evidence gap named in VERDICT.md "Unmeasured": stage-by-stage latency for **cursor-native** CLI output → server → SSE → store → DOM, with numbers, under `loop/evidence/iter1/rc-render/` (add e.g. `CURSOR-NATIVE.md` and grow the cursor-native column in `TIMING.md`). Then patch the render section of `loop/REPORT.md` so problem 2 has ranked confirmed causes for cursor-native too, and remove/qualify any "primarily claude-native" wording.

Stages to measure or bound (cite `file:line` at HEAD; use `grep -n` and `sed -n 'a,bp'`; NEVER read whole files — several exceed 1 MB):
1. tmux `capture-pane` polling — find the interval constant(s) (grep `capture-pane`, `_POLL`, `INTERVAL` in `omnigent/resource_registry.py`, `omnigent/inner/terminal.py`, `omnigent/runner/native/`, `omnigent/cursor_native*.py`); upstream #2702 says ~5 Hz. Give per-tick cost (time a real `tmux capture-pane -p` on this machine if a tmux server is running — read-only) and worst-case added delay.
2. `omnigent/cursor_native_permissions.py` polling — interval, whether it is on the text path or only the approval path, ms contribution.
3. How cursor-native text reaches `session_stream`/SSE — find the cursor-native forwarder/transcript reader (grep `cursor_native` in `omnigent/runner/native/`, `omnigent/*forwarder*`, `omnigent/inner/cursor_native_executor.py`); poll interval, per-delta POST vs batching, any hook-spawn cost (#4589 style).
4. SSE → store → DOM for a cursor-native session: which client pump handles it (`web/src/store/chatStore.ts` — `tapLiveDeltas` :4371-4393 vs the generic rAF pump; grep `harness` / `cursor` there), markdown throttle, React commit. Confirm with grep whether cursor-native deltas take the live-delta (no rAF) path.

For each stage: measured or derived ms, evidence (log excerpt, timing script output saved under the evidence dir, or constant with file:line), and confidence. Sum into an end-to-end floor and compare against the claude-native and claude-sdk columns. If a stage genuinely cannot be measured without a live cursor session, say so explicitly and mark it "bounded by constant, unmeasured" — never guess.

Candidate fixes for cursor-native must carry size, files, risk, and upstream-PR conflict assessment (#4976, #5603, #5405, #4913, #5081, #5544, plus #2702/#3000/#4589 if related).

## Finish
- `git status --porcelain` must show only `loop/` paths.
- Append to `loop/LOG.md`: `- iter 1 | lead | repair: cursor-native render path measured (<one-line result>)`.
- Print a compressed summary of the cursor-native column and the top cause.
