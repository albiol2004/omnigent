"""Manual Codex compaction over the app-server ``thread/compact/start`` RPC.

A loopback fake app-server speaks real JSON-RPC over a websocket, so these
tests drive the production :class:`CodexAppServerClient`. No Codex binary,
model or network is involved.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from collections.abc import AsyncIterator
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection, serve

from omnigent.harnesses.codex_native.manual_compact import (
    CODEX_COMPACT_START_METHOD,
    CodexCompactState,
    CodexManualCompactTracker,
    await_codex_manual_compact,
    start_codex_manual_compact,
)

pytestmark = pytest.mark.asyncio

THREAD = "019e0000-aaaa-7bbb-8ccc-000000000001"
OTHER_THREAD = "019e0000-aaaa-7bbb-8ccc-000000000002"


class _FakeAppServer:
    """
    Minimal Codex app-server: answers ``initialize`` and scripts compact.

    :param compact_mode: ``"ok"`` (``{}``), ``"error"`` (JSON-RPC error),
        ``"silent"`` (never answers) or ``"drop"`` (closes the socket).
    """

    def __init__(self, compact_mode: str = "ok") -> None:
        self.compact_mode = compact_mode
        self.received: list[dict[str, Any]] = []
        self.url = ""

    @property
    def compact_requests(self) -> list[dict[str, Any]]:
        """Return every ``thread/compact/start`` request received."""
        return [m for m in self.received if m.get("method") == CODEX_COMPACT_START_METHOD]

    async def _handler(self, ws: ServerConnection) -> None:
        async for raw in ws:
            message = json.loads(raw)
            self.received.append(message)
            method = message.get("method")
            if method == "initialize":
                await ws.send(json.dumps({"id": message["id"], "result": {}}))
            elif method == CODEX_COMPACT_START_METHOD:
                if self.compact_mode == "ok":
                    await ws.send(json.dumps({"id": message["id"], "result": {}}))
                elif self.compact_mode == "error":
                    await ws.send(
                        json.dumps(
                            {
                                "id": message["id"],
                                "error": {
                                    "code": -32600,
                                    "message": "failed to start compaction: thread not loaded",
                                },
                            }
                        )
                    )
                elif self.compact_mode == "drop":
                    await ws.close()
                    return
                # "silent": never answer.


@contextlib.asynccontextmanager
async def _app_server(compact_mode: str = "ok") -> AsyncIterator[_FakeAppServer]:
    fake = _FakeAppServer(compact_mode)
    async with serve(fake._handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        fake.url = f"ws://127.0.0.1:{port}"
        yield fake


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"ws://127.0.0.1:{port}"


def _event(method: str, **params: Any) -> dict[str, Any]:
    return {"method": method, "params": params}


def _compaction_item(method: str, thread_id: str = THREAD, turn_id: str = "turn_c") -> Any:
    return _event(
        method,
        threadId=thread_id,
        turnId=turn_id,
        item={"type": "contextCompaction", "id": "item_c"},
    )


async def _start(
    fake_url: str,
    tracker: CodexManualCompactTracker,
    *,
    active_turn_id: str | None = None,
    accept_timeout_s: float = 2.0,
) -> Any:
    return await start_codex_manual_compact(
        session_id="conv_1",
        thread_id=THREAD,
        transport=fake_url,
        active_turn_id=active_turn_id,
        tracker=tracker,
        connect_timeout_s=2.0,
        accept_timeout_s=accept_timeout_s,
    )


async def test_sends_thread_compact_start_and_reports_accepted_not_completed() -> None:
    """The RPC carries the session's thread id; the response is only acceptance."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        outcome, entry = await _start(fake.url, tracker)

    assert [m["method"] for m in fake.received] == [
        "initialize",
        "initialized",
        CODEX_COMPACT_START_METHOD,
    ]
    request = fake.compact_requests[0]
    assert request["params"] == {"threadId": THREAD}
    assert outcome.state is CodexCompactState.ACCEPTED
    assert outcome.request_id == request["id"]
    assert entry is not None and not entry.done.done()
    assert tracker.get(THREAD) is entry


