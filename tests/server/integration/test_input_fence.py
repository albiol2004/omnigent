"""Opt-in completion receipt + durable input fence through the real session routes.

Runs the auth-enabled app (owner/editor identities, SQL stores) and routes the
server→runner fence call to the real runner-side handler over a temp bridge dir,
so admission, persistence, verification, and the pane fence are all real code.
"""

# The permission suite's fixtures are imported for reuse, and pytest injects
# them by parameter name, which ruff reads as a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from omnigent.harnesses.cursor_native import forwarder, status
from omnigent.harnesses.cursor_native.fence import handle_runner_fence_request
from omnigent.runtime import pending_inputs
from omnigent.server.auth import LEVEL_EDIT
from omnigent.server.routes import sessions as sessions_module
from omnigent.server.routes._sessions import input_fence
from tests.server.helpers import create_test_agent
from tests.server.integration.test_sessions_permissions import (  # noqa: F401 - fixtures
    _create_session_as,
    _grant_permission,
    auth_app,
    auth_client,
)

pytestmark = pytest.mark.asyncio

_OWNER = {"X-Forwarded-Email": "owner"}
_EDITOR = {"X-Forwarded-Email": "editor"}
_EPOCH = 1_790_000_000_000
_OPT_IN = {input_fence.COMPLETION_RECEIPTS_LABEL: input_fence.COMPLETION_RECEIPTS_VERSION}


class _Runner:
    """Server→runner transport backed by the real runner fence handler."""

    def __init__(self, bridge_dir: Path, store_path: Path) -> None:
        self.bridge_dir = bridge_dir
        self.store_path = store_path
        self.calls: list[dict[str, Any]] = []
        self.fail_open = False
        self.gate: asyncio.Event | None = None

    async def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("type") != "input_fence":
            # Status edges the server relays to the runner are irrelevant here.
            return httpx.Response(204)
        self.calls.append(body["data"])
        if self.gate is not None:
            await self.gate.wait()
        if body["data"]["action"] == "open" and self.fail_open:
            return httpx.Response(503, json={"error": "down"})
        code, payload = handle_runner_fence_request(self.bridge_dir, body["data"])
        return httpx.Response(code, json=payload)


@pytest.fixture(autouse=True)
def _single_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(input_fence.SINGLE_SERVER_ENV, "1")
    input_fence.reset_for_tests()
    pending_inputs.reset_for_tests()


@pytest.fixture()
def runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Runner:
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    store_path = tmp_path / "chats" / "h" / "chat-1" / "store.db"
    store_path.parent.mkdir(parents=True)
    with sqlite3.connect(store_path) as con:
        con.execute("CREATE TABLE blobs(id TEXT PRIMARY KEY, data BLOB)")
    fake = _Runner(bridge_dir, store_path)
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(fake.handle), base_url="http://runner"
    )

    async def _get_runner_client(*_a: object, **_k: object) -> httpx.AsyncClient:
        return client

    monkeypatch.setattr(sessions_module, "_get_runner_client", _get_runner_client)
    # The chat id the runner reports, and the rows turn ends bind to, come from
    # the forwarder's bound store.
    (bridge_dir / "cursor_forwarder.json").write_text(
        json.dumps({"store_path": str(store_path), "last_rowid": 0})
    )
    forwarder._write_receipt_state(bridge_dir, forwarder._ReceiptState(store_path=str(store_path)))
    return fake


async def _session(client: httpx.AsyncClient, labels: dict[str, str] | None = None) -> str:
    agent = await create_test_agent(client, user="owner")
    snap = await _create_session_as(client, agent["id"], "owner")
    if labels:
        resp = await client.patch(
            f"/v1/sessions/{snap['id']}", json={"labels": labels}, headers=_OWNER
        )
        assert resp.status_code == 200, resp.text
    return snap["id"]


def _event(client: httpx.AsyncClient, sid: str, body: dict, headers: dict = _OWNER):
    return client.post(f"/v1/sessions/{sid}/events", json=body, headers=headers)


