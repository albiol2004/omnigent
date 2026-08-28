"""Route-level tests for the fork context byte guard."""

from __future__ import annotations

from starlette.testclient import TestClient

from omnigent.entities import ConversationItem, PagedList
from omnigent.entities.conversation import CompactionData
from omnigent.fork_context import estimate_fork_context_bytes, summary_only_items
from omnigent.server.routes.sessions import routes_core as routes_core_module
from tests.server.routes.test_sessions_fork import (
    _build_app,
    _ConversationStore,
    _make_conversation,
    _make_item,
    _StubAgentCache,
    _switch_agent_store,
)

_SOURCE_ID = "e9f8f58523cec9a57d3bdf93be543e8c"


def test_fork_refuses_oversized_history_before_store_fork(
    monkeypatch,
) -> None:
    """An oversized source never reaches ``fork_conversation``."""
    item = _make_item("item_1", "x" * 300)
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: [item]},
    )
    actual = estimate_fork_context_bytes([item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "0")

    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "fork_context_too_large"
    assert str(actual) in error["message"]
    assert f"threshold {actual - 1} bytes" in error["message"]
    assert store.fork_calls == []


def test_same_family_native_clone_skips_preflight_compaction(monkeypatch) -> None:
    """A native clone carries its local transcript without preflight compaction."""
    source = _make_conversation()
    source.external_session_id = "source-native-session"
    item = _make_item("item_1", "x" * 300)
    store = _ConversationStore(
        conversations={_SOURCE_ID: source},
        items_by_conv={_SOURCE_ID: [item]},
    )
    actual = estimate_fork_context_bytes([item.to_api_dict()])
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(actual - 1))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "1")
    monkeypatch.delenv("OMNIGENT_FORK_NATIVE_GUARD", raising=False)

    async def _native_target_harness(*_args, **_kwargs) -> str:
        return "claude-native"

    def _native_history(_agent) -> bool:
        return True

    def _no_cursor_history(_agent) -> bool:
        return False

    async def _unexpected_compaction(*_args, **_kwargs) -> None:
        raise AssertionError("native clone should skip compact_fork_items")

    monkeypatch.setattr(
        routes_core_module,
        "_resolve_fork_target_harness",
        _native_target_harness,
    )
    monkeypatch.setattr(
        routes_core_module,
        "_agent_carries_native_fork_history",
        _native_history,
    )
    monkeypatch.setattr(
        routes_core_module,
        "_agent_carries_cursor_fork_history",
        _no_cursor_history,
    )
    monkeypatch.setattr(
        routes_core_module,
        "compact_fork_items",
        _unexpected_compaction,
    )

    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert store.fork_calls[0]["replacement_items"] is None
    assert store._items["c538360473d41c84c1eee13918fbeca0"] == [item]


def test_sdk_source_external_id_keeps_preflight_guard(monkeypatch) -> None:
    """A native target does not bypass the guard for an SDK source."""
    source = _make_conversation()
    source.external_session_id = "stale-sdk-session"
    item = _make_item("item_1", "x" * 300)
    store = _ConversationStore(
        conversations={_SOURCE_ID: source},
        items_by_conv={_SOURCE_ID: [item]},
    )
    agent_store = _switch_agent_store()
    cache = _StubAgentCache(
        {
            "087b7cb7ac30abf4debfaa578d052ec6": "claude_sdk",
            "280d725b404d2915f9e9d6cccce91303": "claude-native",
        }
    )
    monkeypatch.setattr(
        "omnigent.server.routes.sessions.get_agent_cache",
        lambda: cache,
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "0")

    app = _build_app(store, agent_store=agent_store, agent_cache=cache)
    response = TestClient(app).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={"agent_id": "280d725b404d2915f9e9d6cccce91303"},
    )

    assert response.status_code == 413, response.text
    assert store.fork_calls == []


def test_fork_allows_summary_only_compaction(monkeypatch) -> None:
    """History covered by a valid compaction marker is not measured twice."""
    old = _make_item("old", "x" * 500)
    compacted = ConversationItem(
        id="compact",
        type="compaction",
        status="completed",
        response_id="resp_compact",
        created_at=2,
        data=CompactionData(
            summary="short summary",
            last_item_id=old.id,
            token_count=2,
        ),
    )
    new = _make_item("new", "after", response_id="resp_new")
    source_items = [old, compacted, new]
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: source_items},
    )
    payload = [item.to_api_dict() for item in source_items]
    compacted_size = estimate_fork_context_bytes(summary_only_items(payload))
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", str(compacted_size + 1))

    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert len(store.fork_calls) == 1


def test_fork_keeps_small_history_unchanged(monkeypatch) -> None:
    """A small session follows the existing fork path."""
    item = _make_item("item_1", "small")
    store = _ConversationStore(
        conversations={_SOURCE_ID: _make_conversation()},
        items_by_conv={_SOURCE_ID: [item]},
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "100000")

    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert len(store.fork_calls) == 1
    assert store.fork_calls[0]["replacement_items"] is None
    assert store._items["c538360473d41c84c1eee13918fbeca0"] == [item]
    assert response.json()["items"][0]["data"]["content"][0]["text"] == "small"


class _PagedConversationStore(_ConversationStore):
    """Return the source history in two pages while keeping fork behavior."""

    def __init__(self, items):
        super().__init__(
            conversations={_SOURCE_ID: _make_conversation()},
            items_by_conv={_SOURCE_ID: items},
        )
        self.page_cursors: list[str | None] = []

    def list_items(
        self,
        conversation_id,
        limit=100,
        after=None,
        before=None,
        order="asc",
        type=None,
    ):
        if conversation_id != _SOURCE_ID or limit != 1000:
            return super().list_items(
                conversation_id,
                limit=limit,
                after=after,
                before=before,
                order=order,
                type=type,
            )
        self.page_cursors.append(after)
        source_items = self._items[_SOURCE_ID]
        page = source_items[:1] if after is None else source_items[1:]
        return PagedList(
            data=page,
            first_id=page[0].id,
            last_id=page[-1].id,
            has_more=after is None,
        )


def test_fork_paginates_source_history_before_measurement(monkeypatch) -> None:
    """The preflight fetch follows the cursor beyond the first page."""
    items = [_make_item("first", "one"), _make_item("last", "two")]
    store = _PagedConversationStore(items)
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "100000")

    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={},
    )

    assert response.status_code == 201, response.text
    assert store.page_cursors == [None, "first"]
