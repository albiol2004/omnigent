"""Tests for the Claude SDK first-prompt fork guard."""

from __future__ import annotations

import logging

import pytest

from omnigent.fork_context import ForkContextTooLarge
from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
from omnigent.stores.conversation_store import (
    FORK_CARRY_HISTORY_LABEL_KEY,
)


def _oversized_messages(
    labels: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    """Build a replay prompt larger than the configured fork limit."""
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "x" * 200},
        {"role": "assistant", "content": "y" * 200},
        {"role": "user", "content": "latest"},
    ]
    if labels is not None:
        messages[0]["metadata"] = {"labels": labels}
    return messages


def test_sdk_full_replay_allows_an_oversized_non_fork_first_prompt(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Non-fork SDK replay logs oversized history instead of raising."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "100")
    messages = _oversized_messages()

    with caplog.at_level(logging.INFO, logger="omnigent.fork_context"):
        prompt = ClaudeSDKExecutor._build_prompt(
            messages,
            resume_session=False,
            is_fork=False,
        )

    assert prompt
    assert "Skipping fork context size guard" in caplog.text


def test_sdk_full_replay_refuses_an_oversized_fork_first_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fork-labeled SDK replay still raises before the optional SDK loads."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "100")
    messages = _oversized_messages({FORK_CARRY_HISTORY_LABEL_KEY: "1"})

    with pytest.raises(ForkContextTooLarge) as raised:
        ClaudeSDKExecutor._build_prompt(messages, resume_session=False)

    assert raised.value.actual_bytes > raised.value.threshold_bytes