def _receipt(**overrides: Any) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "v": 1,
        "epoch": _EPOCH,
        "turn_seq": 1,
        "turn_end_count": 1,
        "inject_count_at_end": 1,
        "inject_count": 1,
        "injections": [{"seq": 1, "message_seq": 1, "sha256": "ab", "kind": "message"}],
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
        "rev": 1,
    }
    receipt.update(overrides)
    return receipt


def _expect() -> dict[str, Any]:
    return {
        "epoch": _EPOCH,
        "turn_seq": 1,
        "inject_count": 1,
        "turn_end_count": 1,
        "chat_id": "chat-1",
    }


def _submitted_row(runner: _Runner, prompt: str) -> None:
    """Append the ``<user_query>`` row cursor writes when *prompt*'s turn starts."""
    blob = {
        "role": "user",
        "content": [{"type": "text", "text": f"<user_query>\n{prompt}\n</user_query>"}],
    }
    with sqlite3.connect(runner.store_path) as con:
        rowid = con.execute("SELECT COALESCE(MAX(rowid), 0) + 1 FROM blobs").fetchone()[0]
        con.execute("INSERT INTO blobs VALUES(?, ?)", (f"b{rowid}", json.dumps(blob).encode()))


#: A real stop payload for the runner's chat (cursor always sends ``conversation_id``).
_STOP = {"status": "completed", "conversation_id": "chat-1"}


def _one_finished_turn(runner: _Runner) -> None:
    status.record_injection(runner.bridge_dir, "prompt", kind="message")
    _submitted_row(runner, "prompt")
    status.record_turn_end(runner.bridge_dir, _STOP)


async def _labels(client: httpx.AsyncClient, sid: str) -> dict[str, str]:
    resp = await client.get(f"/v1/sessions/{sid}", headers=_OWNER)
    assert resp.status_code == 200
    return resp.json()["labels"]


def _close(fence_id: str = "f1", expect: dict | None = None) -> dict:
    return {
        "type": "input_fence",
        "data": {"action": "close", "fence_id": fence_id, "expect": expect or _expect()},
    }


# --------------------------------------------------------------------------- #


async def test_default_session_has_no_fence_capability(auth_client: httpx.AsyncClient) -> None:
    sid = await _session(auth_client)
    resp = await _event(auth_client, sid, _close())
    assert resp.status_code == 409
    assert "capability_unsupported" in resp.text
    assert input_fence.INPUT_FENCE_LABEL not in await _labels(auth_client, sid)


