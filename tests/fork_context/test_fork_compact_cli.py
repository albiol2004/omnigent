"""Tests for CLI-backed fork compaction."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import omnigent.fork_compact as fork_compact
from omnigent.fork_compact_cli import resolve_cli_runner, run_cli_summary
from omnigent.llms.summarize import extract_summary_text
from omnigent.model_fallbacks import _CODEX_MODELS
from omnigent.runtime.compaction import SummaryMetadata

_AUTH_KEYS = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _install_fake_claude(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    stdout: str,
    exit_code: int = 0,
    sleep_s: float = 0,
    stderr: str = "",
) -> Path:
    """Install a fake Claude executable and return its record path."""
    record = tmp_path / "record.json"
    script = tmp_path / "claude"
    script.write_text(
        f"""#!{sys.executable}
import json, os, sys, time
from pathlib import Path

argv = sys.argv[1:]
Path(os.environ["FAKE_CLAUDE_RECORD"]).write_text(json.dumps({{
    "argv": argv, "cwd": os.getcwd(),
    "stdin": sys.stdin.read(),
    "auth": {{key: os.environ.get(key) for key in {_AUTH_KEYS!r}}},
    "mcp": Path(argv[8]).read_text(),
    "claude_config": os.environ.get("CLAUDE_CONFIG_DIR"),
}}))
time.sleep({sleep_s!r})
print({stdout!r})
if {stderr!r}:
    print({stderr!r}, file=sys.stderr)
sys.exit({exit_code})
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", os.pathsep.join((str(tmp_path), os.environ.get("PATH", ""))))
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    return record


def test_claude_argv_environment_and_json_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for key in _AUTH_KEYS:
        monkeypatch.setenv(key, "must-not-leak")
    record = _install_fake_claude(
        monkeypatch,
        tmp_path,
        stdout=json.dumps(
            [
                {"type": "assistant"},
                {"type": "result", "is_error": False, "result": "SUM"},
            ]
        ),
    )
    started: list[bool] = []
    assert (
        run_cli_summary(
            "summarize this",
            runner="claude",
            model="fable",
            on_started=lambda: started.append(True),
        )
        == "SUM"
    )

    data = json.loads(record.read_text(encoding="utf-8"))
    argv = data["argv"]
    assert started == [True]
    assert argv[:6] == ["-p", "--model", "fable", "--output-format", "json", "--safe-mode"]
    assert argv[6:10] == [
        "--strict-mcp-config",
        "--mcp-config",
        argv[8],
        "--no-session-persistence",
    ]
    assert argv[-1] == "-"
    assert data["stdin"] == "summarize this"
    assert data["mcp"] == '{"mcpServers":{}}'
    assert Path(data["cwd"]).name.startswith("omnigent-fork-compact-")
    assert Path(data["cwd"]).is_relative_to(Path(tempfile.gettempdir()))
    assert all(value is None for value in data["auth"].values())


@pytest.mark.parametrize(
    ("sleep_s", "exit_code", "stderr", "expected"),
    [(1, 0, "", TimeoutError), (0, 7, "boom", RuntimeError)],
)
def test_cli_failures_name_runner_and_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sleep_s: float,
    exit_code: int,
    stderr: str,
    expected: type[Exception],
) -> None:
    _install_fake_claude(
        monkeypatch,
        tmp_path,
        stdout="",
        sleep_s=sleep_s,
        exit_code=exit_code,
        stderr=stderr,
    )
    timeout = 0.02 if sleep_s else 1
    monkeypatch.setenv("OMNIGENT_FORK_COMPACT_CLI_TIMEOUT_S", str(timeout))
    with pytest.raises(expected, match=r"claude CLI.*fable"):
        run_cli_summary("prompt", runner="claude", model="fable")


def test_missing_cli_fails_before_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="claude CLI not found"):
        run_cli_summary("prompt", runner="claude", model="fable")


def test_resolve_cli_runner_records_subscription_models() -> None:
    assert resolve_cli_runner("fable") == ("claude", "fable", "claude-cli/fable")
    assert resolve_cli_runner("FABLE") == resolve_cli_runner("fable")
    assert resolve_cli_runner("claude-fable-5") == resolve_cli_runner("fable")
    slug = _CODEX_MODELS[1]
    assert resolve_cli_runner(slug) == ("codex", slug, f"codex-cli/{slug}")


@pytest.mark.asyncio
async def test_compact_fork_items_uses_cli_model_and_ready_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _install_fake_claude(
        monkeypatch,
        tmp_path,
        stdout=json.dumps([{"type": "result", "is_error": False, "result": "SUM"}]),
    )
    monkeypatch.delenv("OMNIGENT_FORK_COMPACT_MODEL", raising=False)
    monkeypatch.delenv("OMNIGENT_FORK_COMPACT_ALLOW_API", raising=False)
    source_spec = SimpleNamespace(
        llm=None,
        executor=SimpleNamespace(model="fable", connection=None, context_window=128_000),
        compaction=None,
    )
    monkeypatch.setattr(fork_compact, "_load_spec", lambda *_args: source_spec)
    monkeypatch.setattr(
        "omnigent.runtime.workflow._prepare_messages",
        lambda *_args, **_kwargs: ("", [], 0),
    )
    monkeypatch.setattr(fork_compact, "_replacement_items", lambda *_args: [])
    ready: list[object] = []

    async def fake_compact(*_args: object, **kwargs: object) -> object:
        assert kwargs["model"] == "claude-cli/fable"
        response = await kwargs["llm_client"].responses.create(
            input=[{"role": "user", "content": "conversation"}],
            instructions="system",
            model=kwargs["model"],
        )
        assert extract_summary_text(response) == "SUM"
        return SimpleNamespace(summary_metadata=SummaryMetadata("SUM", "item", kwargs["model"], 1))

    monkeypatch.setattr(fork_compact, "compact", fake_compact)
    await fork_compact.compact_fork_items(
        source_id="source",
        source=SimpleNamespace(model_override="fable"),
        source_agent=object(),
        target_agent=None,
        context_items=[],
        agent_cache=object(),
        on_llm_ready=ready.append,
    )

    assert ready[0].model == "claude-cli/fable"
    prompt = json.loads(record.read_text())["stdin"]
    assert prompt.index("system") < prompt.index("conversation")
    assert prompt.index("conversation") < prompt.index("Produce the summary now")
