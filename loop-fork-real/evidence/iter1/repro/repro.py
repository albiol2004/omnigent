"""Reproduce fork-compaction failure for model alias fable."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import traceback
from pathlib import Path

EV = Path("/home/alex/omnigent-fixes/loop-fork-real/evidence/iter1/repro")


def redact(s: str) -> str:
    s = re.sub(r"sk-ant-[A-Za-z0-9_-]+", "sk-ant-<redacted>", s)
    s = re.sub(r"sk-[A-Za-z0-9]{10,}", "sk-<redacted>", s)
    for envn in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        val = os.environ.get(envn)
        if val:
            s = s.replace(val, f"<{envn}_redacted>")
    return s


async def time_call(label, factory):
    t0 = time.perf_counter()
    try:
        result = await factory()
        dt = (time.perf_counter() - t0) * 1000
        rec = {
            "label": label,
            "ok": True,
            "ms": round(dt, 2),
            "result_type": type(result).__name__,
        }
        return rec, None
    except Exception as exc:
        dt = (time.perf_counter() - t0) * 1000
        rec = {
            "label": label,
            "ok": False,
            "ms": round(dt, 2),
            "exc_type": type(exc).__name__,
            "exc_module": type(exc).__module__,
            "exc_str": redact(str(exc)),
            "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
            "cause_str": redact(str(exc.__cause__)) if exc.__cause__ else None,
        }
        return rec, redact(traceback.format_exc())


async def main() -> None:
    from omnigent.config import load_global_config, global_config_path
    from omnigent.db.utils import generate_item_id, generate_task_id, now_epoch
    from omnigent.entities import ConversationItem, MessageData
    from omnigent.fork_compact import resolve_fork_compact_model
    from omnigent.llms import Client
    from omnigent.llms.context_window import get_model_context_window
    from omnigent.llms.routing import parse_model_string
    from omnigent.onboarding.provider_config import load_providers
    from omnigent.runtime.compaction import compact
    from omnigent.runtime.workflow import (
        _get_llm_client,
        _route_bare_model_for_compaction,
    )
    from omnigent.spec.types import LLMConfig

    cfg_path = global_config_path()
    out = {
        "config_path": str(cfg_path),
        "config_path_is_scratch": str(cfg_path).startswith(
            "/tmp/fork-compact-repro"
        ),
        "anthropic_env_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai_env_set": bool(os.environ.get("OPENAI_API_KEY")),
    }
    cfg = load_global_config()
    providers = load_providers(cfg)
    out["provider_names"] = sorted(providers)
    shapes = {}
    for name, entry in providers.items():
        fam_info = {}
        for fam_name in ("anthropic", "openai"):
            fam = entry.family(fam_name)
            if fam is None:
                continue
            fam_info[fam_name] = {
                "has_api_key": bool(fam.api_key),
                "api_key_len": len(fam.api_key) if fam.api_key else 0,
                "has_base_url": bool(fam.base_url),
                "default_model": fam.default_model,
            }
        shapes[name] = {
            "kind": entry.kind,
            "cli": entry.cli,
            "families": fam_info,
        }
    out["providers"] = shapes

    resolved = resolve_fork_compact_model(
        source_model_override="fable",
        target_model=None,
        spec_model=None,
    )
    out["resolve_fork_compact_model"] = (
        {"model": resolved.model, "source": resolved.source}
        if resolved
        else None
    )
    routed_cfg = _route_bare_model_for_compaction(LLMConfig(model="fable"))
    out["route_bare_model_for_compaction"] = routed_cfg.model
    parsed = parse_model_string(routed_cfg.model)
    out["parse_model_string_after_route"] = {
        "provider": parsed.provider,
        "model": parsed.model,
    }
    parsed_raw = parse_model_string("fable")
    out["parse_model_string_raw_fable"] = {
        "provider": parsed_raw.provider,
        "model": parsed_raw.model,
    }
    out["context_window_fable"] = get_model_context_window("fable")

    anth = providers["anthropic"].family("anthropic")
    oai = providers["openai"].family("openai")
    conn_anthropic = {"api_key": anth.api_key} if anth and anth.api_key else None
    conn_openai = {"api_key": oai.api_key} if oai and oai.api_key else None
    out["has_anthropic_connection"] = bool(conn_anthropic)
    out["has_openai_connection"] = bool(conn_openai)

    client = Client()

    async def call_fable_no_conn():
        return await client.responses.create(
            model="fable",
            input=[{"role": "user", "content": "ping"}],
            instructions="Reply with ok",
            tools=[],
            connection_params=None,
            timeout=15,
        )

    async def call_fable_openai_conn():
        return await client.responses.create(
            model="fable",
            input=[{"role": "user", "content": "ping"}],
            instructions="Reply with ok",
            tools=[],
            connection_params=conn_openai,
            timeout=15,
        )

    async def call_fable_anthropic_conn():
        return await client.responses.create(
            model="fable",
            input=[{"role": "user", "content": "ping"}],
            instructions="Reply with ok",
            tools=[],
            connection_params=conn_anthropic,
            timeout=15,
        )

    item = ConversationItem(
        id=generate_item_id("message"),
        type="message",
        status="completed",
        response_id="r1",
        created_at=now_epoch(),
        data=MessageData(
            role="user",
            content=[{"type": "input_text", "text": "hello " * 50}],
        ),
    )
    item2 = ConversationItem(
        id=generate_item_id("message"),
        type="message",
        status="completed",
        response_id="r2",
        created_at=now_epoch(),
        data=MessageData(
            role="assistant",
            agent="a",
            content=[{"type": "output_text", "text": "world " * 50}],
        ),
    )
    messages = [
        {"role": "user", "content": "hello " * 50},
        {"role": "assistant", "content": "world " * 50},
    ]

    async def call_compact_fable():
        return await compact(
            list(messages),
            [item, item2],
            config=None,
            context_window=128000,
            system_token_budget=0,
            model="fable",
            task_id=generate_task_id(),
            llm_client=_get_llm_client(),
            connection=None,
            runner_client=None,
            force=True,
            fail_on_summary_error=True,
            conversation_id=None,
        )

    calls = []
    tbs = {}
    for label, factory in (
        ("client.responses.create model=fable connection=None", call_fable_no_conn),
        (
            "client.responses.create model=fable connection=openai-key-from-config",
            call_fable_openai_conn,
        ),
        (
            "client.responses.create model=fable connection=anthropic-key-from-config",
            call_fable_anthropic_conn,
        ),
        (
            "compact() model=fable connection=None fail_on_summary_error",
            call_compact_fable,
        ),
    ):
        rec, tb = await time_call(label, factory)
        calls.append(rec)
        if tb:
            tbs[label] = tb
    out["calls"] = calls
    EV.mkdir(parents=True, exist_ok=True)
    (EV / "repro.json").write_text(json.dumps(out, indent=2) + "\n")
    (EV / "tracebacks.txt").write_text(
        "\n\n=====\n".join(f"{k}\n{v}" for k, v in tbs.items()) + "\n"
    )
    print(json.dumps(out, indent=2))
    print("\n--- TRACEBACKS ---")
    for key, val in tbs.items():
        print("====", key)
        print(val[:5000])


if __name__ == "__main__":
    asyncio.run(main())
