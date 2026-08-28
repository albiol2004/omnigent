"""Resolve fork-compaction models for the generic LLM client."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from omnigent.claude_model_vocabulary import CLAUDE_MODEL_ALIASES
from omnigent.errors import OmnigentError
from omnigent.llms.routing import PROVIDER_CONFIGS
from omnigent.model_fallbacks import _CLAUDE_SUBSCRIPTION_MODELS, _CODEX_MODELS
from omnigent.onboarding.provider_config import (
    ANTHROPIC_FAMILY,
    KEY_KIND,
    OPENAI_FAMILY,
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedForkCompactModel:
    """A server-callable model and its explicit connection."""

    model: str
    source: str
    connection: dict[str, str]


_OPENAI_COMPATIBLE_PROVIDERS = frozenset(PROVIDER_CONFIGS) - {
    "anthropic",
    "gemini",
    "bedrock",
    "vertex",
    "databricks",
}
_PROVIDER_FAMILIES = {
    **dict.fromkeys(_OPENAI_COMPATIBLE_PROVIDERS, OPENAI_FAMILY),
    "anthropic": ANTHROPIC_FAMILY,
    "gemini": "gemini",
}
_CODEX_MODELS_BY_NAME: dict[str, str] = {model.lower(): model for model in _CODEX_MODELS}


_VENDOR_ROOT_URLS = {
    ANTHROPIC_FAMILY: "https://api.anthropic.com",
    OPENAI_FAMILY: "https://api.openai.com",
}


def _key_connection(
    providers: Mapping[str, object],
    family_name: str,
) -> dict[str, str] | None:
    """Return the first configured key-kind connection for a family."""
    for entry in providers.values():
        if getattr(entry, "kind", None) != KEY_KIND:
            continue
        family_getter = getattr(entry, "family", None)
        if not callable(family_getter):
            continue
        try:
            family = family_getter(family_name)
        except OmnigentError:
            continue
        if family is None:
            continue
        api_key = getattr(family, "api_key", None)
        if not isinstance(api_key, str) or not api_key.strip():
            continue
        connection = {"api_key": api_key}
        base_url = getattr(family, "base_url", None)
        if isinstance(base_url, str) and base_url.strip():
            stripped = base_url.strip().rstrip("/")
            # Config often stores the vendor origin without /v1; the
            # generic adapters already append /messages or /responses.
            if stripped != _VENDOR_ROOT_URLS.get(family_name):
                connection["base_url"] = base_url.strip()
        return connection
    return None


def _route_candidate(candidate: str) -> tuple[str, str] | None:
    """Return a provider/model route and its provider family."""
    lowered = candidate.lower()
    if "/" in candidate:
        provider, model_name = candidate.split("/", 1)
        family = _PROVIDER_FAMILIES.get(provider)
        if not provider or not model_name or family is None:
            return None
        return candidate, family

    if lowered in CLAUDE_MODEL_ALIASES:
        concrete = next(
            (model for model in _CLAUDE_SUBSCRIPTION_MODELS if lowered in model.lower()),
            None,
        )
        return (f"anthropic/{concrete}", ANTHROPIC_FAMILY) if concrete else None

    codex_model = _CODEX_MODELS_BY_NAME.get(lowered)
    if codex_model is not None:
        return f"openai/{codex_model}", OPENAI_FAMILY

    if lowered.startswith("claude-"):
        return f"anthropic/{candidate}", ANTHROPIC_FAMILY

    # These ids require Databricks profile auth, not a generic API key.
    if lowered.startswith(("databricks-", "system.ai.")):
        return None
    return f"openai/{candidate}", OPENAI_FAMILY


def _resolve_candidate(
    candidate: str,
    providers: Mapping[str, object],
) -> tuple[str, dict[str, str] | None] | None:
    """Resolve a candidate route and its key-kind connection."""
    route = _route_candidate(candidate)
    if route is None:
        return None
    model, family_name = route
    return model, _key_connection(providers, family_name)


def resolve_fork_compact_candidates(
    candidates: tuple[tuple[str, str | None], ...],
    providers: Mapping[str, object],
) -> ResolvedForkCompactModel:
    """Select the first candidate callable by the generic LLM client."""
    attempts: list[str] = []
    resolved: ResolvedForkCompactModel | None = None

    for source, raw_candidate in candidates:
        if not isinstance(raw_candidate, str) or not raw_candidate.strip():
            attempts.append(f"{source} model=<unset> -> skipped (empty)")
            continue
        candidate = raw_candidate.strip()
        result = _resolve_candidate(candidate, providers)
        if result is None:
            attempts.append(f"{source} model={candidate} -> skipped (unsupported)")
            continue
        model, connection = result
        if connection is None:
            attempts.append(
                f"{source} model={candidate} -> skipped provider/model={model} (no key)"
            )
            continue
        attempts.append(f"{source} model={candidate} -> tried provider/model={model}")
        resolved = ResolvedForkCompactModel(
            model=model,
            source=source,
            connection=connection,
        )
        break

    chain = "; ".join(attempts)
    if resolved is None:
        _logger.info("Fork compaction model resolution: chain=%s", chain)
        raise ValueError(f"No callable model is configured for fork compaction; tried: {chain}")

    _logger.info(
        "Fork compaction model resolution: chain=%s; source=%s provider/model=%s",
        chain,
        resolved.source,
        resolved.model,
    )
    return resolved
