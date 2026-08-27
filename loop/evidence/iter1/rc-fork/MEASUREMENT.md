# MEASUREMENT — synthetic fork sizes

Fixture: 320 user/assistant turns (640 messages), 6000 ASCII chars each.
No live `claude` billed call. Product renderers invoked via
`uv run python loop/evidence/iter1/rc-fork/scratch/measure_fork_bytes.py`.

Lead result (`MEASUREMENT.json`):

| Path | Bytes | Notes |
|---|---:|---|
| Native-style JSONL (640 records) | 3,925,540 | Schema is a simplified analog of Claude JSONL |
| Fresh SDK `_build_prompt` | 3,849,154 | 1 coalesced text block; `"Conversation so far:"` path |
| SDK `resume_session=True` | 0 | Fixture used plain string `content`; extractor likely expects blocks. Treat as unconfirmed exact warm size. Scout reported 6-byte latest message. |
| Cursor preamble | 3,849,378 | `_cursor_fork_history_preamble` |
| Cursor wrapped first injection | 3,849,551 | `wrap_fork_preamble` |

Scout in-memory (same fixture, slightly richer JSONL schema): native JSONL
4,060,446; SDK 3,846,888; cursor 3,846,580. Both ~3.8–4.1 MB — well above
typical Claude prompt limits (~200k tokens). Compaction on native rebuild
only when `compacted_messages` exists (scout: 1,523,688 with snapshot).

Reproduction command:

```bash
uv run python loop/evidence/iter1/rc-fork/scratch/measure_fork_bytes.py
```
