"""Opt-in completion receipts and the pane input fence (cursor-native, runner side).

Drives the real hook recorder, injection path, fence handler, and forwarder poll
loop against a temp bridge dir and a cursor-like SQLite store. tmux is faked the
same way as ``test_cursor_native_bridge``.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import threading
from pathlib import Path

import pytest

from omnigent.harnesses.cursor_native import bridge as cursor_native_bridge
from omnigent.harnesses.cursor_native import forwarder as fwd
from omnigent.harnesses.cursor_native import status, usage
from omnigent.harnesses.cursor_native.fence import handle_runner_fence_request
from tests.test_cursor_native_bridge import _SOCK, _TARGET, _install_fake_tmux
from tests.test_cursor_native_forwarder import _assistant, _make_store, _user

_EPOCH = 1_790_000_000_000


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hook(bridge_dir: Path, monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    """Fire the real ``record-usage`` stop hook entrypoint with *payload* on stdin."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    assert usage._cli_record_usage(bridge_dir) == 0


@pytest.fixture()
def pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[list[str]]]:
    bridge_dir = tmp_path / "bridge"
    cursor_native_bridge.write_tmux_target(
        bridge_dir, socket_path=Path(_SOCK), tmux_target=_TARGET
    )
    captured = _install_fake_tmux(monkeypatch, pane_captures=["Add a follow-up"])
    monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)
    return bridge_dir, captured


def _inject(bridge_dir: Path, text: str) -> None:
    cursor_native_bridge.inject_user_message(bridge_dir, content=text)


# --------------------------------------------------------------------------- #
# Default sessions are unchanged.
# --------------------------------------------------------------------------- #


