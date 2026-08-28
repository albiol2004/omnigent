VERDICT: SHIP

Hotfix `4010cfcba` sizes the fork guard by the rendered transcript.
A ~472 kB API payload whose Claude JSONL is ~668 kB now compact-on-fork
instead of skipping and dying at `claude_native.py:4254`.

## 1. Diff review

`fork_session` (`routes_core.py:2350-2398`) calls
`estimate_fork_context_bytes(payload, renderer=...)` then
`guard_fork_context_bytes`. After `compact_fork_items` it re-estimates
the replacement with the same renderer and guards again (target + max).

Renderer vs 1.8× fallback (`_fork_context_renderer`,
`routes_core.py:303-380`; `fork_context.py:99-119`):

| Harness | Yardstick |
|---|---|
| claude-native, claude-sdk | `_claude_transcript_records_from_session_items` (1.000× vs rebuild when cwd/session match) |
| codex-native | `_codex_rollout_records_from_session_items` |
| pi-native | `pi_session_records_from_session_items` |
| cursor / omnigent / antigravity / qwen / unknown | `ceil(serialized × OMNIGENT_FORK_JSONL_INFLATION)` default 1.8 |

Claude renderer is in-process: no runner client, no `~/.claude` read.
It only builds record dicts. Attachment blocks can rematerialize under
`/tmp/omnigent-<uid>/claude-native` (not `~/.claude`); the incident
shape (text + tool calls/results) does not hit that path. 496-item
render: **8.58 ms**.

Runner 413 suffix
(`orchestration.py:3929-3933` Codex, `:6442-6446` Claude):
`(server did not compact the fork context)`.

## 2. Repro

`loop-fixes/evidence/hotfix3/eval/verify.out`
(script: `eval/verify_fork_estimate.py`; throwaway `:17621`, scratch
`OMNIGENT_DATA_DIR` / `CONFIG_HOME` / `HOME`).

| Case | Result |
|---|---|
| 496 items, raw API **471,821** B | rendered estimate **667,830** B (1.415×); > 600 kB so compact runs |
| `OMNIGENT_FORK_COMPACT=0` | POST `/fork` **413** (`667830` bytes), no store fork |
| compact on, mock Layer-2 summary | **201**, 1 compaction item, 19 fork items |
| post-compact rendered JSONL | **25,735** B << 600 kB |
| `_auto_create_claude_terminal` fake clone 788,545 B | rebuild + `--resume`; dest **25,895** B; no 413 |
| small fork (`"small"`) | `replacement_items is None`; item-set equality |
| unit rebuild match | `test_claude_fork_estimate_matches_rebuilt_transcript`: estimate == file size |

## 3. Tests and pre-commit

Focused: **266 passed** (`eval/focused-tests.log`).
Trio-compat: **5 passed** (`eval/trio-compat.log`).
pre-commit on `5a515ec89..HEAD`: **passed** (`eval/precommit.log`).

## 4. Isolation

- `GET http://127.0.0.1:6767/health` → `200`.
- No `:176xx` listeners after teardown.
- `/home/alex/.claude/projects` mtime unchanged (`1787856490`).
- `/home/alex/.omnigent` mtime unchanged (`1787938374`).
- Product files not edited in this eval.
