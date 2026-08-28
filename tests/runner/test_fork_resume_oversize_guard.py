"""Regression tests for fork-only native context size enforcement."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

import omnigent.claude_native as claude_native
import omnigent.codex_native as codex_native
from omnigent import claude_native_bridge
from omnigent.fork_context import (
    ForkContextTooLarge,
    guard_fork_context,
    serialized_context_bytes,
)
from omnigent.pi_native_resume import ensure_local_pi_resume_session

_THREAD_ID = "019e96aa-0be2-7343-8d3b-6f914d60936b"


def _oversized_history() -> list[dict[str, object]]:
    """Return two completed turns larger than the configured test limit."""
    return [
        {
            "id": "user_1",
            "type": "message",
            "role": "user",
            "response_id": "response_1",
            "content": [{"type": "input_text", "text": "x" * 200}],
        },
        {
            "id": "assistant_1",
            "type": "message",
            "role": "assistant",
            "response_id": "response_1",
            "content": [{"type": "output_text", "text": "done"}],
        },
    ]


def _history_handler(request: httpx.Request) -> httpx.Response:
    """Serve oversized history to each native rebuild helper."""
    del request
    return httpx.Response(
        200,
        json={"data": _oversized_history(), "has_more": False},
    )


def _configure_claude_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Claude resume tests inside the temporary worktree."""
    monkeypatch.setattr(claude_native, "_CLAUDE_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(
        claude_native_bridge,
        "bridge_dir_for_conversation_id",
        lambda _session_id: tmp_path / "bridge",
    )


def test_non_fork_guard_logs_and_allows_oversize(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The shared no-op path logs oversized non-fork context at INFO."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")
    payload = {"role": "user", "content": "x" * 100}

    with caplog.at_level(logging.INFO, logger="omnigent.fork_context"):
        measured = guard_fork_context(payload, guard=False)

    assert measured == serialized_context_bytes(payload)
    assert any("non-fork context" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_claude_resume_allows_oversized_non_fork_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain Claude resume writes oversized history without raising."""
    _configure_claude_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_history_handler),
        base_url="https://example.com",
    ) as client:
        written = await claude_native._ensure_local_claude_resume_transcript(
            client,
            session_id="conv_claude",
            external_session_id="sid123",
            workspace=tmp_path / "workspace",
            guard=False,
        )

    assert written is not None
    assert written.is_file()
    assert written.stat().st_size > 32


@pytest.mark.asyncio
async def test_claude_fork_rejects_oversized_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Claude fork still rejects oversized rebuilt history."""
    _configure_claude_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_history_handler),
        base_url="https://example.com",
    ) as client:
        with pytest.raises(ForkContextTooLarge):
            await claude_native._ensure_local_claude_resume_transcript(
                client,
                session_id="conv_claude",
                external_session_id="fork123",
                workspace=tmp_path / "workspace",
                guard=True,
            )


@pytest.mark.asyncio
async def test_codex_resume_allows_oversized_non_fork_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain Codex resume writes oversized history without raising."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_history_handler),
        base_url="https://example.com",
    ) as client:
        rollout = await codex_native._ensure_local_codex_resume_rollout(
            client,
            session_id="conv_codex",
            external_session_id=_THREAD_ID,
            codex_home=tmp_path / "codex-home",
            workspace=tmp_path / "workspace",
            model_provider="omnigent",
            codex_path=None,
            guard=False,
        )

    assert rollout.is_file()
    assert rollout.stat().st_size > 32


@pytest.mark.asyncio
async def test_pi_resume_allows_oversized_non_fork_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain Pi resume writes oversized history without raising."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_history_handler),
        base_url="https://example.com",
    ) as client:
        session = await ensure_local_pi_resume_session(
            client,
            session_id="conv_pi",
            external_session_id=_THREAD_ID,
            session_dir=tmp_path,
            workspace=tmp_path / "workspace",
            guard=False,
        )

    assert session is not None
    assert session.is_file()
    assert session.stat().st_size > 32
