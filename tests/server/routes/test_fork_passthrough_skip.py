"""Skip-reason log for the native clone passthrough predicate."""

from __future__ import annotations

import logging

from starlette.testclient import TestClient

from omnigent.server.routes.sessions import routes_core as routes_core_module
from omnigent.server.routes.sessions.routes_core import (
    _native_clone_passthrough_skip_reasons,
)
from tests.server.routes.test_fork_oversize_guard import (
    _SOURCE_ID,
    _make_conversation,
    _make_item,
)
from tests.server.routes.test_sessions_fork import _build_app, _ConversationStore


def test_skip_reasons_name_each_failed_condition() -> None:
    """Each false passthrough flag becomes a stable log fragment."""
    reasons = _native_clone_passthrough_skip_reasons(
        guard_enabled=True,
        external_session_id="",
        resume_source_native_session=False,
        up_to_response_id="resp_last",
        carry_history_into_native=False,
        target_harness="claude-sdk",
        source_harness="pi-native",
        source_harness_checked=True,
    )
    assert reasons == [
        "fork_native_guard enabled",
        "source external_session_id empty",
        "resume_source_native_session false",
        "up_to_response_id set",
        "carry_history_into_native false",
        "target harness resolved to claude-sdk",
        "source harness resolved to pi-native",
    ]


def test_skip_reasons_empty_when_passthrough_would_fire() -> None:
    """A same-family native clone with a full history has no skip reasons."""
    reasons = _native_clone_passthrough_skip_reasons(
        guard_enabled=False,
        external_session_id="f4bd03c9-3c11-46fd-b0df-fdc7952301c2",
        resume_source_native_session=True,
        up_to_response_id=None,
        carry_history_into_native=True,
        target_harness="claude-native",
        source_harness="claude-native",
        source_harness_checked=True,
    )
    assert reasons == []


def test_web_style_last_response_allows_native_passthrough(
    monkeypatch, caplog: logging.LogCaptureFixture
) -> None:
    """A full Web UI prefix reuses the existing native session."""
    source = _make_conversation()
    source.external_session_id = "source-native-session"
    item = _make_item("item_1", "x" * 300, response_id="resp_last")
    store = _ConversationStore(
        conversations={_SOURCE_ID: source},
        items_by_conv={_SOURCE_ID: [item]},
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "1")
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "1")
    monkeypatch.delenv("OMNIGENT_FORK_NATIVE_GUARD", raising=False)

    async def _native_target_harness(*_args, **_kwargs) -> str:
        return "claude-native"

    def _native_history(_agent) -> bool:
        return True

    def _no_cursor_history(_agent) -> bool:
        return False

    async def _unexpected_compaction(*_args, **_kwargs) -> None:
        raise AssertionError("a full native prefix should skip compaction")

    monkeypatch.setattr(
        routes_core_module,
        "_resolve_fork_target_harness",
        _native_target_harness,
    )
    monkeypatch.setattr(
        routes_core_module,
        "_agent_carries_native_fork_history",
        _native_history,
    )
    monkeypatch.setattr(
        routes_core_module, "_agent_carries_cursor_fork_history", _no_cursor_history
    )
    monkeypatch.setattr(
        routes_core_module,
        "compact_fork_items",
        _unexpected_compaction,
    )

    caplog.set_level(logging.INFO)
    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={"up_to_response_id": "resp_last"},
    )

    assert response.status_code == 201, response.text
    assert store.fork_calls[0]["up_to_response_id"] == "resp_last"
    assert store.fork_calls[0]["replacement_items"] is None
    assert not any(
        "fork passthrough skipped: up_to_response_id set" in rec.getMessage()
        for rec in caplog.records
    )


def test_truncated_prefix_keeps_native_passthrough_skip(
    monkeypatch, caplog: logging.LogCaptureFixture
) -> None:
    """A Web UI prefix ending before the source tail still guards its size."""
    source = _make_conversation()
    source.external_session_id = "source-native-session"
    items = [
        _make_item("item_1", "x" * 300, response_id="resp_first"),
        _make_item("item_2", "later", response_id="resp_last"),
    ]
    store = _ConversationStore(
        conversations={_SOURCE_ID: source},
        items_by_conv={_SOURCE_ID: items},
    )
    monkeypatch.setenv("OMNIGENT_FORK_MAX_CONTEXT_BYTES", "1")
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT", "0")
    monkeypatch.delenv("OMNIGENT_FORK_NATIVE_GUARD", raising=False)

    async def _native_target_harness(*_args, **_kwargs) -> str:
        return "claude-native"

    def _native_history(_agent) -> bool:
        return True

    def _no_cursor_history(_agent) -> bool:
        return False

    monkeypatch.setattr(
        routes_core_module,
        "_resolve_fork_target_harness",
        _native_target_harness,
    )
    monkeypatch.setattr(
        routes_core_module,
        "_agent_carries_native_fork_history",
        _native_history,
    )
    monkeypatch.setattr(
        routes_core_module, "_agent_carries_cursor_fork_history", _no_cursor_history
    )

    caplog.set_level(logging.INFO)
    response = TestClient(_build_app(store)).post(
        f"/v1/sessions/{_SOURCE_ID}/fork",
        json={"up_to_response_id": "resp_first"},
    )

    assert response.status_code == 413, response.text
    assert store.fork_calls == []
    assert any(
        "fork passthrough skipped: up_to_response_id set" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]