@pytest.mark.parametrize("signal", ["item", "thread_compacted"])
async def test_completion_event_resolves_completed(signal: str) -> None:
    """A ``contextCompaction`` completion (or ``thread/compacted``) completes."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        outcome, entry = await _start(fake.url, tracker)
    assert outcome.state is CodexCompactState.ACCEPTED and entry is not None

    tracker.observe(_event("turn/started", threadId=THREAD, turn={"id": "turn_c"}))
    tracker.observe(_compaction_item("item/started"))
    assert entry.item_started and not entry.done.done()
    if signal == "item":
        tracker.observe(_compaction_item("item/completed"))
    else:
        tracker.observe(_event("thread/compacted", threadId=THREAD, turnId="turn_c"))

    final = await await_codex_manual_compact(entry, tracker=tracker, completion_timeout_s=1.0)
    assert final.state is CodexCompactState.COMPLETED
    assert final.turn_id == "turn_c"
    assert tracker.get(THREAD) is None


async def test_rpc_error_is_rejected_and_releases_thread() -> None:
    """A JSON-RPC error is propagated, and the thread is free again."""
    tracker = CodexManualCompactTracker()
    async with _app_server("error") as fake:
        outcome, entry = await _start(fake.url, tracker)

    assert outcome.state is CodexCompactState.REJECTED
    assert outcome.detail == "failed to start compaction: thread not loaded"
    assert entry is None
    assert tracker.get(THREAD) is None
    assert len(fake.compact_requests) == 1


async def test_missing_completion_times_out_uncertain_without_resend() -> None:
    """No completion event: bounded wait, ``uncertain``, exactly one request."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        outcome, entry = await _start(fake.url, tracker)
        assert outcome.state is CodexCompactState.ACCEPTED and entry is not None
        final = await await_codex_manual_compact(entry, tracker=tracker, completion_timeout_s=0.05)
        await asyncio.sleep(0.05)

    assert final.state is CodexCompactState.UNCERTAIN
    assert final.state is not CodexCompactState.COMPLETED
    assert len(fake.compact_requests) == 1
    assert tracker.get(THREAD) is None


async def test_accept_timeout_is_uncertain_keeps_thread_busy_no_resend() -> None:
    """An unanswered request is uncertain; a repeat click is refused, not resent."""
    tracker = CodexManualCompactTracker()
    async with _app_server("silent") as fake:
        outcome, entry = await _start(fake.url, tracker, accept_timeout_s=0.1)
        again, again_entry = await _start(fake.url, tracker, accept_timeout_s=0.1)

    assert outcome.state is CodexCompactState.UNCERTAIN
    assert entry is not None and tracker.get(THREAD) is entry
    assert again.state is CodexCompactState.BUSY and again_entry is None
    assert len(fake.compact_requests) == 1
    # A late completion still settles the uncertain request.
    tracker.observe(_compaction_item("item/completed"))
    final = await await_codex_manual_compact(entry, tracker=tracker, completion_timeout_s=1.0)
    assert final.state is CodexCompactState.COMPLETED


async def test_connection_dropped_after_send_is_uncertain() -> None:
    """The socket closing mid-request cannot prove failure: ``uncertain``."""
    tracker = CodexManualCompactTracker()
    async with _app_server("drop") as fake:
        outcome, entry = await _start(fake.url, tracker, accept_timeout_s=0.3)

    assert outcome.state is CodexCompactState.UNCERTAIN
    assert entry is not None
    assert len(fake.compact_requests) == 1


