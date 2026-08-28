"""Route tests for compacting an oversized fork snapshot."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from omnigent.entities import CompactionData, ConversationItem, MessageData
from omnigent.fork_context import serialized_context_bytes
from omnigent.runtime.compaction import CompactionResult, SummaryMetadata
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.spec import AgentSpec
from omnigent.spec.types import ExecutorSpec
from tests.server.routes.test_sessions_fork import (
    _build_app,
    _ConversationStore,
    _make_conversation,
    _make_item,
)

_SOURCE_ID = "e9f8f58523cec9a57d3bdf93be543e8c"


class _SpecCache:
    """Return one parsed spec without reading a real agent bundle."""

    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec

    def load(
        self,
        agent_id: str,
        bundle_location: str,
        *,
        expand_env: bool = False,
    ) -> SimpleNamespace:
        del agent_id, bundle_location, expand_env
        return SimpleNamespace(spec=self.spec, workdir=Path("/tmp"))


def _oversized_store(text: str = "x" * 300) -> tuple[_ConversationStore, ConversationItem]:
    """Build a source whose single item exceeds the configured limit."""
    item = _make_item("item_1", text)
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: [item]},
    )
    return store, item


def _make_assistant_item(
    item_id: str,
    text: str,
    response_id: str,
) -> ConversationItem:
    """Build an assistant response for a multi-turn compaction fixture."""
    return ConversationItem(
        id=item_id,
        type="message",
        status="completed",
        response_id=response_id,
        created_at=1,
        data=MessageData(
            role="assistant",
            agent="test-agent",
            content=[{"type": "output_text", "text": text}],
        ),
    )


def _message_text(item: ConversationItem) -> str:
    """Return all text blocks from a message item for verbatim checks."""
    assert isinstance(item.data, MessageData)
    return "\n".join(
        block["text"] for block in item.data.content if isinstance(block.get("text"), str)
    )


def _spec_cache(model: str = "spec-model") -> _SpecCache:
    """Build a cache with the model used by the route's compaction pass."""
    return _SpecCache(
        AgentSpec(
            spec_version=1,
            executor=ExecutorSpec(model=model),
        )
    )


def _patch_compaction_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep route tests inside the mocked compaction boundary."""
    monkeypatch.setattr("omnigent.runtime.workflow._get_llm_client", lambda: object())
    monkeypatch.setattr(
        "omnigent.runtime.workflow._get_runner_client_for_compaction",
        lambda _session_id: None,
    )


@pytest.mark.asyncio
async def test_oversized_fork_uses_compacted_replacement_items(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A short mocked summary is copied without changing the source."""
    store, source_item = _oversized_store()
    actual = serialized_context_bytes([source_item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    _patch_compaction_clients(monkeypatch)
    calls: list[dict[str, object]] = []

    async def _compact(*args: object, **kwargs: object) -> CompactionResult:
        del args
        calls.append(kwargs)
        return CompactionResult(
            messages=[],
            summary_metadata=SummaryMetadata(
                text="short summary",
                last_item_id=source_item.id,
                model="spec-model",
                token_count=2,
            ),
        )

    monkeypatch.setattr("omnigent.fork_compact.compact", _compact)

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert len(calls) == 1
    fork_call = store.fork_calls[0]
    replacement = fork_call["replacement_items"]
    assert replacement is not None
    assert replacement[0].type == "compaction"
    assert replacement[0].data.summary == "short summary"
    assert fork_call["resume_source_native_session"] is False
    assert store._items[_SOURCE_ID] == [source_item]
    assert "source_spec model=spec-model" in caplog.text


@pytest.mark.asyncio
async def test_oversized_fork_keeps_recent_assistant_tail_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real compactor keeps the recent assistant response window."""
    items: list[ConversationItem] = []
    for index in range(10):
        response_id = f"response_{index}"
        items.extend(
            [
                _make_item(
                    f"user_{index}",
                    f"user turn {index}",
                    response_id=response_id,
                ),
                _make_assistant_item(
                    f"assistant_{index}",
                    f"assistant turn {index}",
                    response_id=response_id,
                ),
            ]
        )

    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: items},
    )
    source_snapshot = [item.to_api_dict() for item in items]
    actual = serialized_context_bytes(source_snapshot)
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "1")
    monkeypatch.delenv("OMNIGENT_FORK_COMPACT_MODEL", raising=False)

    summary_models: list[str] = []

    async def _summarize(*args: object, **kwargs: object) -> dict[str, object]:
        del kwargs
        assert len(args) >= 3
        model = args[2]
        assert isinstance(model, str)
        summary_models.append(model)
        return {"text": "fixed summary", "token_count": 2}

    # Mock only the Layer-2 summary call; compact_fork_items and compact stay real.
    monkeypatch.setattr("omnigent.runtime.compaction.summarize_history", _summarize)

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert summary_models == ["spec-model"]
    fork_items = store._items[response.json()["id"]]
    assert len(fork_items) == 10
    assert [item.type for item in fork_items] == [
        "compaction",
        *("message" for _ in range(9)),
    ]

    summary_item = fork_items[0]
    assert isinstance(summary_item.data, CompactionData)
    assert summary_item.data.summary == "fixed summary"
    assert summary_item.data.last_item_id == items[-10].id
    assert summary_item.data.model == "spec-model"

    # The fifth-from-last assistant is the first protected response; its
    # preceding user turn is the inclusive summary boundary.
    expected_tail = items[-9:]
    retained = fork_items[1:]
    assert [item.id for item in retained] == [item.id for item in expected_tail]
    assert [_message_text(item) for item in retained] == [
        _message_text(item) for item in expected_tail
    ]
    assert [item.to_api_dict() for item in retained] == [
        item.to_api_dict() for item in expected_tail
    ]
    assert [item.to_api_dict() for item in store._items[_SOURCE_ID]] == source_snapshot


@pytest.mark.asyncio
async def test_summary_failure_keeps_original_413_and_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed summary never reaches the fork store operation."""
    store, source_item = _oversized_store()
    actual = serialized_context_bytes([source_item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    _patch_compaction_clients(monkeypatch)

    async def _fail(*args: object, **kwargs: object) -> CompactionResult:
        del args, kwargs
        raise RuntimeError("summary unavailable")

    monkeypatch.setattr("omnigent.fork_compact.compact", _fail)

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 413, response.text
    message = response.json()["error"]["message"]
    assert f"{actual} bytes" in message
    assert f"threshold {actual - 1} bytes" in message
    assert store.fork_calls == []
    assert store._items[_SOURCE_ID] == [source_item]


@pytest.mark.asyncio
async def test_running_source_rejects_fork_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A running source cannot be compacted concurrently with its turn."""
    store, source_item = _oversized_store()
    actual = serialized_context_bytes([source_item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setitem(_session_status_cache, _SOURCE_ID, "running")

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "conflict"
    assert "turn is running" in response.json()["error"]["message"]
    assert store.fork_calls == []
