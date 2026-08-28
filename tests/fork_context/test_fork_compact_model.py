"""Unit tests for fork-compaction model selection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import omnigent.fork_compact as fork_compact
from omnigent.model_fallbacks import _CODEX_MODELS
from omnigent.onboarding.provider_config import (
    ANTHROPIC_FAMILY,
    KEY_KIND,
    OPENAI_FAMILY,
    FamilyConfig,
    ProviderEntry,
)
from omnigent.runtime.compaction import SummaryMetadata


def _key_provider(
    name: str,
    family_name: str,
    api_key: str,
    *,
    base_url: str = "https://example.test/v1",
) -> ProviderEntry:
    """Build an in-memory key provider without touching user config."""
    return ProviderEntry(
        name=name,
        kind=KEY_KIND,
        families={
            family_name: FamilyConfig(base_url=base_url, api_key=api_key),
        },
    )


@pytest.fixture
def install_providers(monkeypatch: pytest.MonkeyPatch):
    """Patch both config loaders so tests never read ``~/.omnigent``."""

    def install(*entries: ProviderEntry) -> None:
        providers = {entry.name: entry for entry in entries}
        monkeypatch.delenv("OMNIGENT_FORK_COMPACT_MODEL", raising=False)
        monkeypatch.setattr(fork_compact, "load_global_config", dict)
        monkeypatch.setattr(fork_compact, "load_providers", lambda _config: providers)

    return install


def test_source_pin_wins_over_target_and_spec(
    install_providers,
) -> None:
    """A source session pin is the default fork-compaction choice."""
    install_providers(_key_provider("openai", OPENAI_FAMILY, "sk-openai"))

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override="pinned-model",
        target_model="target-model",
        spec_model="spec-model",
    )

    assert resolved is not None
    assert resolved.model == "openai/pinned-model"
    assert resolved.source == "source_override"


def test_environment_override_wins_when_callable(
    monkeypatch: pytest.MonkeyPatch,
    install_providers,
) -> None:
    """A callable environment override wins over every session setting."""
    install_providers(_key_provider("anthropic", ANTHROPIC_FAMILY, "sk-anthropic"))
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT_MODEL", "anthropic/custom-model")

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override="fable",
        target_model="target-model",
        spec_model="spec-model",
    )

    assert resolved is not None
    assert resolved.model == "anthropic/custom-model"
    assert resolved.source == "env"
    assert resolved.connection == {
        "api_key": "sk-anthropic",
        "base_url": "https://example.test/v1",
    }


def test_fable_maps_to_anthropic_key_provider(install_providers) -> None:
    """The Claude CLI alias becomes a concrete Anthropic model."""
    install_providers(_key_provider("anthropic", ANTHROPIC_FAMILY, "sk-anthropic"))

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override="fable",
        target_model=None,
        spec_model=None,
    )

    assert resolved is not None
    assert resolved.model == "anthropic/claude-fable-5"
    assert resolved.source == "source_override"
    assert resolved.connection == {
        "api_key": "sk-anthropic",
        "base_url": "https://example.test/v1",
    }


def test_fable_without_key_falls_through_to_callable_spec(
    install_providers,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An uncallable Claude alias is skipped before a later OpenAI model."""
    install_providers(_key_provider("openai", OPENAI_FAMILY, "sk-openai"))

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override="fable",
        target_model="gpt-5.6-luna",
        spec_model="unused-model",
    )

    assert resolved is not None
    assert resolved.model == "openai/gpt-5.6-luna"
    assert resolved.source == "target_spec"
    assert "source_override model=fable" in caplog.text
    assert "skipped" in caplog.text


def test_prefixed_model_stays_unchanged(install_providers) -> None:
    """An explicit provider prefix is retained while credentials are checked."""
    install_providers(_key_provider("anthropic", ANTHROPIC_FAMILY, "sk-anthropic"))

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override="anthropic/custom-model",
        target_model=None,
        spec_model=None,
    )

    assert resolved is not None
    assert resolved.model == "anthropic/custom-model"
    assert resolved.connection == {
        "api_key": "sk-anthropic",
        "base_url": "https://example.test/v1",
    }


