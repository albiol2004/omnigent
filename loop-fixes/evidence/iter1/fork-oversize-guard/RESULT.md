# Fork oversize guard evidence

The fixture is synthetic and does not access a database or vendor transcript.

```json
{
  "turns": 320,
  "chars_per_message": 6000,
  "full_item_count": 640,
  "full_context_bytes": 3907941,
  "compacted_item_count": 1,
  "compacted_context_bytes": 134,
  "compaction_retry_allowed_bytes": 134,
  "threshold_bytes": 600000,
  "initial_refusal": "Fork context too large: 3907941 bytes exceeds threshold 600000 bytes (OMNIGENT_FORK_MAX_CONTEXT_BYTES).",
  "final_refusal": "Fork context too large: 600093 bytes exceeds threshold 600000 bytes (OMNIGENT_FORK_MAX_CONTEXT_BYTES)."
}
```