def test_default_session_writes_legacy_marker_and_no_receipt_files(
    pane: tuple[Path, list[list[str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge_dir, captured = pane
    _inject(bridge_dir, "hello")
    _hook(bridge_dir, monkeypatch, {"generation_id": "g1", "status": "completed"})

    lines = (bridge_dir / status.TURN_END_FILE).read_text().splitlines()
    assert len(lines) == 1
    assert set(json.loads(lines[0])) == {"ts", "generation_id"}
    assert not (bridge_dir / status.INJECT_FILE).exists()
    assert not (bridge_dir / "receipt.lock").exists()
    assert status.build_turn_end_receipt(bridge_dir) is None
    assert any("paste-buffer" in cmd for cmd in captured)
    assert handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f"}) == (
        409,
        {"error": "capability_unsupported"},
    )


# --------------------------------------------------------------------------- #
# Receipt binding: sequence + hash, per epoch, message units.
# --------------------------------------------------------------------------- #


def test_receipt_binds_prompt_hash_and_counts(
    pane: tuple[Path, list[list[str]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge_dir, _ = pane
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    _inject(bridge_dir, "role prompt nonce=abc")
    _hook(bridge_dir, monkeypatch, {"generation_id": "g1", "conversation_id": "chat-1"})

    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert receipt["epoch"] == _EPOCH
    assert receipt["turn_seq"] == 1
    assert receipt["turn_end_count"] == 1
    assert receipt["inject_count"] == 1
    assert receipt["inject_count_at_end"] == 1
    assert receipt["injections"] == [
        {"seq": 1, "message_seq": 1, "sha256": _sha("role prompt nonce=abc"), "kind": "message"}
    ]
    # The stop payload carried no status: raw is null, normalized is unknown (not failure).
    assert receipt["stop_status_raw"] is None
    assert receipt["stop_reason"] == "unknown"
    assert receipt["hook_conversation_id"] == "chat-1"


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [("completed", "completed"), ("aborted", "aborted"), ("error", "error"), ("weird", "unknown")],
)
def test_stop_reason_raw_is_preserved(
    pane: tuple[Path, list[list[str]]], monkeypatch: pytest.MonkeyPatch, raw: str, normalized: str
) -> None:
    bridge_dir, _ = pane
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    _inject(bridge_dir, "p")
    _hook(bridge_dir, monkeypatch, {"status": raw})
    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert (receipt["stop_status_raw"], receipt["stop_reason"]) == (raw, normalized)


def test_model_command_is_logged_but_not_counted_as_a_turn(tmp_path: Path) -> None:
    """``inject_count`` and ``inject_count_at_end`` share message-only units."""
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_injection(bridge_dir, "/model gpt-5.2", kind="model_command")
    status.record_injection(bridge_dir, "prompt", kind="message")
    status.record_turn_end(bridge_dir, {})

    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert [(i["seq"], i["message_seq"], i["kind"]) for i in receipt["injections"]] == [
        (1, None, "model_command"),
        (2, 1, "message"),
    ]
    assert receipt["inject_count"] == 1
    assert receipt["inject_count_at_end"] == 1
    assert receipt["turn_end_count"] == receipt["inject_count"]


def test_duplicate_copies_stay_unbalanced_until_each_ends(tmp_path: Path) -> None:
    """Two copies of one prompt need two turn ends; one receipt is not enough."""
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_injection(bridge_dir, "prompt", kind="message")
    status.record_injection(bridge_dir, "prompt", kind="message")  # corrective repost
    status.record_turn_end(bridge_dir, {})

    first = status.build_turn_end_receipt(bridge_dir)
    assert first is not None
    assert (first["inject_count"], first["turn_end_count"]) == (2, 1)
    assert first["inject_count_at_end"] == 2  # both copies pasted before this end

    status.record_turn_end(bridge_dir, {})
    second = status.build_turn_end_receipt(bridge_dir)
    assert second is not None
    assert (second["inject_count"], second["turn_end_count"], second["turn_seq"]) == (2, 2, 2)


def test_relaunch_starts_a_new_epoch_and_ignores_prior_records(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_injection(bridge_dir, "old", kind="message")
    status.record_turn_end(bridge_dir, {})
    # Pre-seeded resume keeps the files but stamps a new epoch.
    status.write_receipt_epoch(bridge_dir, _EPOCH + 1)
    assert status.build_turn_end_receipt(bridge_dir) is None
    status.record_injection(bridge_dir, "new", kind="message")
    status.record_turn_end(bridge_dir, {})
    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert receipt["epoch"] == _EPOCH + 1
    assert (receipt["turn_seq"], receipt["inject_count"]) == (1, 1)
    assert [i["sha256"] for i in receipt["injections"]] == [_sha("new")]


def test_late_foreign_marker_unbalances_instead_of_binding(tmp_path: Path) -> None:
    """A turn end with no matching injection (late hook, typed prompt) is never absorbed."""
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_turn_end(bridge_dir, {})  # arrives before any injection
    status.record_injection(bridge_dir, "prompt", kind="message")
    status.record_turn_end(bridge_dir, {})
    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert receipt["turn_end_count"] == 2
    assert receipt["inject_count"] == 1


def test_reordered_marker_timestamps_do_not_change_sequence(tmp_path: Path) -> None:
    """Sequence comes from lock order, never from ``ts``."""
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_injection(bridge_dir, "a", kind="message")
    status.record_turn_end(bridge_dir, {})
    status.record_injection(bridge_dir, "b", kind="message")
    status.record_turn_end(bridge_dir, {})
    path = bridge_dir / status.TURN_END_FILE
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    lines[0]["ts"], lines[1]["ts"] = lines[1]["ts"] + 100, lines[0]["ts"]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert (receipt["turn_seq"], receipt["inject_count_at_end"]) == (2, 2)


def test_truncated_injection_list_is_flagged(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    for i in range(status.MAX_RECEIPT_INJECTIONS + 1):
        status.record_injection(bridge_dir, f"p{i}", kind="message")
    status.record_turn_end(bridge_dir, {})
    receipt = status.build_turn_end_receipt(bridge_dir)
    assert receipt is not None
    assert receipt["injections_truncated"] is True
    assert len(receipt["injections"]) == status.MAX_RECEIPT_INJECTIONS


# --------------------------------------------------------------------------- #
# Pane fence.
# --------------------------------------------------------------------------- #


def test_fenced_pane_refuses_injection_before_touching_tmux(
    pane: tuple[Path, list[list[str]]],
) -> None:
    bridge_dir, captured = pane
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    code, body = handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f1"})
    assert code == 200
    assert body["same_fence"] is True
    captured.clear()

    with pytest.raises(status.InputFencedError):
        _inject(bridge_dir, "late queued copy")
    assert not any("paste-buffer" in cmd or "load-buffer" in cmd for cmd in captured)
    receipt_injects = (bridge_dir / status.INJECT_FILE).exists()
    assert not receipt_injects


def test_fenced_pane_refuses_model_command(pane: tuple[Path, list[list[str]]]) -> None:
    bridge_dir, captured = pane
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f1"})
    captured.clear()
    with pytest.raises(status.InputFencedError):
        cursor_native_bridge.inject_model_command(
            bridge_dir, model="gpt-5.2", expected_display_name="GPT-5.2"
        )
    assert not any("send-keys" in cmd and "-l" in cmd for cmd in captured)


def test_fence_survives_relaunch_clear_and_new_epoch(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f1"})
    status.clear_cursor_status_state(bridge_dir)
    fwd.clear_receipt_forwarder_state(bridge_dir)
    status.write_receipt_epoch(bridge_dir, _EPOCH + 1)
    with pytest.raises(status.InputFencedError):
        status.record_injection(bridge_dir, "after relaunch", kind="message")
    # Even with receipts turned off, the fence still refuses.
    status.clear_receipt_epoch(bridge_dir)
    with pytest.raises(status.InputFencedError):
        status.record_injection(bridge_dir, "after opt-out", kind="message")


def test_fence_close_is_idempotent_and_open_requires_matching_id(tmp_path: Path) -> None:
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_injection(bridge_dir, "p", kind="message")
    status.record_turn_end(bridge_dir, {})
    code, _first = handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f1"})
    code2, again = handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f1"})
    assert (code, code2) == (200, 200)
    assert again["already_closed"] is True and again["same_fence"] is True
    assert (again["inject_count"], again["turn_end_count"]) == (1, 1)
    _, foreign = handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f2"})
    assert foreign["same_fence"] is False
    assert handle_runner_fence_request(bridge_dir, {"action": "open", "fence_id": "f2"})[0] == 409
    assert handle_runner_fence_request(bridge_dir, {"action": "open", "fence_id": "f1"})[0] == 200
    status.record_injection(bridge_dir, "reopened", kind="message")
    # Re-opening an already-open pane is a success (retry-safe).
    assert handle_runner_fence_request(bridge_dir, {"action": "open", "fence_id": "f1"})[0] == 200


def test_fence_close_linearizes_against_concurrent_injections(tmp_path: Path) -> None:
    """Every injection is either counted by the close or refused after it."""
    bridge_dir = tmp_path / "bridge"
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    admitted: list[int] = []
    refused: list[int] = []
    start = threading.Barrier(9)

    def writer(n: int) -> None:
        start.wait()
        for i in range(25):
            try:
                status.record_injection(bridge_dir, f"{n}-{i}", kind="message")
                admitted.append(1)
            except status.InputFencedError:
                refused.append(1)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    start.wait()
    code, result = handle_runner_fence_request(bridge_dir, {"action": "close", "fence_id": "f"})
    for thread in threads:
        thread.join()
    assert code == 200
    assert result["inject_count"] == len(admitted)
    assert len(admitted) + len(refused) == 200
    records = (bridge_dir / status.INJECT_FILE).read_text().splitlines()
    assert len(records) == len(admitted)
    assert [json.loads(r)["seq"] for r in records] == list(range(1, len(admitted) + 1))


# --------------------------------------------------------------------------- #
# Forwarder: receipt transport, ACK watermark, delayed append.
# --------------------------------------------------------------------------- #


class _StatusRecorder:
    def __init__(self) -> None:
        self.posts: list[dict | None] = []

    async def __call__(
        self, client: object, *, session_id: str, status: str, turn_end: dict | None = None
    ) -> None:
        assert status == "idle"
        self.posts.append(turn_end)


async def _run_forwarder(
    monkeypatch: pytest.MonkeyPatch,
    bridge_dir: Path,
    store: Path,
    *,
    fail_item=lambda item: None,
    until,
    between=None,
) -> _StatusRecorder:
    recorder = _StatusRecorder()

    async def _post_item(client: object, *, session_id: str, item: fwd._MirrorItem) -> None:
        exc = fail_item(item)
        if exc is not None:
            raise exc

    monkeypatch.setattr(fwd, "_discover_store", lambda workspace, launch_ms: store)
    monkeypatch.setattr(fwd, "_chat_claimed_by_other", lambda *a, **k: False)
    monkeypatch.setattr(fwd, "_post_conversation_item", _post_item)
    monkeypatch.setattr(fwd, "_post_external_session_status", recorder)

    async def _noop(*a: object, **k: object) -> None:
        return None

    monkeypatch.setattr(fwd, "_patch_external_session_id", _noop)
    monkeypatch.setattr(fwd, "_post_model_change_if_new", _noop)
    task = asyncio.create_task(
        fwd.forward_cursor_store_to_session(
            base_url="http://test",
            headers={},
            session_id="conv_1",
            bridge_dir=bridge_dir,
            agent_name="cursor-native-ui",
            workspace="/ws",
            launch_epoch_ms=1_000,
            poll_interval_s=0.001,
        )
    )
    try:
        phases = [until] if between is None else [between[0], until]
        for index, cond in enumerate(phases):
            for _ in range(3000):
                if cond(recorder):
                    break
                await asyncio.sleep(0.001)
            else:
                raise AssertionError(f"forwarder never reached phase {index}")
            if between is not None and index == 0:
                between[1]()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return recorder


def _opted_in_store(tmp_path: Path) -> tuple[Path, Path, object]:
    bridge_dir = tmp_path / "bridge"
    store_dir = tmp_path / "chats" / "chat-abc"
    store_dir.mkdir(parents=True)
    store = store_dir / "store.db"
    writer = _make_store(
        store,
        [
            ("u1", _user("<user_query>\nprompt\n</user_query>")),
            ("a1", _assistant([{"type": "text", "text": "partial answer"}])),
        ],
    )
    status.write_receipt_epoch(bridge_dir, _EPOCH)
    status.record_injection(bridge_dir, "prompt", kind="message")
    status.record_turn_end(bridge_dir, {"status": "completed"})
    return bridge_dir, store, writer


@pytest.mark.asyncio
async def test_forwarder_posts_receipt_with_acked_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge_dir, store, writer = _opted_in_store(tmp_path)
    writer.close()
    recorder = await _run_forwarder(monkeypatch, bridge_dir, store, until=lambda r: bool(r.posts))
    receipt = recorder.posts[0]
    assert receipt is not None
    assert receipt["chat_id"] == "chat-abc"
    assert receipt["rev"] == 1
    assert receipt["transcript"] == {
        "store_max_rowid": 2,
        "acked_through_rowid": 2,
        "unacked_rowids": [],
        "observed_max_acked": True,
    }


@pytest.mark.asyncio
async def test_delayed_final_append_flips_ack_and_reposts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stop hook fired before the last blob landed: rev 1 is later superseded."""
    bridge_dir, store, writer = _opted_in_store(tmp_path)

    def _append_late_blob() -> None:
        writer.execute(
            "INSERT INTO blobs(id, data) VALUES(?, ?)",
            ("a2", json.dumps(_assistant([{"type": "text", "text": "final"}])).encode()),
        )
        writer.commit()

    recorder = await _run_forwarder(
        monkeypatch,
        bridge_dir,
        store,
        between=(lambda r: len(r.posts) >= 1, _append_late_blob),
        until=lambda r: (
            len(r.posts) >= 2
            and r.posts[-1]["transcript"]["store_max_rowid"] == 3
            and r.posts[-1]["transcript"]["observed_max_acked"]
        ),
    )
    writer.close()
    first, last = recorder.posts[0], recorder.posts[-1]
    assert first["transcript"]["store_max_rowid"] == 2
    assert (first["turn_seq"], last["turn_seq"]) == (1, 1)
    assert last["rev"] > first["rev"]
    assert last["transcript"]["acked_through_rowid"] == 3


@pytest.mark.asyncio
async def test_skipped_item_is_never_reported_acked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ambiguous POST advances ``last_rowid`` but must stay unacked in the receipt."""
    import httpx

    bridge_dir, store, writer = _opted_in_store(tmp_path)
    writer.close()
    req = httpx.Request("POST", "http://test/v1/sessions/conv_1/events")

    def _fail(item: fwd._MirrorItem) -> Exception | None:
        return httpx.ReadTimeout("lost", request=req) if item.rowid == 2 else None

    recorder = await _run_forwarder(
        monkeypatch, bridge_dir, store, fail_item=_fail, until=lambda r: bool(r.posts)
    )
    transcript = recorder.posts[0]["transcript"]
    assert transcript["unacked_rowids"] == [2]
    assert transcript["observed_max_acked"] is False
    assert fwd._read_state(bridge_dir).last_rowid == 2  # the mirror cursor moved on anyway


@pytest.mark.asyncio
async def test_no_receipt_repost_while_a_newer_injection_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge_dir, store, writer = _opted_in_store(tmp_path)

    def _new_turn_starts() -> None:
        status.record_injection(bridge_dir, "next prompt", kind="message")
        writer.execute(
            "INSERT INTO blobs(id, data) VALUES(?, ?)",
            ("u2", json.dumps(_user("<user_query>\nnext prompt\n</user_query>")).encode()),
        )
        writer.commit()

    recorder = await _run_forwarder(
        monkeypatch,
        bridge_dir,
        store,
        between=(lambda r: len(r.posts) >= 1, _new_turn_starts),
        until=lambda r: fwd._read_state(bridge_dir).last_rowid == 3,
    )
    writer.close()
    assert len(recorder.posts) == 1, "an idle re-post during a running turn would be false"


@pytest.mark.asyncio
async def test_default_session_idle_post_carries_no_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bridge_dir = tmp_path / "bridge"
    store_dir = tmp_path / "chats" / "chat-abc"
    store_dir.mkdir(parents=True)
    store = store_dir / "store.db"
    _make_store(store, [("u1", _user("<user_query>\nhi\n</user_query>"))]).close()
    status.record_turn_end(bridge_dir, {})
    recorder = await _run_forwarder(monkeypatch, bridge_dir, store, until=lambda r: bool(r.posts))
    assert recorder.posts == [None]
    assert not (bridge_dir / fwd.RECEIPT_STATE_FILE).exists()
