# Scout brief — slice 6 (mirror-gap), READ-ONLY except DECISION.md

You are a Trio Luna scout (`gpt-5.6-luna-max`) in ASK/read-only mode.
Workspace: `/home/alex/omnigent-cursor2`.

HARD isolation: `~/.omnigent`, `~/.claude/projects`, `~/.cursor` are
**read-only** (you may **copy** log/db files out). Never write there.
Never touch live :6767 except GET health if needed. Never `omni host`.
Never git in `/home/alex/omnigent`. Do not type into, start, or kill
EXISTING tmux/cursor-agent sessions; `tmux capture-pane -p` on an
existing pane is the only allowed interaction with those.

The ONLY write allowed: `loop-cursor2/evidence/iter1/mirror-gap/`
(DECISION.md + copied evidence snippets). Do not change product code
unless Lead told you — you do NOT patch; you decide.

## Questions

Cause 7: conversation `52d47c71e54b4f61a2563bbaefe6ad34`
(`omnigent_conversation_metadata.kind=1`, label
`omnigent.wrapper=cursor-native-ui`) took **42**
`POST /v1/sessions/<id>/events` yet persisted **exactly one** row
(`pos=0 type=8 session.resource.created`) — zero user/assistant items.
Older conversations (`72126100228d44b7…`, `780cc792e842…`) persisted
correct order.

Hypothesis 6: server 500 on `response.failed` published without
`id` / `model` / `created_at` → pydantic tagged-union failure →
unhandled ASGI exception. Mentioned in
`~/.omnigent/logs/server/server-20260829-093025-885548.log` lines ~178
and ~377. **Copy** those lines into evidence; do not edit the log.

Also: does a failed user-row mirror stall `_awaiting_new_turn` /
epoch (`omnigent/cursor_native_forwarder.py` ~1226,
`omnigent/cursor_native_stream.py` `_start_new_epoch` 189–198)?

## Method

- Copy (cp) relevant log excerpts and, if readable, sqlite query
  **read-only** against a **copy** of the live db if you must — never
  write the live db. Prefer log + code `grep`/`sed` in the worktree.
- `sed -n` / `grep -n` on large files (`omnigent/runner/app.py`,
  `omnigent/cursor_native_forwarder.py`). Find event ingest /
  item persist / `response.failed` models.
- Do not re-derive slices 1–5.

## Deliverable

`loop-cursor2/evidence/iter1/mirror-gap/DECISION.md`:

- What the 42 POSTs were (event types if logs show them).
- Why zero user/assistant items persisted (failed posts? validation?
  wrong conversation id? stream-only deltas never mirrored?).
- Link to cause 4 epoch stall: yes/no/partial.
- Hypothesis 6: CONFIRMED or REFUTED with quoted error + code range.
- Fix-now vs follow-up: only a small clearly-in-scope server fix would
  be recommended; you do not implement it.
