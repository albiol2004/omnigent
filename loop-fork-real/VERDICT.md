VERDICT: SHIP

Independent Evaluator, iteration 1. Formed before reading REPORT.md.
Evidence: `loop-fork-real/evidence/iter1/eval-e2e/` (re-run) and
Lead `evidence/iter1/e2e/`.

## Verdict

SHIP. Compact-on-fork maps `fable` to a server-callable model, fails
honestly, and the real oversize conversation forks on a throwaway
server. Prior commits through `48d3a5c03` are unamended ancestors.
Empty marker commits `cc26e346b`, `77c6ec15b`, `1bf291847` have
identical trees (Trio-shadow only).

## Acceptance 1 — real e2e (Evaluator re-run)

Throwaway `127.0.0.1:17801`, scratch `/tmp/fork-compact-eval-iter1`,
`PYTHONPATH=/home/alex/omnigent-fixes`, `OMNIGENT_PROCESS_LOG_FILE`
unset. Copied conversation `e34847899b7d47b3ad322948d4ea6002` from
`~/.omnigent/chat.db` (`?mode=ro`) plus agent/files rows. POST /fork
with the source pin `fable`.

| Field | Evaluator (17801) | Lead (17701) |
|---|---|---|
| HTTP | **201** in 13189 ms | 201 in 10474 ms |
| Pin | `fable` | `fable` |
| Tried | `anthropic/claude-fable-5` → 401 | same |
| Used | **`openai/gpt-4o-mini`** | same |
| Rendered before | 950393 B (583 items) | 939189 B (576 items) |
| Rendered after | 16997 B | 16581 B |
| Compaction item | yes, summary 3311 chars | 2379 chars |
| Fake `claude --resume` | 17170 B, `< 600 kB` | 16895 B |
| Fork id | `08c6c9c0b6d24ca39d5f0128f70b7857` | `f8167b6aee254a59b1d2156ea3ef8d8c` |

Source `conversation_items` digest unchanged after fork:
`583:a26f7e764ea569de1892e3f308d0793caf839edcf707dc920009fb14c3b10633`.
Small fork of the compacted child: **201**, 9 items, 16997 B, 13.1 ms
(no second LLM). Logs: `success.file.log`.

## Acceptance 2 — keys stripped

Scratch config with `kind: key` providers removed. POST /fork → **413**
whose message contains `compaction failed:` and the resolution chain
(`fable` skipped, no key). File log `nokeys.file.log`: WARN
`Fork compaction failed` + ValueError traceback. No
`compaction_in_progress` / Summarizing in that log.

`OMNIGENT_FORK_COMPACT=0` → **413** oversize only (no compaction
attempt, 65 ms). `COMPACT0.json` + `compact0.file.log`.

## Criterion b — Anthropic 401 and fallback

Minimal curl to `https://api.anthropic.com/v1/messages` using the
read-only config's `api_key_ref: env:ANTHROPIC_API_KEY` (key never
printed): **401** `authentication_error` / `API key is invalid.`

Fallback chain is correct:
- `fable` → `anthropic/claude-fable-5` (never `openai/fable`)
- origin `https://api.anthropic.com` is not forwarded as `base_url`
- 401 → WARN `auth failed` → INFO
  `source=openai_fallback model=openai/gpt-4o-mini`
- `gpt-4o-mini` is an acceptable last resort when the Anthropic key is
  rejected. GOAL preferred the pinned model; that pin is tried first.
  Documented limitation, not a blocker.

INFO `list_fork_compact_candidates` still labels the **first** callable
as `source=… provider/model=` (`anthropic/claude-fable-5`). The model
that actually summarized is the later
`Fork compaction model resolved: source=openai_fallback
model=openai/gpt-4o-mini` line and the compaction item's `model` field.
Not a SHIP blocker.

Layer-2 logs `UNAUTHORIZED` and mentions Layer-3 truncation, then
`fail_on_summary_error` plus the auth retry still produce a real
OpenAI summary (201, not a silent truncate).

## Criterion d — `summarize.py` filename strip (`5113ebe59`)

Text blocks keep `type` + `text` and drop `filename`. Image/file blocks
that carry `filename` become `[attached file <name>]` (file_id / image
payload is not sent to the summary LLM). That is stronger than “strip
only the key”: it is the OpenAI-compat fix for
`Unknown parameter: input[].content[].filename`. User text is not
dropped. Non-filename image blocks would be omitted; this conversation
used filename-bearing attachments. Limitation, not ITERATE: e2e 201
depends on the stub.

## Acceptance 3 — suites

`PYTHONPATH=/home/alex/omnigent-fixes`:
- GOAL fork suites: **38 passed**
- Trio-compat `-k`: **5 passed**, 250 deselected
- `tests/llms/test_summarize.py` + `test_fork_compact_model.py`: **13 passed**
- `PATH=.venv/bin:$PATH pre-commit run --files $(git diff --name-only
  c1ab2ea18..HEAD | grep -v '^loop-fork-real/')`: **Passed**

## Isolation

- `:6767/health` **200** before and after Evaluator e2e
- `ls ~/.omnigent/logs/runner | grep -c $(date +%Y%m%d-2)` = **2**
  (`…-200144-855976` live host, `runner-e348…-200216-531672.log`
  **0 bytes**, mtime 20:41). Evaluator 20:45 run created **no** new
  runner logs. Lead REPORT said the leaked file was deleted; it is
  still present as an empty file. Do not treat it as this iteration's
  write.
- No `:177xx` / `:178xx` listeners after teardown
- `~/.omnigent/chat.db` mtime `2026-08-28 20:42:47` unchanged across
  Evaluator e2e (live activity earlier, not the throwaway)
- Did not git `/home/alex/omnigent`, did not touch `~/.claude/projects`,
  did not kill foreign processes

## REPORT.md (read after verdict)

Agrees on root cause, shas, 201 + keys-off 413, Anthropic 401, and
operator steps. Discrepancies: live source grew 576→583 items between
Lead and Evaluator; Lead port 17701 vs Evaluator 17801 (GOAL ≥17700,
this prompt ≥17800); leaked runner log still on disk empty; resolution
INFO “final” is the first candidate (Evaluator logs show the real
model on the retry line). Operator steps (Acceptance 5) are present
and sufficient.

## Human check

None. `verify: human` not required for SHIP.

## Guidance

Fast-forward live `trio-v0.10.0-fixes` as in REPORT operator steps.
Replace the Anthropic Messages-API key if the pin should summarize.

commit: e32f147dac507f0305a381022f1e43d704817a8f
commit: 0cc2551749481bdfa126754d546b5f5f58f72bd8
commit: 9d249f2099c6876347414015c807c4b4e3ccc1e1
commit: f946532a4559b62bf5d3dd748df5556552f773fe
commit: 5113ebe59a3c0138e6b1732f02e3ef5ad32bcb8c
