"""A cursor child's repeated terminal post keeps its outcome and has no repeated effects.

Drives the real ``POST /v1/sessions/{id}/events`` route (the ``status_route``
fixture: real stores, real parent/child rows, a captured runner). A completion
receipt re-post names its turn by ``(epoch, turn_seq)``; a forwarder that
predates ``_ReceiptState.posted_outcome`` re-posts a failed/cancelled turn as a
bare ``idle``, and a fixed one repeats the outcome. Either way the server must
keep the turn's outcome and deliver its terminal side effects once.
"""

# pytest injects the imported fixture by parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811
from __future__ import annotations

from typing import Any

import pytest

from omnigent.entities import MessageData, NewConversationItem
from omnigent.server.routes import sessions
from omnigent.server.routes._sessions import common, input_fence
from omnigent.server.routes._sessions import helpers as session_helpers
from omnigent.server.routes.sessions import routes_events
from tests.server.routes.test_subagent_status import (  # noqa: F401 - fixture
    _flush_live_state,
    _StatusRoute,
    status_route,
)

pytestmark = pytest.mark.asyncio

_EPOCH = 1_790_000_000_000


def _receipt(turn_seq: int, rev: int) -> dict[str, Any]:
    return {
        "v": 1,
        "epoch": _EPOCH,
        "turn_seq": turn_seq,
        "turn_end_count": turn_seq,
        "inject_count_at_end": turn_seq,
        "inject_count": turn_seq,
        "injections": [],
        "injections_truncated": False,
        "stop_status_raw": None,
        "stop_reason": "unknown",
        "generation_id": None,
        "hook_conversation_id": None,
        "chat_id": "chat-1",
        "transcript": {
            "store_max_rowid": 2,
            "acked_through_rowid": 2,
            "unacked_rowids": [],
            "observed_max_acked": True,
        },
        "rev": rev,
    }


@pytest.fixture
def route(status_route: _StatusRoute, monkeypatch: pytest.MonkeyPatch) -> _StatusRoute:
    status_route.store.set_labels(
        status_route.child_id,
        {input_fence.COMPLETION_RECEIPTS_LABEL: input_fence.COMPLETION_RECEIPTS_VERSION},
    )
    monkeypatch.setattr(sessions, "_resolve_harness", lambda *a, **k: "cursor-native")
    return status_route


def _mirror_reply(route: _StatusRoute, response_id: str) -> None:
    route.store.append(
        route.child_id,
        [
            NewConversationItem(
                type="message",
                response_id=response_id,
                data=MessageData(
                    role="assistant",
                    agent="Cursor",
                    content=[{"type": "output_text", "text": "x"}],
                ),
            )
        ],
    )


async def _post(
    route: _StatusRoute,
    *,
    turn_seq: int,
    rev: int,
    outcome: str | None,
    status: str | None = None,
) -> None:
    """One forwarder terminal post: ``failed`` for a failed turn, else ``idle``."""
    data: dict[str, Any] = {
        "status": status or ("failed" if outcome == "failed" else "idle"),
        "turn_end": _receipt(turn_seq, rev),
    }
    if outcome is not None:
        data["turn_outcome"] = outcome
    resp = await route.client.post(
        f"/v1/sessions/{route.child_id}/events",
        json={"type": "external_session_status", "data": data},
    )
    assert resp.status_code == 202, resp.text


def _returned(route: _StatusRoute) -> list[str]:
    return [
        item.data.resource["status"]
        for item in route.store.list_items(route.parent_id).data
        if item.data.event_type == "session.subagent.returned"
    ]


