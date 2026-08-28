# DECISION — why the same-family native fork compacted

## Reproduced cause
The Web UI's only fork entry point (`ChatPage` "Fork from here") always
sends `up_to_response_id` (the bubble's `responseId`). The passthrough
predicate requires `body.up_to_response_id is None`, so that request
skips the clone and takes the compaction path even when the chosen
response is the **last** one (full history, not a truncated prefix).

## Evidence (throwaway :18021, compact off, real conversation copy)
Source `e34847899b7d47b3ad322948d4ea6002` (labels `omnigent.ui=terminal`,
`omnigent.wrapper=claude-code-native-ui`, `external_session_id` present).
Last `response_id` `resp_claude_55c8498065ecb5751484fc73cacb82c6` covers
every item (`items_after_cut=0`).

| POST body | status | wall | skip log |
| --- | --- | --- | --- |
| `{title}` only (no fork point) | **201** | **133.9 ms** | none (passthrough fired) |
| `{title, up_to_response_id: last}` (Web UI) | **413** | **147.5 ms** | `fork passthrough skipped: up_to_response_id set` |

With `OMNIGENT_FORK_COMPACT=1` the second POST is the 56 s live incident.
With compact off it 413s on the 1 062 123-byte prefix (threshold 600 000).

Log line (INFO `server.routes.sessions` `fork_session`):
```
INFO  08-28 22:10:17.771 server.routes.sessions           fork_session       | fork passthrough skipped: up_to_response_id set
```
See `server.log` in this directory and `full_fork.txt` / `web_fork.txt`.

## Ruled out on this source
- `OMNIGENT_FORK_NATIVE_GUARD` unset
- `external_session_id` set (`f4bd03c9-3c11-46fd-b0df-fdc7952301c2`)
- same agent / same family: full POST cloned with `omnigent.fork.carry_history=1`
- target/source harness re-resolve did not skip (no harness skip log)
- `carry_history_into_native` was true on the successful full POST

## Slice 2 implication
Treat a prefix that is the **entire** source item list as a full fork for
passthrough. Do **not** passthrough truncated prefixes, SDK sources, or
cross-family switches.