async def test_fence_requires_single_server_declaration(
    auth_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    monkeypatch.delenv(input_fence.SINGLE_SERVER_ENV)
    resp = await _event(auth_client, sid, _close())
    assert resp.status_code == 409
    assert "capability_unsupported" in resp.text
    assert runner.calls == []


async def test_reserved_labels_cannot_be_forged(auth_client: httpx.AsyncClient) -> None:
    sid = await _session(auth_client, _OPT_IN)
    for key in sorted(input_fence.SERVER_RESERVED_LABELS):
        resp = await auth_client.patch(
            f"/v1/sessions/{sid}", json={"labels": {key: "{}"}}, headers=_OWNER
        )
        assert resp.status_code == 400, key


async def test_receipt_persisted_for_owner_and_monotonic(auth_client: httpx.AsyncClient) -> None:
    sid = await _session(auth_client, _OPT_IN)
    status_event = {"type": "external_session_status", "data": {"status": "idle"}}

    resp = await _event(
        auth_client, sid, {**status_event, "data": {"status": "idle", "turn_end": _receipt(rev=2)}}
    )
    assert resp.status_code == 202
    labels = await _labels(auth_client, sid)
    stored = json.loads(labels[input_fence.TURN_RECEIPT_LABEL])
    assert (stored["turn_seq"], stored["rev"], stored["received_seq"]) == (1, 2, 1)
    assert stored["chat_id"] == "chat-1"
    detail = json.loads(labels[input_fence.TURN_RECEIPT_DETAIL_LABEL])
    # A consumer recomputes the digest from its own prompt hash and copy count.
    assert detail["msg_digest"] == input_fence.message_injections_digest(["ab"])
    assert detail["observed_max_acked"] is True

    # An older revision arriving late never replaces a newer one.
    await _event(
        auth_client, sid, {**status_event, "data": {"status": "idle", "turn_end": _receipt(rev=1)}}
    )
    stored = json.loads((await _labels(auth_client, sid))[input_fence.TURN_RECEIPT_LABEL])
    assert stored["rev"] == 2

    # A malformed receipt is dropped but the idle edge is still accepted.
    bad = _receipt(turn_seq=2, rev=1)
    del bad["transcript"]
    resp = await _event(
        auth_client, sid, {**status_event, "data": {"status": "idle", "turn_end": bad}}
    )
    assert resp.status_code == 202
    stored = json.loads((await _labels(auth_client, sid))[input_fence.TURN_RECEIPT_LABEL])
    assert stored["turn_seq"] == 1


async def test_editor_cannot_forge_receipt_or_fence(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    resp = await _grant_permission(
        auth_client, sid, granter="owner", target_user="editor", level=LEVEL_EDIT
    )
    assert resp.status_code == 200
    resp = await _event(
        auth_client,
        sid,
        {"type": "external_session_status", "data": {"status": "idle", "turn_end": _receipt()}},
        headers=_EDITOR,
    )
    assert resp.status_code == 202
    assert input_fence.TURN_RECEIPT_LABEL not in await _labels(auth_client, sid)
    resp = await _event(auth_client, sid, _close(), headers=_EDITOR)
    assert resp.status_code == 403
    assert runner.calls == []


async def test_verified_fence_rejects_every_input_api_and_persists(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    resp = await _event(auth_client, sid, _close())
    assert resp.status_code == 202, resp.text
    fence = resp.json()["fence"]
    assert fence["verified"] is True, fence
    assert fence["state"] == "closed"

    inputs = [
        {
            "type": "message",
            "data": {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
        },
        {"type": "slash_command", "data": {"command": "/compact"}},
        {"type": "compact", "data": {}},
        {"type": "retry_session", "data": {}},
        {"type": "approval", "data": {}},
    ]
    for body in inputs:
        resp = await _event(auth_client, sid, body)
        assert resp.status_code == 409, (body["type"], resp.text)
        assert "input_fenced" in resp.text

    # The pane fence is in place too, and survives a relaunch-style clear.
    status.clear_cursor_status_state(runner.bridge_dir)
    with pytest.raises(status.InputFencedError):
        status.record_injection(runner.bridge_dir, "x", kind="message")

    # A fresh process (server restart) still refuses from the durable label.
    input_fence.reset_for_tests()
    resp = await _event(auth_client, sid, inputs[0])
    assert resp.status_code == 409


async def test_new_input_racing_a_close_is_refused(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    runner.gate = asyncio.Event()
    closing = asyncio.create_task(_event(auth_client, sid, _close()))
    for _ in range(500):
        if runner.calls:
            break
        await asyncio.sleep(0.005)
    assert runner.calls, "close never reached the runner"
    msg = {
        "type": "message",
        "data": {"role": "user", "content": [{"type": "input_text", "text": "race"}]},
    }
    resp = await _event(auth_client, sid, msg)
    assert resp.status_code == 409
    runner.gate.set()
    resp = await closing
    assert resp.json()["fence"]["verified"] is True


async def test_pending_copy_blocks_verification_until_accounted(
    auth_client: httpx.AsyncClient, runner: _Runner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An accepted-but-unmirrored copy keeps the fence unverified; a retry reconciles."""
    monkeypatch.setattr(input_fence, "_DRAIN_TIMEOUT_S", 0.05)
    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    pending_id = pending_inputs.record(sid, [{"type": "input_text", "text": "repost"}])
    resp = await _event(auth_client, sid, _close())
    fence = resp.json()["fence"]
    assert (fence["verified"], fence["reason"]) == (False, "inputs_not_drained")

    pending_inputs.resolve(sid, pending_id)
    resp = await _event(auth_client, sid, _close())
    fence = resp.json()["fence"]
    assert fence["verified"] is True, fence
    assert fence["attempts"] == 2


async def test_injection_after_receipt_fails_verification(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    status.record_injection(runner.bridge_dir, "newer prompt", kind="message")
    resp = await _event(auth_client, sid, _close())
    fence = resp.json()["fence"]
    assert fence["verified"] is False
    assert fence["reason"] == "mismatch_inject_count"
    # Retrying with the same expect cannot launder the mismatch.
    resp = await _event(auth_client, sid, _close())
    assert resp.json()["fence"]["verified"] is False
    # Nor can a retry quietly change what it expects.
    changed = {**_expect(), "inject_count": 2, "turn_end_count": 1}
    resp = await _event(auth_client, sid, _close(expect=changed))
    assert resp.status_code == 409
    assert "fence_expect_changed" in resp.text


async def test_crash_mid_close_reconciles_on_retry(
    auth_client: httpx.AsyncClient, runner: _Runner, db_uri: str
) -> None:
    from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    # Simulate a server crash after the durable (atomic, two-label) write but
    # before the runner call.
    SqlAlchemyConversationStore(db_uri).set_labels(
        sid,
        {
            input_fence.INPUT_FENCE_LABEL: json.dumps(
                {"v": 1, "state": "closing", "fence_id": "f1", "attempts": 1, "closed_at": 1}
            ),
            input_fence.INPUT_FENCE_EXPECT_LABEL: json.dumps(_expect()),
        },
    )
    input_fence.reset_for_tests()
    msg = {
        "type": "message",
        "data": {"role": "user", "content": [{"type": "input_text", "text": "x"}]},
    }
    assert (await _event(auth_client, sid, msg)).status_code == 409
    resp = await _event(auth_client, sid, _close())
    fence = resp.json()["fence"]
    assert (fence["state"], fence["verified"], fence["attempts"]) == ("closed", True, 2)


async def test_open_is_runner_first_and_fails_closed(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    await _event(auth_client, sid, _close())
    runner.fail_open = True
    resp = await _event(
        auth_client, sid, {"type": "input_fence", "data": {"action": "open", "fence_id": "f1"}}
    )
    assert resp.status_code == 409
    assert "runner_open_failed" in resp.text
    assert input_fence.INPUT_FENCE_LABEL in await _labels(auth_client, sid)
    with pytest.raises(status.InputFencedError):
        status.record_injection(runner.bridge_dir, "x", kind="message")

    runner.fail_open = False
    resp = await _event(
        auth_client, sid, {"type": "input_fence", "data": {"action": "open", "fence_id": "wrong"}}
    )
    assert resp.status_code == 409
    resp = await _event(
        auth_client, sid, {"type": "input_fence", "data": {"action": "open", "fence_id": "f1"}}
    )
    assert resp.status_code == 202, resp.text
    assert input_fence.INPUT_FENCE_LABEL not in await _labels(auth_client, sid)
    status.record_injection(runner.bridge_dir, "reopened", kind="message")


async def test_different_fence_id_cannot_replace_a_closed_fence(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    await _event(auth_client, sid, _close("f1"))
    resp = await _event(auth_client, sid, _close("f2"))
    assert resp.status_code == 409
    assert "fence_exists" in resp.text


async def test_balanced_counts_with_a_foreign_turn_leave_the_fence_unverified(
    auth_client: httpx.AsyncClient, runner: _Runner
) -> None:
    """A stop that closed some other turn (a hook follow-up) must not close the prompt's."""
    sid = await _session(auth_client, _OPT_IN)
    status.record_injection(runner.bridge_dir, "prompt", kind="message")
    _submitted_row(runner, "Continue: double-check the tests pass.")
    status.record_turn_end(runner.bridge_dir, _STOP)
    resp = await _event(auth_client, sid, _close())
    assert resp.status_code == 202, resp.text
    fence = resp.json()["fence"]
    assert (fence["verified"], fence["reason"]) == (False, "turns_unbound")
    assert fence["runner_ack"]["inject_count"] == fence["runner_ack"]["turn_end_count"] == 1
    assert fence["runner_ack"]["bind_reason"] == "user_rows_mismatch"


@pytest.mark.parametrize(
    ("payload", "bind_reason"),
    [
        ({"status": "completed", "conversation_id": "chat-other"}, "turn_end_foreign"),
        ({"status": "completed"}, "turn_end_unattributed"),
    ],
    ids=["foreign", "missing"],
)
async def test_stop_from_another_or_unknown_chat_leaves_the_fence_unverified(
    auth_client: httpx.AsyncClient, runner: _Runner, payload: dict, bind_reason: str
) -> None:
    """Balanced counts and the prompt's own row, but the stop is not this chat's."""
    sid = await _session(auth_client, _OPT_IN)
    status.record_injection(runner.bridge_dir, "prompt", kind="message")
    _submitted_row(runner, "prompt")
    status.record_turn_end(runner.bridge_dir, payload)
    resp = await _event(auth_client, sid, _close())
    assert resp.status_code == 202, resp.text
    fence = resp.json()["fence"]
    assert (fence["verified"], fence["reason"]) == (False, "turns_unbound")
    assert fence["runner_ack"]["inject_count"] == fence["runner_ack"]["turn_end_count"] == 1
    assert fence["runner_ack"]["bind_reason"] == bind_reason


async def test_receipt_binding_is_stored_in_its_own_label(auth_client: httpx.AsyncClient) -> None:
    sid = await _session(auth_client, _OPT_IN)

    async def _post(receipt: dict[str, Any]) -> dict[str, str]:
        body = {"type": "external_session_status", "data": {"status": "idle", "turn_end": receipt}}
        assert (await _event(auth_client, sid, body)).status_code == 202
        return await _labels(auth_client, sid)

    bound = {"v": 1, "bound": True, "reason": None, "user_rows": 1, "closed_turns": 1}
    labels = await _post(_receipt(rev=1, binding=bound))
    assert json.loads(labels[input_fence.TURN_RECEIPT_BINDING_LABEL]) == {
        "bound": True,
        "reason": None,
        "user_rows": 1,
        "closed_turns": 1,
    }
    # Inconsistent or unknown binding shapes are dropped with the whole receipt.
    for bad in (
        {**bound, "reason": "turn_open"},
        {**bound, "bound": False, "reason": "made_up"},
        {**bound, "user_rows": -1},
    ):
        labels = await _post(_receipt(rev=2, binding=bad))
        assert json.loads(labels[input_fence.TURN_RECEIPT_LABEL])["rev"] == 1
    # A runner that sends no binding stores ``bound: null``, which a consumer holds on.
    labels = await _post(_receipt(rev=3))
    assert json.loads(labels[input_fence.TURN_RECEIPT_BINDING_LABEL])["bound"] is None


async def test_internal_parent_wake_is_refused_while_fenced(
    auth_client: httpx.AsyncClient, runner: _Runner, db_uri: str
) -> None:
    """A server-internal dispatch goes through the same fence as the events route."""
    from omnigent.server.routes._sessions import orchestration
    from omnigent.stores.conversation_store.sqlalchemy_store import SqlAlchemyConversationStore

    sid = await _session(auth_client, _OPT_IN)
    _one_finished_turn(runner)
    resp = await _event(auth_client, sid, _close())
    assert resp.json()["fence"]["verified"] is True
    store = SqlAlchemyConversationStore(db_uri)
    conv = await asyncio.to_thread(store.get_conversation, sid)
    delivered = await orchestration._wake_parent_for_blocked_child(
        sid,
        conv,
        "[System: child blocked on approval]",
        conversation_store=store,
        runner_router=None,
    )
    assert delivered is False
    assert len(status._epoch_records(runner.bridge_dir / status.INJECT_FILE, _EPOCH)) == 1
