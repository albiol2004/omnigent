# DECISION — cause 7 mirror-gap + hypothesis 6

Session: `52d47c71e54b4f61a2563bbaefe6ad34`
Evidence: copies of
`~/.omnigent/logs/server/server-20260829-093025-885548.log` in this
directory; scout notes in `loop-cursor2/evidence/iter1/builders/slice-6.log`.
Luna scout: `gpt-5.6-luna-max` (ask mode could not write this file).

## The 42 POSTs (window 09:31:27–09:31:58)

All **202 Accepted**. Not failed item posts.

| Count | Type | Persists transcript item? |
|------:|------|---------------------------|
| 2 | `message` (browser UA) | No — cursor-native forwards to the pane; AP does not persist |
| 1 | `external_model_change` | No (model_override only) |
| 33 | `external_output_text_delta` | No (transient live SSE) |
| 4 | `external_session_status` | No |
| 2 | `external_session_usage` | No |
| 0 | `external_conversation_item` | Would persist; **none occurred** |

The single DB row (`pos=0 type=8 session.resource.created`) comes from
the terminal resource endpoint, not from these POSTs.

## Why zero user/assistant items

Native web `message` events on cursor-native are forwarded to tmux and
are **not** the transcript writer. The store-tail forwarder
(`omnigent/cursor_native_forwarder.py` `_post_conversation_item`) is.
Runner log for this session: the Cursor `store.db` was **already
mirrored by another session** (`6511d339…`, earlier launch), so this
session **paused** the item mirror (`cursor_native_forwarder.py`
~295–331 / ~1083–1102). Assistant text still streamed as
`external_output_text_delta` (the 33 POSTs). No durable items.

Follow-up (not this loop): ownership/transfer when two cursor sessions
share a workspace store.

## Cause 4 epoch stall

**Partial, not this incident.** `start_new_turn()` runs only after a
successful user-row item POST. Here the mirror paused before any item
POST, so epoch never advanced — same class of stall, different trigger
(shared-store pause, not a rejected user row).

## Hypothesis 6 — CONFIRMED (separate bug)

Server log lines 178 and 377: unhandled pydantic tagged-union errors on
`response.failed.response.{id,model,created_at}` missing. Input looks
like `{status: failed, error: {type: ReadError, ...}}`.

Producer: `omnigent/runner/app.py` `_response_failed_event` (~899–911)
and several `_publish_event` failure dicts omit a full `ResponseObject`
(`omnigent/server/schemas.py` ~1092–1096; `FailedEvent` ~3795–3801).

**Not** why session 52’s `/events` POSTs left no items (those were 202).
It **does** drop the failure event from the client stream (ASGI 500).

**Fix now (this loop):** complete `response.failed` payloads before
publish/SSE. Shared-store ownership remains a follow-up.
