"""Focused tests for fork context sizing and native history pagination."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import omnigent.claude_native as claude_native
from omnigent.claude_native import _fetch_all_session_items_for_claude_resume
from omnigent.fork_context import (
    DEFAULT_FORK_MAX_CONTEXT_BYTES,
    ForkContextTooLarge,
    guard_fork_context,
    max_fork_context_bytes,
    serialized_context_bytes,
    summary_only_items,
)


def test_oversized_context_names_actual_size_and_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized payload is rejected with both byte counts."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")
    payload = {"role": "user", "content": "x" * 100}

    with pytest.raises(ForkContextTooLarge) as raised:
        guard_fork_context(payload)

    error = raised.value
    assert error.actual_bytes == serialized_context_bytes(payload)
    assert error.threshold_bytes == 32
    assert str(error).find(str(error.actual_bytes)) >= 0
    assert "threshold 32 bytes" in str(error)


def test_invalid_limit_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid environment values do not disable the safety guard."""
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "not-an-int")
    assert max_fork_context_bytes() == DEFAULT_FORK_MAX_CONTEXT_BYTES


def test_summary_only_compaction_is_measured_again() -> None:
    """A valid compaction marker drops its covered prefix before refusal."""
    items = [
        {
            "id": "old",
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "x" * 500}],
        },
        {
            "id": "compact",
            "type": "compaction",
            "summary": "short summary",
            "last_item_id": "old",
            "token_count": 2,
        },
        {
            "id": "new",
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "new"}],
        },
    ]
    compacted = summary_only_items(items)
    limit = serialized_context_bytes(compacted) + 1

    assert [item["id"] for item in compacted] == ["compact", "new"]
    assert guard_fork_context(
        items,
        compacted_value=compacted,
        threshold=limit,
    ) == serialized_context_bytes(compacted)

    with pytest.raises(ForkContextTooLarge) as raised:
        guard_fork_context(
            items,
            compacted_value=[{**item, "summary": "y" * 100} for item in compacted],
            threshold=limit,
        )
    assert raised.value.threshold_bytes == limit


@pytest.mark.asyncio
async def test_claude_history_fetch_drains_all_pages() -> None:
    """Native resume history does not stop at the first 1000-item page."""
    pages = [
        {"data": [{"id": "first", "type": "message"}], "has_more": True, "last_id": "first"},
        {"data": [{"id": "last", "type": "message"}], "has_more": False, "last_id": "last"},
    ]
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        items = await _fetch_all_session_items_for_claude_resume(client, "conv_test")

    assert [item["id"] for item in items] == ["first", "last"]
    assert len(requests) == 2
    assert requests[0].url.params["limit"] == "1000"
    assert requests[1].url.params["after"] == "first"


def test_small_context_is_returned_without_mutation() -> None:
    """A payload under the limit remains byte-for-byte equivalent."""
    payload = {"role": "user", "content": "small"}
    original = dict(payload)

    measured = guard_fork_context(payload, threshold=10_000)

    assert payload == original
    assert measured == serialized_context_bytes(payload)


def test_claude_clone_refuses_oversized_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native clone is rejected before its destination is committed."""
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps({"type": "user", "message": {"content": "x" * 200}}) + "\n",
        encoding="utf-8",
    )
    target_root = tmp_path / "projects"
    monkeypatch.setattr(
        claude_native,
        "_find_claude_transcript",
        lambda _session_id, exclude=None: source,
    )
    monkeypatch.setattr(
        claude_native,
        "_claude_project_dir_for_cwd",
        lambda _cwd: target_root,
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")

    with pytest.raises(ForkContextTooLarge):
        claude_native._clone_claude_transcript(
            source_external_session_id="00000000-0000-0000-0000-000000000000",
            target_external_session_id="11111111-1111-1111-1111-111111111111",
            clone_workspace=tmp_path / "clone",
        )

    assert not (target_root / "11111111-1111-1111-1111-111111111111.jsonl").exists()


def test_claude_clone_retries_with_summary_only_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized native clone keeps its latest compacted boundary."""
    source = tmp_path / "source.jsonl"
    records = [
        {"type": "user", "message": {"content": "x" * 500}},
        {"type": "system", "subtype": "compact_boundary"},
        {"type": "user", "isCompactSummary": True, "message": {"content": "summary"}},
        {"type": "user", "message": {"content": "post-summary"}},
    ]
    source.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    target_root = tmp_path / "projects"
    monkeypatch.setattr(
        claude_native,
        "_find_claude_transcript",
        lambda _session_id, exclude=None: source,
    )
    monkeypatch.setattr(
        claude_native,
        "_claude_project_dir_for_cwd",
        lambda _cwd: target_root,
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "300")

    target = claude_native._clone_claude_transcript(
        source_external_session_id="00000000-0000-0000-0000-000000000000",
        target_external_session_id="11111111-1111-1111-1111-111111111111",
        clone_workspace=tmp_path / "clone",
    )

    assert target is not None
    contents = target.read_text(encoding="utf-8")
    assert "x" * 500 not in contents
    assert "post-summary" in contents
