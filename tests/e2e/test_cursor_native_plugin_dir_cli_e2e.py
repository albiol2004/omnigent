"""Real-CLI check of the cursor-native ``--plugin-dir`` route (r17).

Verifies the cursor-agent behaviour :func:`write_cursor_plugin` and
:func:`write_plugin_stop_armer` rely on, against the installed CLI:

1. a plugin laid out by ``write_cursor_plugin`` loads with ``--plugin-dir`` and
   its MCP server is callable with no project ``.cursor/mcp.json``;
2. in the interactive TUI, two sessions in ONE workspace with different plugin
   dirs each get only their own plugin ``stop`` hook, once the project
   ``hooks.json`` carries the constant armer (cursor-agent dispatches ``stop``
   only when a user/project stop hook exists).

3. a LIVE project-route sibling's usage hook left in the project ``hooks.json``
   does not record the plugin session's turns (the recorder skips a firing
   whose ``--bridge-dir`` is not the TUI's ``OMNIGENT_CURSOR_SESSION_BRIDGE_DIR``);
4. a LIVE project-route sibling's ``omnigent`` server left in the project
   ``mcp.json`` refuses to serve the plugin session (``serve-mcp`` reads the
   marker from its parent cursor-agent), while the sibling keeps its own server.

The MCP server and hook commands are swapped for trivial probes (the layout and
the armer are the real ones), so no Omnigent server is needed; test 3 runs the
real recorder from this tree. **Opt-in only** (paid real-model turns): set
``OMNIGENT_E2E_CURSOR_NATIVE=1``; also needs an authenticated ``cursor-agent``
and ``tmux``. Cleans up the workspace's Cursor chat/project state.

Run::

    OMNIGENT_E2E_CURSOR_NATIVE=1 \
        .venv/bin/python -m pytest tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py -v
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from omnigent.harnesses.cursor_native import bridge as cb

#: The production bridge root (tests below monkeypatch ``cb._BRIDGE_ROOT``);
#: the real ``serve-mcp`` accepts only bridge dirs under it.
_REAL_BRIDGE_ROOT = cb._BRIDGE_ROOT

pytestmark = pytest.mark.skipif(
    os.environ.get("OMNIGENT_E2E_CURSOR_NATIVE") != "1"
    or shutil.which("cursor-agent") is None
    or shutil.which("tmux") is None,
    reason="opt-in real-CLI e2e: set OMNIGENT_E2E_CURSOR_NATIVE=1; needs the "
    "cursor-agent CLI (authenticated) and tmux",
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


def _wait_idle(sock: Path, targets: list[str], timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not all(
        any(m in _tmux(sock, "capture-pane", "-p", "-t", t) for m in cb._IDLE_MARKERS)
        for t in targets
    ):
        time.sleep(1)


def test_live_sibling_project_hook_skips_plugin_session_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    """Mixed rollout: a sibling's project usage hook must not bill our turns."""
    from omnigent.harnesses.cursor_native import status as cursor_native_status
    from omnigent.harnesses.cursor_native import usage as cursor_native_usage

    tree = Path(__file__).resolve().parents[2]

    def recorder(bridge: Path) -> str:
        # This tree's recorder (``-I`` dropped so PYTHONPATH wins over the install).
        return (
            f"env PYTHONPATH={shlex.quote(str(tree))} {shlex.quote(sys.executable)} -m "
            f"omnigent.harnesses.cursor_native.usage record-usage --bridge-dir "
            f"{shlex.quote(str(bridge))}"
        )

    _probe_plugin(tmp_path, monkeypatch, "A")
    monkeypatch.setattr(
        cb,
        "build_hooks_config",
        lambda b, **_k: {"version": 1, "hooks": {"stop": [{"command": recorder(b)}]}},
    )
    own = tmp_path / "cb" / "own"
    sibling = tmp_path / "cb" / "sibling"
    sibling.mkdir(parents=True)
    plugin_dir = cb.write_cursor_plugin(own)
    (workspace / ".cursor").mkdir()
    (workspace / ".cursor" / "hooks.json").write_text(
        json.dumps(
            {
                "version": 1,
                "hooks": {
                    "stop": [
                        {"command": recorder(sibling)},
                        {"command": cb.PLUGIN_STOP_ARMER_COMMAND},
                    ]
                },
            }
        )
    )
    sock = tmp_path / "tmux.sock"
    own_turn_end = own / cursor_native_status.TURN_END_FILE
    try:
        command = (
            f"env {cursor_native_usage.SESSION_BRIDGE_ENV_VAR}={shlex.quote(str(own))} "
            f"cursor-agent --trust --approve-mcps --plugin-dir {shlex.quote(str(plugin_dir))}"
        )
        _tmux(sock, "new-session", "-d", "-s", "A", "-x", "200", "-y", "50", "-c",
              str(workspace), command)  # fmt: skip
        _wait_idle(sock, ["A"])
        _tmux(sock, "send-keys", "-t", "A", "-l", "Reply with the single word: hi")
        time.sleep(2)
        _tmux(sock, "send-keys", "-t", "A", "Enter")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not (
            own_turn_end.exists() and own_turn_end.read_text().strip()
        ):
            time.sleep(2)
        time.sleep(5)  # the sibling hook runs in the same stop dispatch
        pane = _tmux(sock, "capture-pane", "-p", "-t", "A")
    finally:
        _tmux(sock, "kill-server")
    assert own_turn_end.exists(), pane
    assert len(own_turn_end.read_text().splitlines()) == 1
    assert (own / cursor_native_usage.USAGE_FILE).read_text().strip()
    assert list(sibling.iterdir()) == []


