"""End-to-end completion receipts, turn binding and the input fence (cursor-native).

Real: the auth-enabled server app with SQL stores and the events route, the
cursor-native forwarder over ASGI with store discovery under a private HOME,
``CursorNativeExecutor`` pasting into a real tmux pane, the real stop-hook CLI,
and the runner fence handler on the same bridge dir. Substituted: the
cursor-agent TUI (``cursor_fake_tui.py``), the runner app's route wrapper, and
HTTP faults on the forwarder→server hop.

Each false-completion scenario first satisfies the rev2 consumer rules (counts
only) and then shows the fence refusing to verify; the rev3 rule (binding) never
passes on them. The controls show the valid paths still verify.
"""

# ruff: noqa: F811
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from omnigent.harnesses.cursor_native import bridge as cbridge
from omnigent.harnesses.cursor_native import forwarder as fwd
from omnigent.harnesses.cursor_native import status
from omnigent.harnesses.cursor_native.fence import handle_runner_fence_request
from omnigent.inner.cursor_native_executor import CursorNativeExecutor
from omnigent.runtime import pending_inputs
from omnigent.server.routes import sessions as sessions_module
from omnigent.server.routes._sessions import input_fence
from tests.server.helpers import create_test_agent
from tests.server.integration.test_sessions_permissions import (  # noqa: F401 - fixtures
    _create_session_as,
    auth_app,
    auth_client,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux"),
]

_OWNER = {"X-Forwarded-Email": "owner"}
_FAKE_TUI = Path(__file__).with_name("cursor_fake_tui.py")
_FOLLOWUP = "Continue: double-check the tests pass."


def _dump(name: str, record: dict[str, Any]) -> None:
    """Keep a scenario's real server labels for a consumer check (opt-in by env)."""
    out = os.environ.get("OMNIGENT_RECEIPT_E2E_EVIDENCE")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, indent=2, default=lambda o: sorted(o, key=str))
        (Path(out) / f"{name}.json").write_text(text)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _RunnerSide:
    """Server→runner transport: ``input_fence`` reaches the real runner handler."""

    def __init__(self, bridge_dir: Path) -> None:
        self.bridge_dir = bridge_dir

    async def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if isinstance(body, dict) and body.get("type") == "input_fence":
            code, payload = await asyncio.to_thread(
                handle_runner_fence_request, self.bridge_dir, body["data"]
            )
            return httpx.Response(code, json=payload)
        return httpx.Response(200, json={})


class _Faults:
    def __init__(self) -> None:
        self.lost: set[str] = set()  # ReadTimeout without delivering
        self.hang: set[str] = set()  # block until cancelled
        self.hang_entered = asyncio.Event()


class _FaultyTransport(httpx.AsyncBaseTransport):
    def __init__(self, app: Any, faults: _Faults) -> None:
        self._inner = httpx.ASGITransport(app=app)
        self._faults = faults

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        text = ""
        body = json.loads(request.content or b"{}")
        if isinstance(body, dict) and body.get("type") == "external_conversation_item":
            parts = body["data"].get("item_data", {}).get("content") or []
            text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
        if text and any(k in text for k in self._faults.lost):
            raise httpx.ReadTimeout("response lost", request=request)
        if text and any(k in text for k in self._faults.hang):
            self._faults.hang_entered.set()
            await asyncio.Event().wait()
        return await self._inner.handle_async_request(request)


def _route_forwarder_to(monkeypatch: pytest.MonkeyPatch, app: Any, faults: _Faults) -> None:
    real = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = _FaultyTransport(app, faults)
        return real(*args, **kwargs)

    shim = types.SimpleNamespace(
        **{k: getattr(httpx, k) for k in dir(httpx) if not k.startswith("__")}
    )
    shim.AsyncClient = factory
    monkeypatch.setattr(fwd, "httpx", shim)