def _terminal_forwards(route: _StatusRoute) -> list[dict[str, Any]]:
    return [
        body["data"]
        for _path, body in route.forwarded
        if body.get("type") == "external_session_status"
        and body["data"].get("status") in {"idle", "failed"}
    ]


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
async def test_pre_upgrade_bare_idle_repost_keeps_the_turns_outcome(
    route: _StatusRoute, outcome: str
) -> None:
    """A receipt state without ``posted_outcome`` re-posts a bare idle for the same turn."""
    _mirror_reply(route, "turn-1")
    await _post(route, turn_seq=1, rev=1, outcome=outcome)
    assert _returned(route) == [outcome]
    first = _terminal_forwards(route)
    assert len(first) == 1

    # The old forwarder's re-post: same (epoch, turn_seq), higher rev, no outcome.
    _mirror_reply(route, "turn-1-late-flush")
    await _post(route, turn_seq=1, rev=2, outcome=None, status="idle")

    assert _returned(route) == [outcome]
    # The child's session status is still the turn's terminal one: a failed
    # turn must not flip to idle (a cancelled turn is idle by definition).
    await _flush_live_state()
    expected_status = "failed" if outcome == "failed" else "idle"
    assert common._session_status_cache[route.child_id] == expected_status
    live = route.store.get_conversation(route.child_id)
    assert live is not None and live.live_status == expected_status
    assert len(_terminal_forwards(route)) == 1
    # The refreshed receipt is still stored.
    stored = route.store.get_conversation(route.child_id)
    assert stored is not None
    assert '"rev":2' in stored.labels[input_fence.TURN_RECEIPT_LABEL]
    assert stored.labels[input_fence.TURN_TERMINAL_LABEL]


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
async def test_bare_idle_for_a_new_turn_still_completes(route: _StatusRoute, outcome: str) -> None:
    _mirror_reply(route, "turn-1")
    await _post(route, turn_seq=1, rev=1, outcome=outcome)
    _mirror_reply(route, "turn-2")
    await _post(route, turn_seq=2, rev=1, outcome=None, status="idle")
    assert _returned(route) == [outcome, "completed"]
    forwards = _terminal_forwards(route)
    assert [f["status"] for f in forwards] == ["failed" if outcome == "failed" else "idle", "idle"]
    assert "turn_outcome" not in forwards[1]


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
async def test_repeated_terminal_post_delivers_its_effects_once(
    route: _StatusRoute, outcome: str
) -> None:
    """Two identical terminal posts for one turn: one returned event, one forward."""
    _mirror_reply(route, "turn-1")
    await _post(route, turn_seq=1, rev=1, outcome=outcome)
    # A delayed transcript flush lands between the posts, so the repeat would
    # otherwise key a different ``returned`` event off the newest item.
    _mirror_reply(route, "turn-1-late-flush")
    await _post(route, turn_seq=1, rev=2, outcome=outcome)
    assert _returned(route) == [outcome]
    assert len(_terminal_forwards(route)) == 1
    route.telemetry.assert_called_once()

    # A later turn's failure is its own event and forward.
    _mirror_reply(route, "turn-2")
    await _post(route, turn_seq=2, rev=1, outcome=outcome)
    assert _returned(route) == [outcome, outcome]
    assert len(_terminal_forwards(route)) == 2


async def test_a_terminal_post_whose_forward_failed_is_redelivered(
    route: _StatusRoute, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delivery marker is written only after the forward succeeded."""
    real_forward = routes_events._forward_session_change_to_runner
    down = {"on": True}

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        if down["on"]:
            return session_helpers._RunnerForwardResult(status_code=503, body="down")
        return await real_forward(*args, **kwargs)

    monkeypatch.setattr(routes_events, "_forward_session_change_to_runner", flaky)
    _mirror_reply(route, "turn-1")
    resp = await route.client.post(
        f"/v1/sessions/{route.child_id}/events",
        json={
            "type": "external_session_status",
            "data": {"status": "failed", "turn_outcome": "failed", "turn_end": _receipt(1, 1)},
        },
    )
    assert resp.status_code >= 500
    assert _terminal_forwards(route) == []

    down["on"] = False
    await _post(route, turn_seq=1, rev=1, outcome="failed")
    assert _returned(route) == ["failed"]
    assert len(_terminal_forwards(route)) == 1


async def test_unauthorised_receipt_caller_does_not_write_the_turn_marker(
    route: _StatusRoute, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edit access without runner/owner authority: ``turn_end`` names no turn.

    The failed post is delivered as before, but its ``turn_end`` is neither
    stored nor used for the terminal marker, so a later authorised bare idle
    for that turn is a plain completion, not an inherited-and-suppressed one.
    """
    real_require_access = routes_events._require_access

    async def deny_owner(user_id: Any, session_id: str, level: Any, *args: Any, **kwargs: Any):
        if level == routes_events.LEVEL_OWNER:
            raise routes_events.OmnigentError("owner required", code="forbidden")
        return await real_require_access(user_id, session_id, level, *args, **kwargs)

    _mirror_reply(route, "turn-1")
    monkeypatch.setattr(routes_events, "_require_access", deny_owner)
    await _post(route, turn_seq=1, rev=1, outcome="failed")
    assert _returned(route) == ["failed"]
    unauthorised = route.store.get_conversation(route.child_id)
    assert unauthorised is not None
    assert input_fence.TURN_TERMINAL_LABEL not in unauthorised.labels
    assert input_fence.TURN_RECEIPT_LABEL not in unauthorised.labels

    monkeypatch.setattr(routes_events, "_require_access", real_require_access)
    _mirror_reply(route, "turn-1-late-flush")
    await _post(route, turn_seq=1, rev=2, outcome=None, status="idle")
    assert _returned(route) == ["failed", "completed"]
    assert len(_terminal_forwards(route)) == 2
    authorised = route.store.get_conversation(route.child_id)
    assert authorised is not None
    assert authorised.labels[input_fence.TURN_TERMINAL_LABEL]
