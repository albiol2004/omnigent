"""Run fork-compaction summaries through installed subscription CLIs."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from omnigent.claude_model_vocabulary import CLAUDE_MODEL_ALIASES
from omnigent.inner import _proc
from omnigent.llms.summarize import _SUMMARIZATION_TRIGGER_MESSAGE
from omnigent.model_fallbacks import _CODEX_MODELS

_TIMEOUT_ENV = "OMNIGENT_FORK_COMPACT_CLI_TIMEOUT_S"
_AUTH_ENV_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def resolve_cli_runner(candidate: str) -> tuple[str, str, str] | None:
    """Map a model pin to ``(binary, argv_model, recorded_model)``."""
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    raw = candidate.strip()
    model = raw
    if "/" in raw and raw.split("/", 1)[0].lower() in {
        "anthropic",
        "claude",
        "codex",
        "openai",
        "cursor",
    }:
        model = raw.split("/", 1)[1]
    lowered = model.lower()
    if raw.lower().startswith("cursor"):
        if shutil.which("cursor-agent") is not None:
            return "cursor-agent", model, f"cursor-cli/{model}"
        return "claude", "fable", "claude-cli/fable"
    if lowered in CLAUDE_MODEL_ALIASES or lowered.startswith("claude-"):
        alias = next(
            (item for item in CLAUDE_MODEL_ALIASES if f"-{item}" in lowered),
            lowered if lowered in CLAUDE_MODEL_ALIASES else model,
        )
        return "claude", alias, f"claude-cli/{alias}"
    codex_model = next((item for item in _CODEX_MODELS if item.lower() == lowered), None)
    if codex_model is not None:
        return "codex", codex_model, f"codex-cli/{codex_model}"
    return None


def _summary_text(runner: str, model: str, stdout: str, output_path: Path) -> str:
    if runner == "codex":
        try:
            text = output_path.read_text(errors="replace").strip()
        except OSError as exc:
            raise ValueError(f"codex CLI returned no summary for model {model!r}") from exc
    elif runner == "cursor-agent":
        text = stdout.strip()
    else:
        try:
            events = json.loads(stdout)
            result = next(
                event
                for event in reversed(events)
                if isinstance(event, dict) and event.get("type") == "result"
            )
        except (json.JSONDecodeError, StopIteration, TypeError) as exc:
            raise ValueError(f"claude CLI returned no result for model {model!r}") from exc
        if result.get("is_error"):
            detail = str(result.get("result") or "unknown CLI error")
            raise ValueError(f"claude CLI returned an error for model {model!r}: {detail}")
        value = result.get("result")
        text = value.strip() if isinstance(value, str) else ""
    if not text:
        raise ValueError(f"{runner} CLI returned an empty summary for model {model!r}")
    return text


def run_cli_summary(
    prompt: str,
    *,
    runner: str,
    model: str,
    timeout_s: float | None = None,
    on_started: Callable[[], None] | None = None,
) -> str:
    """Run one summary in a temporary working directory."""
    name = Path(runner).name
    if shutil.which(runner) is None:
        raise FileNotFoundError(f"{name} CLI not found for model {model!r}")
    raw_timeout = (
        str(timeout_s) if timeout_s is not None else os.environ.get(_TIMEOUT_ENV, "300")
    )
    try:
        timeout = float(raw_timeout)
    except ValueError as exc:
        raise ValueError(f"{_TIMEOUT_ENV} must be a positive number") from exc
    if timeout <= 0:
        raise ValueError(f"{_TIMEOUT_ENV} must be a positive number")
    with tempfile.TemporaryDirectory(prefix="omnigent-fork-compact-") as temp_dir:
        cwd = Path(temp_dir)
        mcp_path = cwd / "empty-mcp.json"
        output_path = cwd / "last-message.txt"
        mcp_path.write_text('{"mcpServers":{}}', encoding="utf-8")
        if runner == "claude":
            argv = [
                runner,
                "-p",
                "--model",
                model,
                "--output-format",
                "json",
                "--safe-mode",
                "--strict-mcp-config",
                "--mcp-config",
                str(mcp_path),
                "--no-session-persistence",
                prompt,
            ]
        elif runner == "codex":
            argv = [
                runner,
                "exec",
                "--model",
                model,
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "-o",
                str(output_path),
                "--",
                prompt,
            ]
        elif runner == "cursor-agent":
            argv = [
                runner,
                "-p",
                "--output-format",
                "text",
                "--model",
                model,
                "--workspace",
                str(cwd),
                prompt,
            ]
        else:
            raise ValueError(f"Unsupported fork compaction CLI runner: {runner}")
        env = dict(os.environ)
        for key in _AUTH_ENV_VARS:
            env.pop(key, None)
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **_proc.spawn_kwargs(),
        )
        if on_started is not None:
            on_started()
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise TimeoutError(
                f"{name} CLI timed out for model {model!r} after {timeout:g}s"
            ) from exc
        if process.returncode != 0:
            detail = stderr.strip()
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(
                f"{name} CLI failed for model {model!r} with exit code "
                f"{process.returncode}{suffix}"
            )
        return _summary_text(name, model, stdout, output_path)


def _flatten_prompt(instructions: str | None, input_items: list[dict[str, Any]]) -> str:
    """Flatten Responses input and keep the summary trigger last."""
    parts = [instructions.strip()] if instructions and instructions.strip() else []
    for item in input_items:
        content = item.get("content")
        text = content if isinstance(content, str) else json.dumps(
            item, ensure_ascii=False, default=str
        )
        if text.strip() != _SUMMARIZATION_TRIGGER_MESSAGE:
            parts.append(f"{item.get('role') or item.get('type') or 'item'}: {text}")
    parts.append(_SUMMARIZATION_TRIGGER_MESSAGE)
    return "\n\n".join(parts)


class _CliResponses:
    """Minimal Responses API namespace backed by one CLI process."""

    def __init__(
        self,
        runner: str,
        model: str,
        on_started: Callable[[], None] | None,
    ) -> None:
        self._runner = runner
        self._model = model
        self._on_started = on_started

    async def create(
        self,
        *,
        input: list[dict[str, Any]],
        instructions: str | None = None,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        connection_params: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        del model, tools, connection_params, kwargs
        text = await asyncio.to_thread(
            run_cli_summary,
            _flatten_prompt(instructions, input),
            runner=self._runner,
            model=self._model,
            timeout_s=None,
            on_started=self._on_started,
        )
        return SimpleNamespace(output=[SimpleNamespace(content=[SimpleNamespace(text=text)])])


class CliSummaryClient:
    """Tiny async client implementing Layer 2's ``responses`` surface."""

    def __init__(
        self,
        runner: str,
        model: str,
        on_started: Callable[[], None] | None = None,
    ) -> None:
        self.responses = _CliResponses(runner, model, on_started)
