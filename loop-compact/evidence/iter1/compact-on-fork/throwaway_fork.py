"""Throwaway :17110 fork of a ~3.9 MB synthetic session (mock LLM)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

SOURCE_ID = "e9f8f58523cec9a57d3bdf93be543e8c"
PORT = 17110
TURNS = 320
CHARS = 6000
BODY = "x" * CHARS


def _synthetic_items() -> list[Any]:
    from omnigent.entities import ConversationItem, MessageData
    from tests.server.routes.test_sessions_fork import _make_item

    items: list[ConversationItem] = []
    for i in range(TURNS):
        response_id = f"r{i}"
        items.append(_make_item(f"u{i}", f"U{i} {BODY}", response_id=response_id))
        items.append(
            ConversationItem(
                id=f"a{i}",
                type="message",
                status="completed",
                response_id=response_id,
                created_at=1,
                data=MessageData(
                    role="assistant",
                    agent="mock-agent",
                    content=[{"type": "output_text", "text": f"A{i} {BODY}"}],
                ),
            )
        )
    return items


def _message_text(item: Any) -> str:
    """Return message text for a source-versus-tail comparison."""
    from omnigent.entities import MessageData

    assert isinstance(item.data, MessageData)
    return "\n".join(
        block["text"] for block in item.data.content if isinstance(block.get("text"), str)
    )


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="fork-compact-"))
    os.environ["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    os.environ["OMNIGENT_CONFIG_HOME"] = str(scratch / "config")
    (scratch / "data").mkdir()
    (scratch / "config").mkdir()
    os.environ["OMNIGENT_FORK_MAX_CONTEXT_BYTES"] = "600000"
    os.environ["OMNIGENT_FORK_COMPACT"] = "1"
    os.environ["OMNIGENT_FORK_COMPACT_MODEL"] = "mock-compact-model"
    os.environ["AP_CONTEXT_WINDOW_OVERRIDE"] = "128000"

    from omnigent.entities import CompactionData
    from omnigent.fork_context import serialized_context_bytes
    from omnigent.spec import AgentSpec
    from omnigent.spec.types import ExecutorSpec
    from tests.server.routes.test_fork_compact import _SpecCache
    from tests.server.routes.test_sessions_fork import (
        _build_app,
        _ConversationStore,
        _make_conversation,
    )

    items = _synthetic_items()
    payload = [item.to_api_dict() for item in items]
    source_snapshot = list(payload)
    before = serialized_context_bytes(payload)
    store = _ConversationStore(
        conversations={SOURCE_ID: _make_conversation()},
        items_by_conv={SOURCE_ID: items},
    )
    app = _build_app(
        store,
        agent_cache=_SpecCache(
            AgentSpec(spec_version=1, executor=ExecutorSpec(model="spec-model"))
        ),
    )

    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and not server.started:
            time.sleep(0.05)
        if not server.started:
            raise SystemExit("throwaway server failed to bind 17110")

        summary_models: list[str] = []

        async def _fixed_summary(
            *args: object,
            **kwargs: object,
        ) -> dict[str, object]:
            del kwargs
            if len(args) < 3 or not isinstance(args[2], str):
                raise AssertionError("summary call did not receive a model")
            summary_models.append(args[2])
            return {
                "text": "synthetic summary of 320 turns",
                "token_count": 8,
            }

        # Only Layer 2's LLM call is mocked; the compaction layers stay real.
        with patch(
            "omnigent.runtime.compaction.summarize_history",
            new=_fixed_summary,
        ):
            response = httpx.post(
                f"http://127.0.0.1:{PORT}/v1/sessions/{SOURCE_ID}/fork",
                json={},
                timeout=60.0,
            )

        if not store.fork_calls:
            raise SystemExit("fork route did not reach the store")
        replacement = store.fork_calls[0]["replacement_items"]
        if replacement is None:
            raise SystemExit("fork route did not provide replacement items")
        compacted_payload = [item.to_api_dict() for item in replacement]
        after = serialized_context_bytes(compacted_payload)
        compaction_items = [item for item in replacement if item.type == "compaction"]
        if len(compaction_items) != 1:
            raise SystemExit(f"expected one compaction item, got {len(compaction_items)}")
        summary_item = compaction_items[0]
        if not isinstance(summary_item.data, CompactionData):
            raise SystemExit("compaction item has the wrong data type")
        retained = [item for item in replacement if item.type != "compaction"]
        expected_tail = items[-9:]
        if [item.id for item in retained] != [item.id for item in expected_tail]:
            raise SystemExit("retained tail IDs differ from the source tail")
        if [_message_text(item) for item in retained] != [
            _message_text(item) for item in expected_tail
        ]:
            raise SystemExit("retained tail text differs from the source tail")
        if [item.to_api_dict() for item in retained] != [
            item.to_api_dict() for item in expected_tail
        ]:
            raise SystemExit("retained tail items are not verbatim")
        if [item.to_api_dict() for item in store._items[SOURCE_ID]] != source_snapshot:
            raise SystemExit("source items changed during compaction")
        if summary_models != [summary_item.data.model]:
            raise SystemExit(f"unexpected summary models: {summary_models!r}")
        if response.status_code != 201:
            raise SystemExit(f"fork failed: {response.status_code} {response.text}")

        resolved_model = summary_item.data.model
        if not resolved_model:
            raise SystemExit("compaction item did not record a resolved model")
        max_bytes = int(os.environ["OMNIGENT_FORK_MAX_CONTEXT_BYTES"])
        result = {
            "status_code": response.status_code,
            "bytes_before": before,
            "bytes_after": after,
            "max_context_bytes": max_bytes,
            "resolved_model": resolved_model,
            "resolved_source": "env",
            "port": PORT,
            "scratch": str(scratch),
            "source_item_count": len(items),
            "fork_item_count": len(replacement),
            "retained_non_summary_item_count": len(retained),
            "compaction_item_id": summary_item.id,
            "summary_last_item_id": summary_item.data.last_item_id,
            "retained_tail_ids": [item.id for item in retained],
            "retained_tail_verbatim": True,
            "summary_call_count": len(summary_models),
            "source_unchanged": [item.to_api_dict() for item in store._items[SOURCE_ID]]
            == source_snapshot,
        }
        out = Path(__file__).with_name("THROWAWAY.json")
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        if after >= before:
            raise SystemExit("compacted fork was not smaller")
        if after >= max_bytes:
            raise SystemExit("compacted fork still over threshold")
        if not retained:
            raise SystemExit("compacted fork retained no non-summary items")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        if thread.is_alive():
            raise SystemExit("throwaway server did not shut down")
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
