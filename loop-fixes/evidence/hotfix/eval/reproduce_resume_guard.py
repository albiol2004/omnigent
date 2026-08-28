"""Reproduce the hotfix: oversized non-fork resume vs fork 413.

Isolation: scratch HOME / data / config / Claude projects only.
Does not talk to :6767 or ~/.omnigent / ~/.claude/projects.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

import httpx

# Keep this script's imports on the worktree, not a live install.
ROOT = Path("/home/alex/omnigent-fixes")
sys.path.insert(0, str(ROOT))

from omnigent.fork_context import (  # noqa: E402
    ForkContextTooLarge,
    DEFAULT_FORK_MAX_CONTEXT_BYTES,
)
from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor  # noqa: E402

SID = "02857840-6362-408f-b41f-309e396ed7c6"
SESSION_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _oversized_items() -> list[dict[str, object]]:
    """Build AP items whose rebuilt Claude JSONL exceeds 600 kB."""
    # ~1.07 MB production incident; pad one user turn to ~1.1 MB of text.
    blob = "x" * 1_100_000
    return [
        {
            "id": "user_1",
            "type": "message",
            "role": "user",
            "response_id": "response_1",
            "content": [{"type": "input_text", "text": blob}],
        },
        {
            "id": "assistant_1",
            "type": "message",
            "role": "assistant",
            "response_id": "response_1",
            "content": [{"type": "output_text", "text": "ok"}],
        },
    ]


def _history_handler(request: httpx.Request) -> httpx.Response:
    """Serve oversized items; ignore other paths with empty JSON."""
    path = request.url.path
    if path.endswith("/items"):
        return httpx.Response(
            200,
            json={"data": _oversized_items(), "has_more": False},
        )
    return httpx.Response(200, json={})


async def _resume(scratch: Path, *, guard: bool) -> dict[str, object]:
    """Call the exact helper on the production incident path."""
    import omnigent.claude_native as claude_native
    from omnigent import claude_native_bridge

    claude_native._CLAUDE_PROJECTS_DIR = scratch / "claude-projects"
    claude_native_bridge.bridge_dir_for_conversation_id = (  # type: ignore[method-assign]
        lambda _sid: scratch / "bridge"
    )
    workspace = scratch / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_history_handler),
        base_url="https://eval.invalid",
    ) as client:
        written = await claude_native._ensure_local_claude_resume_transcript(
            client,
            session_id=SESSION_ID,
            external_session_id=SID,
            workspace=workspace,
            guard=guard,
        )
    size = written.stat().st_size if written is not None else 0
    return {
        "guard": guard,
        "path": str(written) if written else None,
        "bytes": size,
        "threshold": DEFAULT_FORK_MAX_CONTEXT_BYTES,
        "over_threshold": size > DEFAULT_FORK_MAX_CONTEXT_BYTES,
    }


async def _auto_create(
    scratch: Path,
    *,
    fork: bool,
) -> dict[str, object]:
    """Drive runner launch with a fake terminal; fork=True sets carry_history."""
    import omnigent.claude_native as claude_native
    from omnigent import claude_native_bridge
    from omnigent.entities.session_resources import SessionResourceView
    from omnigent.runner.native.orchestration import _auto_create_claude_terminal
    from omnigent.runner.session_init_protocol import RunnerSessionInitEnvelope

    claude_native._CLAUDE_PROJECTS_DIR = scratch / "claude-projects"
    (scratch / "bridges").mkdir(parents=True, exist_ok=True)
    (scratch / "workspace").mkdir(parents=True, exist_ok=True)
    claude_native_bridge._TRUSTED_PARENT = scratch  # type: ignore[attr-defined]
    claude_native_bridge._BRIDGE_ROOT = scratch / "bridges"  # type: ignore[attr-defined]
    claude_native_bridge.ensure_claude_workspace_trusted = lambda _p: None  # type: ignore[assignment]
    os.environ["RUNNER_SERVER_URL"] = "http://127.0.0.1:17301"
    os.environ["OMNIGENT_RUNNER_WORKSPACE"] = str(scratch / "workspace")

    captured: dict[str, object] = {}

    class _FakeRegistry:
        terminal_registry = None

        async def launch_required_terminal(self, **kwargs: object) -> SessionResourceView:
            captured["kwargs"] = {k: str(type(v)) for k, v in kwargs.items()}
            spec = kwargs.get("spec")
            captured["args"] = list(getattr(spec, "args", []) or [])
            return SessionResourceView(
                id="terminal_claude_main",
                type="terminal",
                session_id=kwargs["session_id"],  # type: ignore[arg-type]
                name="claude:main",
                metadata={"terminal_name": "claude", "session_key": "main", "running": True},
            )

    async def _no_op_forwarder(**_kwargs: object) -> None:
        return None

    import omnigent.claude_native_forwarder as forwarder

    forwarder.supervise_forwarder = _no_op_forwarder  # type: ignore[assignment]

    def _handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/items"):
            return httpx.Response(
                200,
                json={"data": _oversized_items(), "has_more": False},
            )
        return httpx.Response(200, json={"labels": {}, "external_session_id": SID})

    labels = {"omnigent.fork.carry_history": "1"} if fork else {}
    snapshot: dict[str, object] = {
        "created_at": 10,
        "updated_at": 11,
        "workspace": str(scratch / "workspace"),
        "labels": labels,
    }
    if not fork:
        snapshot["external_session_id"] = SID
    session_init = RunnerSessionInitEnvelope.model_validate(
        {
            "protocol_version": 2,
            "server_version": "0.6.0.dev0",
            "session_id": SESSION_ID,
            "agent_id": "agent",
            "snapshot": snapshot,
        }
    )
    client = httpx.AsyncClient(
        base_url="http://127.0.0.1:17301",
        transport=httpx.MockTransport(_handle),
    )
    try:
        await _auto_create_claude_terminal(
            SESSION_ID,
            _FakeRegistry(),
            lambda _sid, _evt: None,
            server_client=client,
            session_init=session_init,
        )
        args = captured.get("args") or []
        return {"raised": False, "resume_in_args": "--resume" in args, "args": args}
    except ForkContextTooLarge as exc:
        return {
            "raised": True,
            "type": type(exc).__name__,
            "message": str(exc),
            "http_status": exc.http_status,
        }
    finally:
        await client.aclose()


def _sdk_cold_replay() -> dict[str, object]:
    """Non-fork SDK first prompt still guards (remaining hole)."""
    messages = [
        {"role": "user", "content": "x" * 400_000},
        {"role": "assistant", "content": "y" * 400_000},
        {"role": "user", "content": "continue"},
    ]
    try:
        ClaudeSDKExecutor._build_prompt(messages, resume_session=False)
        return {"raised": False}
    except ForkContextTooLarge as exc:
        return {
            "raised": True,
            "file": "omnigent/inner/claude_sdk_executor.py:3130",
            "actual_bytes": exc.actual_bytes,
            "threshold_bytes": exc.threshold_bytes,
            "http_status": exc.http_status,
            "message": str(exc),
        }


async def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="hotfix-eval-"))
    os.environ["HOME"] = str(scratch / "home")
    os.environ["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    os.environ["OMNIGENT_CONFIG_HOME"] = str(scratch / "config")
    (scratch / "home").mkdir()
    result: dict[str, object] = {"scratch": str(scratch)}
    try:
        result["non_fork_direct"] = await _resume(scratch, guard=False)
    except Exception as exc:  # noqa: BLE001 — evidence capture
        result["non_fork_direct"] = {
            "raised": True,
            "type": type(exc).__name__,
            "message": str(exc),
            "trace": traceback.format_exc(),
        }
    try:
        await _resume(scratch / "fork", guard=True)
        result["fork_direct"] = {"raised": False}
    except ForkContextTooLarge as exc:
        result["fork_direct"] = {
            "raised": True,
            "http_status": exc.http_status,
            "actual_bytes": exc.actual_bytes,
            "threshold_bytes": exc.threshold_bytes,
            "message": str(exc),
        }
    try:
        result["auto_create_non_fork"] = await _auto_create(
            scratch / "auto",
            fork=False,
        )
    except Exception as exc:  # noqa: BLE001 — evidence capture
        result["auto_create_non_fork"] = {
            "raised": True,
            "type": type(exc).__name__,
            "message": str(exc),
            "trace": traceback.format_exc(),
        }
    try:
        result["auto_create_fork"] = await _auto_create(scratch / "auto-fork", fork=True)
    except ForkContextTooLarge as exc:
        result["auto_create_fork"] = {
            "raised": True,
            "http_status": exc.http_status,
            "message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 — evidence capture
        result["auto_create_fork"] = {
            "raised": True,
            "type": type(exc).__name__,
            "message": str(exc),
            "trace": traceback.format_exc(),
        }
    result["sdk_cold_replay"] = _sdk_cold_replay()
    out = Path(__file__).resolve().parent / "RESULT.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