async def test_active_turn_is_busy_and_sends_nothing() -> None:
    """A turn in progress is refused before any connection is opened."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        outcome, entry = await _start(fake.url, tracker, active_turn_id="turn_live")

    assert outcome.state is CodexCompactState.BUSY
    assert entry is None
    assert fake.received == []
    assert tracker.get(THREAD) is None


async def test_compaction_in_flight_is_busy() -> None:
    """A second compaction for the same thread is refused, not queued."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        first, entry = await _start(fake.url, tracker)
        second, second_entry = await _start(fake.url, tracker)

    assert first.state is CodexCompactState.ACCEPTED and entry is not None
    assert second.state is CodexCompactState.BUSY and second_entry is None
    assert len(fake.compact_requests) == 1


async def test_other_thread_events_are_ignored() -> None:
    """Completion and failure signals for another thread never settle ours."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        _, entry = await _start(fake.url, tracker)
    assert entry is not None

    tracker.observe(_event("turn/started", threadId=OTHER_THREAD, turn={"id": "turn_x"}))
    tracker.observe(_compaction_item("item/completed", thread_id=OTHER_THREAD))
    tracker.observe(_event("thread/compacted", threadId=OTHER_THREAD, turnId="turn_x"))
    tracker.observe(
        _event("turn/completed", threadId=OTHER_THREAD, turn={"id": "turn_x", "status": "failed"})
    )
    tracker.observe(
        _event("error", threadId=OTHER_THREAD, turnId="turn_x", willRetry=False, error={})
    )
    tracker.observe(
        {"method": "item/completed", "params": {"item": {"type": "contextCompaction"}}}
    )

    assert not entry.done.done()
    assert entry.turn_id is None


@pytest.mark.parametrize("status", ["failed", "interrupted"])
async def test_failed_compaction_turn_is_failed(status: str) -> None:
    """A compaction turn that ends failed/interrupted reports ``failed``."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        _, entry = await _start(fake.url, tracker)
    assert entry is not None

    tracker.observe(_compaction_item("item/started"))
    tracker.observe(
        _event(
            "turn/completed",
            threadId=THREAD,
            turn={"id": "turn_c", "status": status, "error": {"message": "context too large"}},
        )
    )
    final = await await_codex_manual_compact(entry, tracker=tracker, completion_timeout_s=1.0)
    assert final.state is CodexCompactState.FAILED
    assert final.detail == "context too large"


