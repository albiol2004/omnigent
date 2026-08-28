"""Tests for the Claude SDK first-prompt fork guard."""

from __future__ import annotations

import pytest

from omnigent.fork_context import ForkContextTooLarge
from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor


def test_sdk_full_replay_refuses_an_oversized_first_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SDK prompt guard runs before the optional SDK is loaded."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "100")
    messages = [
        {"role": "user", "content": "x" * 200},
        {"role": "assistant", "content": "y" * 200},
        {"role": "user", "content": "latest"},
    ]

    with pytest.raises(ForkContextTooLarge) as raised:
        ClaudeSDKExecutor._build_prompt(messages, resume_session=False)

    assert raised.value.actual_bytes > raised.value.threshold_bytes
