"""A prior receipt epoch that cannot be removed aborts the cursor-native launch.

Drives the real launch, ``orchestration._auto_create_cursor_terminal`` (real
server snapshot opt-in, real hooks files under a private HOME/workspace), with
the terminal registry substituted so "terminal started" is observable. If the
prior launch's ``receipt_epoch.json`` survives, a held or not-opted-in launch
must not start the TUI: the stale capability would otherwise stay readable and
the stop hook / runner fence would treat this launch as armed.
"""

# ruff: noqa: F811
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from omnigent.harnesses.cursor_native import bridge as cbridge
from omnigent.harnesses.cursor_native import status
from omnigent.runner.native import orchestration
from omnigent.server.routes._sessions import input_fence
from tests.server.integration import test_cursor_receipt_binding_e2e as b
from tests.server.integration.test_sessions_permissions import (  # noqa: F401 - fixtures
    auth_app,
)  # ``auth_client`` now lives in tests/server/conftest.py and picks this ``auth_app`` up.

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores directory modes"
    ),
]

_OWNER = b._OWNER


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(input_fence.SINGLE_SERVER_ENV, "1")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RUNNER_SERVER_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(cbridge, "_SYSTEM_HOOKS_PATHS", (tmp_path / "etc-cursor-hooks.json",))
    monkeypatch.setattr(cbridge, "_BRIDGE_ROOT", tmp_path / "bridge-root", raising=False)
    input_fence.reset_for_tests()
    b.pending_inputs.reset_for_tests()
    monkeypatch.setattr(sys, "executable", b._hook_python(tmp_path))
    monkeypatch.setattr(
        "omnigent.harnesses.cursor_native.main.resolve_cursor_executable", lambda: "cursor-agent"
    )

    async def _noop(**_k: Any) -> None:
        return None

    for target in (
        "omnigent.harnesses.cursor_native.forwarder.supervise_cursor_forwarder",
        "omnigent.harnesses.cursor_native.usage.supervise_cursor_usage_forwarder",
        "omnigent.harnesses.cursor_native.permissions.supervise_cursor_transcript_elicitations",
    ):
        monkeypatch.setattr(target, _noop)
    from omnigent.runner import _entry as runner_entry

    monkeypatch.setattr(runner_entry, "_make_auth_token_factory", lambda *a, **k: None)


class _Registry:
    terminal_registry = None

    def __init__(self) -> None:
        self.specs: list[Any] = []

    async def launch_required_terminal(
        self, *, session_id, terminal_name, session_key, spec, **_k
    ):
        from omnigent.entities.session_resources import SessionResourceView

        self.specs.append(spec)
        return SessionResourceView(
            id="terminal_cursor_main",
            type="terminal",
            session_id=session_id,
            name="cursor:main",
            metadata={"terminal_name": "cursor", "session_key": "main", "running": True},
        )


async def _real_launch(app: Any, sid: str, ws: Path, strip_optin: bool = False) -> dict[str, Any]:
    inner = httpx.ASGITransport(app=app)

    async def handler(request: httpx.Request) -> httpx.Response:
        req = httpx.Request(
            request.method,
            request.url,
            headers={**dict(request.headers), **_OWNER},
            content=request.content,
        )
        resp = await inner.handle_async_request(req)
        await resp.aread()
        body = json.loads(resp.content or b"{}")
        if isinstance(body, dict) and "labels" in body:
            body["workspace"] = str(ws)
            if strip_optin and isinstance(body["labels"], dict):
                body["labels"].pop(input_fence.COMPLETION_RECEIPTS_LABEL, None)
        return httpx.Response(resp.status_code, json=body)

    client = httpx.AsyncClient(base_url="http://srv", transport=httpx.MockTransport(handler))
    reg = _Registry()
    error = None
    try:
        await orchestration._auto_create_cursor_terminal(
            sid, reg, lambda *_a: None, server_client=client, ensure_comment_relay=None
        )
    except Exception as exc:  # recorded, asserted by the caller
        error = f"{type(exc).__name__}: {exc}"
    finally:
        await client.aclose()
    await asyncio.sleep(0.05)
    bridge_dir = cbridge.bridge_dir_for_session_id(sid)
    return {
        "bridge_dir": bridge_dir,
        "epoch": status.read_receipt_epoch(bridge_dir),
        "terminal_started": bool(reg.specs),
        "error": error,
    }


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


