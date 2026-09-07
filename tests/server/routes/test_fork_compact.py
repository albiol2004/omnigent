"""Route tests for compacting an oversized fork snapshot."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from omnigent.entities import (
    CompactionData,
    ConversationItem,
    FunctionCallData,
    FunctionCallOutputData,
    MessageData,
)
from omnigent.fork_compact_routing import ResolvedForkCompactModel
from omnigent.fork_context import estimate_fork_context_bytes, serialized_context_bytes
from omnigent.runtime.compaction import CompactionResult, SummaryMetadata
from omnigent.server.routes._sessions.common import _session_status_cache
from omnigent.server.routes.sessions import routes_core as routes_core_module
from omnigent.server.routes.sessions.routes_core import _fork_context_renderer
from omnigent.spec import AgentSpec
from omnigent.spec.types import ExecutorSpec
from tests.server.routes.test_sessions_fork import (
    _build_app,
    _ConversationStore,
    _make_conversation,
    _make_item,
)

_SOURCE_ID = "e9f8f58523cec9a57d3bdf93be543e8c"


@pytest.fixture(autouse=True)
def _use_synchronous_fork_compaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy blocking assertions explicit as async becomes the default."""
    monkeypatch.setenv("OMNIGENT_FORK_ASYNC", "0")


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


def _spec_cache(
    model: str = "spec-model",
    harness: str = "omnigent",
) -> _SpecCache:
    """Build a cache with the model used by the route's compaction pass."""
    return _SpecCache(
        AgentSpec(
            spec_version=1,
            executor=ExecutorSpec(model=model, config={"harness": harness}),
        )
    )


def _rendered_size_items() -> list[ConversationItem]:
    """Build 496 mixed items whose Claude JSONL envelope exceeds 600 kB."""
    items: list[ConversationItem] = []
    text = "x" * 780
    for index in range(496):
        response_id = f"response_{index // 4:04d}"
        kind = index % 4
        if kind < 2:
            data = MessageData(
                role="user",
                content=[{"type": "input_text", "text": text}],
            )
            item_type = "message"
        elif kind == 2:
            data = FunctionCallData(
                agent="agent",
                name="Read",
                arguments=f'{{"path":"src/file.py","query":"{text}"}}',
                call_id=f"call_{index:04d}",
            )
            item_type = "function_call"
        else:
            data = FunctionCallOutputData(
                call_id=f"call_{index - 1:04d}",
                output=text,
            )
            item_type = "function_call_output"
        items.append(
            ConversationItem(
                id=f"item_{index:04d}",
                type=item_type,
                status="completed",
                response_id=response_id,
                created_at=1,
                data=data,
            )
        )
    return items


def _patch_compaction_clients(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model: str = "anthropic/claude-fable-5",
) -> None:
    """Keep route tests inside the mocked compaction boundary."""
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT_ALLOW_API", "1")
    monkeypatch.setattr("omnigent.runtime.workflow._get_llm_client", lambda: object())
    resolved = ResolvedForkCompactModel(
        model=model,
        source="test",
        connection={"api_key": "test-key"},
    )
    monkeypatch.setattr(
        "omnigent.fork_compact.list_fork_compact_candidates",
        lambda *_args, **_kwargs: [resolved],
    )


@pytest.mark.asyncio
async def test_oversized_fork_uses_compacted_replacement_items(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A short mocked summary is copied without changing the source."""
    store, source_item = _oversized_store()
    actual = estimate_fork_context_bytes([source_item.to_api_dict()])
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
    assert "source=test model=" in caplog.text


@pytest.mark.asyncio
async def test_one_turn_oversized_fork_creates_summary_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A short oversized fork summarizes its first completed turn."""
    response_id = "response_1"
    items = [
        _make_item("user_1", "x" * 300, response_id=response_id),
        _make_assistant_item("assistant_1", "done", response_id=response_id),
    ]
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: items},
    )
    actual = estimate_fork_context_bytes([item.to_api_dict() for item in items])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT_TARGET_BYTES", str(actual))
    _patch_compaction_clients(monkeypatch)

    async def _summarize(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"text": "one-turn summary", "token_count": 2}

    monkeypatch.setattr("omnigent.runtime.compaction.summarize_history", _summarize)

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    fork_items = store._items[response.json()["id"]]
    assert [item.type for item in fork_items] == ["compaction", "message"]
    summary_item = fork_items[0]
    assert isinstance(summary_item.data, CompactionData)
    assert summary_item.data.summary == "one-turn summary"
    assert summary_item.data.last_item_id == items[0].id
    assert fork_items[1].id == items[1].id


