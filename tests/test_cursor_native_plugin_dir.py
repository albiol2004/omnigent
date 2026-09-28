"""Unit tests for the cursor-native per-launch ``--plugin-dir`` config route.

The route (``OMNIGENT_CURSOR_PLUGIN_DIR=1``) gives each session its own Cursor
plugin under its bridge dir carrying the Omnigent MCP server and the usage
``stop`` hook, instead of the single-slot project ``.cursor/{hooks,mcp}.json``.
Only a constant no-op ``stop`` entry (the "armer") is merged into the project
``hooks.json``: cursor-agent dispatches ``stop`` to plugin hooks only when the
user or project hooks file declares one (verified against the 2026.09.26 CLI).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omnigent.harnesses.cursor_native import bridge as cb
from omnigent.harnesses.cursor_native import status as cursor_native_status


@pytest.fixture(autouse=True)
def _bridge_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bridge dirs live under ``tmp_path / "cb"`` (the secure-dir allowlist root)."""
    monkeypatch.setattr(cb, "_BRIDGE_ROOT", tmp_path / "cb")


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private HOME with a Cursor CLI config, so no test touches the real one."""
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    (home / ".cursor" / "cli-config.json").write_text(
        json.dumps({"permissions": {"allow": ["Shell(ls)"], "deny": []}})
    )
    monkeypatch.setenv("HOME", str(home))
    return home


def _stop_hooks(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text())["hooks"]["stop"]


def _owned(bridge: Path) -> dict[str, str]:
    return cb.build_hooks_config(bridge)["hooks"]["stop"][0]  # type: ignore[index]


@pytest.mark.parametrize(
    ("value", "enabled"),
    [("1", True), ("true", True), ("ON", True), (" yes ", True), ("0", False), ("", False)],
)
def test_plugin_dir_mode_flag(value: str, enabled: bool) -> None:
    assert cb.plugin_dir_mode_enabled({cb.PLUGIN_DIR_ENV_VAR: value}, config={}) is enabled


def test_plugin_dir_mode_defaults_off() -> None:
    assert cb.plugin_dir_mode_enabled({}, config={}) is False


@pytest.mark.parametrize(
    ("setting", "enabled"),
    [(True, True), ("on", True), (False, False), ("0", False), (1, False), (None, False)],
)
def test_plugin_dir_mode_config_switch(setting: object, enabled: bool) -> None:
    config = {cb.PLUGIN_DIR_CONFIG_SECTION: {cb.PLUGIN_DIR_CONFIG_KEY: setting}}
    assert cb.plugin_dir_mode_enabled({}, config=config) is enabled


def test_plugin_dir_mode_env_overrides_config() -> None:
    on = {cb.PLUGIN_DIR_CONFIG_SECTION: {cb.PLUGIN_DIR_CONFIG_KEY: True}}
    assert cb.plugin_dir_mode_enabled({cb.PLUGIN_DIR_ENV_VAR: "0"}, config=on) is False
    assert cb.plugin_dir_mode_enabled({cb.PLUGIN_DIR_ENV_VAR: "1"}, config={}) is True


def test_plugin_dir_mode_reads_user_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIGENT_CONFIG_HOME", str(tmp_path))
    assert cb.plugin_dir_mode_enabled({}) is False
    (tmp_path / "config.yaml").write_text("cursor_native:\n  plugin_dir: true\n")
    assert cb.plugin_dir_mode_enabled({}) is True
    (tmp_path / "config.yaml").write_text("cursor_native: [unclosed\n")
    assert cb.plugin_dir_mode_enabled({}) is False


def test_plugin_dir_basename_fixes_server_id(tmp_path: Path) -> None:
    """cursor-agent ids plugin servers ``plugin-<dir basename>-<server>``."""
    plugin_dir = cb.plugin_dir_for_bridge(tmp_path / "cb" / "bridge")
    assert plugin_dir.is_relative_to(tmp_path / "cb" / "bridge")
    assert f"plugin-{plugin_dir.name}-omnigent" == cb.PLUGIN_MCP_SERVER_ID


class TestWriteCursorPlugin:
    def test_layout_binds_only_this_bridge(self, tmp_path: Path, home: Path) -> None:
        del home
        bridge = tmp_path / "cb" / "bridge"
        plugin_dir = cb.write_cursor_plugin(bridge, python_executable="/usr/bin/python3")
        assert plugin_dir == cb.plugin_dir_for_bridge(bridge)
        manifest = json.loads((plugin_dir / ".cursor-plugin" / "plugin.json").read_text())
        assert manifest["name"] == "omnigent"
        mcp = json.loads((plugin_dir / "mcp.json").read_text())
        assert mcp == cb.build_mcp_config(bridge, python_executable="/usr/bin/python3")
        hooks = json.loads((plugin_dir / "hooks" / "hooks.json").read_text())
        assert hooks == cb.build_hooks_config(bridge, python_executable="/usr/bin/python3")
        assert cb.is_owned_usage_hook_command(hooks["hooks"]["stop"][0]["command"])
        assert (bridge / "bridge.json").is_file()  # relay token for serve-mcp

    def test_does_not_touch_the_workspace(self, tmp_path: Path, home: Path) -> None:
        del home
        ws = tmp_path / "ws"
        ws.mkdir()
        cb.write_cursor_plugin(tmp_path / "cb" / "bridge", workspace=ws)
        assert list(ws.iterdir()) == []

    def test_allows_tools_under_plugin_server_id(self, tmp_path: Path, home: Path) -> None:
        cb.write_cursor_plugin(tmp_path / "cb" / "bridge")
        cb.write_cursor_plugin(tmp_path / "cb" / "bridge2")  # idempotent across sessions
        allow = json.loads((home / ".cursor" / "cli-config.json").read_text())["permissions"][
            "allow"
        ]
        assert f"Mcp({cb.PLUGIN_MCP_SERVER_ID}:sys_os_read)" in allow
        assert len(allow) == len(set(allow))
        assert not any(a.startswith("Mcp(omnigent:") for a in allow)

    def test_reenables_disabled_plugin_server(self, tmp_path: Path, home: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        disabled = home / ".cursor" / "projects" / cb.cursor_project_key(ws) / "mcp-disabled.json"
        disabled.parent.mkdir(parents=True)
        disabled.write_text(json.dumps([cb.PLUGIN_MCP_SERVER_ID, "other"]))
        cb.write_cursor_plugin(tmp_path / "cb" / "bridge", workspace=ws)
        assert json.loads(disabled.read_text()) == ["other"]

    def test_two_sessions_get_separate_plugins(self, tmp_path: Path, home: Path) -> None:
        del home
        a = cb.write_cursor_plugin(tmp_path / "cb" / "a")
        b = cb.write_cursor_plugin(tmp_path / "cb" / "b")
        assert a != b
        assert str(tmp_path / "cb" / "a") in (a / "hooks" / "hooks.json").read_text()
        assert str(tmp_path / "cb" / "b") not in (a / "hooks" / "hooks.json").read_text()
        assert str(tmp_path / "cb" / "b") in (b / "mcp.json").read_text()


class TestPluginStopArmer:
    def test_writes_constant_armer(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        path = cb.write_plugin_stop_armer(ws, home=tmp_path / "home")
        assert path == ws / ".cursor" / "hooks.json"
        assert _stop_hooks(path) == [{"command": cb.PLUGIN_STOP_ARMER_COMMAND}]
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        assert cb.write_plugin_stop_armer(ws, home=tmp_path / "home") == path
        assert path.read_bytes() == before
        assert path.stat().st_mtime_ns == mtime  # no rewrite when already armed

    def test_preserves_foreign_hooks(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        (ws / ".cursor").mkdir(parents=True)
        (ws / ".cursor" / "hooks.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "hooks": {
                        "preToolUse": [{"command": "./policy.sh"}],
                        "stop": [{"command": "./mine.sh"}],
                    },
                }
            )
        )
        path = cb.write_plugin_stop_armer(ws, home=tmp_path / "home")
        assert path is not None
        data = json.loads(path.read_text())
        assert data["hooks"]["preToolUse"] == [{"command": "./policy.sh"}]
        assert data["hooks"]["stop"] == [
            {"command": "./mine.sh"},
            {"command": cb.PLUGIN_STOP_ARMER_COMMAND},
        ]

    def test_drops_dead_project_route_hook_keeps_live(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        dead, live = tmp_path / "cb" / "dead", tmp_path / "cb" / "live"
        dead.mkdir(parents=True)
        live.mkdir(parents=True)
        (ws / ".cursor").mkdir(parents=True)
        (ws / ".cursor" / "hooks.json").write_text(
            json.dumps({"version": 1, "hooks": {"stop": [_owned(dead), _owned(live)]}})
        )
        path = cb.write_plugin_stop_armer(
            ws, home=tmp_path / "home", is_live=lambda b: b.name == "live"
        )
        assert path is not None
        assert _stop_hooks(path) == [_owned(live), {"command": cb.PLUGIN_STOP_ARMER_COMMAND}]

    def test_shared_user_scope_is_left_alone(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        assert cb.write_plugin_stop_armer(home, home=home) is None
        assert not (home / ".cursor").exists()


class TestRemoveStaleWorkspaceMcpServer:
    def _write(self, ws: Path, servers: dict[str, object]) -> Path:
        path = ws / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"mcpServers": servers}))
        return path

    def test_dead_only_entry_leaves_empty_servers_untracked(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        dead = tmp_path / "cb" / "dead"
        path = self._write(ws, dict(cb.build_mcp_config(dead)["mcpServers"]))  # type: ignore[arg-type]
        assert cb.remove_stale_workspace_mcp_server(ws, home=tmp_path / "home") is True
        assert json.loads(path.read_text()) == {"mcpServers": {}}

    def test_tracked_file_is_never_deleted(self, tmp_path: Path) -> None:
        """A committed mcp.json holding only a dead entry is stripped, not deleted.

        A deletion shows as `` D .cursor/mcp.json`` and Trio refuses the
        aggregate as a foreign change; a stripped file is a plain modification.
        """
        import subprocess

        ws = tmp_path / "ws"
        dead = tmp_path / "cb" / "dead"
        path = self._write(ws, dict(cb.build_mcp_config(dead)["mcpServers"]))  # type: ignore[arg-type]
        git = ["git", "-C", str(ws), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", ".cursor/mcp.json"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
        assert cb.remove_stale_workspace_mcp_server(ws, home=tmp_path / "home") is True
        assert json.loads(path.read_text()) == {"mcpServers": {}}
        status = subprocess.run(
            [*git, "status", "--porcelain"], check=True, capture_output=True, text=True
        ).stdout
        assert status.splitlines() == [" M .cursor/mcp.json"]

    def test_keeps_other_servers(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        servers = dict(cb.build_mcp_config(tmp_path / "cb" / "dead")["mcpServers"])  # type: ignore[arg-type]
        servers["user"] = {"command": "user-mcp"}
        path = self._write(ws, servers)
        assert cb.remove_stale_workspace_mcp_server(ws, home=tmp_path / "home") is True
        assert json.loads(path.read_text()) == {"mcpServers": {"user": {"command": "user-mcp"}}}

    def test_keeps_live_sibling_and_foreign_omnigent(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        live = tmp_path / "cb" / "live"
        live.mkdir(parents=True)
        path = self._write(ws, dict(cb.build_mcp_config(live)["mcpServers"]))  # type: ignore[arg-type]
        before = path.read_bytes()
        assert not cb.remove_stale_workspace_mcp_server(
            ws, home=tmp_path / "home", is_live=lambda _b: True
        )
        assert path.read_bytes() == before
        path = self._write(ws, {"omnigent": {"command": "npx", "args": ["some-other-omnigent"]}})
        before = path.read_bytes()
        assert not cb.remove_stale_workspace_mcp_server(ws, home=tmp_path / "home")
        assert path.read_bytes() == before


class TestPluginRouteReceipts:
    def _arm(self, tmp_path: Path, plugin_dir: Path | None) -> str | None:
        return cb.arm_completion_receipts(
            tmp_path / "cb" / "bridge",
            tmp_path / "ws",
            123,
            opted_in=True,
            home=tmp_path / "home",
            system_paths=(),
            plugin_dir=plugin_dir,
        )

    def test_armer_plus_own_plugin_hook_arms(self, tmp_path: Path, home: Path) -> None:
        del home
        (tmp_path / "ws").mkdir()
        plugin_dir = cb.write_cursor_plugin(tmp_path / "cb" / "bridge")
        cb.write_plugin_stop_armer(tmp_path / "ws", home=tmp_path / "home")
        assert self._arm(tmp_path, plugin_dir) is None
        assert cursor_native_status.read_receipt_epoch(tmp_path / "cb" / "bridge") == 123

    def test_missing_plugin_hooks_hold(self, tmp_path: Path) -> None:
        (tmp_path / "ws").mkdir()
        plugin_dir = tmp_path / "cb" / "bridge" / "cursor-plugin" / "omnigent"
        reason = self._arm(tmp_path, plugin_dir)
        assert reason == f"plugin_hooks_missing:{plugin_dir / 'hooks' / 'hooks.json'}"
        assert cursor_native_status.read_receipt_epoch(tmp_path / "cb" / "bridge") is None

    def test_live_sibling_project_hook_holds(self, tmp_path: Path, home: Path) -> None:
        del home
        plugin_dir = cb.write_cursor_plugin(tmp_path / "cb" / "bridge")
        path = tmp_path / "ws" / ".cursor" / "hooks.json"
        path.parent.mkdir(parents=True)
        sibling = _owned(tmp_path / "cb" / "sibling")
        path.write_text(json.dumps({"hooks": {"stop": [sibling]}}))
        assert self._arm(tmp_path, plugin_dir) == f"foreign_stop_hook:{path}"

    def test_foreign_bridge_in_plugin_holds(self, tmp_path: Path, home: Path) -> None:
        del home
        (tmp_path / "ws").mkdir()
        plugin_dir = cb.write_cursor_plugin(tmp_path / "cb" / "other")
        reason = self._arm(tmp_path, plugin_dir)
        assert reason == f"foreign_stop_hook:{plugin_dir / 'hooks' / 'hooks.json'}"

    def test_armer_is_benign_on_the_project_route(self, tmp_path: Path) -> None:
        bridge = tmp_path / "cb" / "bridge"
        ws = tmp_path / "ws"
        path = ws / ".cursor" / "hooks.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {"hooks": {"stop": [{"command": cb.PLUGIN_STOP_ARMER_COMMAND}, _owned(bridge)]}}
            )
        )
        assert self._arm(tmp_path, None) is None


class TestPluginRouteLaunchChecks:
    """enableUserLocalPlugins detection (N4) and plugin basename collisions (N5)."""

    @pytest.mark.parametrize(
        "args",
        [["--authless"], ["--enable-bedrock"], ["--model", "x", "--enable-local-bedrock"]],
    )
    def test_plugins_off_flags_refuse(self, args: list[str]) -> None:
        with pytest.raises(cb.CursorPluginRouteError) as refused:
            cb.check_plugin_route_launch("/usr/bin/cursor-agent", args, env={})
        assert "enableUserLocalPlugins" in refused.value.user_message()
        assert args[-1] in refused.value.user_message()

    @pytest.mark.parametrize(
        "name", ["CURSOR_ENABLE_AUTHLESS", "CURSOR_ENABLE_BEDROCK", "CURSOR_ENABLE_LOCAL_BEDROCK"]
    )
    def test_plugins_off_env_refuses_local_build_only(self, name: str, tmp_path: Path) -> None:
        local = tmp_path / "cursor-agent-local" / "versions" / "1" / "cursor-agent-local"
        local.parent.mkdir(parents=True)
        local.touch()
        with pytest.raises(cb.CursorPluginRouteError, match=f"{name}=1"):
            cb.check_plugin_route_launch(str(local), [], env={name: "1"})
        # The standard build ignores these env vars: plugins still load.
        assert cb.check_plugin_route_launch("/usr/bin/cursor-agent", [], env={name: "1"}) == (
            "omnigent"
        )
        assert cb.user_local_plugins_disabled_reason(str(local), [], env={name: "0"}) is None

    def test_default_launch_passes(self) -> None:
        assert cb.check_plugin_route_launch("cursor-agent", ["--force"], env={}) == "omnigent"

    @pytest.mark.parametrize(
        "args",
        [
            ["--plugin-dir", "/x/omnigent"],
            ["--plugin-dir=/x/omnigent/"],
            ["--plugin-dir", "omnigent"],
        ],
    )
    def test_user_plugin_named_omnigent_gets_distinct_name(self, args: list[str]) -> None:
        assert cb.plugin_dir_name_for_launch(args) == "omnigent-session"
        assert cb.plugin_dir_name_for_launch(["--plugin-dir", "/x/other"]) == "omnigent"

    def test_both_names_taken_refuses(self) -> None:
        args = ["--plugin-dir", "/a/omnigent", "--plugin-dir=/b/omnigent-session"]
        with pytest.raises(cb.CursorPluginRouteError, match="--plugin-dir"):
            cb.plugin_dir_name_for_launch(args)

    def test_fallback_name_sets_server_id_and_allowlist(self, tmp_path: Path, home: Path) -> None:
        plugin_dir = cb.write_cursor_plugin(tmp_path / "cb" / "bridge", name="omnigent-session")
        assert plugin_dir.name == "omnigent-session"
        assert cb.plugin_mcp_server_id("omnigent-session") == "plugin-omnigent-session-omnigent"
        allow = json.loads((home / ".cursor" / "cli-config.json").read_text())["permissions"][
            "allow"
        ]
        assert "Mcp(plugin-omnigent-session-omnigent:sys_os_read)" in allow


class TestSiblingLivenessGrace:
    """N10: a mid-launch sibling is not judged dead; this launch's own entries are."""

    def _launching_sibling(self, tmp_path: Path, age_s: float = 0.0) -> Path:
        import os
        import time

        sibling = tmp_path / "cb" / "sibling"
        cb.write_bridge_owner(sibling, "conv_sibling")  # no heartbeat, no tmux.json yet
        if age_s:
            stamp = time.time() - age_s
            os.utime(sibling / "owner.json", (stamp, stamp))
        return sibling

    def _hooks_bound_to(self, ws: Path, *bridges: Path) -> Path:
        path = ws / ".cursor" / "hooks.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "hooks": {"stop": [_owned(b) for b in bridges]}})
        )
        return path

    def test_armer_keeps_mid_launch_sibling(self, tmp_path: Path) -> None:
        sibling = self._launching_sibling(tmp_path)
        path = self._hooks_bound_to(tmp_path / "ws", sibling)
        cb.write_plugin_stop_armer(tmp_path / "ws", home=tmp_path / "home")
        assert _stop_hooks(path) == [_owned(sibling), {"command": cb.PLUGIN_STOP_ARMER_COMMAND}]
        warned = cb.live_foreign_config_bridges(
            tmp_path / "ws", tmp_path / "cb" / "me", launch_grace=True
        )
        assert warned == {"hooks.json": [sibling]}

    def test_armer_drops_sibling_after_grace(self, tmp_path: Path) -> None:
        sibling = self._launching_sibling(tmp_path, age_s=cb._LAUNCH_GRACE_S + 60)
        path = self._hooks_bound_to(tmp_path / "ws", sibling)
        cb.write_plugin_stop_armer(tmp_path / "ws", home=tmp_path / "home")
        assert _stop_hooks(path) == [{"command": cb.PLUGIN_STOP_ARMER_COMMAND}]

    def test_own_bridge_entries_always_dropped(self, tmp_path: Path) -> None:
        own = self._launching_sibling(tmp_path)  # fresh owner file == this launch
        path = self._hooks_bound_to(tmp_path / "ws", own)
        mcp = tmp_path / "ws" / ".cursor" / "mcp.json"
        mcp.write_text(json.dumps(cb.build_mcp_config(own)))
        cb.write_plugin_stop_armer(
            tmp_path / "ws", home=tmp_path / "home", is_live=lambda _b: True, own_bridge=own
        )
        assert _stop_hooks(path) == [{"command": cb.PLUGIN_STOP_ARMER_COMMAND}]
        assert cb.remove_stale_workspace_mcp_server(
            tmp_path / "ws", home=tmp_path / "home", is_live=lambda _b: True, own_bridge=own
        )
        assert json.loads(mcp.read_text()) == {"mcpServers": {}}

    def test_mcp_cleanup_keeps_mid_launch_sibling(self, tmp_path: Path) -> None:
        sibling = self._launching_sibling(tmp_path)
        mcp = tmp_path / "ws" / ".cursor" / "mcp.json"
        mcp.parent.mkdir(parents=True)
        mcp.write_text(json.dumps(cb.build_mcp_config(sibling)))
        assert not cb.remove_stale_workspace_mcp_server(tmp_path / "ws", home=tmp_path / "home")

    def test_atomic_write_keeps_mode_and_leaves_no_tmp(self, tmp_path: Path) -> None:
        path = self._hooks_bound_to(tmp_path / "ws")
        path.chmod(0o664)
        cb.write_plugin_stop_armer(tmp_path / "ws", home=tmp_path / "home")
        assert path.stat().st_mode & 0o777 == 0o664
        assert sorted(p.name for p in path.parent.iterdir()) == ["hooks.json"]


def test_recorder_recreates_bridge_dir_owner_only(tmp_path: Path) -> None:
    """N9: a bridge dir deleted mid-session comes back 0700, not umask-default."""
    from omnigent.harnesses.cursor_native import usage

    bridge = tmp_path / "gone" / "bridge"
    usage.record_usage_payload(
        bridge, {"generation_id": "g1", "input_tokens": 5, "output_tokens": 1}
    )
    cursor_native_status.record_turn_end(bridge, {"generation_id": "g1"})
    assert bridge.stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "gone").stat().st_mode & 0o777 == 0o700