async def test_error_notification_fails_only_when_not_retrying() -> None:
    """``error`` with ``willRetry`` is transient; without it the compaction failed."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        _, entry = await _start(fake.url, tracker)
    assert entry is not None

    tracker.observe(_event("turn/started", threadId=THREAD, turn={"id": "turn_c"}))
    tracker.observe(
        _event(
            "error", threadId=THREAD, turnId="turn_c", willRetry=True, error={"message": "retry"}
        )
    )
    assert not entry.done.done()
    tracker.observe(
        _event(
            "error", threadId=THREAD, turnId="turn_c", willRetry=False, error={"message": "boom"}
        )
    )
    final = await await_codex_manual_compact(entry, tracker=tracker, completion_timeout_s=1.0)
    assert final.state is CodexCompactState.FAILED
    assert final.detail == "boom"


async def test_turn_completed_without_compaction_item_is_uncertain() -> None:
    """A clean turn end with no compaction signal is not reported as completed."""
    tracker = CodexManualCompactTracker()
    async with _app_server("ok") as fake:
        _, entry = await _start(fake.url, tracker)
    assert entry is not None

    tracker.observe(_event("turn/started", threadId=THREAD, turn={"id": "turn_c"}))
    tracker.observe(
        _event("turn/completed", threadId=THREAD, turn={"id": "turn_c", "status": "completed"})
    )
    final = await await_codex_manual_compact(entry, tracker=tracker, completion_timeout_s=1.0)
    assert final.state is CodexCompactState.UNCERTAIN


async def test_unreachable_app_server_is_disconnected() -> None:
    """No listener: ``disconnected`` and the thread is released."""
    tracker = CodexManualCompactTracker()
    outcome, entry = await _start(_closed_port_url(), tracker)

    assert outcome.state is CodexCompactState.DISCONNECTED
    assert entry is None
    assert tracker.get(THREAD) is None


class _ForwarderFakeClient:
    """Subscribed forwarder connection replaying scripted live events."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def connect(self) -> None:
        """No-op connect."""

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Answer ``thread/resume`` with an empty thread."""
        self.requests.append((method, params))
        return {"result": {"thread": {"id": THREAD, "turns": []}}}

    async def iter_events(self) -> Any:
        """Yield the scripted events, then end the stream."""
        for event in self.events:
            yield event

    async def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        """Unused."""

    async def close(self) -> None:
        """Mark closed."""
        self.closed = True


async def test_forwarder_live_stream_settles_manual_compact_and_still_mirrors(
    tmp_path: Any,
) -> None:
    """
    The forwarder feeds live events to the process tracker (ignoring other
    threads) while still mirroring compaction status to Omnigent as before.
    """
    import httpx

    from omnigent.harnesses.codex_native import forwarder
    from omnigent.harnesses.codex_native.manual_compact import codex_manual_compact_tracker

    tracker = codex_manual_compact_tracker()
    tracker._by_thread.clear()
    entry = tracker.begin("conv_123", THREAD)
    assert entry is not None
    posts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(json.loads(request.content))
        return httpx.Response(200, json={})

    fake = _ForwarderFakeClient(
        [
            _compaction_item("item/completed", thread_id=OTHER_THREAD),
            _event("turn/started", threadId=THREAD, turn={"id": "turn_c", "items": []}),
            _compaction_item("item/started"),
            _compaction_item("item/completed"),
        ]
    )
    try:
        await forwarder.supervise_forwarder(
            base_url="http://127.0.0.1:1",
            headers={},
            session_id="conv_123",
            bridge_dir=tmp_path,
            app_server_url="ws://127.0.0.1:1",
            thread_id=THREAD,
            client=fake,  # type: ignore[arg-type]
            ap_transport=httpx.MockTransport(handler),
        )
        assert entry.done.done()
        outcome = entry.done.result()
    finally:
        tracker._by_thread.clear()

    assert outcome.state is CodexCompactState.COMPLETED
    assert outcome.turn_id == "turn_c"
    statuses = [
        p["data"]["status"] for p in posts if p.get("type") == "external_compaction_status"
    ]
    assert statuses == ["in_progress", "completed"]


@pytest.mark.parametrize(
    ("turn_status", "expected"),
    [("failed", "failed"), ("interrupted", "failed"), ("completed", "completed")],
)
async def test_turn_boundary_safety_net_does_not_fake_completion(
    tmp_path: Any, turn_status: str, expected: str
) -> None:
    """
    A spinner left in progress is closed at the turn boundary as ``failed``
    when the turn failed or was interrupted, and ``completed`` only otherwise.
    """
    import httpx

    from omnigent.harnesses.codex_native import forwarder as fwd

    posts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(json.loads(request.content))
        return httpx.Response(200, json={})

    state = fwd._CodexForwarderState()
    state.compaction_status_posted = "in_progress"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ap"
    ) as client:
        usage = fwd._SessionUsageCoalescer(client, "conv_x")
        tracker = fwd._CodexElicitationTaskTracker()
        try:
            await fwd._handle_terminal_turn_boundary(
                client,
                session_id="conv_x",
                bridge_dir=tmp_path,
                method="turn/completed",
                params={
                    "threadId": THREAD,
                    "turn": {"id": "turn_c", "status": turn_status, "items": []},
                },
                usage_coalescer=usage,
                delta_coalescer=None,
                elicitation_tracker=tracker,
                codex_client=None,
                forwarder_state=state,
            )
        finally:
            await usage.close()
            await tracker.close()

    statuses = [
        p["data"]["status"] for p in posts if p.get("type") == "external_compaction_status"
    ]
    assert statuses == [expected]