@pytest.mark.asyncio
async def test_rendered_claude_size_triggers_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude's rendered JSONL, rather than API JSON, triggers compaction."""
    items = _rendered_size_items()
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: items},
    )
    payload = [item.to_api_dict() for item in items]
    raw_bytes = serialized_context_bytes(payload)
    assert 450_000 < raw_bytes < 500_000
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "600000")
    _patch_compaction_clients(monkeypatch)
    calls: list[dict[str, object]] = []

    async def _compact(*args: object, **kwargs: object) -> CompactionResult:
        del args
        calls.append(kwargs)
        return CompactionResult(
            messages=[],
            summary_metadata=SummaryMetadata(
                text="compact rendered history",
                last_item_id=items[-1].id,
                model="spec-model",
                token_count=3,
            ),
        )

    monkeypatch.setattr("omnigent.fork_compact.compact", _compact)

    response = TestClient(
        _build_app(
            store,
            agent_cache=_spec_cache(harness="claude-native"),
        )
    ).post(f"/v1/sessions/{_SOURCE_ID}/fork", json={})

    assert response.status_code == 201, response.text
    assert len(calls) == 1
    fork_items = store._items[response.json()["id"]]
    assert fork_items[0].type == "compaction"
    assert isinstance(fork_items[0].data, CompactionData)
    assert fork_items[0].data.summary == "compact rendered history"


def test_rendered_claude_size_still_rejects_when_compaction_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rendered estimate still returns 413 when compaction is disabled."""
    item = _make_item("item_1", "x" * 300)
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: [item]},
    )
    payload = [item.to_api_dict()]
    renderer = _fork_context_renderer(
        "claude-native",
        session_id=_SOURCE_ID,
        workspace=None,
        terminal_launch_args=None,
    )
    assert renderer is not None
    actual = estimate_fork_context_bytes(payload, renderer=renderer)
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "0")

    response = TestClient(
        _build_app(
            store,
            agent_cache=_spec_cache(harness="claude-native"),
        )
    ).post(f"/v1/sessions/{_SOURCE_ID}/fork", json={})

    assert response.status_code == 413, response.text
    assert str(actual) in response.json()["error"]["message"]
    assert store.fork_calls == []


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
    actual = estimate_fork_context_bytes(source_snapshot)
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "1")
    monkeypatch.delenv("OMNIGENT_FORK_COMPACT_MODEL", raising=False)
    _patch_compaction_clients(monkeypatch, model="spec-model")

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
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed summary never reaches the fork store operation."""
    store, source_item = _oversized_store()
    actual = estimate_fork_context_bytes([source_item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    _patch_compaction_clients(monkeypatch)
    caplog.set_level(logging.WARNING)

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
    assert "compaction failed: summary unavailable" in message
    assert "RuntimeError: summary unavailable" in caplog.text
    assert any(
        record.levelno == logging.WARNING
        and record.exc_info is not None
        and "summary unavailable" in record.getMessage()
        for record in caplog.records
    )
    assert store.fork_calls == []
    assert store._items[_SOURCE_ID] == [source_item]


@pytest.mark.asyncio
async def test_compaction_resolve_failure_does_not_publish_in_progress(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resolution failures dismiss compaction without showing a spinner."""
    store, source_item = _oversized_store()
    actual = estimate_fork_context_bytes([source_item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    caplog.set_level(logging.WARNING)
    published: list[str] = []
    failed: list[str] = []
    monkeypatch.setattr(
        routes_core_module,
        "_publish_compaction_in_progress",
        lambda session_id: published.append(session_id),
    )
    monkeypatch.setattr(
        routes_core_module,
        "_publish_compaction_failed",
        lambda session_id: failed.append(session_id),
    )

    async def _fail_before_ready(
        *,
        on_llm_ready: Callable[[object], None],
        **kwargs: object,
    ) -> list[ConversationItem]:
        del on_llm_ready, kwargs
        raise RuntimeError("model resolution unavailable")

    monkeypatch.setattr(
        routes_core_module,
        "compact_fork_items",
        _fail_before_ready,
    )

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 413, response.text
    assert "compaction failed: model resolution unavailable" in response.json()["error"]["message"]
    assert published == []
    assert failed == [_SOURCE_ID]
    assert store.fork_calls == []
    assert store._items[_SOURCE_ID] == [source_item]


@pytest.mark.asyncio
async def test_compaction_publishes_progress_when_llm_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compaction entered after resolution emits one progress event."""
    store, source_item = _oversized_store()
    actual = estimate_fork_context_bytes([source_item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    published: list[str] = []
    failed: list[str] = []
    monkeypatch.setattr(
        routes_core_module,
        "_publish_compaction_in_progress",
        lambda session_id: published.append(session_id),
    )
    monkeypatch.setattr(
        routes_core_module,
        "_publish_compaction_failed",
        lambda session_id: failed.append(session_id),
    )

    async def _compact_after_ready(
        *,
        on_llm_ready: Callable[[object], None],
        **kwargs: object,
    ) -> list[ConversationItem]:
        del kwargs
        on_llm_ready(SimpleNamespace(model="compact-model", provider="anthropic"))
        return [_make_item("replacement", "short summary")]

    monkeypatch.setattr(
        routes_core_module,
        "compact_fork_items",
        _compact_after_ready,
    )

    response = TestClient(_build_app(store, agent_cache=_spec_cache())).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert published == [_SOURCE_ID]
    assert failed == []
    assert len(store.fork_calls) == 1


@pytest.mark.asyncio
async def test_running_source_rejects_fork_compaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A running source cannot be compacted concurrently with its turn."""
    store, source_item = _oversized_store()
    actual = estimate_fork_context_bytes([source_item.to_api_dict()])
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
