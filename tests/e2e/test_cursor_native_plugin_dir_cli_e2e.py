"""Real-CLI check of the cursor-native ``--plugin-dir`` route (r17).

Verifies the cursor-agent behaviour :func:`write_cursor_plugin` and
:func:`write_plugin_stop_armer` rely on, against the installed CLI:

1. a plugin laid out by ``write_cursor_plugin`` loads with ``--plugin-dir`` and
   its MCP server is callable with no project ``.cursor/mcp.json``;
2. in the interactive TUI, two sessions in ONE workspace with different plugin
   dirs each get only their own plugin ``stop`` hook, once the project
   ``hooks.json`` carries the constant armer (cursor-agent dispatches ``stop``
   only when a user/project stop hook exists).

The MCP server and hook commands are swapped for trivial probes (the layout and
the armer are the real ones), so no Omnigent server is needed. Needs an
authenticated ``cursor-agent`` (real model turns) and ``tmux``; skipped when
either binary is missing. Cleans up the workspace's Cursor chat/project state.

Run::

    .venv/bin/python -m pytest tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py -v
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from omnigent.harnesses.cursor_native import bridge as cb

pytestmark = pytest.mark.skipif(
    shutil.which("cursor-agent") is None or shutil.which("tmux") is None,
    reason="needs the cursor-agent CLI (authenticated) and tmux",
)

_PROBE_SERVER = r"""
import json, sys
tag, log = sys.argv[1], open(sys.argv[2], "a")
for line in sys.stdin:
    if not line.strip():
        continue
    msg = json.loads(line)
    log.write(line if line.endswith("\n") else line + "\n"); log.flush()
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        continue
    if method == "initialize":
        res = {"protocolVersion": msg["params"].get("protocolVersion", "2024-11-05"),
               "capabilities": {"tools": {}}, "serverInfo": {"name": "probe", "version": "1"}}
    elif method == "tools/list":
        res = {"tools": [{"name": "probe_secret", "description": "Returns the probe secret.",
                          "inputSchema": {"type": "object", "properties": {}}}]}
    elif method == "tools/call":
        res = {"content": [{"type": "text", "text": "SECRET-" + tag}]}
    else:
        res = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
    sys.stdout.flush()
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    """A git-rooted workspace (so Cursor's project root is the workspace itself)."""
    ws = (tmp_path / "ws").resolve()
    ws.mkdir()
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    yield ws
    home = Path.home() / ".cursor"
    shutil.rmtree(home / "chats" / hashlib.md5(str(ws).encode()).hexdigest(), True)
    shutil.rmtree(home / "projects" / cb.cursor_project_key(ws), True)


def _probe_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str
) -> tuple[Path, Path, Path]:
    """Lay out a real plugin whose server/hook are probes; returns (dir, mcp log, stop log)."""
    monkeypatch.setattr(cb, "_BRIDGE_ROOT", tmp_path / "cb")
    monkeypatch.setattr(cb, "allow_mcp_tools_in_cli_config", lambda *_a: None)
    server = tmp_path / "probe_server.py"
    server.write_text(_PROBE_SERVER)
    mcp_log, stop_log = tmp_path / f"mcp_{tag}.log", tmp_path / f"stop_{tag}.jsonl"
    monkeypatch.setattr(
        cb,
        "build_mcp_config",
        lambda _b, **_k: {
            "mcpServers": {
                "omnigent": {"command": sys.executable, "args": [str(server), tag, str(mcp_log)]}
            }
        },
    )
    monkeypatch.setattr(
        cb,
        "build_hooks_config",
        lambda _b, **_k: {
            "version": 1,
            "hooks": {"stop": [{"command": f"sh -c 'cat >> {stop_log}; echo >> {stop_log}'"}]},
        },
    )
    plugin_dir = cb.write_cursor_plugin(tmp_path / "cb" / tag)
    return plugin_dir, mcp_log, stop_log


def test_plugin_mcp_server_loads_without_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    plugin_dir, mcp_log, _ = _probe_plugin(tmp_path, monkeypatch, "A")
    out = subprocess.run(
        ["cursor-agent", "-p", "--trust", "--force", "--plugin-dir", str(plugin_dir),
         "--workspace", str(workspace),
         "Call the MCP tool probe_secret and reply with exactly what it returns."],
        cwd=workspace, capture_output=True, text=True, timeout=240, check=False,
    )  # fmt: skip
    assert "SECRET-A" in out.stdout, out.stdout + out.stderr
    assert '"tools/call"' in mcp_log.read_text()
    assert not (workspace / ".cursor").exists()


def _tmux(sock: Path, *args: str) -> str:
    return subprocess.run(
        ["tmux", "-S", str(sock), *args], capture_output=True, text=True, check=False
    ).stdout


def test_same_workspace_tui_sessions_get_own_stop_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    plugins = {tag: _probe_plugin(tmp_path, monkeypatch, tag) for tag in ("A", "B")}
    assert cb.write_plugin_stop_armer(workspace) is not None
    sock = tmp_path / "tmux.sock"
    try:
        for tag, (plugin_dir, _, _) in plugins.items():
            command = f"cursor-agent --trust --approve-mcps --plugin-dir {plugin_dir}"
            _tmux(sock, "new-session", "-d", "-s", tag, "-x", "200", "-y", "50", "-c",
                  str(workspace), command)  # fmt: skip
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and not all(
            any(m in _tmux(sock, "capture-pane", "-p", "-t", t) for m in cb._IDLE_MARKERS)
            for t in plugins
        ):
            time.sleep(1)
        for tag in plugins:
            _tmux(sock, "send-keys", "-t", tag, "-l", "Call the MCP tool probe_secret.")
        time.sleep(2)
        for tag in plugins:
            _tmux(sock, "send-keys", "-t", tag, "Enter")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not all(
            s.exists() and s.read_text().strip() for _, _, s in plugins.values()
        ):
            time.sleep(2)
        time.sleep(5)  # a crossed hook would land a little later
        panes = {t: _tmux(sock, "capture-pane", "-p", "-t", t) for t in plugins}
    finally:
        _tmux(sock, "kill-server")
    conversations = {}
    for tag, (_, mcp_log, stop_log) in plugins.items():
        assert stop_log.exists(), panes[tag]
        lines = [json.loads(x) for x in stop_log.read_text().splitlines() if x.strip()]
        assert len(lines) == 1, (tag, lines)
        conversations[tag] = lines[0]["conversation_id"]
        assert '"tools/call"' in mcp_log.read_text()
    assert conversations["A"] != conversations["B"]
