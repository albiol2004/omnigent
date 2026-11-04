"""#10251 shared-runner ownership must not defeat the fork's kill-on-close."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx

from omnigent.db.utils import generate_agent_id
from omnigent.runtime import set_runner_client
from omnigent.server.routes._sessions.helpers import (
    _owns_host_runner,
    _stop_session_via_runner_impl,
)
from omnigent.stores.agent_store.sqlalchemy_store import SqlAlchemyAgentStore
from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

_HOST_ID = "1234567890abcdef1234567890abcdef"
_RUNNER_ID = "runner-shared-parent"


def _family(db_uri: str) -> tuple[str, str]:
    """Insert a host-bound parent and a child riding the same runner."""
    store = SqlAlchemyConversationStore(db_uri)
    agent_id = generate_agent_id()
    SqlAlchemyAgentStore(db_uri).create(agent_id, name="test", bundle_location="test:///bundle")
    parent = store.create_conversation(agent_id=agent_id)
    store.set_runner_id(parent.id, _RUNNER_ID)
    store.set_host_id(parent.id, _HOST_ID, workspace="/workspace")
    child = store.create_conversation(
        agent_id=agent_id,
        kind="sub_agent",
        parent_conversation_id=parent.id,
        title="child C",
    )
    store.set_runner_id(child.id, _RUNNER_ID)
    store.set_host_id(child.id, _HOST_ID, workspace="/workspace")
    return parent.id, child.id


def _recording_runner() -> tuple[httpx.AsyncClient, list[tuple[str, dict[str, Any]]]]:
    """Fake runner client that 204s every call and records POSTed events."""
    posts: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content) if request.content else {}
            posts.append((request.url.path, body))
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://runner")
    return client, posts


async def _stop_session_like_events_route(
    session_id: str,
    store: SqlAlchemyConversationStore,
    host_stop: AsyncMock,
) -> bool:
    """Drive the real stop_session teardown: runner hard-stop, then #10251 host gate."""
    delivered = await _stop_session_via_runner_impl(session_id, None)
    conv = store.get_conversation(session_id)
    if (
        conv is not None
        and conv.host_id
        and conv.runner_id
        and await _owns_host_runner(conv, store)
    ):
        await host_stop(session_id, conv.host_id, conv.runner_id)
    return delivered


async def test_stop_subagent_child_kills_native_harness_without_stopping_shared_host_runner(
    db_uri: str,
) -> None:
    """Child close/stop hard-stops the child's native harness, not the shared host runner.

    A sub-agent created with ``parent_conversation_id`` inherits the parent's
    ``runner_id``. The ``stop_session`` path ``sys_session_close`` uses for
    claude/codex/cursor native children must still POST ``stop_session`` to the
    runner that kills the child's pane, while #10251's ``_owns_host_runner``
    must leave the parent's host runner up.
    """
    parent_id, child_id = _family(db_uri)
    store = SqlAlchemyConversationStore(db_uri)
    fake_runner, posts = _recording_runner()
    host_stop = AsyncMock(return_value=True)
    set_runner_client(fake_runner)
    try:
        delivered = await _stop_session_like_events_route(child_id, store, host_stop)
    finally:
        set_runner_client(None)
        await fake_runner.aclose()
    assert delivered is True
    child_stops = [body for path, body in posts if path == f"/v1/sessions/{child_id}/events"]
    assert child_stops, (
        f"child {child_id} stop must forward a runner stop_session "
        f"(native hard-stop); recorded POSTs: {posts}"
    )
    assert any(body.get("type") == "stop_session" for body in child_stops), child_stops
    host_stop.assert_not_awaited()
    parent = store.get_conversation(parent_id)
    assert parent is not None and parent.runner_id == _RUNNER_ID


async def test_stop_top_level_host_session_stops_owned_host_runner(
    db_uri: str,
) -> None:
    """Closing a top-level host-launched session stops the host runner it owns."""
    parent_id, _child_id = _family(db_uri)
    store = SqlAlchemyConversationStore(db_uri)
    fake_runner, posts = _recording_runner()
    host_stop = AsyncMock(return_value=True)
    set_runner_client(fake_runner)
    try:
        delivered = await _stop_session_like_events_route(parent_id, store, host_stop)
    finally:
        set_runner_client(None)
        await fake_runner.aclose()
    assert delivered is True
    parent_stops = [body for path, body in posts if path == f"/v1/sessions/{parent_id}/events"]
    assert any(body.get("type") == "stop_session" for body in parent_stops), posts
    host_stop.assert_awaited()
    assert host_stop.await_args.args[:3] == (parent_id, _HOST_ID, _RUNNER_ID)