_FOREIGN_STOP = {"hooks": {"stop": [{"command": 'echo \'{"followup_message":"x"}\''}]}}


@pytest.mark.parametrize(
    "second", ["opted_in_foreign_user_hook", "not_opted_in", "opted_in_clean"]
)
async def test_unremovable_stale_epoch_aborts_before_terminal_start(
    second: str, auth_app, auth_client, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await b._opted_in_session(auth_client)
    l1 = await _real_launch(auth_app, sid, ws)
    assert l1["error"] is None and l1["terminal_started"]
    assert l1["epoch"] is not None
    bridge_dir = l1["bridge_dir"]
    if second == "opted_in_foreign_user_hook":
        _write(Path(os.environ["HOME"]) / ".cursor" / "hooks.json", _FOREIGN_STOP)
    strip = second == "not_opted_in"
    os.chmod(bridge_dir, 0o500)
    try:
        l2 = await _real_launch(auth_app, sid, ws, strip_optin=strip)
    finally:
        os.chmod(bridge_dir, 0o700)
    # Fail closed: an actionable error and no terminal, never a started TUI with
    # the prior capability still readable.
    assert not l2["terminal_started"], l2
    assert l2["error"] is not None and l2["error"].startswith("ReceiptEpochClearError"), l2
    assert str(bridge_dir / status.RECEIPT_EPOCH_FILE) in l2["error"]
    assert "relaunch" in l2["error"]
    assert l2["epoch"] == l1["epoch"]  # the leftover is reported, not hidden
    # Once the operator fixes the directory, the relaunch clears it and follows
    # the normal gate.
    l3 = await _real_launch(auth_app, sid, ws, strip_optin=strip)
    assert l3["error"] is None and l3["terminal_started"], l3
    if second == "opted_in_clean":
        assert l3["epoch"] is not None and l3["epoch"] != l1["epoch"]
    else:
        assert l3["epoch"] is None
        assert not (bridge_dir / status.RECEIPT_EPOCH_FILE).exists()


async def test_default_off_launch_without_epoch_ignores_read_only_bridge_dir(
    auth_app, auth_client, tmp_path: Path
) -> None:
    # Absent-file idempotence: nothing to remove is not an error, even when the
    # directory would refuse an unlink.
    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await b._opted_in_session(auth_client)
    l1 = await _real_launch(auth_app, sid, ws, strip_optin=True)
    assert l1["error"] is None and l1["terminal_started"] and l1["epoch"] is None
    bridge_dir = l1["bridge_dir"]
    os.chmod(bridge_dir, 0o500)
    try:
        l2 = await _real_launch(auth_app, sid, ws, strip_optin=True)
    finally:
        os.chmod(bridge_dir, 0o700)
    assert l2["error"] is None and l2["terminal_started"], l2
    assert l2["epoch"] is None


async def test_clean_launch_and_relaunch_arm_with_new_epoch(
    auth_app, auth_client, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    sid = await b._opted_in_session(auth_client)
    l1 = await _real_launch(auth_app, sid, ws)
    await asyncio.sleep(0.01)  # distinct launch_epoch_ms
    l2 = await _real_launch(auth_app, sid, ws)
    for launch in (l1, l2):
        assert launch["error"] is None and launch["terminal_started"], launch
        assert launch["epoch"] is not None
    assert l2["epoch"] > l1["epoch"]
    # Default-off relaunch drops the epoch and still starts.
    l3 = await _real_launch(auth_app, sid, ws, strip_optin=True)
    assert l3["error"] is None and l3["terminal_started"] and l3["epoch"] is None
