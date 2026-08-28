"""Unit tests for fork-compaction model selection."""

from __future__ import annotations

from omnigent.fork_compact import resolve_fork_compact_model


def test_source_pin_wins_over_target_and_spec() -> None:
    """A source session pin is the default fork-compaction choice."""
    resolved = resolve_fork_compact_model(
        source_model_override="pinned-model",
        target_model="target-model",
        spec_model="spec-model",
    )

    assert resolved is not None
    assert resolved.model == "pinned-model"
    assert resolved.source == "source_override"


def test_environment_override_wins_over_source_pin(monkeypatch) -> None:
    """The explicit environment override wins over every session setting."""
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT_MODEL", "env-model")

    resolved = resolve_fork_compact_model(
        source_model_override="pinned-model",
        target_model="target-model",
        spec_model="spec-model",
    )

    assert resolved is not None
    assert resolved.model == "env-model"
    assert resolved.source == "env"


def test_requested_target_model_beats_source_spec() -> None:
    """A switch-target model is used when the source has no pin."""
    resolved = resolve_fork_compact_model(
        source_model_override=None,
        target_model="target-model",
        spec_model="spec-model",
    )

    assert resolved is not None
    assert resolved.model == "target-model"
    assert resolved.source == "target_spec"


def test_model_resolution_falls_back_to_source_spec() -> None:
    """A spec model is used when no session or target model is available."""
    resolved = resolve_fork_compact_model(
        source_model_override=None,
        target_model=None,
        spec_model="spec-model",
    )

    assert resolved is not None
    assert resolved.model == "spec-model"
    assert resolved.source == "source_spec"
