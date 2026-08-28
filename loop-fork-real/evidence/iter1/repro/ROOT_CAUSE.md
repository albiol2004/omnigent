# Reproduced root cause — fable fork compaction (iter 1)

## Chain
`compact_fork_items` (`fork_compact.py:88-167`)
→ `resolve_fork_compact_model` returns `fable` / `source_override`
→ `_llm_config_for_model` copies spec connection (claude-native: none)
→ `_route_bare_model_for_compaction` (`workflow.py:2758-2788`)
  leaves `fable` unprefixed (only `claude-*` / `databricks-*`)
→ `compact(..., model="fable", llm_client=_get_llm_client())`
→ `Client._do_create` → `parse_model_string("fable")`
  → provider=`openai`, model=`fable`
→ `OpenAIAdapter.responses_create` POST
  `https://api.openai.com/v1/responses`

## Actual exceptions (scratch OMNIGENT_CONFIG_HOME, read-only config copy)
| Call | ms | Exception |
|---|---|---|
| model=fable, connection=None (production-like) | 296 | `httpx.HTTPStatusError` 401 Missing bearer |
| model=fable, openai key from config | 1369 | 400 `The requested model 'fable' does not exist.` |
| model=fable, anthropic key in connection | 411 | 401 Incorrect API key (anthropic key sent to OpenAI) |
| `compact()` same as first | 297 | same 401, then `fail_on_summary_error` re-raises |

Live log 36 ms is this same OpenAI reject, not a missing import.

## Why the UI lied
`routes_core.py:2380` publishes `compaction_in_progress` before
`compact_fork_items`. `2398-2400` maps every failure to the original
413 `ForkContextTooLarge` and drops `compact_exc`.
