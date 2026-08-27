🤖 HEAD is `9926c9145`. Product files are unchanged; only the pre-existing
`loop/` changes remain. The fork path is an intentional deep copy followed by
target-specific rendering, not a bounded-history operation.

Important correction: `_ensure_local_claude_resume_transcript` is a
Claude-native transcript builder, not an SDK-target renderer. A fresh
`claude-sdk` fork loads copied items and `_build_prompt` replays them as one
prompt. Warm SDK sessions send only new user input.

Ask mode prevented writing `FINDINGS.md`, `CITATIONS.md`, or `MEASUREMENT.md`.
I performed an in-memory measurement with the actual renderer functions,
without starting Claude or creating files.

### Fact grading

| Fact | Grade | HEAD evidence |
|---|---|---|
| Fork route copies the session | Confirmed | `routes_core.py:1979-2200`, especially `1990`, `1998-2006`, `2152-2172` |
| Store deep-copies conversation items | Confirmed | `sqlalchemy_store.py:3397-3520`, actual item copy at `3633-3666` |
| Runner consumes fork labels | Confirmed | `orchestration.py:5907-5925`, `6233-6276`, `6283-6409` |
| Native Claude clones local JSONL and resumes it | Confirmed | `claude_native.py:1780-1843`; `orchestration.py:5519-5569` |
| SDK targets use `_ensure_local...` | Refuted as written | SDK uses `runner/app.py:3233-3237`, `5781-5783`, then `claude_sdk_executor.py:3051-3123` |
| Fresh SDK forks replay `"Conversation so far:"` | Confirmed, fresh-client only | `claude_sdk_executor.py:3080-3123` |
| Cursor-native uses a first-message preamble | Confirmed | `cursor_native_executor.py:93-114`; renderer at `orchestration.py:5415-5443` |
| UI has fork/switch history predicates | Confirmed | `web/src/lib/forkHarness.ts:118-158` |
| Related upstream reports are relevant | Confirmed, qualified | [#5498](https://github.com/omnigent-ai/omnigent/issues/5498), [#5180](https://github.com/omnigent-ai/omnigent/issues/5180), [#2967](https://github.com/omnigent-ai/omnigent/issues/2967), and [#3469](https://github.com/omnigent-ai/omnigent/issues/3469) are issues, not PRs |

```1995:2006:omnigent/server/routes/sessions/routes_core.py
        """
        Fork an existing session into a new session.

        Deep-copies the source session's conversation items and
        clones the agent into a new session. When ``body.agent_id``
        is set, the fork binds that built-in agent instead of the
        source's — switching harness (e.g. Claude-SDK → Claude Code,
        or Claude → Codex). The source's model settings carry over
        only within the same provider family; a same-family native
        target also carries conversation history (the runner rebuilds
        its transcript).
```

```3651:3665:omnigent/stores/conversation_store/sqlalchemy_store.py
                new_item_id = generate_item_id(decode_item_type(src_item.type))
                new_item = SqlConversationItem(
                    id=new_item_id,
                    conversation_id=new_conv.id,
                    response_id=src_item.response_id,
                    created_at=now,
                    status=src_item.status,
                    position=pos,
                    type=src_item.type,
                    data=src_item.data,
                    search_text=src_item.search_text,
                    created_by=src_item.created_by,
                )
                session.add(new_item)
                fts_rows.append((new_item_id, new_conv.id, src_item.search_text or ""))
```

```6264:6278:omnigent/omnigent/runner/native/orchestration.py
    if server_client is not None and session_external_id is not None:
        from omnigent.claude_native import _ensure_local_claude_resume_transcript

        try:
            _transcript = await _ensure_local_claude_resume_transcript(
                server_client,
                session_id=session_id,
                external_session_id=session_external_id,
                workspace=Path(workspace).resolve(),
            )
            if _transcript is not None:
                resume_external_session_id = session_external_id
                resume_prefix_bytes = _measured_prefix_bytes(_transcript)
        except Exception:
```

```3080:3094:omnigent/omnigent/inner/claude_sdk_executor.py
        if resume_session:
            return ClaudeSDKExecutor._extract_trailing_user_content(messages)

        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if len(messages) <= 1 or len(user_messages) <= 1:
            return ClaudeSDKExecutor._extract_latest_user_content(messages)

        # Check if the latest user message is multimodal — if so,
        # serialize prior history as a text prefix but preserve the
        # latest message's content blocks for native multimodal
        # delivery to the Anthropic API.
        latest_content = ClaudeSDKExecutor._extract_latest_user_content(messages)
        prior = messages[:-1]

        prior_blocks: list[_JsonObject] = [_text_block("Conversation so far:")]
```

```93:107:omnigent/omnigent/inner/cursor_native_executor.py
        # A fork into cursor carries history as a text preamble: cursor's
        # conversation is server-backed (no local store to seed for --resume), so
        # the runner stashed the prior turns and we prepend them to the FIRST
        # injected message. We READ the preamble here but only CLEAR it after a
        # successful injection (below) — consuming it up front would lose the
        # forked history permanently if this injection fails.
        preamble = read_fork_preamble(self._bridge_dir)
        if preamble:
            text = wrap_fork_preamble(preamble, text)
        try:
            async with self._inject_lock:
                await asyncio.to_thread(inject_user_message, self._bridge_dir, content=text)
        except RuntimeError as exc:
            yield ExecutorError(message=describe_exception(exc))
            return
```

```4333:4344:omnigent/omnigent/claude_native.py
    for index, item in enumerate(items):
        # Compaction items carry the post-compaction context. Replace
        # all prior records with the compacted messages so the
        # reconstructed transcript reflects the compacted state.
        if item.get("type") == "compaction":
            compacted_messages = item.get("compacted_messages")
            if isinstance(compacted_messages, list) and compacted_messages:
                records.clear()
                parent_uuid = None
                tool_parent_by_call_id.clear()
                # Emit a compact_boundary system record so Claude
```

### In-memory measurement

Synthetic fixture: 320 user/assistant turns, 640 items, 6,000 ASCII
characters per message. Values exclude system prompts, tool schemas, and HTTP
envelopes.

| Path | Records/messages | Bytes | Compaction |
|---|---:|---:|---|
| Native JSONL clone | 640 records | 4,060,446 | Copies existing transcript; does not compact |
| Claude-native `_ensure` rebuild | 640 records | 4,060,446 | None |
| `_ensure` with valid compacted snapshot | 243 records | 1,523,688 | Prior records replaced by boundary + 2 compacted messages |
| `_ensure` with summary but no snapshot | 640 records | 4,060,446 | Compaction marker skipped; prior records remain |
| Fresh Claude SDK replay | 641 input messages, 2 blocks | 3,846,888 serialized bytes | None inside `_build_prompt` |
| Cursor first injection | 640 replayed messages | 3,846,580 bytes | None; compaction items are ignored |

A warm SDK sample sent only the latest six-byte message. This confirms the
large-prompt problem is specifically the fresh/fork path.

### Ranked causes

1. **High — unbounded fork rendering.** The store copies every item, while
   native clone, native rebuild, SDK replay, and Cursor preamble all preserve
   large history.
2. **High — native resume failures silently become fresh sessions.** The
   `_ensure` path uses `limit=1000`; any fetch error falls back to launching
   without `--resume`. A failed local native clone also does not fall through
   to item-based rebuild.
3. **High — no fork-time compaction.** Claude SDK compaction is available for a
   warm SDK client, but `claude-sdk` rejects configured compaction
   (`validator.py:157-178`) and fresh forks replay history before SDK
   compaction can help.
4. **Medium-high — compaction is conditional.** Native rebuild compacts only
   when `compacted_messages` exists. Summary-only compaction records do not
   remove old records. Cursor has no compaction handling.
5. **Medium — duplicated or oversized tool results.** [#5180](https://github.com/omnigent-ai/omnigent/issues/5180)
   reports retry-created duplicates; [#3469](https://github.com/omnigent-ai/omnigent/issues/3469)
   documents oversized tool output causing compaction spirals.
6. **Medium — UI capability mismatch.** `antigravity-native` is offered by
   `forkHarness.ts`, but `harness_plugins.py:406-416` declares
   `fork_history=NONE`.

### Candidate fixes

| Fix | Size / files | Main risk |
|---|---|---|
| Use smaller pagination and rebuild when native clone fails | S–M; `claude_native.py`, `runner/native/orchestration.py` | Local/source transcript divergence |
| Preflight transcript/token size and never silently launch blank | S–M; native orchestration and runner app | Blocks users unless compact/retry UX exists |
| Add explicit fork-local or user-confirmed compaction | M–L; route, store, runtime, renderer, UI | Summary loss; requires a usable model |
| Honor summary-only compaction in native and Cursor renderers | S–M; `claude_native.py`, `orchestration.py` | Intentional loss of pre-summary detail |
| Add forwarder idempotency keyed by source item ID | M–L; native forwarder, events route, store | Schema/migration complexity; avoid payload-only dedupe |
| Drive UI predicates from server `fork_history` capability | S; `forkHarness.ts`, tests | May hide currently unverified targets |

### Upstream conflict map

- [PR #4976](https://github.com/omnigent-ai/omnigent/pull/4976): no direct
  fork/render overlap; process teardown only.
- [PR #5603](https://github.com/omnigent-ai/omnigent/pull/5603): high overlap
  with `routes_core.py`, `sqlalchemy_store.py`, and `ForkSessionDialog.tsx`.
- [PR #5405](https://github.com/omnigent-ai/omnigent/pull/5405): high overlap
  with route/store, `runner/app.py`, orchestration, and capability helpers.
- [PR #4913](https://github.com/omnigent-ai/omnigent/pull/4913): low–medium
  UI/API overlap through `sessionsApi.ts`, `ChatPage.tsx`, and render tests.
- [PR #5081](https://github.com/omnigent-ai/omnigent/pull/5081): medium UI
  overlap in `ForkSessionDialog.tsx`.
- [PR #5544](https://github.com/omnigent-ai/omnigent/pull/5544): medium
  overlap for runner-app or event changes; it is already merged.
- [#5498](https://github.com/omnigent-ai/omnigent/issues/5498) directly
  supports the `limit=1000` native-resume failure cause.
- [#2967](https://github.com/omnigent-ai/omnigent/issues/2967) directly
  supports the fresh SDK “Prompt is too long” cause.

No tests were run because this was read-only reconnaissance. Relevant follow-up
verification commands are:

```text
uv run pytest tests/server/routes/test_sessions_fork.py tests/server/test_runner_session_init.py -q
uv run pytest tests/inner/test_claude_sdk_executor.py tests/runner/test_app_cursor_native_model.py -q
pnpm --dir web exec vitest run src/lib/forkHarness.test.ts
```
