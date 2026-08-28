"""Adversarial repro: oversize clone falls back to compacted items.

Isolation: scratch HOME / data / config / Claude projects only.
Never talks to :6767 or ~/.claude/projects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

import httpx

ROOT = Path("/home/alex/omnigent-fixes")
sys.path.insert(0, str(ROOT))

from omnigent.fork_context import (  # noqa: E402
    DEFAULT_FORK_MAX_CONTEXT_BYTES,
    ForkContextTooLarge,
)
from omnigent.stores.conversation_store import (  # noqa: E402
    FORK_CARRY_HISTORY_LABEL_KEY,
    FORK_SOURCE_EXTERNAL_SESSION_LABEL_KEY,
)

SOURCE_SID = "02857840-6362-408f-b41f-309e396ed7c6"
FORK_SESSION = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
RESUME_SESSION = "cccccccccccccccccccccccccccccccc"

# Production incident size (raw clone before compact-on-fork).
OVERSIZE_CLONE_BYTES = 782_357


def _compact_items() -> list[dict[str, object]]:
    """Fork DB items after compact-on-fork (well under the 600 kB guard)."""
    return [
        {
            "id": "user_1",
            "type": "message",
            "role": "user",
            "response_id": "response_1",
            "content": [{"type": "input_text", "text": "hi after compact"}],
        },
        {
            "id": "assistant_1",
            "type": "message",
            "role": "assistant",
            "response_id": "response_1",
            "content": [{"type": "output_text", "text": "ok"}],
        },
    ]


def _oversize_items() -> list[dict[str, object]]:
    """Fork items that still exceed the guard after rebuild."""
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


_ORIG_CLONE = None
_ORIG_REBUILD = None


def _write_source_jsonl(projects: Path, *, nbytes: int) -> Path:
    """Write a Claude jsonl with no compact_boundary (clone cannot shrink)."""
    # `_find_claude_transcript` only looks inside project *subdirs*.
    project_dir = projects / "isolated-eval-project"
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{SOURCE_SID}.jsonl"
    pad = max(nbytes - 80, 1)
    record = {
        "type": "user",
        "sessionId": SOURCE_SID,
        "cwd": "/tmp/isolated-eval",
        "message": {"content": "y" * pad},
    }
    text = json.dumps(record, separators=(",", ":")) + "\n"
    if len(text.encode("utf-8")) < nbytes:
        extra = nbytes - len(text.encode("utf-8"))
        record["message"]["content"] += "z" * extra
        text = json.dumps(record, separators=(",", ":")) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def _patch_launch(scratch: Path) -> None:
    """Keep runner launch off the live filesystem and live ports."""
    import omnigent.claude_native as claude_native
    from omnigent import claude_native_bridge
    from omnigent.runner.native import orchestration

    claude_native._CLAUDE_PROJECTS_DIR = scratch / "claude-projects"
    (scratch / "bridges").mkdir(parents=True, exist_ok=True)
    (scratch / "workspace").mkdir(parents=True, exist_ok=True)
    claude_native_bridge._TRUSTED_PARENT = scratch
    claude_native_bridge._BRIDGE_ROOT = scratch / "bridges"
    claude_native_bridge.ensure_claude_workspace_trusted = lambda _: None
    os.environ["RUNNER_SERVER_URL"] = "http://127.0.0.1:17401"
    os.environ["OMNIGENT_RUNNER_WORKSPACE"] = str(scratch / "workspace")

    async def _noop_forwarder(**kwargs: Any) -> None:
        del kwargs

    import omnigent.claude_native_forwarder as forwarder

    forwarder.supervise_forwarder = _noop_forwarder  # type: ignore[assignment]
    forwarder.reset_transcript_forward_state = lambda _: None  # type: ignore[assignment]

    orchestration._claude_native_bridge_id_with_optional_labels = (  # type: ignore[assignment]
        lambda **_kwargs: _async_return(None)
    )
    orchestration._start_subagent_router_for_native_session = (  # type: ignore[assignment]
        lambda *args, **kwargs: (None, None)
    )
    orchestration._start_turn_router_for_native_session = (  # type: ignore[assignment]
        lambda *args, **kwargs: None
    )
    orchestration._register_auto_forwarder_task = lambda *args: None  # type: ignore[assignment]

    import omnigent.claude_launcher as claude_launcher

    claude_launcher.resolve_claude_launch = lambda command, args: (command, args)
    claude_native.resolve_native_claude_config = lambda *, spec: None
    import omnigent.runner._entry as entry

    entry._make_auth_token_factory = lambda: None


async def _async_return(value: Any) -> Any:
    return value


async def _launch(
    scratch: Path,
    *,
    items: list[dict[str, object]],
    fork: bool,
    clone_error: Exception | None = None,
    source_bytes: int | None = OVERSIZE_CLONE_BYTES,
) -> dict[str, object]:
    """Drive `_auto_create_claude_terminal` with a fake terminal."""
    import omnigent.claude_native as claude_native
    from omnigent.entities.session_resources import SessionResourceView
    from omnigent.runner.native.orchestration import _auto_create_claude_terminal
    from omnigent.runner.session_init_protocol import RunnerSessionInitEnvelope

    _patch_launch(scratch)
    projects = scratch / "claude-projects"
    source_path = None
    if source_bytes is not None:
        source_path = _write_source_jsonl(projects, nbytes=source_bytes)

    global _ORIG_CLONE, _ORIG_REBUILD
    clone_calls: list[dict[str, object]] = []
    rebuild_calls: list[dict[str, object]] = []
    if _ORIG_CLONE is None:
        _ORIG_CLONE = claude_native._clone_claude_transcript
        _ORIG_REBUILD = claude_native._ensure_local_claude_resume_transcript
    real_clone = _ORIG_CLONE
    real_rebuild = _ORIG_REBUILD

    def _clone(**kwargs: Any) -> Path | None:
        entry: dict[str, object] = {
            "source": kwargs.get("source_external_session_id"),
            "target": kwargs.get("target_external_session_id"),
        }
        clone_calls.append(entry)
        if clone_error is not None:
            entry["forced_error"] = type(clone_error).__name__
            raise clone_error
        try:
            written = real_clone(**kwargs)
        except Exception as exc:
            entry["raised"] = type(exc).__name__
            if isinstance(exc, ForkContextTooLarge):
                entry["actual_bytes"] = exc.actual_bytes
            raise
        entry["written"] = str(written) if written is not None else None
        if written is not None:
            entry["written_bytes"] = written.stat().st_size
        return written

    async def _rebuild(client: Any, **kwargs: Any) -> Path | None:
        rebuild_calls.append(
            {
                "session_id": kwargs.get("session_id"),
                "guard": kwargs.get("guard"),
                "external_session_id": kwargs.get("external_session_id"),
            }
        )
        return await real_rebuild(client, **kwargs)

    claude_native._clone_claude_transcript = _clone  # type: ignore[assignment]
    claude_native._ensure_local_claude_resume_transcript = _rebuild  # type: ignore[assignment]

    launched: list[list[str]] = []

    class _FakeRegistry:
        terminal_registry = None

        async def launch_required_terminal(self, **kwargs: Any) -> SessionResourceView:
            spec = kwargs["spec"]
            launched.append(list(spec.args or []))
            return SessionResourceView(
                id="terminal_claude_main",
                type="terminal",
                session_id=kwargs["session_id"],
                name="claude:main",
                metadata={"terminal_name": "claude", "session_key": "main", "running": True},
            )

    def _handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/items"):
            return httpx.Response(200, json={"data": items, "has_more": False})
        return httpx.Response(200, json={})

    labels: dict[str, str] = {}
    snapshot: dict[str, object] = {
        "created_at": 10,
        "updated_at": 11,
        "workspace": str(scratch / "workspace"),
        "labels": labels,
    }
    session_id = FORK_SESSION if fork else RESUME_SESSION
    if fork:
        labels[FORK_CARRY_HISTORY_LABEL_KEY] = "1"
        labels[FORK_SOURCE_EXTERNAL_SESSION_LABEL_KEY] = SOURCE_SID
    else:
        snapshot["external_session_id"] = SOURCE_SID

    session_init = RunnerSessionInitEnvelope.model_validate(
        {
            "protocol_version": 2,
            "server_version": "0.6.0.dev0",
            "session_id": session_id,
            "agent_id": "agent",
            "snapshot": snapshot,
        }
    )
    client = httpx.AsyncClient(
        base_url="http://127.0.0.1:17401",
        transport=httpx.MockTransport(_handle),
    )
    log_buffer: list[str] = []
    handler = logging.Handler()

    class _Buf(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_buffer.append(record.getMessage())

    logger = logging.getLogger("omnigent.runner.app")
    buf = _Buf()
    buf.setLevel(logging.INFO)
    logger.addHandler(buf)
    logger.setLevel(logging.INFO)
    result: dict[str, object]
    try:
        await _auto_create_claude_terminal(
            session_id,
            _FakeRegistry(),  # type: ignore[arg-type]
            lambda _sid, _evt: None,
            server_client=client,
            session_init=session_init,
        )
        await asyncio.sleep(0)
        args = launched[0] if launched else []
        resume_id = args[1] if len(args) >= 2 and args[0] == "--resume" else None
        dest = None
        dest_size = None
        if isinstance(resume_id, str):
            dest = claude_native._claude_project_dir_for_cwd(
                (scratch / "workspace").resolve()
            ) / f"{resume_id}.jsonl"
            dest_size = dest.stat().st_size if dest.is_file() else None
        result = {
            "raised": False,
            "resume": "--resume" in args,
            "resume_id": resume_id,
            "args_head": args[:3],
            "clone_calls": clone_calls,
            "rebuild_calls": rebuild_calls,
            "source_bytes": source_path.stat().st_size if source_path else None,
            "dest_bytes": dest_size,
            "dest_is_clone_size": (
                dest_size is not None and dest_size >= OVERSIZE_CLONE_BYTES - 100
            ),
            "logs": [m for m in log_buffer if "transcript" in m or "fork" in m],
        }
    except ForkContextTooLarge as exc:
        result = {
            "raised": True,
            "type": type(exc).__name__,
            "http_status": exc.http_status,
            "actual_bytes": exc.actual_bytes,
            "threshold_bytes": exc.threshold_bytes,
            "message": str(exc),
            "clone_calls": clone_calls,
            "rebuild_calls": rebuild_calls,
            "logs": [m for m in log_buffer if "transcript" in m or "fork" in m],
        }
    except Exception as exc:  # noqa: BLE001 — evidence
        result = {
            "raised": True,
            "type": type(exc).__name__,
            "message": str(exc),
            "trace": traceback.format_exc(),
            "clone_calls": clone_calls,
            "rebuild_calls": rebuild_calls,
        }
    finally:
        logger.removeHandler(buf)
        await client.aclose()
        claude_native._clone_claude_transcript = real_clone  # type: ignore[assignment]
        claude_native._ensure_local_claude_resume_transcript = (  # type: ignore[assignment]
            real_rebuild
        )
    return result


async def main() -> int:
    scratch_root = Path(tempfile.mkdtemp(prefix="hotfix2-eval-"))
    os.environ["HOME"] = str(scratch_root / "home")
    os.environ["OMNIGENT_DATA_DIR"] = str(scratch_root / "data")
    os.environ["OMNIGENT_CONFIG_HOME"] = str(scratch_root / "config")
    (scratch_root / "home").mkdir()
    (scratch_root / "data").mkdir()
    (scratch_root / "config").mkdir()

    out: dict[str, object] = {
        "scratch": str(scratch_root),
        "threshold": DEFAULT_FORK_MAX_CONTEXT_BYTES,
        "real_claude_projects": str(Path.home().parents[0] / "alex" / ".claude" / "projects"),
    }
    # Path.home() now points at scratch; record the live dir separately.
    out["live_claude_projects"] = "/home/alex/.claude/projects"
    out["live_claude_projects_mtime"] = (
        Path("/home/alex/.claude/projects").stat().st_mtime
        if Path("/home/alex/.claude/projects").exists()
        else None
    )

    out["fork_oversize_clone_compact_items"] = await _launch(
        scratch_root / "fork-ok",
        items=_compact_items(),
        fork=True,
    )
    out["fork_oversize_clone_oversize_items"] = await _launch(
        scratch_root / "fork-413",
        items=_oversize_items(),
        fork=True,
    )
    out["fork_generic_clone_error"] = await _launch(
        scratch_root / "fork-generic",
        items=_compact_items(),
        fork=True,
        clone_error=RuntimeError("clone boom"),
    )
    out["fork_small_clone"] = await _launch(
        scratch_root / "fork-small",
        items=_compact_items(),
        fork=True,
        source_bytes=1200,
    )
    out["non_fork_oversize_resume"] = await _launch(
        scratch_root / "resume",
        items=_oversize_items(),
        fork=False,
        source_bytes=None,
    )

    live_mtime_after = (
        Path("/home/alex/.claude/projects").stat().st_mtime
        if Path("/home/alex/.claude/projects").exists()
        else None
    )
    out["live_claude_projects_mtime_after"] = live_mtime_after
    dest = Path(__file__).resolve().parent / "RESULT.json"
    dest.write_text(json.dumps(out, indent=2, default=str) + "\n")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
