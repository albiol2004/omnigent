"""Focused tests for fork context sizing and native history pagination."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import omnigent.claude_native as claude_native
import omnigent.codex_native as codex_native
from omnigent import claude_native_bridge
from omnigent.claude_native import _fetch_all_session_items_for_claude_resume
from omnigent.fork_context import (
    DEFAULT_FORK_JSONL_INFLATION,
    DEFAULT_FORK_MAX_CONTEXT_BYTES,
    ForkContextTooLarge,
    estimate_fork_context_bytes,
    fork_jsonl_inflation,
    guard_fork_context,
    max_fork_context_bytes,
    serialized_context_bytes,
    summary_only_items,
)


def _configure_claude_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep Claude estimate tests inside the temporary worktree."""
    monkeypatch.setattr(claude_native, "_CLAUDE_PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(
        claude_native_bridge,
        "bridge_dir_for_conversation_id",
        lambda _session_id: tmp_path / "bridge",
    )


def _estimate_history_handler(request: httpx.Request) -> httpx.Response:
    """Serve a small synthetic conversation to the Claude rebuild."""
    del request
    return httpx.Response(
        200,
        json={
            "data": [
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
            ],
            "has_more": False,
        },
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


def test_invalid_jsonl_inflation_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid renderer fallback values do not disable the safety estimate."""
    monkeypatch.setenv("OMNIGENT_FORK_JSONL_INFLATION", "not-a-number")
    assert fork_jsonl_inflation() == DEFAULT_FORK_JSONL_INFLATION


def test_fork_estimate_uses_jsonl_inflation_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing renderer applies the configured JSONL inflation factor."""
    payload = {"role": "user", "content": "x" * 100}
    monkeypatch.setenv("OMNIGENT_FORK_JSONL_INFLATION", "2")

    assert estimate_fork_context_bytes(payload) == 2 * serialized_context_bytes(payload)


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


@pytest.mark.asyncio
async def test_claude_fork_estimate_matches_rebuilt_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pure estimate matches the bytes written by Claude's rebuild."""
    _configure_claude_paths(tmp_path, monkeypatch)
    workspace = tmp_path / "workspace"
    external_session_id = "00000000-0000-0000-0000-000000000000"
    bridge_dir = tmp_path / "bridge"

    def render(value: object) -> list[dict[str, object]]:
        return claude_native._claude_transcript_records_from_session_items(
            value,  # type: ignore[arg-type]
            session_id="conv_claude",
            external_session_id=external_session_id,
            cwd=workspace,
            bridge_dir=bridge_dir,
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_estimate_history_handler),
        base_url="https://example.com",
    ) as client:
        items = await _fetch_all_session_items_for_claude_resume(client, "conv_claude")
        estimated = estimate_fork_context_bytes(items, renderer=render)
        written = await claude_native._ensure_local_claude_resume_transcript(
            client,
            session_id="conv_claude",
            external_session_id=external_session_id,
            workspace=workspace,
            guard=False,
        )

    assert written is not None
    assert estimated == written.stat().st_size


def test_small_context_is_returned_without_mutation() -> None:
    """A payload under the limit remains byte-for-byte equivalent."""
    payload = {"role": "user", "content": "small"}
    original = dict(payload)

    measured = guard_fork_context(payload, threshold=10_000)

    assert payload == original
    assert measured == serialized_context_bytes(payload)


@pytest.mark.parametrize("native_guard", [False, True], ids=["passthrough", "guarded"])
def test_claude_clone_refuses_oversized_transcript(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_guard: bool,
) -> None:
    """A native clone only rejects oversized history in guarded mode."""
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
    if native_guard:
        monkeypatch.setenv("OMNIGENT_FORK_NATIVE_GUARD", "1")
    else:
        monkeypatch.delenv("OMNIGENT_FORK_NATIVE_GUARD", raising=False)

    def clone() -> Path | None:
        return claude_native._clone_claude_transcript(
            source_external_session_id="00000000-0000-0000-0000-000000000000",
            target_external_session_id="11111111-1111-1111-1111-111111111111",
            clone_workspace=tmp_path / "clone",
        )

    target = target_root / "11111111-1111-1111-1111-111111111111.jsonl"
    if native_guard:
        with pytest.raises(ForkContextTooLarge):
            clone()
        assert not target.exists()
    else:
        result = clone()
        assert result == target
        assert target.is_file()
        assert target.stat().st_size > 32


@pytest.mark.parametrize("native_guard", [False, True], ids=["passthrough", "guarded"])
def test_codex_clone_oversized_rollout_honors_native_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_guard: bool,
) -> None:
    """A Codex clone only rejects oversized history in guarded mode."""
    source_home = tmp_path / "source-home"
    source = (
        source_home / "sessions" / "2026" / "06" / "05" / "rollout-2026-06-05T15-23-07-"
        "019e96aa-0be2-7343-8d3b-6f914d60936b.jsonl"
    )
    source.parent.mkdir(parents=True)
    source.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "019e96aa-0be2-7343-8d3b-6f914d60936b",
                            "cwd": str(tmp_path),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {"text": "x" * 200},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        codex_native,
        "codex_home_for_bridge_dir",
        lambda _bridge_dir: source_home,
    )
    monkeypatch.setattr(
        codex_native,
        "_find_codex_rollout",
        lambda *_args: source,
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "32")
    if native_guard:
        monkeypatch.setenv("OMNIGENT_FORK_NATIVE_GUARD", "1")
    else:
        monkeypatch.delenv("OMNIGENT_FORK_NATIVE_GUARD", raising=False)

    target_thread = "019eaa11-1111-7222-8333-444455556666"
    clone_home = tmp_path / "clone-home"

    def clone() -> Path | None:
        return codex_native._clone_codex_rollout(
            source_session_id="conv_source",
            source_thread_id="019e96aa-0be2-7343-8d3b-6f914d60936b",
            target_thread_id=target_thread,
            clone_codex_home=clone_home,
            clone_workspace=tmp_path / "clone",
        )

    target = (
        clone_home
        / "sessions"
        / "2026"
        / "06"
        / "05"
        / (f"rollout-2026-06-05T15-23-07-{target_thread}.jsonl")
    )
    if native_guard:
        with pytest.raises(ForkContextTooLarge):
            clone()
        assert not target.exists()
    else:
        result = clone()
        assert result == target
        assert target.is_file()
        assert target.stat().st_size > 32


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
