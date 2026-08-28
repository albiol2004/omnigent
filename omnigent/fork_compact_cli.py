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
_PROVIDER_PREFIXES = frozenset(("anthropic", "claude", "codex", "openai", "cursor"))
_CLAUDE_FLAGS = ("--output-format", "json", "--safe-mode", "--strict-mcp-config")
_CODEX_FLAGS = ("--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only", "-o")


def resolve_cli_runner(candidate: str) -> tuple[str, str, str] | None:
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    raw = candidate.strip().lower()
    prefix, separator, suffix = raw.partition("/")
    model = suffix if separator and prefix in _PROVIDER_PREFIXES else raw
    lowered = model
    if raw.startswith("cursor"):
        if shutil.which("cursor-agent") is not None:
            return "cursor-agent", model, f"cursor-cli/{model}"
        return "claude", "fable", "claude-cli/fable"
    if lowered in CLAUDE_MODEL_ALIASES or lowered.startswith("claude-"):
        alias = next((item for item in CLAUDE_MODEL_ALIASES if f"-{item}" in lowered), model)
        return "claude", alias, f"claude-cli/{alias}"
    codex_model = next((item for item in _CODEX_MODELS if item.lower() == lowered), None)
    if codex_model is not None:
        return "codex", codex_model, f"codex-cli/{codex_model}"
    return None


def _cli_argv(
    runner: str, model: str, _prompt: str, mcp_path: Path, output_path: Path
) -> list[str]:
    if runner == "claude":
        argv = [runner, "-p", "--model", model]
        argv.extend(_CLAUDE_FLAGS)
        argv.extend(["--mcp-config", str(mcp_path), "--no-session-persistence", "-"])
    elif runner == "codex":
        argv = [runner, "exec", "--model", model]
        argv.extend(_CODEX_FLAGS)
        argv.extend([str(output_path), "--", "-"])
    elif runner == "cursor-agent":
        argv = [runner, "-p", "--model", model, "-"]
    else:
        raise ValueError(f"Unsupported fork compaction CLI runner: {runner}")
    return argv


def _summary_text(runner: str, model: str, stdout: str, output_path: Path) -> str:
    text = stdout.strip()
    if runner == "codex":
        try:
            text = output_path.read_text(errors="replace").strip()
        except OSError as exc:
            raise ValueError(f"codex CLI returned no summary for model {model!r}") from exc
    if runner == "claude":
        try:
            events = json.loads(stdout)
            if isinstance(events, dict):
                events = [events]
            result = next(
                (
                    event
                    for event in reversed(events)
                    if isinstance(event, dict) and event.get("type") == "result"
                ),
                None,
            )
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"claude CLI returned no summary for model {model!r}") from exc
        if result is None:
            raise ValueError(f"claude CLI returned no result for model {model!r}")
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
    raw_timeout = str(timeout_s) if timeout_s is not None else os.environ.get(_TIMEOUT_ENV, "300")
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
        argv = _cli_argv(runner, model, prompt, mcp_path, output_path)
        env = dict(os.environ)
        for key in _AUTH_ENV_VARS:
            env.pop(key, None)
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **_proc.spawn_kwargs(),
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"{name} CLI not found for model {model!r}") from exc
        if on_started is not None:
            on_started()
        try:
            stdout, stderr = process.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise TimeoutError(
                f"{name} CLI timed out for model {model!r} after {timeout:g}s"
            ) from exc
        if process.returncode != 0:
            detail = (stderr or "").strip() or (stdout or "").strip()[:500]
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
        text = content if isinstance(content, str) else json.dumps(item, default=str)
        if text.strip() != _SUMMARIZATION_TRIGGER_MESSAGE:
            parts.append(f"{item.get('role') or item.get('type') or 'item'}: {text}")
    parts.append(_SUMMARIZATION_TRIGGER_MESSAGE)
    return "\n\n".join(parts)


class CliSummaryClient:
    """Tiny async client implementing Layer 2's ``responses`` surface."""

    def __init__(
        self, runner: str, model: str, on_started: Callable[[], None] | None = None
    ) -> None:
        self._runner = runner
        self._model = model
        self._on_started = on_started
        self.responses = self

    async def create(
        self,
        *,
        input: list[dict[str, Any]],
        instructions: str | None = None,
        **_: Any,
    ) -> Any:
        text = await asyncio.to_thread(
            run_cli_summary,
            _flatten_prompt(instructions, input),
            runner=self._runner,
            model=self._model,
            on_started=self._on_started,
        )
        return SimpleNamespace(output=[SimpleNamespace(content=[SimpleNamespace(text=text)])])
