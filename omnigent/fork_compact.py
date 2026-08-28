"""Server-side compaction for oversized fork snapshots."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import replace

from omnigent.config import load_global_config
from omnigent.db.utils import generate_item_id, generate_task_id, now_epoch
from omnigent.entities import Agent, CompactionData, Conversation, ConversationItem
from omnigent.fork_compact_routing import (
    ResolvedForkCompactModel,
    list_fork_compact_candidates,
)
from omnigent.model_fallbacks import static_model_fallback
from omnigent.onboarding.provider_config import KEY_KIND, load_providers
from omnigent.runtime.agent_cache import AgentCache
from omnigent.runtime.compaction import SummaryMetadata, _CompactionState, compact
from omnigent.spec import AgentSpec
from omnigent.spec.types import LLMConfig

_logger = logging.getLogger(__name__)

FORK_COMPACT_ENV = "OMNIGENT_FORK_COMPACT"
FORK_COMPACT_MODEL_ENV = "OMNIGENT_FORK_COMPACT_MODEL"
FORK_COMPACT_TARGET_BYTES_ENV = "OMNIGENT_FORK_COMPACT_TARGET_BYTES"


def fork_compact_enabled() -> bool:
    """Return whether oversized forks may invoke server-side compaction."""
    return os.environ.get(FORK_COMPACT_ENV, "1").strip() != "0"


def fork_compact_target_bytes() -> int:
    """Return the positive byte target for a successful compacted fork."""
    from omnigent.fork_context import max_fork_context_bytes

    raw = os.environ.get(FORK_COMPACT_TARGET_BYTES_ENV)
    if raw is not None:
        try:
            configured = int(raw)
        except ValueError:
            configured = 0
        if configured > 0:
            return configured
    return max(1, int(max_fork_context_bytes() * 0.7))


def _fork_compact_candidate_rows(
    *,
    source_model_override: str | None,
    target_model: str | None,
    spec_model: str | None,
) -> tuple[tuple[str, str | None], ...]:
    """Return the documented candidate list plus an OpenAI summary fallback."""
    fallback = static_model_fallback(KEY_KIND, "fork_compact")
    openai_fallback = fallback.model_ids[0] if fallback and fallback.model_ids else None
    return (
        ("env", os.environ.get(FORK_COMPACT_MODEL_ENV)),
        ("source_override", source_model_override),
        ("target_spec", target_model),
        ("source_spec", spec_model),
        ("openai_fallback", openai_fallback),
    )


def resolve_fork_compact_model(
    *,
    source_model_override: str | None,
    target_model: str | None,
    spec_model: str | None,
) -> ResolvedForkCompactModel:
    """Resolve the model in the documented fork-compaction precedence order."""
    providers = load_providers(load_global_config())
    return list_fork_compact_candidates(
        _fork_compact_candidate_rows(
            source_model_override=source_model_override,
            target_model=target_model,
            spec_model=spec_model,
        ),
        providers,
    )[0]


def _spec_model(spec: AgentSpec) -> str | None:
    return spec.llm.model if spec.llm and spec.llm.model else spec.executor.model


def _load_spec(agent_cache: AgentCache | None, agent: Agent) -> AgentSpec:
    if agent_cache is None:
        raise RuntimeError("Fork compaction is unavailable: agent cache is not configured")
    return agent_cache.load(
        agent.id, agent.bundle_location, expand_env=agent.session_id is None
    ).spec


def _llm_config_for_model(
    spec: AgentSpec,
    model: str,
    connection: dict[str, str] | None = None,
) -> LLMConfig:
    base = spec.llm or LLMConfig(
        model=spec.executor.model or model,
        connection=spec.executor.connection,
    )
    return replace(
        base,
        model=model,
        connection=connection if connection is not None else base.connection,
    )


async def _compact_with_resolved(
    *,
    source_id: str,
    source_spec: AgentSpec,
    config_spec: AgentSpec,
    context_items: Sequence[ConversationItem],
    resolved: ResolvedForkCompactModel,
    on_llm_ready: Callable[[ResolvedForkCompactModel], None] | None,
) -> list[ConversationItem]:
    """Run Layer-2 compact for one already-resolved callable model."""
    llm_config = _llm_config_for_model(
        config_spec,
        resolved.model,
        resolved.connection,
    )
    from omnigent.runtime.workflow import (
        _get_llm_client,
        _prepare_messages,
        _route_bare_model_for_compaction,
    )

    llm_config = _route_bare_model_for_compaction(llm_config)
    _logger.info(
        "Fork compaction model resolved: source=%s model=%s",
        resolved.source,
        llm_config.model,
    )
    history = list(context_items)
    state = _CompactionState(
        context_window=None,
        last_summary=None,
        config=source_spec.compaction,
        model=llm_config.model,
        connection=llm_config.connection,
        conversation_id=source_id,
    )
    _, messages, system_token_budget = _prepare_messages(
        source_spec,
        llm_config,
        history,
        None,
        [],
        state,
        {},
        conversation_id=source_id,
    )
    from omnigent.llms.context_window import get_model_context_window

    context_window = (
        config_spec.executor.context_window
        if config_spec.executor.context_window is not None
        else get_model_context_window(llm_config.model)
    )
    task_id = generate_task_id()
    if on_llm_ready is not None:
        on_llm_ready(resolved)
    result = await compact(
        messages,
        history,
        config=state.config,
        context_window=context_window,
        system_token_budget=system_token_budget,
        model=llm_config.model,
        task_id=task_id,
        llm_client=_get_llm_client(),
        connection=llm_config.connection,
        runner_client=None,
        force=True,
        fail_on_summary_error=True,
        conversation_id=None,
    )
    summary = result.summary_metadata
    if summary is None or not summary.text or not summary.last_item_id:
        raise ValueError("Compaction did not produce a valid summary")
    return _replacement_items(summary, history, task_id)


async def compact_fork_items(
    *,
    source_id: str,
    source: Conversation,
    source_agent: Agent,
    target_agent: Agent | None,
    context_items: Sequence[ConversationItem],
    agent_cache: AgentCache | None,
    on_llm_ready: Callable[[ResolvedForkCompactModel], None] | None = None,
) -> list[ConversationItem]:
    """Compact an in-memory fork prefix and return its replacement items."""
    source_spec = _load_spec(agent_cache, source_agent)
    target_spec = _load_spec(agent_cache, target_agent) if target_agent else None
    providers = load_providers(load_global_config())
    resolved_list = list_fork_compact_candidates(
        _fork_compact_candidate_rows(
            source_model_override=source.model_override,
            target_model=_spec_model(target_spec) if target_spec else None,
            spec_model=_spec_model(source_spec),
        ),
        providers,
    )
    last_error: BaseException | None = None
    published = False
    for resolved in resolved_list:
        config_spec = target_spec if resolved.source == "target_spec" else source_spec
        assert config_spec is not None
        try:
            replacement = await _compact_with_resolved(
                source_id=source_id,
                source_spec=source_spec,
                config_spec=config_spec,
                context_items=context_items,
                resolved=resolved,
                on_llm_ready=on_llm_ready if not published else None,
            )
        except Exception as exc:
            last_error = exc
            text = str(exc)
            is_auth = any(token in text for token in ("401", "403", "Unauthorized", "Forbidden"))
            if not is_auth:
                raise
            _logger.warning(
                "Fork compaction auth failed for %s; trying next candidate",
                resolved.model,
            )
            published = True
            continue
        return replacement
    assert last_error is not None
    raise last_error


def _replacement_items(
    summary: SummaryMetadata,
    history: Sequence[ConversationItem],
    task_id: str,
) -> list[ConversationItem]:
    boundary = next(
        (index for index, item in enumerate(history) if item.id == summary.last_item_id),
        None,
    )
    if boundary is None:
        raise ValueError(f"Compaction boundary item not found: {summary.last_item_id!r}")
    marker = ConversationItem(
        id=generate_item_id("compaction"),
        type="compaction",
        status="completed",
        response_id=task_id,
        created_at=now_epoch(),
        data=CompactionData(
            summary=summary.text,
            last_item_id=summary.last_item_id,
            model=summary.model,
            token_count=summary.token_count,
        ),
    )
    return [marker, *history[boundary + 1 :]]
