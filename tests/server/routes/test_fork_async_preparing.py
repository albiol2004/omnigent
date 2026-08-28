"""Focused tests for asynchronous fork preparation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from omnigent.entities import ConversationItem
from omnigent.errors import ErrorCode, OmnigentError
from omnigent.fork_context import estimate_fork_context_bytes
from omnigent.server.routes._host_launch import resolve_host_launch
from omnigent.server.routes.sessions import routes_core as routes_core_module
from tests.server.routes.test_fork_compact import _spec_cache
from tests.server.routes.test_host_launch import (
    _FakeConversationStore,
    _FakeHost,
    _FakeHostRegistry,
    _FakeHostStore,
)
from tests.server.routes.test_sessions_fork import (
    _build_app,
    _ConversationStore,
    _make_conversation,
    _make_item,
)

_SOURCE_ID = "e9f8f58523cec9a57d3bdf93be543e8c"
_PREPARING = "omnigent.fork.preparing"
_PREPARING_REASON = "omnigent.fork.preparing_reason"


def _oversized_store() -> tuple[_ConversationStore, ConversationItem]:
    """Build a source that requires compaction."""
    item = _make_item("source-item", "x" * 300)
    return (
        _ConversationStore(
            conversations={_SOURCE_ID: _make_conversation()},
            items_by_conv={_SOURCE_ID: [item]},
        ),
        item,
    )


def _force_compaction(
    monkeypatch: pytest.MonkeyPatch,
    item: ConversationItem,
) -> None:
    """Set a limit below the source snapshot and enable compaction."""
    actual = estimate_fork_context_bytes([item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "1")


def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    """Wait briefly for the app-owned preparation task to finish."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "fork preparation task did not finish"


@pytest.mark.parametrize("compact_failure", [False, True])
def test_async_fork_prepares_in_background(
    monkeypatch: pytest.MonkeyPatch,
    compact_failure: bool,
) -> None:
    """Async forks respond first, then clear or fail their preparing marker."""
    store, source_item = _oversized_store()
    _force_compaction(monkeypatch, source_item)
    replacement = _make_item("replacement", "short summary")

    async def _compact(*, on_llm_ready: object, **kwargs: object) -> list[ConversationItem]:
        del on_llm_ready, kwargs
        await asyncio.sleep(0.3)
        if compact_failure:
            raise RuntimeError("summary unavailable")
        return [replacement]

    monkeypatch.setattr(routes_core_module, "compact_fork_items", _compact)
    app = _build_app(store, agent_cache=_spec_cache())

    with TestClient(app) as client:
        started = time.monotonic()
        response = client.post(f"/v1/sessions/{_SOURCE_ID}/fork", json={})
        elapsed = time.monotonic() - started
        assert response.status_code == 201, response.text
        fork_id = response.json()["id"]
        assert response.json()["labels"][_PREPARING] == "1"
        assert elapsed < 0.3

        if compact_failure:
            _wait_until(lambda: store._convs[fork_id].labels.get(_PREPARING) == "failed")
            assert "summary unavailable" in store._convs[fork_id].labels[_PREPARING_REASON]
            assert store._items[fork_id] == [source_item]
        else:
            _wait_until(lambda: _PREPARING not in store._convs[fork_id].labels)
            assert _PREPARING_REASON not in store._convs[fork_id].labels
            assert store._items[fork_id] == [replacement]


def test_sync_fork_waits_for_compaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-out restores compact-then-201 behavior."""
    store, source_item = _oversized_store()
    _force_compaction(monkeypatch, source_item)
    monkeypatch.setenv("OMNIGENT_FORK_ASYNC", "0")
    replacement = _make_item("replacement", "short summary")

    async def _compact(*, on_llm_ready: object, **kwargs: object) -> list[ConversationItem]:
        del on_llm_ready, kwargs
        await asyncio.sleep(0.15)
        return [replacement]

    monkeypatch.setattr(routes_core_module, "compact_fork_items", _compact)

    with TestClient(_build_app(store, agent_cache=_spec_cache())) as client:
        started = time.monotonic()
        response = client.post(f"/v1/sessions/{_SOURCE_ID}/fork", json={})
        elapsed = time.monotonic() - started

    assert response.status_code == 201, response.text
    assert elapsed >= 0.13
    assert _PREPARING not in response.json()["labels"]
    assert store._items[response.json()["id"]] == [replacement]


def test_launch_runner_guard_rejects_preparing_fork() -> None:
    """A host runner cannot bind to a half-prepared fork."""
    conversation = _make_conversation(conv_id="session_1")
    conversation.labels[_PREPARING] = "1"
    conversation_store = _FakeConversationStore({"session_1": conversation})

    with pytest.raises(OmnigentError) as exc_info:
        resolve_host_launch(
            user_id=None,
            host_id="host_1",
            session_id="session_1",
            host_store=_FakeHostStore({"host_1": _FakeHost()}),
            host_registry=_FakeHostRegistry({"host_1": object()}),
            conversation_store=conversation_store,
            permission_store=None,
        )

    assert exc_info.value.code == ErrorCode.CONFLICT


@pytest.mark.asyncio
async def test_native_launch_config_rejects_preparing_fork() -> None:
    """Native launch config refuses to build while preparation is active."""

    class _Client:
        async def get(self, url: str, timeout: float) -> SimpleNamespace:
            del url, timeout
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"labels": {_PREPARING: "1"}},
            )

    from omnigent.runner.native.orchestration import _pi_native_launch_config

    with pytest.raises(RuntimeError, match="fork preparation is still in progress"):
        await _pi_native_launch_config(session_id="session_1", server_client=_Client())


def test_native_passthrough_has_no_preparing_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full same-family native clone still bypasses compaction."""
    source = _make_conversation()
    source.external_session_id = "source-native-session"
    source_item = _make_item("source-item", "x" * 300, response_id="resp_last")
    store = _ConversationStore(
        conversations={_SOURCE_ID: source},
        items_by_conv={_SOURCE_ID: [source_item]},
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "1")
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "1")
    monkeypatch.setenv("OMNIGENT_FORK_ASYNC", "1")

    async def _unexpected_compaction(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("native passthrough must not compact")

    monkeypatch.setattr(
        routes_core_module,
        "_resolve_fork_target_harness",
        _native_harness,
    )
    monkeypatch.setattr(
        routes_core_module,
        "_agent_carries_native_fork_history",
        lambda _agent: True,
    )
    monkeypatch.setattr(
        routes_core_module,
        "_agent_carries_cursor_fork_history",
        lambda _agent: False,
    )
    monkeypatch.setattr(
        routes_core_module,
        "compact_fork_items",
        _unexpected_compaction,
    )

    response = TestClient(
        _build_app(store, agent_cache=_spec_cache(harness="claude-native"))
    ).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={"up_to_response_id": "resp_last"},
    )

    assert response.status_code == 201, response.text
    assert _PREPARING not in response.json()["labels"]
    assert store._items[response.json()["id"]] == [source_item]


async def _native_harness(*args: object, **kwargs: object) -> str:
    """Resolve the native passthrough target for the fixture."""
    del args, kwargs
    return "claude-native"
