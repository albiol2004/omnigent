"""CLI argv the claude_native bridge injects must match the hook module parser."""

from __future__ import annotations

import argparse
import re
import shlex
from pathlib import Path
from typing import Any

import pytest

from omnigent.harnesses.claude_native import bridge as claude_native_bridge
from omnigent.harnesses.claude_native import hook as claude_native_hook
from omnigent.harnesses.claude_native.bridge import augment_claude_args, build_hook_settings
from tests.harnesses.claude_native.test_claude_native_bridge import _load_invocation_settings

_HOOK_MODULE = "omnigent.harnesses.claude_native.hook"
_ALWAYS_REGISTERED = (
    "SessionStart",
    "SessionEnd",
    "Stop",
    "StopFailure",
    "UserPromptSubmit",
    "TaskCreated",
    "TaskCompleted",
    "PostToolUse",
    "PreCompact",
    "MessageDisplay",
)
_HOOK_INVOCATION = re.compile(
    r"env TMPDIR=(?P<tmpdir>\S+)\s+(?P<python>\S+)\s+-I\s+-m\s+"
    + re.escape(_HOOK_MODULE)
    + r"(?P<rest>(?:\s+(?!2>>)[^\s;]+)*"
    + r")"
)


def _walk_commands(node: Any) -> list[str]:
    commands: list[str] = []
    if isinstance(node, dict):
        command = node.get("command")
        if isinstance(command, str):
            commands.append(command)
        for value in node.values():
            commands.extend(_walk_commands(value))
    elif isinstance(node, list):
        for item in node:
            commands.extend(_walk_commands(item))
    return commands


def _invocations(command: str) -> list[list[str]]:
    found: list[list[str]] = []
    for match in _HOOK_INVOCATION.finditer(command):
        rest = match.group("rest")
        if "2>>" in rest:
            rest = rest.split("2>>", 1)[0]
        rest = rest.strip().rstrip(";").strip()
        joined = (
            f"env TMPDIR={match.group('tmpdir')} {match.group('python')} "
            f"-I -m {_HOOK_MODULE} {rest}"
        )
        found.append(shlex.split(joined.strip()))
    return found


def _parse_hook_argv(after_module: list[str]) -> argparse.Namespace:
    """Parse argv after ``-m omnigent.harnesses.claude_native.hook`` without side effects."""
    if after_module and not after_module[0].startswith("-"):
        subcommand, rest = after_module[0], after_module[1:]
    else:
        subcommand, rest = None, after_module
    if subcommand is None:
        return claude_native_hook._parse_args(rest)
    if subcommand in {"evaluate-policy", "framework-context", "pre-tool-use"}:
        return claude_native_hook._parse_evaluate_policy_args(rest)
    if subcommand == "permission-request":
        return claude_native_hook._parse_permission_args(rest)
    if subcommand == "observe-tool":
        parser = argparse.ArgumentParser()
        parser.add_argument("--bridge-dir", required=True)
        return parser.parse_args(rest)
    if subcommand == "route-turn":
        parser = argparse.ArgumentParser()
        parser.add_argument("--bridge-dir", required=True)
        parser.add_argument("--harness", default="claude-native")
        return parser.parse_args(rest)
    raise AssertionError(f"unrecognized hook subcommand {subcommand!r} in {after_module}")


def _assert_hook_argv(argv: list[str], *, trusted_tmpdir: Path, bridge_dir: Path) -> None:
    assert argv[0] == "env", argv
    assert argv[1].startswith("TMPDIR="), argv
    tmpdir = argv[1].removeprefix("TMPDIR=")
    assert Path(tmpdir).is_absolute(), tmpdir
    assert Path(tmpdir) == trusted_tmpdir, (tmpdir, trusted_tmpdir)
    assert argv[2:6] == [argv[2], "-I", "-m", _HOOK_MODULE], argv
    assert "--bridge-dir" in argv, argv
    injected_bridge = argv[argv.index("--bridge-dir") + 1]
    assert Path(injected_bridge).is_absolute(), injected_bridge
    assert Path(injected_bridge) == bridge_dir, (injected_bridge, bridge_dir)
    after_module = argv[argv.index(_HOOK_MODULE) + 1 :]
    parsed = _parse_hook_argv(after_module)
    assert Path(parsed.bridge_dir) == bridge_dir


def test_always_registered_hook_commands_match_hook_cli_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Always-registered Claude settings hooks pin TMPDIR and parse with the hook CLI.

    Covers PreCompact and every event ``build_hook_settings`` registers without
    optional policy/routing flags. MessageDisplay is a shell appender and is
    only required to be present.
    """
    trusted = tmp_path
    bridge_dir = trusted / "bridge"
    bridge_dir.mkdir()
    python = "/venv/bin/python"
    monkeypatch.setattr(claude_native_bridge, "_TRUSTED_PARENT", trusted)
    monkeypatch.setattr(claude_native_bridge, "_BRIDGE_ROOT", trusted)

    settings = build_hook_settings(bridge_dir, python_executable=python)
    hooks = settings["hooks"]
    assert isinstance(hooks, dict)
    missing = [name for name in _ALWAYS_REGISTERED if name not in hooks]
    assert not missing, missing

    python_events: set[str] = set()
    for event, entries in hooks.items():
        for command in _walk_commands(entries):
            invocations = _invocations(command)
            if invocations:
                python_events.add(str(event))
            for argv in invocations:
                _assert_hook_argv(argv, trusted_tmpdir=trusted, bridge_dir=bridge_dir)

    assert "PreCompact" in python_events
    for event in _ALWAYS_REGISTERED:
        if event == "MessageDisplay":
            continue
        assert event in python_events, event


def test_injected_optional_hook_commands_match_hook_cli_parser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permission, policy, observer, and route-turn hook argv parse without error."""
    trusted = tmp_path
    monkeypatch.setattr(claude_native_bridge, "_TRUSTED_PARENT", trusted)
    monkeypatch.setattr(claude_native_bridge, "_BRIDGE_ROOT", trusted)
    bridge_dir = trusted / "session"
    bridge_dir.mkdir()
    python = "/venv/bin/python"

    args = augment_claude_args(
        (),
        bridge_dir=bridge_dir,
        python_executable=python,
        ap_server_url="http://127.0.0.1:8787",
        turn_routing=True,
    )
    settings = _load_invocation_settings(args)
    invocations: list[list[str]] = []
    for command in _walk_commands(settings["hooks"]):
        invocations.extend(_invocations(command))
    assert invocations
    subcommands = {
        argv[argv.index(_HOOK_MODULE) + 1]
        for argv in invocations
        if argv[argv.index(_HOOK_MODULE) + 1 : argv.index(_HOOK_MODULE) + 2]
        and not argv[argv.index(_HOOK_MODULE) + 1].startswith("-")
    }
    assert "permission-request" in subcommands
    assert "evaluate-policy" in subcommands
    assert "route-turn" in subcommands
    assert "observe-tool" in subcommands
    assert "framework-context" in subcommands
    for argv in invocations:
        _assert_hook_argv(argv, trusted_tmpdir=trusted, bridge_dir=bridge_dir)
