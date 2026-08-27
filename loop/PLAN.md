# PLAN — iter 1 (investigation only)

## Objective
Produce an evidence-backed root-cause report for fork context overload,
slow CLI-output rendering, and unkilled CLI sessions. Confirm or refute
every scouted fact at HEAD `9926c9145` (product tree `ead098caf`). No
product code changes.

## Verification standard
mode: implement-then-smoke

Evidence for each investigation slice lives under
`loop/evidence/iter1/<slice>/` (reproductions, measurements, process
listings, citation tables). Claims without a file:line at HEAD plus an
artifact in that directory are unconfirmed hypotheses, not causes.

Smoke: Lead cross-checks worker citations with `sed -n` against HEAD,
`git status --porcelain` is loop/-only, then
`python3 /home/alex/pruebas/agent-trio-template/metrics/trio-shadow.py --mailbox loop --require-commits`.

## Out of scope
No edits outside `loop/`. No git checkout/stash/reset/amend/push. Do not
kill processes we did not start. Do not touch `~/.claude/projects` or
real user sessions. Reproductions use temp data dirs / scratch only.
No `slice(...)` product commits (no code-changing slices).

```yaml
slices:
  - id: rc-fork
    repo: .
    writes: [loop/evidence/iter1/rc-fork/]
    reads: []
    gate: false
    status: complete
    iteration: 1
  - id: rc-render
    repo: .
    writes: [loop/evidence/iter1/rc-render/]
    reads: []
    gate: false
    status: complete
    iteration: 1
  - id: rc-kill
    repo: .
    writes: [loop/evidence/iter1/rc-kill/]
    reads: []
    gate: false
    status: complete
    iteration: 1
  - id: rc-report
    repo: .
    writes: [loop/REPORT.md, loop/LOG.md, loop/PLAN.md, loop/briefs/, loop/evidence/iter1/_trioctl/]
    reads: []
    gate: false
    status: complete
    iteration: 1
```

## Slices

### rc-fork
status: complete
writes: [loop/evidence/iter1/rc-fork/]
done: Every GOAL scouted fork fact confirmed/refuted with `file:line` at
HEAD; synthetic large-conversation measurement of prompt/transcript
bytes reaching `claude`; ranked causes; candidate fixes with
size/files/risk/upstream-PR conflict.

### rc-render
status: complete
writes: [loop/evidence/iter1/rc-render/]
done: Per-stage latency budget (hook, 250 ms poll, per-delta POST,
session_stream, SSE, store, React) from logs/instrumentation copies in
scratch; dominant stage identified; scouted render facts
confirmed/refuted; ranked causes + candidate fixes.

### rc-kill
status: complete
writes: [loop/evidence/iter1/rc-kill/]
done: Orphan census NOW (`ps`/`pgrep`, list only); per-path trace of
what each session-ending path actually kills; scouted kill facts
confirmed/refuted; ranked causes + candidate fixes.

### rc-report
status: complete
writes: [loop/REPORT.md, loop/LOG.md, loop/PLAN.md, loop/briefs/, loop/evidence/iter1/_trioctl/]
done: `loop/REPORT.md` satisfies GOAL Acceptance 1–3; captured `trioctl`
results and Luna model per worker; LOG line for iter 1.
