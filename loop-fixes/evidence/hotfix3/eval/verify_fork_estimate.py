"""Independent hotfix-3 repro: rendered-size fork guard.

Isolation: scratch OMNIGENT_* dirs, CLAUDE projects, HOME. Port >= 17600.
Never talks to :6767 or ~/.omnigent / ~/.claude/projects.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import uvicorn

ROOT = Path("/home/alex/omnigent-fixes")
sys.path.insert(0, str(ROOT))

SOURCE_ID = "e9f8f58523cec9a57d3bdf93be543e8c"
PORT = 17621


def _items() -> list[Any]:
    from tests.server.routes.test_fork_compact import _rendered_size_items

    return _rendered_size_items()


def _scratch() -> Path:
    scratch = Path(tempfile.mkdtemp(prefix="hotfix3-eval-"))
    os.environ["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    os.environ["OMNIGENT_CONFIG_HOME"] = str(scratch / "config")
    os.environ["HOME"] = str(scratch / "home")
    (scratch / "data").mkdir()
    (scratch / "config").mkdir()
    (scratch / "home").mkdir()
    os.environ["OMNIGENT_FORK_MAX_CONTEXT_BYTES"] = "600000"
    os.environ["OMNIGENT_FORK_COMPACT"] = "1"
    return scratch


def _renderer(session_id: str):
    from omnigent.server.routes.sessions.routes_core import _fork_context_renderer

    return _fork_context_renderer(
        "claude-native",
        session_id=session_id,
        workspace="/tmp/omnigent-fork-workspace",
        terminal_launch_args=None,
    )


def _time_render(payload: list[dict[str, Any]]) -> dict[str, Any]:
    from omnigent.fork_context import (
        estimate_fork_context_bytes,
        serialized_context_bytes,
    )

    renderer = _renderer(SOURCE_ID)
    assert renderer is not None
    t0 = time.perf_counter()
    estimated = estimate_fork_context_bytes(payload, renderer=renderer)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    raw = serialized_context_bytes(payload)
    return {
        "raw_api_bytes": raw,
        "rendered_estimate_bytes": estimated,
        "estimate_raw_ratio": round(estimated / raw, 3),
        "render_ms": round(elapsed_ms, 2),
        "item_count": len(payload),
    }


def _harness_map() -> dict[str, str]:
    from omnigent.server.routes.sessions.routes_core import _fork_context_renderer

    mapping: dict[str, str] = {}
    for harness in (
        "claude-native",
        "claude-sdk",
        "codex-native",
        "pi-native",
        "cursor-native",
        "omnigent",
        "antigravity-native",
        "qwen-native",
    ):
        renderer = _fork_context_renderer(
            harness,
            session_id="sess",
            workspace=None,
            terminal_launch_args=None,
        )
        mapping[harness] = "renderer" if renderer is not None else "1.8x"
    return mapping


def _build_store_app(items, harness: str = "claude-native"):
    from omnigent.spec import AgentSpec
    from omnigent.spec.types import ExecutorSpec
    from tests.server.routes.test_fork_compact import _SpecCache
    from tests.server.routes.test_sessions_fork import (
        _build_app,
        _ConversationStore,
        _make_conversation,
        _make_item,
    )

    store = _ConversationStore(
        conversations={SOURCE_ID: _make_conversation()},
        items_by_conv={SOURCE_ID: items},
    )
    app = _build_app(
        store,
        agent_cache=_SpecCache(
            AgentSpec(
                spec_version=1,
                executor=ExecutorSpec(
                    model="spec-model",
                    config={"harness": harness},
                ),
            )
        ),
    )
    return store, app, _make_item


def _serve(app) -> uvicorn.Server:
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        raise SystemExit(f"throwaway server failed to bind {PORT}")
    return server


def _fork(compact: str) -> httpx.Response:
    os.environ["OMNIGENT_FORK_COMPACT"] = compact

    async def _summary(*args: object, **kwargs: object) -> dict[str, object]:
        del args, kwargs
        return {"text": "eval summary", "token_count": 4}

    with patch("omnigent.runtime.compaction.summarize_history", new=_summary):
        return httpx.post(
            f"http://127.0.0.1:{PORT}/v1/sessions/{SOURCE_ID}/fork",
            json={},
            timeout=60.0,
        )


async def _launch_resume(scratch: Path, fork_items: list[dict[str, object]]) -> dict[str, Any]:
    import asyncio

    import omnigent.claude_native as claude_native
    from omnigent import claude_native_bridge
    from omnigent.entities.session_resources import SessionResourceView
    from omnigent.fork_context import ForkContextTooLarge
    from omnigent.runner.native import orchestration
    from omnigent.runner.session_init_protocol import RunnerSessionInitEnvelope
    from omnigent.stores.conversation_store import (
        FORK_CARRY_HISTORY_LABEL_KEY,
        FORK_SOURCE_EXTERNAL_SESSION_LABEL_KEY,
    )

    claude_native._CLAUDE_PROJECTS_DIR = scratch / "claude-projects"
    claude_native_bridge._TRUSTED_PARENT = scratch
    claude_native_bridge._BRIDGE_ROOT = scratch / "bridges"
    (scratch / "bridges").mkdir(parents=True, exist_ok=True)
    (scratch / "workspace").mkdir(parents=True, exist_ok=True)
    os.environ["RUNNER_SERVER_URL"] = "http://127.0.0.1:17622"
    os.environ["OMNIGENT_RUNNER_WORKSPACE"] = str(scratch / "workspace")
    claude_native_bridge.ensure_claude_workspace_trusted = lambda _: None

    async def _noop(**kwargs: Any) -> None:
        del kwargs

    orchestration._claude_native_bridge_id_with_optional_labels = (
        lambda **_k: _async_none()
    )
    orchestration._start_subagent_router_for_native_session = (
        lambda *a, **k: (None, None)
    )
    orchestration._start_turn_router_for_native_session = lambda *a, **k: None
    orchestration._register_auto_forwarder_task = lambda *a: None
    import omnigent.claude_native_forwarder as fwd
    import omnigent.claude_launcher as launcher
    import omnigent.runner._entry as entry

    fwd.supervise_forwarder = _noop
    fwd.reset_transcript_forward_state = lambda _: None
    launcher.resolve_claude_launch = lambda command, args: (command, args)
    claude_native.resolve_native_claude_config = lambda *, spec: None
    entry._make_auth_token_factory = lambda: None

    def _clone(**kwargs: Any) -> Path:
        del kwargs
        raise ForkContextTooLarge(788_545, 600_000)

    claude_native._clone_claude_transcript = _clone
    launched: list[list[str]] = []

    class _Fake:
        terminal_registry = None

        async def launch_required_terminal(self, **kwargs: Any) -> SessionResourceView:
            launched.append(list(kwargs["spec"].args or []))
            return SessionResourceView(
                id="terminal_claude_main",
                type="terminal",
                session_id=kwargs["session_id"],
                name="claude:main",
                metadata={
                    "terminal_name": "claude",
                    "session_key": "main",
                    "running": True,
                },
            )

    def _handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/items"):
            return httpx.Response(200, json={"data": fork_items, "has_more": False})
        return httpx.Response(200, json={})

    labels = {
        FORK_CARRY_HISTORY_LABEL_KEY: "1",
        FORK_SOURCE_EXTERNAL_SESSION_LABEL_KEY: "02857840-6362-408f-b41f-309e396ed7c6",
    }
    session_init = RunnerSessionInitEnvelope.model_validate(
        {
            "protocol_version": 2,
            "server_version": "0.6.0.dev0",
            "session_id": "c538360473d41c84c1eee13918fbeca0",
            "agent_id": "agent",
            "snapshot": {
                "created_at": 10,
                "updated_at": 11,
                "workspace": str(scratch / "workspace"),
                "labels": labels,
            },
        }
    )
    client = httpx.AsyncClient(
        base_url="http://127.0.0.1:17622",
        transport=httpx.MockTransport(_handle),
    )
    await orchestration._auto_create_claude_terminal(
        "c538360473d41c84c1eee13918fbeca0",
        _Fake(),  # type: ignore[arg-type]
        lambda _s, _e: None,
        server_client=client,
        session_init=session_init,
    )
    await asyncio.sleep(0)
    args = launched[0] if launched else []
    resume_id = args[1] if args[:1] == ["--resume"] else None
    dest = None
    if isinstance(resume_id, str):
        dest = claude_native._claude_project_dir_for_cwd(
            (scratch / "workspace").resolve()
        ) / f"{resume_id}.jsonl"
    return {
        "resume": args[:1] == ["--resume"],
        "args_head": args[:3],
        "dest_bytes": dest.stat().st_size if dest is not None and dest.is_file() else None,
        "dest": str(dest) if dest is not None else None,
    }


async def _async_none() -> None:
    return None


def main() -> None:
    scratch = _scratch()
    result: dict[str, Any] = {"scratch": str(scratch), "port": PORT}
    server = None
    try:
        items = _items()
        payload = [item.to_api_dict() for item in items]
        result["timing"] = _time_render(payload)
        result["harness_map"] = _harness_map()
        assert result["timing"]["raw_api_bytes"] < 600_000
        assert result["timing"]["rendered_estimate_bytes"] > 600_000

        store, app, make_item = _build_store_app(items)
        server = _serve(app)
        compact_off = _fork("0")
        result["compact_disabled"] = {
            "status": compact_off.status_code,
            "body": compact_off.json() if compact_off.headers.get("content-type", "").startswith("application/json") else compact_off.text[:400],
        }
        assert compact_off.status_code == 413
        assert store.fork_calls == []

        compact_on = _fork("1")
        result["fork"] = {
            "status": compact_on.status_code,
            "id": compact_on.json().get("id") if compact_on.status_code == 201 else None,
        }
        assert compact_on.status_code == 201, compact_on.text
        fork_id = compact_on.json()["id"]
        fork_items = store._items[fork_id]
        result["fork"]["compaction_items"] = sum(
            1 for item in fork_items if item.type == "compaction"
        )
        assert result["fork"]["compaction_items"] == 1

        from omnigent.fork_context import estimate_fork_context_bytes, jsonl_context_bytes
        import omnigent.claude_native as claude_native

        api_payload = [item.to_api_dict() for item in fork_items]
        renderer = _renderer(fork_id)
        estimated = estimate_fork_context_bytes(api_payload, renderer=renderer)
        records = renderer(api_payload)
        jsonl_bytes = jsonl_context_bytes(records)
        result["post_compact"] = {
            "item_count": len(fork_items),
            "rendered_estimate": estimated,
            "jsonl_bytes": jsonl_bytes,
        }
        assert estimated < 600_000
        assert jsonl_bytes < 600_000

        import asyncio

        result["launch"] = asyncio.run(
            _launch_resume(scratch, api_payload)
        )
        assert result["launch"]["resume"] is True
        assert result["launch"]["dest_bytes"] is not None
        assert result["launch"]["dest_bytes"] < 600_000

        # Small fork: item-set equality.
        small = [make_item("item_1", "small")]
        small_store, small_app, _ = _build_store_app(small)
        from starlette.testclient import TestClient

        os.environ["OMNIGENT_FORK_COMPACT"] = "1"
        small_resp = TestClient(small_app).post(
            f"/v1/sessions/{SOURCE_ID}/fork", json={}
        )
        assert small_resp.status_code == 201
        assert small_store.fork_calls[0]["replacement_items"] is None
        fork_small_id = small_resp.json()["id"]
        result["small_fork"] = {
            "status": 201,
            "item_ids": [item.id for item in small_store._items[fork_small_id]],
            "equal": small_store._items[fork_small_id] == small,
        }
        assert result["small_fork"]["equal"] is True

        from omnigent.fork_context import ForkContextTooLarge

        err = ForkContextTooLarge(1, 1, message_suffix="(server did not compact the fork context)")
        result["runner_413_message"] = str(err)
        assert "server did not compact" in str(err)

        result["ok"] = True
        print(json.dumps(result, indent=2))
    finally:
        if server is not None:
            server.should_exit = True
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