def _route_runner_to(monkeypatch: pytest.MonkeyPatch, bridge_dir: Path) -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(_RunnerSide(bridge_dir).handle), base_url="http://runner"
    )

    async def _get(*_a: object, **_k: object) -> httpx.AsyncClient:
        return client

    monkeypatch.setattr(sessions_module, "_get_runner_client", _get)


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(input_fence.SINGLE_SERVER_ENV, "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    # System hooks.json paths are host state; the unit tests cover them explicitly.
    monkeypatch.setattr(cbridge, "_SYSTEM_HOOKS_PATHS", (), raising=False)
    input_fence.reset_for_tests()
    pending_inputs.reset_for_tests()


async def _opted_in_session(client: httpx.AsyncClient) -> str:
    agent = await create_test_agent(client, user="owner")
    snap = await _create_session_as(client, agent["id"], "owner")
    resp = await client.patch(
        f"/v1/sessions/{snap['id']}",
        json={"labels": {input_fence.COMPLETION_RECEIPTS_LABEL: "v1"}},
        headers=_OWNER,
    )
    assert resp.status_code == 200, resp.text
    return snap["id"]


async def _snapshot(client: httpx.AsyncClient, sid: str) -> dict[str, Any]:
    resp = await client.get(f"/v1/sessions/{sid}", headers=_OWNER)
    assert resp.status_code == 200, resp.text
    return resp.json()


def consumer(snap: dict[str, Any], epoch: int, sent: list[str], *, rev: int) -> tuple[str, dict]:
    """Contract consumer rules R1–R4 (rev2), plus R3b binding for ``rev=3``."""
    labels = snap.get("labels") or {}
    if input_fence.TURN_RECEIPT_LABEL not in labels:
        return "no_receipt", {}
    core = json.loads(labels[input_fence.TURN_RECEIPT_LABEL])
    detail = json.loads(labels[input_fence.TURN_RECEIPT_DETAIL_LABEL])
    binding = json.loads(labels.get(input_fence.TURN_RECEIPT_BINDING_LABEL) or "{}")
    ctx = {"core": core, "detail": detail, "binding": binding}
    if core.get("chat_id") is None or snap.get("external_session_id") != core["chat_id"]:
        return "R1_identity", ctx
    if core["epoch"] != epoch:
        return "R1_epoch", ctx
    if detail["truncated"] or not (detail["msg_listed"] == core["inject_count"] == len(sent)):
        return "R2_count", ctx
    if detail["msg_digest"] != input_fence.message_injections_digest(sent):
        return "R2_digest", ctx
    if not (core["turn_end_count"] == core["inject_count"] == core["inject_count_at_end"]):
        return "R3_unbalanced", ctx
    if rev >= 3 and not (
        binding.get("bound") is True
        and binding.get("user_rows") == binding.get("closed_turns") == core["inject_count"]
    ):
        return "R3b_unbound", ctx
    if detail["observed_max_acked"] is not True:
        return "R4_unacked", ctx
    return "ok", ctx


async def _wait(cond: Callable[[], Awaitable[Any]], timeout: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await cond()
        if value:
            return value
        await asyncio.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def _tui_events(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


class _Pane:
    """The fake cursor TUI in a real tmux server on a private socket."""

    def __init__(self, tmp_path: Path, bridge_dir: Path, ws: Path, cfg: dict) -> None:
        self._sock_dir = Path(tempfile.mkdtemp(prefix="omg-tmux-"))
        self.sock = self._sock_dir / "s.sock"
        self.log = tmp_path / "tui.jsonl"
        cfg_path = tmp_path / "tui.json"
        cfg_path.write_text(json.dumps(cfg))
        chats = Path(os.environ["HOME"]) / ".cursor" / "chats"
        cmd = " ".join(
            [
                sys.executable,
                str(_FAKE_TUI),
                "--bridge-dir",
                str(bridge_dir),
                "--workspace",
                str(ws),
                "--chats",
                str(chats),
                "--chat-id",
                "chat-" + uuid.uuid4().hex[:12],
                "--cfg",
                str(cfg_path),
                "--log",
                str(self.log),
            ]
        )
        subprocess.run(
            [
                "tmux",
                "-S",
                str(self.sock),
                "-f",
                "/dev/null",
                "new-session",
                "-d",
                "-s",
                "cur",
                "-x",
                "200",
                "-y",
                "50",
                cmd,
            ],
            check=True,
            env={**os.environ},
        )
        cbridge.write_tmux_target(bridge_dir, socket_path=self.sock, tmux_target="cur")

    def type_line(self, text: str) -> None:
        """A local user typing straight into the pane (not through Omnigent)."""
        subprocess.run(
            ["tmux", "-S", str(self.sock), "send-keys", "-t", "cur", "-l", text], check=True
        )
        subprocess.run(
            ["tmux", "-S", str(self.sock), "send-keys", "-t", "cur", "Enter"], check=True
        )

    def events(self) -> list[dict[str, Any]]:
        return _tui_events(self.log)

    def close(self) -> None:
        subprocess.run(["tmux", "-S", str(self.sock), "kill-server"], check=False)
        shutil.rmtree(self._sock_dir, ignore_errors=True)


async def _fence_close(client: httpx.AsyncClient, sid: str, core: dict) -> dict[str, Any]:
    expect = {
        k: core[k] for k in ("epoch", "turn_seq", "inject_count", "turn_end_count", "chat_id")
    }
    resp = await client.post(
        f"/v1/sessions/{sid}/events",
        json={
            "type": "input_fence",
            "data": {"action": "close", "fence_id": uuid.uuid4().hex, "expect": expect},
        },
        headers=_OWNER,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["fence"]


async def _scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    client: httpx.AsyncClient,
    *,
    cfg: dict,
    during_turn_1: Callable[[CursorNativeExecutor, _Pane, str, list[str]], Awaitable[None]],
    fence_on: int,
    setup_hooks: Callable[[Path], None] | None = None,
    hold_until_stops: int | None = None,
) -> dict[str, Any]:
    """Dispatch one prompt, act during turn 1, then fence when the rev-*fence_on* rules pass.

    With *hold_until_stops*, the launch is expected to be held by the hook gate:
    poll as a rev3 consumer until that many turn ends, fencing only if the
    consumer passes, then probe the fence once.
    """
    sid = await _opted_in_session(client)
    bridge_dir = cbridge.bridge_dir_for_session_id(sid)
    ws = tmp_path / "ws"
    ws.mkdir()
    if setup_hooks is not None:
        setup_hooks(ws)
    launch_ms = int(time.time() * 1000) - 1000
    # The runner's launch steps for an opted-in session, in its order.
    status.clear_cursor_status_state(bridge_dir)
    fwd.clear_receipt_forwarder_state(bridge_dir)
    precheck = cbridge.prepare_completion_receipts(bridge_dir, ws, opted_in=True)
    cbridge.write_hooks_config(ws, bridge_dir, python_executable=_hook_python(tmp_path))
    hold_reason = cbridge.arm_completion_receipts(
        bridge_dir, ws, launch_ms, opted_in=True, precheck=precheck
    )
    _route_runner_to(monkeypatch, bridge_dir)
    _route_forwarder_to(monkeypatch, app, _Faults())
    pane = _Pane(tmp_path, bridge_dir, ws, {"turn_s": 1.0, **cfg})
    fwd_task = asyncio.create_task(
        fwd.forward_cursor_store_to_session(
            base_url="http://srv",
            headers=_OWNER,
            session_id=sid,
            bridge_dir=bridge_dir,
            agent_name="cursor-native-ui",
            workspace=str(ws),
            launch_epoch_ms=launch_ms,
            poll_interval_s=0.05,
        )
    )
    executor = CursorNativeExecutor(bridge_dir)
    prompt = f"TASK nonce={uuid.uuid4().hex} implement slice S and run tests"
    sent: list[str] = []
    record: dict[str, Any] = {
        "passed_rev3_before_fence": [],
        "hold_reason": hold_reason,
        "bridge_dir": str(bridge_dir),
    }
    try:
        async for _ev in executor.run_turn([{"role": "user", "content": prompt}], [], ""):
            pass
        sent.append(_sha(prompt))

        async def _turn_1_started() -> bool:
            return any(e["ev"] == "turn_start" for e in pane.events())

        await _wait(_turn_1_started, 20, "turn 1 start")
        await during_turn_1(executor, pane, prompt, sent)
        if hold_until_stops is not None:
            await _held(client, sid, pane, launch_ms, sent, record, hold_until_stops)
            return record

        async def _consumer_pass() -> tuple[dict, dict] | None:
            snap = await _snapshot(client, sid)
            why3, ctx = consumer(snap, launch_ms, sent, rev=3)
            if why3 == "ok":
                record["passed_rev3_before_fence"].append(ctx["binding"])
            why, ctx = consumer(snap, launch_ms, sent, rev=fence_on)
            record.setdefault("binding_reasons", set()).add(ctx.get("binding", {}).get("reason"))
            return (snap, ctx) if why == "ok" else None

        snap, ctx = await _wait(_consumer_pass, 40, f"rev{fence_on} consumer pass")
        record["sent_prompt_shas"] = list(sent)
        record["epoch"] = launch_ms
        record["snapshot_at_pass"] = {
            k: snap.get(k) for k in ("id", "runner_id", "external_session_id", "labels")
        }
        record["t_fence"] = time.time()
        record["fence"] = await _fence_close(client, sid, ctx["core"])
        record["expect_turn_end_count"] = ctx["core"]["turn_end_count"]
        await asyncio.sleep(6.0)  # let the pane run whatever it still holds
        events = pane.events()
        record["turns_ending_after_fence"] = [
            e for e in events if e["ev"] == "stop_hook" and e["t"] > record["t_fence"]
        ]
        final = await _snapshot(client, sid)
        record["final_core"] = json.loads(final["labels"][input_fence.TURN_RECEIPT_LABEL])
        record["final_labels"] = final["labels"]
        record["tui_events"] = events
        return record
    finally:
        fwd_task.cancel()
        await asyncio.gather(fwd_task, return_exceptions=True)
        pane.close()


def _hook_python(tmp_path: Path) -> str:
    """A ``python`` for the generated hook command that works in the test sandbox.

    The real command runs ``<python> -I -m …``; ``-I`` would ignore the
    PYTHONPATH that points the sandbox at the tree under test, so this wrapper
    drops it. The hook command keeps its canonical, owned shape.
    """
    wrapper = tmp_path / "pybin" / "python"
    if not wrapper.exists():
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(
            '#!/bin/sh\n[ "$1" = "-I" ] && shift\nexec ' + shlex.quote(sys.executable) + ' "$@"\n'
        )
        wrapper.chmod(0o755)
    return str(wrapper)


async def _held(
    client: httpx.AsyncClient,
    sid: str,
    pane: _Pane,
    launch_ms: int,
    sent: list[str],
    record: dict[str, Any],
    stops: int,
) -> None:
    """Act as a rev3 consumer until *stops* turn ends, then probe the fence."""
    record["receipt_seen"] = False

    async def _poll() -> bool:
        snap = await _snapshot(client, sid)
        if input_fence.TURN_RECEIPT_LABEL in (snap.get("labels") or {}):
            record["receipt_seen"] = True
        if "fence" not in record:
            why, ctx = consumer(snap, launch_ms, sent, rev=3)
            if why == "ok":
                record["passed_rev3_before_fence"].append(ctx["binding"])
                record["t_fence"] = time.time()
                record["fence"] = await _fence_close(client, sid, ctx["core"])
        return sum(e["ev"] == "stop_hook" for e in pane.events()) >= stops

    await _wait(_poll, 40, f"{stops} turn ends")
    await asyncio.sleep(2.0)  # give the forwarder time to post anything it would
    await _poll()
    events = pane.events()
    record["tui_events"] = events
    if "t_fence" in record:
        record["turns_ending_after_fence"] = [
            e for e in events if e["ev"] == "stop_hook" and e["t"] > record["t_fence"]
        ]
    resp = await client.post(
        f"/v1/sessions/{sid}/events",
        json={
            "type": "input_fence",
            "data": {
                "action": "close",
                "fence_id": uuid.uuid4().hex,
                "expect": {
                    "epoch": launch_ms,
                    "turn_seq": stops,
                    "inject_count": len(sent),
                    "turn_end_count": stops,
                    "chat_id": "probe",
                },
            },
        },
        headers=_OWNER,
    )
    record["fence_probe"] = {"status": resp.status_code, "body": resp.json()}
    record["final_labels"] = (await _snapshot(client, sid)).get("labels")


async def _repost(executor: CursorNativeExecutor, prompt: str, sent: list[str]) -> None:
    assert await executor.enqueue_session_message("k", prompt)
    sent.append(_sha(prompt))


async def test_followup_turn_plus_queued_repost_never_verifies(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stop-hook follow-up turn balances the counts while the repost is still queued."""

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={
            "turn_s_by_prefix": {"TASK": 2.5},
            "followup_after_turns": [1],
            "followup_text": _FOLLOWUP,
        },
        during_turn_1=_act,
        fence_on=2,
    )
    _dump("followup_turn_plus_queued_repost_never_verifies", rec)
    assert rec["passed_rev3_before_fence"] == []
    assert (rec["fence"]["verified"], rec["fence"]["reason"]) == (False, "turns_unbound")
    assert rec["fence"]["runner_ack"]["bind_reason"] == "user_rows_mismatch"
    # The queued repost really was still pending: it ends after the fence.
    assert rec["turns_ending_after_fence"]


async def test_duplicate_stop_plus_queued_repost_never_verifies(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hypothetical cursor behaviour: two stops for one turn, no extra user row."""

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"turn_s_by_prefix": {"TASK": 2.5}, "double_stop_turns": [1]},
        during_turn_1=_act,
        fence_on=2,
    )
    _dump("duplicate_stop_plus_queued_repost_never_verifies", rec)
    assert rec["passed_rev3_before_fence"] == []
    assert (rec["fence"]["verified"], rec["fence"]["reason"]) == (False, "turns_unbound")
    assert rec["fence"]["runner_ack"]["bind_reason"] in {
        "user_rows_mismatch",
        "duplicate_turn_end",
    }
    assert rec["turns_ending_after_fence"]


async def test_typed_turn_plus_queued_repost_never_verifies(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A turn typed straight into the pane balances the counts with a queued API copy."""

    async def _act(executor, pane, prompt, sent) -> None:
        pane.type_line("typed by a local user")

        async def _typed_queued() -> bool:
            return any(e["ev"] == "submit" and e["origin"] == "pane" for e in pane.events())

        await _wait(_typed_queued, 10, "typed submit")
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"turn_s_by_prefix": {"TASK": 2.5}},
        during_turn_1=_act,
        fence_on=2,
    )
    _dump("typed_turn_plus_queued_repost_never_verifies", rec)
    assert rec["passed_rev3_before_fence"] == []
    assert (rec["fence"]["verified"], rec["fence"]["reason"]) == (False, "turns_unbound")
    assert rec["turns_ending_after_fence"]


async def test_queued_repost_verifies_only_after_both_copies_end(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"turn_s_by_prefix": {"TASK": 2.5}},
        during_turn_1=_act,
        fence_on=3,
    )
    _dump("queued_repost_verifies_only_after_both_copies_end", rec)
    assert (rec["fence"]["verified"], rec["fence"]["reason"]) == (True, None), rec["fence"]
    assert rec["turns_ending_after_fence"] == []
    assert rec["final_core"]["turn_end_count"] == rec["expect_turn_end_count"] == 2


async def test_single_late_turn_verifies_once_it_ends(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The supported v1 path: one dispatch, polled while it runs, fenced after it ends."""

    async def _act(executor, pane, prompt, sent) -> None:
        return None

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"turn_s_by_prefix": {"TASK": 4.0}},
        during_turn_1=_act,
        fence_on=3,
    )
    _dump("single_late_turn_verifies_once_it_ends", rec)
    assert (rec["fence"]["verified"], rec["fence"]["reason"]) == (True, None), rec["fence"]
    assert rec["fence"]["runner_ack"]["bound"] is True
    assert rec["turns_ending_after_fence"] == []
    assert rec["final_core"]["turn_end_count"] == rec["expect_turn_end_count"] == 1


# --------------------------------------------------------------------------- #
# ACK watermark across a forwarder restart in the middle of a pass.
# --------------------------------------------------------------------------- #


def _blob(role: str, text: str) -> dict:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _store_with(ws: str, rows: list[dict]) -> None:
    chat_dir = (
        Path(os.environ["HOME"])
        / ".cursor"
        / "chats"
        / hashlib.md5(ws.encode()).hexdigest()
        / "chat-b"
    )
    chat_dir.mkdir(parents=True)
    (chat_dir / "meta.json").write_text(json.dumps({"createdAtMs": int(time.time() * 1000)}))
    with sqlite3.connect(chat_dir / "store.db") as con:
        con.execute("CREATE TABLE blobs(id TEXT PRIMARY KEY, data BLOB)")
        for i, row in enumerate(rows):
            con.execute("INSERT INTO blobs VALUES(?, ?)", (f"b{i}", json.dumps(row).encode()))


async def _ack_scenario(tmp_path, monkeypatch, app, client, *, restart: bool) -> dict[str, Any]:
    sid = await _opted_in_session(client)
    bridge_dir = cbridge.bridge_dir_for_session_id(sid)
    ws = str(tmp_path / "ws")
    launch_ms = int(time.time() * 1000) - 1000
    status.write_receipt_epoch(bridge_dir, launch_ms)
    prompt = "TASK nonce=b"
    status.record_injection(bridge_dir, prompt, kind="message")
    _store_with(
        ws,
        [
            _blob("user", f"<user_query>\n{prompt}\n</user_query>"),
            _blob("assistant", "ALPHA intermediate result"),
            _blob("assistant", "OMEGA final answer"),
        ],
    )
    status.record_turn_end(bridge_dir, {"status": "completed"})
    faults = _Faults()
    faults.lost.add("ALPHA")
    if restart:
        faults.hang.add("OMEGA")
    _route_forwarder_to(monkeypatch, app, faults)

    def _run() -> asyncio.Task:
        return asyncio.create_task(
            fwd.forward_cursor_store_to_session(
                base_url="http://srv",
                headers=_OWNER,
                session_id=sid,
                bridge_dir=bridge_dir,
                agent_name="cursor-native-ui",
                workspace=ws,
                launch_epoch_ms=launch_ms,
                poll_interval_s=0.05,
            )
        )

    task = _run()
    if restart:
        await asyncio.wait_for(faults.hang_entered.wait(), 20)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        faults.hang.clear()
        task = _run()
    try:

        async def _detail() -> dict | None:
            snap = await _snapshot(client, sid)
            raw = (snap.get("labels") or {}).get(input_fence.TURN_RECEIPT_DETAIL_LABEL)
            detail = json.loads(raw) if raw else None
            return (
                detail
                if detail and detail["store_max"] == 3 and detail["acked_through"] >= 2
                else None
            )

        await _wait(_detail, 30, "receipt detail")
        await asyncio.sleep(0.5)
        snap = await _snapshot(client, sid)
        items = await client.get(f"/v1/sessions/{sid}/items", headers=_OWNER)
        why, ctx = consumer(snap, launch_ms, [_sha(prompt)], rev=2)
        return {
            "detail": ctx["detail"],
            "consumer": why,
            "server_has_alpha": "ALPHA" in items.text,
            "labels": snap.get("labels"),
        }
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_restart_mid_pass_keeps_the_lost_row_unacked(
    auth_app, auth_client, tmp_path, monkeypatch
) -> None:
    rec = await _ack_scenario(tmp_path, monkeypatch, auth_app, auth_client, restart=True)
    _dump("restart_mid_pass_keeps_the_lost_row_unacked", rec)
    assert rec["server_has_alpha"] is False
    assert (rec["detail"]["observed_max_acked"], rec["detail"]["unacked"]) == (False, 1)
    assert rec["consumer"] == "R4_unacked"


async def test_lost_row_without_restart_stays_unacked(
    auth_app, auth_client, tmp_path, monkeypatch
) -> None:
    rec = await _ack_scenario(tmp_path, monkeypatch, auth_app, auth_client, restart=False)
    _dump("lost_row_without_restart_stays_unacked", rec)
    assert rec["server_has_alpha"] is False
    assert (rec["detail"]["observed_max_acked"], rec["detail"]["unacked"]) == (False, 1)
    assert rec["consumer"] == "R4_unacked"


# --------------------------------------------------------------------------- #
# Launch hook gate: a foreign stop hook disables receipts.
# --------------------------------------------------------------------------- #

#: The follow-up a foreign stop hook asks for at stop 1 is queued
#: BEHIND the queued repost, and its user row lands 2 s into its own turn.
_FOLLOWUP_BEHIND_REPOST_CFG = {
    "hooks_from_config": True,
    "turn_s_by_prefix": {"TASK": 2.5, "Continue": 4.0},
    "followup_front": False,
    "user_row_delay_by_origin": {"stop_hook_followup": 2.0},
}


def _foreign_followup_hook(tmp_path: Path) -> dict[str, Any]:
    """A user's stop hook that answers ``followup_message`` at its first stop only."""
    script = tmp_path / "followup_hook.py"
    script.write_text(
        "import json, pathlib, sys\n"
        "json.load(sys.stdin)\n"
        "n = pathlib.Path(sys.argv[1])\n"
        "seen = int(n.read_text()) if n.exists() else 0\n"
        "n.write_text(str(seen + 1))\n"
        f"print(json.dumps({{'followup_message': {_FOLLOWUP!r}}}) if seen == 0 else '')\n"
    )
    command = " ".join(
        shlex.quote(p) for p in (sys.executable, str(script), str(tmp_path / "followups"))
    )
    return {"version": 1, "hooks": {"stop": [{"command": command}]}}


def _write_hooks(path: Path, cfg: dict[str, Any] | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg if isinstance(cfg, str) else json.dumps(cfg))


def _assert_held(rec: dict[str, Any], reason_prefix: str) -> None:
    assert rec["hold_reason"] is not None and rec["hold_reason"].startswith(reason_prefix)
    # No receipt ever, so no consumer pass and no fence close was attempted …
    assert rec["receipt_seen"] is False
    assert rec["passed_rev3_before_fence"] == []
    assert "fence" not in rec, rec.get("fence")
    # … and even a fence probe never verifies: the runner refuses it as unsupported.
    fence = rec["fence_probe"]["body"]["fence"]
    assert (fence["verified"], fence["reason"]) == (False, "runner_rejected_409"), fence
    assert fence["runner_ack"] == {"error": "capability_unsupported"}
    assert input_fence.TURN_RECEIPT_LABEL not in (rec["final_labels"] or {})


async def test_foreign_project_followup_hook_holds(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project follow-up stop hook disables receipts at launch.

    Without the gate this ordering false-completes: the rev3 consumer passes,
    the fence verifies, and the follow-up turn ends after it.
    """
    hooks = _foreign_followup_hook(tmp_path)

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg=_FOLLOWUP_BEHIND_REPOST_CFG,
        during_turn_1=_act,
        fence_on=3,
        setup_hooks=lambda ws: _write_hooks(ws / ".cursor" / "hooks.json", hooks),
        hold_until_stops=3,
    )
    _dump("foreign_project_followup_hook_holds", rec)
    _assert_held(rec, "foreign_stop_hook:")
    # The ordering really ran: prompt, queued repost, then the follow-up.
    starts = [e["origin"] for e in rec["tui_events"] if e["ev"] == "turn_start"]
    assert starts == ["pane", "pane", "stop_hook_followup"], starts
    # The user's hook was kept and ran next to Omnigent's own.
    ran = {e["command"] for e in rec["tui_events"] if e["ev"] == "config_stop_hook"}
    assert hooks["hooks"]["stop"][0]["command"] in ran
    assert any(cbridge.is_owned_usage_hook_command(c) for c in ran)


async def test_foreign_user_followup_hook_holds(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same ordering with the follow-up hook in the user-level ``~/.cursor/hooks.json``."""
    hooks = _foreign_followup_hook(tmp_path)
    _write_hooks(Path(os.environ["HOME"]) / ".cursor" / "hooks.json", hooks)

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg=_FOLLOWUP_BEHIND_REPOST_CFG,
        during_turn_1=_act,
        fence_on=3,
        hold_until_stops=3,
    )
    _dump("foreign_user_followup_hook_holds", rec)
    _assert_held(rec, "foreign_stop_hook:")
    starts = [e["origin"] for e in rec["tui_events"] if e["ev"] == "turn_start"]
    assert starts == ["pane", "pane", "stop_hook_followup"], starts


async def test_malformed_project_hooks_config_holds(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed project hooks.json fails closed, although the launch rewrites it clean."""

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"hooks_from_config": True, "turn_s_by_prefix": {"TASK": 2.5}},
        during_turn_1=_act,
        fence_on=3,
        setup_hooks=lambda ws: _write_hooks(ws / ".cursor" / "hooks.json", "{not json"),
        hold_until_stops=2,
    )
    _dump("malformed_project_hooks_config_holds", rec)
    _assert_held(rec, "hooks_config_malformed:")


async def test_owned_hooks_only_stays_capable(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: only Omnigent's own project hooks (a stale one is replaced) → receipts work."""
    stale = cbridge.build_hooks_config(
        tmp_path / "older-bridge", python_executable=_hook_python(tmp_path)
    )

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"hooks_from_config": True, "turn_s_by_prefix": {"TASK": 2.5}},
        during_turn_1=_act,
        fence_on=3,
        setup_hooks=lambda ws: _write_hooks(ws / ".cursor" / "hooks.json", stale),
    )
    _dump("owned_hooks_only_stays_capable", rec)
    assert rec["hold_reason"] is None
    assert (rec["fence"]["verified"], rec["fence"]["reason"]) == (True, None), rec["fence"]
    assert rec["turns_ending_after_fence"] == []
    assert rec["final_core"]["turn_end_count"] == rec["expect_turn_end_count"] == 2
    ran = [e["command"] for e in rec["tui_events"] if e["ev"] == "config_stop_hook"]
    assert stale["hooks"]["stop"][0]["command"] not in ran