def test_live_sibling_project_mcp_refuses_plugin_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace: Path
) -> None:
    """Mixed rollout (r17 N11): a sibling's project ``omnigent`` server never serves us."""
    import tempfile

    from omnigent.harnesses.cursor_native import usage as cursor_native_usage

    tree = Path(__file__).resolve().parents[2]
    plugin_dir, own_mcp_log, _ = _probe_plugin(tmp_path, monkeypatch, "A")
    own = plugin_dir.parents[1]
    _REAL_BRIDGE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    sibling = Path(tempfile.mkdtemp(prefix="e2e-n11-sibling-", dir=_REAL_BRIDGE_ROOT))
    sibling_stderr = tmp_path / "sibling_serve_mcp.stderr"
    sock = tmp_path / "tmux.sock"
    try:
        (sibling / "bridge.json").write_text(
            json.dumps({"token": "e2e-n11", "workspace": str(workspace)})
        )
        # The project-route sibling's server entry, running this tree's serve-mcp
        # (``exec`` keeps cursor-agent the server's parent).
        serve = (
            f"exec env PYTHONPATH={shlex.quote(str(tree))} {shlex.quote(sys.executable)} -m "
            f"omnigent.harnesses.claude_native.bridge serve-mcp --bridge-dir "
            f"{shlex.quote(str(sibling))} 2>>{shlex.quote(str(sibling_stderr))}"
        )
        (workspace / ".cursor").mkdir()
        (workspace / ".cursor" / "mcp.json").write_text(
            json.dumps({"mcpServers": {"omnigent": {"command": "sh", "args": ["-c", serve]}}})
        )
        # The live sibling: a project-route TUI (no marker) serving its bridge.
        _tmux(sock, "new-session", "-d", "-s", "S", "-x", "200", "-y", "50", "-c",
              str(workspace), "cursor-agent --trust --approve-mcps")  # fmt: skip
        server_file = sibling / "server.json"
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline and not server_file.exists():
            time.sleep(1)
        assert server_file.exists(), _tmux(sock, "capture-pane", "-p", "-t", "S")
        _wait_idle(sock, ["S"])
        # Our plugin-route session in the same workspace.
        command = (
            f"env {cursor_native_usage.SESSION_BRIDGE_ENV_VAR}={shlex.quote(str(own))} "
            f"cursor-agent --trust --approve-mcps --plugin-dir {shlex.quote(str(plugin_dir))}"
        )
        _tmux(sock, "new-session", "-d", "-s", "A", "-x", "200", "-y", "50", "-c",
              str(workspace), command)  # fmt: skip
        _wait_idle(sock, ["A"])
        prompt = "Call the MCP tool probe_secret, then try the MCP tool sys_os_read on README."
        _tmux(sock, "send-keys", "-t", "A", "-l", prompt)
        time.sleep(2)
        _tmux(sock, "send-keys", "-t", "A", "Enter")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline and not (
            own_mcp_log.exists() and '"tools/call"' in own_mcp_log.read_text()
        ):
            time.sleep(2)
        time.sleep(5)
        pane = _tmux(sock, "capture-pane", "-p", "-t", "A")
        # The sibling's bridge still points at a server the SIBLING spawned (cursor
        # spawns its servers more than once, so compare parents, not pids).
        serving = json.loads(server_file.read_text())["pid"]
        parent = Path(f"/proc/{serving}/stat").read_text().rsplit(")", 1)[1].split()[1]
        parent_env = Path(f"/proc/{parent}/environ").read_bytes()
        assert cursor_native_usage.SESSION_BRIDGE_ENV_VAR.encode() not in parent_env
    finally:
        _tmux(sock, "kill-server")
        shutil.rmtree(sibling, True)
    assert '"tools/call"' in own_mcp_log.read_text(), pane
    refusals = [ln for ln in sibling_stderr.read_text().splitlines() if "refused" in ln]
    # One line per refused server process (cursor-agent spawns its servers twice).
    assert refusals, sibling_stderr.read_text()
    assert all(str(sibling) in ln and str(own) in ln for ln in refusals)