def test_codex_slug_maps_to_openai_key_provider(install_providers) -> None:
    """A Codex CLI slug becomes a generic OpenAI model."""
    install_providers(_key_provider("openai", OPENAI_FAMILY, "sk-openai"))

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override=_CODEX_MODELS[1],
        target_model=None,
        spec_model=None,
    )

    assert resolved is not None
    assert resolved.model == f"openai/{_CODEX_MODELS[1]}"
    assert resolved.connection == {
        "api_key": "sk-openai",
        "base_url": "https://example.test/v1",
    }


def test_anthropic_origin_url_does_not_override_adapter_v1(
    install_providers,
) -> None:
    """Vendor origin URLs without /v1 must not be forwarded as base_url."""
    install_providers(
        _key_provider(
            "anthropic",
            ANTHROPIC_FAMILY,
            "sk-anthropic",
            base_url="https://api.anthropic.com",
        )
    )

    resolved = fork_compact.resolve_fork_compact_model(
        source_model_override="fable",
        target_model=None,
        spec_model=None,
    )

    assert resolved.model == "anthropic/claude-fable-5"
    assert resolved.connection == {"api_key": "sk-anthropic"}


def test_no_callable_model_raises_before_summary(install_providers) -> None:
    """No provider key produces a clear error instead of a generic LLM call."""
    install_providers()

    with pytest.raises(ValueError, match="callable"):
        fork_compact.resolve_fork_compact_model(
            source_model_override="fable",
            target_model=None,
            spec_model=None,
        )


@pytest.mark.asyncio
async def test_compaction_ready_callback_precedes_call_and_disables_inner_sse(
    monkeypatch: pytest.MonkeyPatch,
    install_providers,
) -> None:
    """Readiness fires after routing and compaction receives no conversation id."""
    install_providers(_key_provider("anthropic", ANTHROPIC_FAMILY, "sk-anthropic"))
    source_spec = SimpleNamespace(
        llm=None,
        executor=SimpleNamespace(
            model="fable",
            connection=None,
            context_window=128_000,
        ),
        compaction=None,
    )
    monkeypatch.setattr(fork_compact, "_load_spec", lambda _cache, _agent: source_spec)
    monkeypatch.setattr(
        "omnigent.runtime.workflow._prepare_messages",
        lambda *args, **kwargs: ("", [], 0),
    )
    monkeypatch.setattr(
        "omnigent.runtime.workflow._get_llm_client",
        lambda: object(),
    )
    monkeypatch.setattr(fork_compact, "_replacement_items", lambda *args: [])
    events: list[object] = []
    calls: list[dict[str, object]] = []

    async def fake_compact(*args: object, **kwargs: object) -> object:
        del args
        events.append("compact")
        calls.append(kwargs)
        return SimpleNamespace(
            summary_metadata=SummaryMetadata(
                text="summary",
                last_item_id="item",
                model="anthropic/claude-fable-5",
                token_count=1,
            )
        )

    monkeypatch.setattr(fork_compact, "compact", fake_compact)

    await fork_compact.compact_fork_items(
        source_id="source",
        source=SimpleNamespace(model_override=None),
        source_agent=object(),
        target_agent=None,
        context_items=[],
        agent_cache=object(),
        on_llm_ready=lambda resolved: events.append(resolved),
    )

    assert isinstance(events[0], fork_compact.ResolvedForkCompactModel)
    assert events[1] == "compact"
    assert calls[0]["connection"] == {
        "api_key": "sk-anthropic",
        "base_url": "https://example.test/v1",
    }
    assert calls[0]["conversation_id"] is None
    assert calls[0]["runner_client"] is None