async def test_owned_shaped_user_hook_holds(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An Omnigent-shaped hook in the shared user file is not owned by any launch."""
    shared = cbridge.build_hooks_config(
        tmp_path / "older-bridge", python_executable=_hook_python(tmp_path)
    )
    user = Path(os.environ["HOME"]) / ".cursor" / "hooks.json"
    _write_hooks(user, shared)
    before = user.read_bytes()

    async def _act(executor, pane, prompt, sent) -> None:
        await _repost(executor, prompt, sent)

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"hooks_from_config": True, "turn_s_by_prefix": {"TASK": 2.5}},
        during_turn_1=_act,
        fence_on=3,
        hold_until_stops=2,
    )
    _dump("owned_shaped_user_hook_holds", rec)
    _assert_held(rec, f"foreign_stop_hook:{user}")
    assert user.read_bytes() == before


async def test_workspace_that_is_home_holds(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """workspace == HOME (through a symlink alias): the project file is the user file."""
    alias = tmp_path / "home-alias"
    alias.symlink_to(tmp_path / "ws", target_is_directory=True)
    monkeypatch.setenv("HOME", str(alias))

    async def _act(executor, pane, prompt, sent) -> None:
        return None

    rec = await _scenario(
        tmp_path,
        monkeypatch,
        auth_app,
        auth_client,
        cfg={"hooks_from_config": True, "turn_s_by_prefix": {"TASK": 1.5}},
        during_turn_1=_act,
        fence_on=3,
        hold_until_stops=1,
    )
    _dump("workspace_that_is_home_holds", rec)
    _assert_held(rec, "workspace_is_home:")


async def test_shared_user_hook_from_another_session_cannot_close_a_running_turn(
    auth_app, auth_client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live F4 shape: after A armed cleanly, a user-scope hook bound to A's bridge
    appears, and session B (another chat on the same HOME) ends a turn while A's turn
    still runs. B's stop lands in A's bridge but never closes A's row; A stays held.
    """
    others: list[_Pane] = []
    b_dir = tmp_path / "b"
    b_dir.mkdir()

    async def _act(executor, pane, prompt, sent) -> None:
        bridge_a = executor._bridge_dir
        shared = cbridge.build_hooks_config(bridge_a, python_executable=_hook_python(tmp_path))
        _write_hooks(Path(os.environ["HOME"]) / ".cursor" / "hooks.json", shared)
        ws_b = tmp_path / "ws-b"
        ws_b.mkdir()
        pane_b = _Pane(b_dir, b_dir / "bridge", ws_b, {"hooks_from_config": True, "turn_s": 0.5})
        others.append(pane_b)
        await asyncio.sleep(0.5)
        pane_b.type_line("OTHER session prompt")

        async def _b_stopped() -> bool:
            return any(e["ev"] == "stop_hook" for e in pane_b.events())

        await _wait(_b_stopped, 20, "session B turn end")
        a_events = pane.events()
        assert not any(e["ev"] == "stop_hook" for e in a_events), "A ended before B's stop"

    try:
        rec = await _scenario(
            tmp_path,
            monkeypatch,
            auth_app,
            auth_client,
            cfg={"hooks_from_config": True, "turn_s_by_prefix": {"TASK": 6.0}},
            during_turn_1=_act,
            fence_on=3,
            hold_until_stops=1,
        )
    finally:
        for other in others:
            other.close()
    _dump("shared_user_hook_from_another_session_cannot_close_a_running_turn", rec)
    assert rec["hold_reason"] is None  # A armed on a clean launch
    assert rec["receipt_seen"] is True
    assert rec["passed_rev3_before_fence"] == []
    assert "fence" not in rec, rec.get("fence")
    binding = json.loads(rec["final_labels"][input_fence.TURN_RECEIPT_BINDING_LABEL])
    assert (binding["bound"], binding["reason"]) == (False, "turn_end_foreign"), binding
    bridge_a = Path(rec["bridge_dir"])
    ends = [
        json.loads(line) for line in (bridge_a / status.TURN_END_FILE).read_text().splitlines()
    ]
    foreign = [e for e in ends if e.get("conversation_check") == "mismatch"]
    own = [e for e in ends if e.get("conversation_check") == "match"]
    assert foreign and own, ends
    # B's stop landed first, while A's row existed, and was never positioned locally.
    assert ends[0]["conversation_check"] == "mismatch"
    assert ends[0]["hook_conversation_id"] != ends[0]["observed_store_chat"]
    assert (ends[0]["store_chat_at_end"], ends[0]["store_rowid_at_end"]) == (None, None)
    assert {e["hook_conversation_id"] for e in own} == {e["store_chat_at_end"] for e in own}
