"""Regression tests for native fork clone fallback behavior."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

import omnigent.claude_native as claude_native
import omnigent.claude_native_bridge as claude_native_bridge
from omnigent.entities.session_resources import SessionResourceView
from omnigent.fork_context import ForkContextTooLarge
from omnigent.runner.native import orchestration
from tests.runner.helpers import NullServerClient


async def _async_return(value: Any) -> Any:
    """Return a value from an async monkeypatch."""
    return value


async def _noop_forwarder(**kwargs: Any) -> None:
    """Keep the test from opening a network stream."""
    del kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "native_guard,rebuild_oversized",
    [
        (False, False),
        (True, False),
        (True, True),
    ],
    ids=["clone-passthrough", "guarded-rebuilds", "guarded-still-oversized"],
)
async def test_claude_fork_clone_oversize_rebuilds_from_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    native_guard: bool,
    rebuild_oversized: bool,
) -> None:
    """Only the guarded oversized clone falls back to copied items."""
    monkeypatch.setattr(claude_native_bridge, "_TRUSTED_PARENT", tmp_path)
    monkeypatch.setattr(claude_native_bridge, "_BRIDGE_ROOT", tmp_path / "bridges")
    monkeypatch.setenv("RUNNER_SERVER_URL", "http://127.0.0.1:17400")
    monkeypatch.setenv("OMNIGENT_RUNNER_WORKSPACE", str(tmp_path))
    if native_guard:
        monkeypatch.setenv("OMNIGENT_FORK_NATIVE_GUARD", "1")
    else:
        monkeypatch.delenv("OMNIGENT_FORK_NATIVE_GUARD", raising=False)

    metadata = orchestration._ClaudeSessionLaunchMetadata(
        fork_source_external_id="source-claude-id",
        fork_carry_history=True,
    )
    monkeypatch.setattr(
        orchestration,
        "_load_claude_launch_metadata",
        lambda **_kwargs: _async_return(metadata),
    )

    clone_calls: list[dict[str, Any]] = []

    def _oversized_clone(**kwargs: Any) -> Path:
        clone_calls.append(kwargs)
        if native_guard:
            raise ForkContextTooLarge(782_357, 600_000)
        transcript = tmp_path / "cloned.jsonl"
        transcript.write_bytes(b"x" * 600_001)
        return transcript

    monkeypatch.setattr(claude_native, "_clone_claude_transcript", _oversized_clone)
    rebuild_calls: list[dict[str, Any]] = []

    async def _rebuild(
        client: Any,
        *,
        session_id: str,
        external_session_id: str,
        workspace: Path,
        guard: bool,
    ) -> Path:
        del client, session_id, workspace
        rebuild_calls.append({"external_session_id": external_session_id, "guard": guard})
        if rebuild_oversized:
            raise ForkContextTooLarge(782_358, 600_000)
        transcript = tmp_path / "rebuilt.jsonl"
        transcript.write_text("{}\n", encoding="utf-8")
        return transcript

    monkeypatch.setattr(claude_native, "_ensure_local_claude_resume_transcript", _rebuild)
    monkeypatch.setattr(
        orchestration,
        "_claude_native_bridge_id_with_optional_labels",
        lambda **_kwargs: _async_return(None),
    )
    monkeypatch.setattr(
        claude_native_bridge,
        "ensure_claude_workspace_trusted",
        lambda _: None,
    )
    monkeypatch.setattr(
        "omnigent.claude_native_forwarder.supervise_forwarder",
        _noop_forwarder,
    )
    monkeypatch.setattr(
        "omnigent.claude_native_forwarder.reset_transcript_forward_state",
        lambda _: None,
    )
    monkeypatch.setattr(
        "omnigent.claude_launcher.resolve_claude_launch",
        lambda command, args: (command, args),
    )
    monkeypatch.setattr(
        "omnigent.claude_native.resolve_native_claude_config",
        lambda *, spec: None,
    )
    monkeypatch.setattr("omnigent.runner._entry._make_auth_token_factory", lambda: None)
    monkeypatch.setattr(
        orchestration,
        "_start_subagent_router_for_native_session",
        lambda *args, **kwargs: (None, None),
    )
    monkeypatch.setattr(
        orchestration,
        "_start_turn_router_for_native_session",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(orchestration, "_register_auto_forwarder_task", lambda *args: None)

    launched_args: list[Any] = []

    class _FakeResourceRegistry:
        """Capture the launch without starting a terminal."""

        terminal_registry = None

        async def launch_required_terminal(self, **kwargs: Any) -> SessionResourceView:
            launched_args.append(kwargs["spec"].args)
            return SessionResourceView(
                id="terminal_claude_main",
                type="terminal",
                session_id="forked-session",
                name="claude:main",
                metadata={"terminal_name": "claude", "session_key": "main", "running": True},
            )

    with caplog.at_level(logging.INFO, logger="omnigent.runner.app"):
        if native_guard and rebuild_oversized:
            with pytest.raises(ForkContextTooLarge) as raised:
                await orchestration._auto_create_claude_terminal(
                    "forked-session",
                    _FakeResourceRegistry(),  # type: ignore[arg-type]
                    lambda _sid, _event: None,
                    server_client=NullServerClient(),  # type: ignore[arg-type]
                )
            assert raised.value.http_status == 413
            assert "server did not compact" in str(raised.value)
        else:
            await orchestration._auto_create_claude_terminal(
                "forked-session",
                _FakeResourceRegistry(),  # type: ignore[arg-type]
                lambda _sid, _event: None,
                server_client=NullServerClient(),  # type: ignore[arg-type]
            )
            await asyncio.sleep(0)

    assert len(clone_calls) == 1
    if native_guard:
        assert len(rebuild_calls) == 1
        assert rebuild_calls[0]["guard"] is True
        assert (
            "source transcript 782357 bytes > threshold; rebuilding from compacted items"
        ) in caplog.text
    else:
        assert rebuild_calls == []
        assert "rebuilding from compacted items" not in caplog.text
        assert clone_calls[0]["target_external_session_id"]
        assert (tmp_path / "cloned.jsonl").stat().st_size > 600_000
    if native_guard and rebuild_oversized:
        assert launched_args == []
    elif native_guard:
        assert len(launched_args) == 1
        assert list(launched_args[0][:2]) == [
            "--resume",
            rebuild_calls[0]["external_session_id"],
        ]
    else:
        assert len(launched_args) == 1
        assert list(launched_args[0][:2]) == [
            "--resume",
            clone_calls[0]["target_external_session_id"],
        ]
