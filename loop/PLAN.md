# PLAN — iter 2 (investigation only)

## Objective
Investigate problem 4 / slice **rc-freeze** only: session open hangs
~1 min then self-heals. Preserve iter-1 slices as complete. No product
code changes.

## Verification standard
mode: implement-then-smoke

Evidence for rc-freeze lives under
`loop/evidence/iter2/rc-freeze/` (transport facts, timeout constants
with file:line, DB/event-loop notes, log excerpts, optional read-only
SSE-hold reproduction). Claims without a file:line at product tree
`ead098caf` plus an artifact in that directory are unconfirmed
hypotheses, not causes.

Smoke: Lead cross-checks worker citations with `sed -n` against HEAD,
`git status --porcelain` is loop/-only, then
`python3 /home/alex/pruebas/agent-trio-template/metrics/trio-shadow.py --mailbox loop --require-commits`.

## Out of scope
No edits outside `loop/`. No git checkout/stash/reset/amend/push. Do not
kill processes we did not start. Do not touch `~/.claude/projects` or
real user sessions. Reproductions use temp data dirs / scratch only, or
read-only GETs against the running server. Do not redo rc-fork /
rc-render / rc-kill. No `slice(...)` product commits.

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
  - id: rc-freeze
    repo: .
    writes: [loop/evidence/iter2/rc-freeze/, loop/REPORT.md]
    reads: []
    gate: false
    status: complete
    iteration: 2
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
done: `loop/REPORT.md` satisfies GOAL Acceptance 1–3 for problems 1–3;
captured `trioctl` results and Luna model per worker; LOG line for
iter 1. Problem 4 is iteration 2 (`rc-freeze`).

### rc-freeze
status: complete
writes: [loop/evidence/iter2/rc-freeze/, loop/REPORT.md]
done: Transport facts (HTTP/1.1 vs h2; long-lived conn count per
open session; close-on-switch); ~30/60/70 s constants with file:line;
updates-WS 4 s rescan + snapshot/`/items` DB/event-loop facts; local
server/runner log excerpts; reproduction or explicit unreproduced
bound. Fold problem-4 section into REPORT recommended fix order.
