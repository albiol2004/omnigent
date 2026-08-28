VERDICT: SHIP

The production claude-native restart refusal is fixed (`54b9ca859`).
Repair 2 (`7792bcf5f`) stops a non-fork Claude SDK cold replay from
raising at `_build_prompt`. An 800,133-byte unlabeled replay no longer
413s; it logs at INFO and returns the prompt.

## Known limitation (not a blocker)

A real Omnigent SDK turn does **not** carry fork labels into the
executor. `_extract_role_keyed_messages` in
`omnigent/runtime/harnesses/_executor_adapter.py:1000` copies only
`role` and `content`. `_has_fork_labels` therefore returns False on
the harness path even when AP items have `omnigent.fork.carry_history`.
The executor guard is defense-in-depth and will not fire on a normal
fork launch through that adapter. That is acceptable: `fork_session`
plus compact-on-fork (`routes_core.py:2217-2247`, `1c2a417e3`) already
refuse or compact before launch. A normal (non-fork) session cannot
be refused at `:3164` unless someone stamps fork labels onto inner
messages.

Direct `_build_prompt` / labeled-message tests still 413 when labels
are present.

## 1. Call sites

| Location | Non-fork resume/restart? | Raises? |
|---|---|---|
| `fork_context.py:71-98` | helper; `guard=False` logs+returns | only if `guard=True` |
| `claude_native.py:1890` clone | fork clone only | fork |
| `claude_native.py:4254` resume transcript | default `guard=False` | no on resume |
| `orchestration.py:6325` cold resume | incident path, `guard=False` | no |
| `orchestration.py:6354` / `6424` | fork clone / fork rebuild | yes |
| `codex_native.py:1825` clone | fork | yes |
| `codex_native.py:1920` + CLI `1157` | resume `guard=False` | no |
| `orchestration.py:3922` / `3973` | fork / resume | as labeled |
| `pi_native_resume.py:629` + orch `1988`/`2031` | resume / fork | as labeled |
| `orchestration.py:1830` opencode | `guard=fork_carry_history` | no on lost-session resume |
| `orchestration.py:3263` qwen | caller gated on fork labels | fork |
| `orchestration.py:2451` cursor preamble | gated `fork_carry_history` | fork |
| `routes_core.py:2217-2247` | POST fork | yes, then compact |
| `claude_sdk_executor.py:3164` | unlabeled / adapter-stripped: `guard=False`; labeled messages: True | no on ordinary SDK launch |

## 2. Repro (eval2)

`loop-fixes/evidence/hotfix/eval2/RESULT.json`

- Unlabeled 800,133-byte `_build_prompt(resume_session=False)`: no raise;
  INFO skip log.
- Same messages with `metadata.labels[omnigent.fork.carry_history]=1`:
  413.
- Adapter extract of fork-labeled AP items: keys `{role, content}` only;
  `_has_fork_labels` is False.

Native incident evidence from the prior pass remains under
`loop-fixes/evidence/hotfix/eval/` (~1.10 MB resume writes; fork 413).

## 3. Tests and pre-commit

Focused: 444 passed (`loop-fixes/evidence/hotfix/eval2/focused-tests.log`).
Trio-compat: 5 passed (`loop-fixes/evidence/hotfix/eval2/trio-compat.log`).
pre-commit on `44f69fc88..HEAD`: passed
(`loop-fixes/evidence/hotfix/eval2/precommit.log`).
`test_fork_compact.py` included (compact-on-fork still active).

## 4. Isolation

- `GET http://127.0.0.1:6767/health` → `200`.
- No `:173xx` listeners.
- No leftover servers; no `omni host`; no git in `/home/alex/omnigent`.
- `~/.claude/projects` mtime unchanged (2026-08-27).
- Product files not edited in this eval.
