"""Unit tests for :mod:`omnigent.harnesses.cursor_native.bridge` composer handling.

Focused on the leftover-draft clear (:func:`_clear_composer`) and its use by
:func:`inject_user_message`. cursor-agent restores the interrupted prompt into
the composer when a turn is cancelled (web-UI Stop -> ``inject_interrupt`` sends
``Escape``), and its input widget ignores the readline ``C-a``/``C-k`` keys the
clear used to send — so the leftover survived and prepended the next message.
The clear now floods ``Backspace`` until the pane stops changing.
"""

from __future__ import annotations

import types
from pathlib import Path

import click
import pytest

from omnigent import native_tmux_kill
from omnigent.harnesses.cursor_native import bridge as cursor_native_bridge
from omnigent.harnesses.cursor_native.bridge import kill_session, write_tmux_target

_SOCK = "/tmp/example/cursor.sock"
_TARGET = "cursor:0.0"


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, stdout: str = "") -> None:
        self.returncode = 0
        self.stdout = stdout
        self.stderr = ""


def _install_fake_tmux(
    monkeypatch: pytest.MonkeyPatch,
    *,
    pane_captures: list[str],
) -> list[list[str]]:
    """Patch ``subprocess.run`` so tmux is mocked.

    ``send-keys`` calls are recorded (and returned). ``capture-pane`` calls pop
    the next value from *pane_captures* (the last value repeats once exhausted,
    modelling a composer that has settled).

    :returns: The list that accumulates every tmux argv invoked.
    """
    captured: list[list[str]] = []
    remaining = list(pane_captures)

    def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
        del kwargs
        captured.append(cmd)
        if "capture-pane" in cmd:
            value = remaining.pop(0) if len(remaining) > 1 else (remaining[0] if remaining else "")
            return _FakeCompleted(stdout=value)
        return _FakeCompleted()

    monkeypatch.setattr("subprocess.run", _fake_run)
    return captured


def _send_keys_calls(captured: list[list[str]]) -> list[list[str]]:
    """The send-keys argv tails (everything after ``send-keys``)."""
    return [cmd[cmd.index("send-keys") + 1 :] for cmd in captured if "send-keys" in cmd]


def test_clear_composer_floods_backspace_until_pane_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The clear sends End, then Backspace bursts, stopping once the pane settles.

    Two distinct captures (draft shrinking) then a repeat (empty) means three
    bursts: the third sees no change and returns. It must never send the old
    ``C-a``/``C-k`` keys, which cursor-agent's composer ignores.
    """
    # #1 is the placeholder check (a draft hides it); previous=#2 (draft); round1
    # sees #3 (empty, changed -> continue); round2 sees #4 (unchanged -> stop).
    captured = _install_fake_tmux(
        monkeypatch,
        pane_captures=["draft-content", "draft-content", "empty", "empty"],
    )

    cursor_native_bridge._clear_composer(_SOCK, _TARGET)

    tails = _send_keys_calls(captured)
    # End once, then one Backspace burst per round until stable.
    assert tails[0] == ["-t", _TARGET, "End"]
    bursts = [t for t in tails if "BSpace" in t]
    assert all(
        t == ["-t", _TARGET, "-N", str(cursor_native_bridge._COMPOSER_CLEAR_CHUNK), "BSpace"]
        for t in bursts
    )
    assert len(bursts) == 2, f"expected to stop once the pane stabilized; got {len(bursts)}"
    # The removed, ineffective readline clears must not come back.
    assert not any("C-a" in t or "C-k" in t for t in tails)


def test_clear_composer_terminates_on_empty_composer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An already-empty composer settles immediately (one harmless burst).

    A burst on empty input is a no-op (unlike ``C-c``, which would arm exit), so
    the clear is safe to run before every injection. The pane never changes, so
    the first burst's capture matches and the loop returns at once — never
    reaching the round cap.
    """
    captured = _install_fake_tmux(monkeypatch, pane_captures=["idle-placeholder"])

    cursor_native_bridge._clear_composer(_SOCK, _TARGET)

    bursts = [t for t in _send_keys_calls(captured) if "BSpace" in t]
    assert len(bursts) == 1, "empty composer should settle after a single burst"


def test_clear_composer_is_bounded_when_pane_never_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pane that keeps changing is bounded by the round cap, not infinite."""

    counter = {"n": 0}

    def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
        del kwargs
        if "capture-pane" in cmd:
            counter["n"] += 1
            return _FakeCompleted(stdout=f"ever-changing-{counter['n']}")
        return _FakeCompleted()

    monkeypatch.setattr("subprocess.run", _fake_run)

    cursor_native_bridge._clear_composer(_SOCK, _TARGET)

    # The placeholder check, one capture seeding `previous`, then one per round.
    assert counter["n"] == cursor_native_bridge._COMPOSER_CLEAR_MAX_ROUNDS + 2


def test_inject_user_message_clears_before_pasting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leftover-draft clear runs before the paste, so it can't survive it.

    Regression for the reported bug: pressing Stop left the previous message in
    the composer, which then prepended (blocked) the next web-UI message. The
    Backspace flood must precede ``load-buffer``/``paste-buffer``.
    """
    bridge_dir = tmp_path / "bridge"
    write_tmux_target(
        bridge_dir,
        socket_path=Path(_SOCK),
        tmux_target=_TARGET,
    )
    cursor_native_bridge._mark_composer_ready(bridge_dir)
    # Settle sees the running placeholder; the clear then sees a draft (which
    # hides it), floods until the pane settles, and the paste-commit poll sees
    # the needle.
    captured = _install_fake_tmux(
        monkeypatch,
        pane_captures=["Add a follow-up", "leftover", "leftover", "hello marker", "hello marker"],
    )
    # Avoid real sleeps in the paste-commit settle.
    monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

    cursor_native_bridge.inject_user_message(bridge_dir, content="hello marker")

    first_backspace = next(
        i for i, cmd in enumerate(captured) if "send-keys" in cmd and "BSpace" in cmd
    )
    first_paste = next(i for i, cmd in enumerate(captured) if "paste-buffer" in cmd)
    assert first_backspace < first_paste, "draft must be cleared before the new paste"
    # The old ineffective readline clear is gone.
    assert not any("C-a" in cmd or "C-k" in cmd for cmd in captured)
    # Submit still happens last.
    assert any("send-keys" in cmd and "Enter" in cmd for cmd in captured)


def test_clear_composer_sends_nothing_when_placeholder_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A visible placeholder means an empty composer: no End and no Backspace at all.

    On a still-booting TUI a Backspace burst is stored as literal DELs ahead of
    the next paste, and the pane cannot show it.
    """
    for marker in cursor_native_bridge._IDLE_MARKERS:
        captured = _install_fake_tmux(monkeypatch, pane_captures=[f"> {marker}"])

        cursor_native_bridge._clear_composer(_SOCK, _TARGET)

        assert _send_keys_calls(captured) == []


class TestColdStartReadiness:
    """The first injection into a fresh TUI waits for a stable composer, or sends nothing."""

    def test_settle_requires_consecutive_identical_captures(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        n = cursor_native_bridge._COMPOSER_READY_STABLE_CAPTURES
        booting = [f"{_IDLE}\nstarting {i}" for i in range(4)]
        captured = _install_fake_tmux(monkeypatch, pane_captures=["", *booting, _IDLE])
        monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

        ready = cursor_native_bridge._settle_pane(
            _SOCK, _TARGET, timeout_s=5.0, require_stable=True
        )

        assert ready
        captures = [c for c in captured if "capture-pane" in c]
        assert len(captures) == 1 + len(booting) + n

    def test_warm_settle_returns_on_first_marker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_fake_tmux(monkeypatch, pane_captures=[f"{_IDLE} 1", f"{_IDLE} 2"])

        assert cursor_native_bridge._settle_pane(_SOCK, _TARGET, timeout_s=5.0)
        assert len([c for c in captured if "capture-pane" in c]) == 1

    def test_cold_inject_times_out_without_typing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pane that never settles: raise before any key, paste or Enter."""
        bridge_dir = _prepare_bridge(tmp_path)
        counter = {"n": 0}
        captured: list[list[str]] = []

        def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
            del kwargs
            captured.append(cmd)
            if "capture-pane" in cmd:
                counter["n"] += 1
                return _FakeCompleted(stdout=f"{_IDLE}\nstarting {counter['n']}")
            return _FakeCompleted()

        monkeypatch.setattr("subprocess.run", _fake_run)

        with pytest.raises(RuntimeError, match="not stably ready"):
            cursor_native_bridge.inject_user_message(bridge_dir, content="hello", timeout_s=0.5)

        keys = ("send-keys", "load-buffer", "paste-buffer")
        typed = [c for c in captured if any(k in c for k in keys)]
        assert typed == []
        assert not cursor_native_bridge._composer_ready_seen(bridge_dir)

    def test_ready_stamp_follows_the_tui_instance(self, tmp_path: Path) -> None:
        """A relaunch rewrites tmux.json, so the next injection is cold again."""
        bridge_dir = _prepare_bridge(tmp_path)
        assert not cursor_native_bridge._composer_ready_seen(bridge_dir)
        cursor_native_bridge._mark_composer_ready(bridge_dir)
        assert cursor_native_bridge._composer_ready_seen(bridge_dir)

        write_tmux_target(bridge_dir, socket_path=Path(_SOCK), tmux_target=_TARGET, pid=4242)

        assert not cursor_native_bridge._composer_ready_seen(bridge_dir)

    def test_warm_inject_skips_the_stability_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Once stamped, a changing pane (a running turn) does not delay steering."""
        bridge_dir = _prepare_bridge(tmp_path)
        cursor_native_bridge._mark_composer_ready(bridge_dir)
        counter = {"n": 0}
        captured: list[list[str]] = []

        def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
            del kwargs
            captured.append(cmd)
            if "capture-pane" in cmd:
                counter["n"] += 1
                return _FakeCompleted(stdout=f"{_IDLE} hello marker {counter['n']}")
            return _FakeCompleted()

        monkeypatch.setattr("subprocess.run", _fake_run)
        monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

        cursor_native_bridge.inject_user_message(bridge_dir, content="hello marker", timeout_s=0.5)

        tails = _send_keys_calls(captured)
        assert tails == [["-t", _TARGET, "Enter"]]  # no clear keys, one submit
        assert counter["n"] == 3  # settle, placeholder check, needle poll


# Idle marker so _settle_pane returns and _clear_composer settles at once.
_IDLE = "Add a follow-up"


def _prepare_bridge(tmp_path: Path) -> Path:
    """Write a tmux target so ``_wait_for_tmux_info`` resolves in-process."""
    bridge_dir = tmp_path / "bridge"
    write_tmux_target(bridge_dir, socket_path=Path(_SOCK), tmux_target=_TARGET)
    return bridge_dir


class TestInjectModelGate:
    """``inject_model_command`` must gate Enter on the picker's filter result.

    Regression for the reviewer-flagged bug: the readiness check used
    ``model in pane``, which is satisfied instantly by the echoed
    ``/model <id>`` composer text and never confirms a match landed — so an
    unavailable id would press Enter against "No matches" and mis-select.
    """

    def test_presses_enter_when_picker_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A landed filter ("Models matching") commits the selection with Enter."""
        bridge_dir = _prepare_bridge(tmp_path)
        monkeypatch.setattr(
            cursor_native_bridge,
            "_live_cursor_model_options",
            lambda: pytest.fail("cached display name must avoid a second CLI listing"),
        )
        captured = _install_fake_tmux(
            monkeypatch, pane_captures=[f'{_IDLE}\nModels matching "gpt-5.2"\n →  GPT-5.2   High']
        )
        monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

        cursor_native_bridge.inject_model_command(
            bridge_dir,
            model="gpt-5.2",
            expected_display_name="GPT-5.2",
        )

        tails = _send_keys_calls(captured)
        assert ["-t", _TARGET, "-l", "/model gpt-5.2"] in tails  # the filter command
        assert ["-t", _TARGET, "Enter"] in tails  # selection committed
        assert ["-t", _TARGET, "Escape"] not in tails  # no dismiss on a real match

    def test_missing_cli_catalog_raises_clean_runtime_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cold switch without cursor-agent degrades through the runner's handled error path."""

        def _missing_cli() -> list[dict[str, object]]:
            raise click.ClickException("cursor-agent missing")

        monkeypatch.setattr(cursor_native_bridge, "_live_cursor_model_options", _missing_cli)

        with pytest.raises(RuntimeError, match="could not verify the live model catalog") as error:
            cursor_native_bridge.inject_model_command(tmp_path, model="gpt-5.2")

        assert isinstance(error.value.__cause__, click.ClickException)

    def test_raises_without_enter_on_no_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "No matches" fails loudly, dismisses the picker, and never presses Enter."""
        bridge_dir = _prepare_bridge(tmp_path)
        monkeypatch.setattr(
            cursor_native_bridge,
            "_live_cursor_model_options",
            lambda: [{"id": "bogus-model", "displayName": "Bogus Model"}],
        )
        captured = _install_fake_tmux(
            monkeypatch, pane_captures=[f"{_IDLE}\n → /model bogus-model\n    No matches"]
        )
        monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

        with pytest.raises(RuntimeError, match="not available"):
            cursor_native_bridge.inject_model_command(bridge_dir, model="bogus-model")

        tails = _send_keys_calls(captured)
        assert ["-t", _TARGET, "Enter"] not in tails  # wrong/no selection never committed
        assert ["-t", _TARGET, "Escape"] in tails  # picker dismissed

    def test_echoed_command_alone_does_not_satisfy_the_gate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The id in the echoed composer line (no header) is still treated as no-match.

        The pane contains the typed ``/model gpt-5.2`` — a naive ``model in
        pane`` check would pass — but with a "No matches" result and no "Models
        matching" header the gate must refuse to press Enter.
        """
        bridge_dir = _prepare_bridge(tmp_path)
        monkeypatch.setattr(
            cursor_native_bridge,
            "_live_cursor_model_options",
            lambda: [{"id": "gpt-5.2", "displayName": "GPT-5.2"}],
        )
        captured = _install_fake_tmux(
            monkeypatch, pane_captures=[f"{_IDLE}\n → /model gpt-5.2\n    No matches"]
        )
        monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

        with pytest.raises(RuntimeError, match="not available"):
            cursor_native_bridge.inject_model_command(bridge_dir, model="gpt-5.2")

        assert ["-t", _TARGET, "Enter"] not in _send_keys_calls(captured)

    def test_rejects_fuzzy_match_for_a_different_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fuzzy top result cannot silently select a different catalog row."""
        bridge_dir = _prepare_bridge(tmp_path)
        monkeypatch.setattr(
            cursor_native_bridge,
            "_live_cursor_model_options",
            lambda: [{"id": "requested-model", "displayName": "Requested Model"}],
        )
        captured = _install_fake_tmux(
            monkeypatch,
            pane_captures=[
                f'{_IDLE}\nModels matching "requested-model"\n →  Different Model   High'
            ],
        )
        monkeypatch.setattr(cursor_native_bridge.time, "sleep", lambda *_a, **_k: None)

        with pytest.raises(RuntimeError, match="exact picker row"):
            cursor_native_bridge.inject_model_command(bridge_dir, model="requested-model")

        tails = _send_keys_calls(captured)
        assert ["-t", _TARGET, "Enter"] not in tails
        assert ["-t", _TARGET, "Escape"] in tails


@pytest.mark.parametrize(
    ("row", "display_name", "expected"),
    [
        ("Provider Model", "Provider Model", True),
        ("Provider Model   High", "Provider Model", True),
        ("Provider Modelish High", "Provider Model", False),
        ("Other Provider Model", "Provider Model", False),
    ],
)
def test_picker_row_matches_complete_display_label(
    row: str,
    display_name: str,
    expected: bool,
) -> None:
    """Variant suffixes are allowed, but longer-name prefixes are not."""
    assert cursor_native_bridge._picker_row_matches_display(row, display_name) is expected


class TestHooksConfig:
    """The ``hooks.json`` that registers cursor's per-turn usage ``stop`` hook."""

    def test_build_hooks_config_shape(self) -> None:
        cfg = cursor_native_bridge.build_hooks_config(
            Path("/tmp/bridge"), python_executable="/usr/bin/python3"
        )
        assert cfg["version"] == 1
        hooks = cfg["hooks"]["stop"]
        assert len(hooks) == 1
        command = hooks[0]["command"]
        # The recorder is invoked isolated (-I) on the usage module, with the
        # absolute bridge dir baked in so it writes where the forwarder reads.
        assert "-I" in command
        assert "omnigent.harnesses.cursor_native.usage" in command
        assert "record-usage" in command
        assert "/tmp/bridge" in command
        assert command.startswith("/usr/bin/python3")

    def test_build_hooks_config_quotes_spaced_paths(self) -> None:
        cfg = cursor_native_bridge.build_hooks_config(
            Path("/tmp/dir with space"), python_executable="/usr/bin/python3"
        )
        command = cfg["hooks"]["stop"][0]["command"]
        # A shell-quoted path keeps the spaced bridge dir a single argv token.
        assert "'/tmp/dir with space'" in command

    def test_write_hooks_config_writes_project_scoped_file(self, tmp_path: Path) -> None:
        import json

        workspace = tmp_path / "ws"
        workspace.mkdir()
        bridge_dir = tmp_path / "bridge"
        path = cursor_native_bridge.write_hooks_config(workspace, bridge_dir)
        assert path == workspace / ".cursor" / "hooks.json"
        payload = json.loads(path.read_text())
        assert payload["hooks"]["stop"][0]["command"].endswith(str(bridge_dir))
        # No leftover temp file from the atomic write.
        assert not (workspace / ".cursor" / "hooks.json.tmp").exists()

    def test_write_hooks_config_preserves_existing_hooks(self, tmp_path: Path) -> None:
        import json

        workspace = tmp_path / "ws"
        cursor_dir = workspace / ".cursor"
        cursor_dir.mkdir(parents=True)
        path = cursor_dir / "hooks.json"
        pre_existing = {
            "version": 1,
            "hooks": {
                "preToolUse": [{"command": "./scripts/pre-tool-guard.sh"}],
                "stop": [{"command": "./scripts/notify-done.sh"}],
            },
        }
        path.write_text(json.dumps(pre_existing), encoding="utf-8")

        cursor_native_bridge.write_hooks_config(workspace, tmp_path / "bridge")

        payload = json.loads(path.read_text())
        # The workspace's own hooks survive the launch write...
        assert payload["hooks"]["preToolUse"] == [{"command": "./scripts/pre-tool-guard.sh"}]
        stop_commands = [entry["command"] for entry in payload["hooks"]["stop"]]
        assert "./scripts/notify-done.sh" in stop_commands
        # ...and Omnigent's usage stop hook is registered alongside them.
        assert any(
            "omnigent.harnesses.cursor_native.usage" in command for command in stop_commands
        )

    def test_write_hooks_config_replaces_stale_usage_hook(self, tmp_path: Path) -> None:
        import json

        workspace = tmp_path / "ws"
        workspace.mkdir()
        cursor_native_bridge.write_hooks_config(workspace, tmp_path / "bridge-old")
        path = cursor_native_bridge.write_hooks_config(workspace, tmp_path / "bridge-new")

        payload = json.loads(path.read_text())
        usage_commands = [
            entry["command"]
            for entry in payload["hooks"]["stop"]
            if "omnigent.harnesses.cursor_native.usage" in entry["command"]
        ]
        # Relaunching must not accumulate recorders pointing at dead bridge dirs.
        assert len(usage_commands) == 1
        assert usage_commands[0].endswith(str(tmp_path / "bridge-new"))

    def test_write_hooks_config_tolerates_malformed_file(self, tmp_path: Path) -> None:
        import json

        workspace = tmp_path / "ws"
        cursor_dir = workspace / ".cursor"
        cursor_dir.mkdir(parents=True)
        (cursor_dir / "hooks.json").write_text("{not json", encoding="utf-8")

        path = cursor_native_bridge.write_hooks_config(workspace, tmp_path / "bridge")

        payload = json.loads(path.read_text())
        assert payload["version"] == 1
        stop_commands = [entry["command"] for entry in payload["hooks"]["stop"]]
        assert any(
            "omnigent.harnesses.cursor_native.usage" in command for command in stop_commands
        )

    def test_write_hooks_config_tolerates_invalid_utf8_file(self, tmp_path: Path) -> None:
        import json

        workspace = tmp_path / "ws"
        cursor_dir = workspace / ".cursor"
        cursor_dir.mkdir(parents=True)
        # Invalid UTF-8 must not crash the launch: reading it raises
        # UnicodeDecodeError (a ValueError, not a JSONDecodeError), which the
        # shared tolerant loader must swallow.
        (cursor_dir / "hooks.json").write_bytes(b'\xff\xfe{"hooks": {}}')

        path = cursor_native_bridge.write_hooks_config(workspace, tmp_path / "bridge")

        payload = json.loads(path.read_text())
        assert payload["version"] == 1
        stop_commands = [entry["command"] for entry in payload["hooks"]["stop"]]
        assert any(
            "omnigent.harnesses.cursor_native.usage" in command for command in stop_commands
        )

    def test_write_mcp_config_tolerates_invalid_utf8_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        # Stub the bridge-token write and Cursor CLI plumbing: this test only
        # exercises the mcp.json read-merge-write path.
        monkeypatch.setattr(cursor_native_bridge, "write_mcp_bridge_config", lambda _: None)
        monkeypatch.setattr(cursor_native_bridge, "enable_mcp_for_workspace", lambda _: None)
        monkeypatch.setattr(cursor_native_bridge, "allow_mcp_tools_in_cli_config", lambda: None)
        workspace = tmp_path / "ws"
        cursor_dir = workspace / ".cursor"
        cursor_dir.mkdir(parents=True)
        # The sibling mcp.json writer shares the decode policy: invalid UTF-8
        # must not crash the launch either.
        (cursor_dir / "mcp.json").write_bytes(b'\xff\xfe{"mcpServers": {}}')

        path = cursor_native_bridge.write_mcp_config(workspace, tmp_path / "bridge")

        payload = json.loads(path.read_text())
        assert "omnigent" in payload["mcpServers"]


class TestMcpBridgeConfigSecureDir:
    """``bridge.json`` holds a relay bearer token, so its tree must be owner-only."""

    @staticmethod
    def _bridge_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
        """Point the bridge root at a production-shaped tree under ``tmp_path``.

        ``_ensure_secure_bridge_dir`` anchors the ancestor walk at the uid-scoped
        dir's parent, so mirror ``<trusted>/omnigent-<uid>/cursor-native/<digest>``.
        """
        uid_dir = tmp_path / "omnigent-test"
        monkeypatch.setattr(cursor_native_bridge, "_BRIDGE_ROOT", uid_dir / "cursor-native")
        return uid_dir, cursor_native_bridge.bridge_dir_for_session_id("sess")

    def test_writes_token_under_owner_only_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The happy path still mints and persists the relay token."""
        import json

        _, bridge_dir = self._bridge_dir(tmp_path, monkeypatch)
        cursor_native_bridge.write_mcp_bridge_config(bridge_dir)

        token = json.loads((bridge_dir / "bridge.json").read_text(encoding="utf-8"))["token"]
        assert isinstance(token, str) and token

    def test_rejects_symlinked_ancestor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A symlinked bridge-tree ancestor is refused — the token is never written.

        On a shared host the sticky bit on ``/tmp`` blocks deletion, not creation,
        so another local user can pre-create the uid-scoped dir as a symlink and
        capture the relay token. Writing must fail loudly instead.
        """
        uid_dir, bridge_dir = self._bridge_dir(tmp_path, monkeypatch)
        elsewhere = tmp_path / "attacker"
        elsewhere.mkdir()
        uid_dir.symlink_to(elsewhere, target_is_directory=True)

        with pytest.raises(RuntimeError, match="is a symlink"):
            cursor_native_bridge.write_mcp_bridge_config(bridge_dir)
        # No token leaked into the attacker-controlled destination.
        assert not (elsewhere / "cursor-native").exists()
        assert not (bridge_dir / "bridge.json").exists()

    def test_rejects_foreign_owned_ancestor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pre-existing world-writable ancestor owned by another uid is refused.

        Models the attacker pre-creating ``$TMPDIR/omnigent-<uid>`` as a 0o777
        directory they own: the ancestor walk must reject it rather than write the
        token into a tree somebody else controls.
        """
        import os

        if not hasattr(os, "getuid"):
            pytest.skip("POSIX uid ownership checks are unavailable on this platform")

        uid_dir, bridge_dir = self._bridge_dir(tmp_path, monkeypatch)
        uid_dir.mkdir(parents=True)
        uid_dir.chmod(0o777)
        # The dir belongs to the real uid, so pretend we are somebody else.
        monkeypatch.setattr(os, "getuid", lambda: os.stat(uid_dir).st_uid + 1)

        with pytest.raises(RuntimeError, match="owned by uid"):
            cursor_native_bridge.write_mcp_bridge_config(bridge_dir)
        assert not (bridge_dir / "bridge.json").exists()


def test_kill_session_issues_kill_session_on_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``kill_session`` issues exactly ``tmux kill-session -t <target>``.

    Hard-stop the web UI's "Stop session" relies on. A recorded pane pid that is
    not alive means no leftover escalation, so exactly one tmux call is made.
    Mirrors the claude-native test.
    """
    bridge_dir = tmp_path / "bridge"
    write_tmux_target(bridge_dir, socket_path=Path(_SOCK), tmux_target=_TARGET, pid=12345)

    captured: list[list[str]] = []

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
        del kwargs
        captured.append(cmd)
        return _FakeCompleted()

    monkeypatch.setattr("subprocess.run", _fake_run)
    # Recorded pid 12345 is not alive -> no leftover SIGKILL, no extra tmux call.
    monkeypatch.setattr(native_tmux_kill._proc, "process_alive", lambda _pid: False)
    kill_session(bridge_dir)

    assert len(captured) == 1, f"Expected 1 tmux kill-session call, got {len(captured)}."
    assert captured[0] == ["tmux", "-S", _SOCK, "kill-session", "-t", _TARGET]


def test_kill_session_escalates_live_pane_after_tmux_kill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pane that survives kill-session receives a SIGKILL for its group.

    With no recorded pid, the pane pid is resolved via ``tmux list-panes``; the
    leftover pane process is then SIGKILLed through ``_proc._killpg``. Mirrors
    :func:`tests.test_claude_native_bridge.test_kill_session_escalates_live_pane_after_tmux_kill`.
    """
    bridge_dir = tmp_path / "bridge"
    write_tmux_target(bridge_dir, socket_path=Path(_SOCK), tmux_target=_TARGET)

    captured: list[list[str]] = []

    class _FakeCompleted:
        returncode = 0
        stdout = "24680\n"
        stderr = ""

    def _fake_run(cmd: list[str], **kwargs: object) -> _FakeCompleted:
        del kwargs
        captured.append(cmd)
        return _FakeCompleted()

    alive = iter((True, False))
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setattr(
        native_tmux_kill._proc,
        "process_alive",
        lambda _pid: next(alive),
    )
    monkeypatch.setattr(
        native_tmux_kill._proc,
        "_killpg",
        lambda pid, sig: killed.append((pid, sig)) or True,
    )

    kill_session(bridge_dir)

    assert captured == [
        ["tmux", "-S", _SOCK, "list-panes", "-t", _TARGET, "-F", "#{pane_pid}"],
        ["tmux", "-S", _SOCK, "kill-session", "-t", _TARGET],
    ]
    assert killed == [(24680, native_tmux_kill._proc._SIGKILL)]


class TestCompletionReceiptHookGate:
    """Receipts arm only when no non-Omnigent ``stop`` hook is configured."""

    _PY = "/usr/bin/python3"

    def _owned(self, bridge: str = "/tmp/bridge-x") -> str:
        cfg = cursor_native_bridge.build_hooks_config(Path(bridge), python_executable=self._PY)
        hooks = cfg["hooks"]
        assert isinstance(hooks, dict)
        return hooks["stop"][0]["command"]

    def _write(self, path: Path, payload: object) -> Path:
        import json

        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        elif isinstance(payload, str):
            path.write_text(payload)
        else:
            path.write_text(json.dumps(payload))
        return path

    def _reason(self, tmp_path: Path, system: tuple[Path, ...] = ()) -> str | None:
        return cursor_native_bridge.completion_receipt_hook_hold_reason(
            tmp_path / "ws", Path("/tmp/bridge-x"), home=tmp_path / "home", system_paths=system
        )

    def test_owned_command_matches_generated_shapes(self) -> None:
        assert cursor_native_bridge.is_owned_usage_hook_command(self._owned())
        assert cursor_native_bridge.is_owned_usage_hook_command(self._owned("/tmp/dir with space"))

    @pytest.mark.parametrize(
        "command",
        [
            # Incidental substrings of the module / subcommand in a foreign command.
            "sh -c 'python -m omnigent.harnesses.cursor_native.usage record-usage'",
            "/usr/bin/python3 -I -m omnigent.harnesses.cursor_native.usage record-usage "
            '--bridge-dir /tmp/b; echo \'{"followup_message":"go"}\'',
            "/usr/bin/python3 -I -m omnigent.harnesses.cursor_native.usage record-usage "
            "--bridge-dir /tmp/b&&./followup.sh",
            "/usr/bin/python3 -m omnigent.harnesses.cursor_native.usage record-usage "
            "--bridge-dir /tmp/b",
            "/bin/bash -I -m omnigent.harnesses.cursor_native.usage record-usage "
            "--bridge-dir /tmp/b",
            "python3 -I -m omnigent.harnesses.cursor_native.usage record-usage "
            "--bridge-dir /tmp/b",
            "/usr/bin/python3 -I -m omnigent.harnesses.cursor_native.usage record-usage "
            "--bridge-dir rel/b",
            "./scripts/followup.sh omnigent.harnesses.cursor_native.usage",
            "'unterminated",
            None,
            ["/usr/bin/python3"],
        ],
    )
    def test_owned_command_rejects_lookalikes(self, command: object) -> None:
        assert not cursor_native_bridge.is_owned_usage_hook_command(command)

    def test_no_hooks_files_is_capable(self, tmp_path: Path) -> None:
        assert self._reason(tmp_path) is None

    def test_owned_and_non_stop_hooks_are_capable(self, tmp_path: Path) -> None:
        self._write(
            tmp_path / "ws" / ".cursor" / "hooks.json",
            {
                "version": 1,
                "hooks": {
                    "stop": [{"command": self._owned()}],
                    "preToolUse": [{"command": "./guard.sh"}],
                    "afterFileEdit": "not-a-list-but-not-a-stop-event",
                },
            },
        )
        self._write(
            tmp_path / "home" / ".cursor" / "hooks.json",
            {"version": 1, "hooks": {"preToolUse": [{"command": "./user-guard.sh"}]}},
        )
        assert self._reason(tmp_path) is None

    def test_stale_project_hook_passes_precheck_but_not_the_armed_check(
        self, tmp_path: Path
    ) -> None:
        """A stale project hook is replaced before arming; left in place, it holds."""
        path = self._write(
            tmp_path / "ws" / ".cursor" / "hooks.json",
            {"version": 1, "hooks": {"stop": [{"command": self._owned("/tmp/old")}]}},
        )
        precheck = cursor_native_bridge.completion_receipt_project_precheck(
            tmp_path / "ws", home=tmp_path / "home"
        )
        assert precheck is None
        assert self._reason(tmp_path) == f"foreign_stop_hook:{path}"

    @pytest.mark.parametrize("where", ["user", "system"])
    @pytest.mark.parametrize(
        "bridge", ["/tmp/bridge-x", "/tmp/other-session"], ids=["this-bridge", "other-bridge"]
    )
    def test_owned_shaped_hook_in_a_shared_file_holds(
        self, tmp_path: Path, where: str, bridge: str
    ) -> None:
        """Every Cursor session loads the user/system file, so no entry there is owned."""
        path = self._write(
            tmp_path / ("home/.cursor/hooks.json" if where == "user" else "etc/hooks.json"),
            {"version": 1, "hooks": {"stop": [{"command": self._owned(bridge)}]}},
        )
        before = path.read_bytes()
        reason = self._reason(tmp_path, system=(tmp_path / "etc" / "hooks.json",))
        assert reason == f"foreign_stop_hook:{path}"
        assert path.read_bytes() == before

    def test_legacy_usage_module_hook_in_user_file_holds(self, tmp_path: Path) -> None:
        path = self._write(
            tmp_path / "home" / ".cursor" / "hooks.json",
            {
                "version": 1,
                "hooks": {
                    "stop": [
                        {
                            "command": "/usr/bin/python3 -I -m omnigent.cursor_native_usage "
                            "record-usage --bridge-dir /tmp/bridge-x"
                        }
                    ]
                },
            },
        )
        assert self._reason(tmp_path) == f"foreign_stop_hook:{path}"

    def test_project_hook_bridge_matches_through_path_aliases(self, tmp_path: Path) -> None:
        real = tmp_path / "bridges" / "b1"
        real.mkdir(parents=True)
        alias = tmp_path / "bridge-link"
        alias.symlink_to(real)
        self._write(
            tmp_path / "ws" / ".cursor" / "hooks.json",
            {"version": 1, "hooks": {"stop": [{"command": self._owned(str(alias))}]}},
        )
        reason = cursor_native_bridge.completion_receipt_hook_hold_reason(
            tmp_path / "ws", real, home=tmp_path / "home", system_paths=()
        )
        assert reason is None

    @pytest.mark.parametrize("alias", ["same", "symlink", "dotdot", "cursor_dir_link"])
    def test_workspace_that_is_home_refuses_receipts(self, tmp_path: Path, alias: str) -> None:
        """With workspace == HOME the project hooks file is the user hooks file."""
        home = tmp_path / "home"
        home.mkdir()
        if alias == "same":
            ws = home
        elif alias == "symlink":
            ws = tmp_path / "ws-link"
            ws.symlink_to(home)
        elif alias == "dotdot":
            (home / "sub").mkdir()
            ws = home / "sub" / ".."
        else:
            ws = tmp_path / "ws"
            ws.mkdir()
            (home / ".cursor").mkdir()
            (ws / ".cursor").symlink_to(home / ".cursor")
        want = f"workspace_is_home:{ws}"
        assert cursor_native_bridge.completion_receipt_project_precheck(ws, home=home) == want
        reason = cursor_native_bridge.completion_receipt_hook_hold_reason(
            ws, Path("/tmp/bridge-x"), home=home, system_paths=()
        )
        assert reason == want

    def test_account_home_is_refused_even_when_home_env_differs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pwd

        account_home = tmp_path / "account-home"
        account_home.mkdir()
        entry = types.SimpleNamespace(pw_dir=str(account_home))
        monkeypatch.setattr(pwd, "getpwuid", lambda _uid: entry)
        reason = cursor_native_bridge.completion_receipt_project_precheck(
            account_home, home=tmp_path / "env-home"
        )
        assert reason == f"workspace_is_home:{account_home}"

    @pytest.mark.parametrize("where", ["project", "user", "system"])
    @pytest.mark.parametrize("event", ["stop", "subagentStop"])
    def test_foreign_stop_hook_anywhere_holds(
        self, tmp_path: Path, where: str, event: str
    ) -> None:
        paths = {
            "project": tmp_path / "ws" / ".cursor" / "hooks.json",
            "user": tmp_path / "home" / ".cursor" / "hooks.json",
            "system": tmp_path / "etc" / "hooks.json",
        }
        path = self._write(
            paths[where],
            {"version": 1, "hooks": {event: [{"command": self._owned()}, {"command": "./f.sh"}]}},
        )
        reason = self._reason(tmp_path, system=(paths["system"],))
        assert reason == f"foreign_stop_hook:{path}"

    @pytest.mark.parametrize(
        "payload",
        [
            "{not json",
            b"\xff\xfe{}",
            [],
            {"hooks": []},
            {"hooks": {"stop": {"command": "./f.sh"}}},
            {"hooks": {"stop": ["./f.sh"]}},
            {"hooks": {"stop": [{"cmd": "./f.sh"}]}},
        ],
    )
    def test_malformed_hooks_config_holds(self, tmp_path: Path, payload: object) -> None:
        path = self._write(tmp_path / "home" / ".cursor" / "hooks.json", payload)
        reason = self._reason(tmp_path)
        assert reason is not None
        assert reason.endswith(str(path))
        assert reason.split(":", 1)[0] in {"hooks_config_malformed", "foreign_stop_hook"}

    def test_unreadable_hooks_config_holds(self, tmp_path: Path) -> None:
        # A directory where the file should be cannot be read as a file.
        path = tmp_path / "ws" / ".cursor" / "hooks.json"
        path.mkdir(parents=True)
        assert self._reason(tmp_path) == f"hooks_config_unreadable:{path}"

    def test_arm_writes_epoch_only_when_capable(self, tmp_path: Path) -> None:
        from omnigent.harnesses.cursor_native import status

        bridge = tmp_path / "bridge"
        ws = tmp_path / "ws"
        kw = {"home": tmp_path / "home", "system_paths": ()}
        assert (
            cursor_native_bridge.arm_completion_receipts(bridge, ws, 111, opted_in=True, **kw)
            is None
        )
        assert status.read_receipt_epoch(bridge) == 111

    def test_arm_refused_drops_stale_epoch_and_keeps_user_hooks(self, tmp_path: Path) -> None:
        from omnigent.harnesses.cursor_native import status

        bridge = tmp_path / "bridge"
        ws = tmp_path / "ws"
        status.write_receipt_epoch(bridge, 111)  # a prior launch's capability
        path = self._write(
            ws / ".cursor" / "hooks.json",
            {"version": 1, "hooks": {"stop": [{"command": "./f.sh"}]}},
        )
        before = path.read_bytes()
        kw = {"home": tmp_path / "home", "system_paths": ()}
        reason = cursor_native_bridge.arm_completion_receipts(bridge, ws, 222, opted_in=True, **kw)
        assert reason == f"foreign_stop_hook:{path}"
        assert status.read_receipt_epoch(bridge) is None
        assert not (bridge / status.RECEIPT_EPOCH_FILE).exists()
        assert path.read_bytes() == before

    @pytest.mark.parametrize("opted_in", [True, False])
    def test_prepare_and_arm_raise_when_stale_epoch_survives(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, opted_in: bool
    ) -> None:
        import errno

        from omnigent.harnesses.cursor_native import status

        bridge = tmp_path / "bridge"
        ws = tmp_path / "ws"
        status.write_receipt_epoch(bridge, 111)

        def _fail(self: Path, missing_ok: bool = False) -> None:
            raise OSError(errno.EBUSY, "busy", str(self))

        monkeypatch.setattr(Path, "unlink", _fail)
        kw = {"home": tmp_path / "home"}
        with pytest.raises(status.ReceiptEpochClearError):
            cursor_native_bridge.prepare_completion_receipts(bridge, ws, opted_in=opted_in, **kw)
        with pytest.raises(status.ReceiptEpochClearError):
            cursor_native_bridge.arm_completion_receipts(
                bridge, ws, 222, opted_in=opted_in, system_paths=(), **kw
            )
        monkeypatch.undo()
        assert status.read_receipt_epoch(bridge) == 111  # never replaced by 222

    def test_prepare_and_arm_without_prior_epoch_do_not_raise(self, tmp_path: Path) -> None:
        from omnigent.harnesses.cursor_native import status

        bridge = tmp_path / "bridge"
        ws = tmp_path / "ws"
        kw = {"home": tmp_path / "home"}
        assert (
            cursor_native_bridge.prepare_completion_receipts(bridge, ws, opted_in=False, **kw)
            == "not_opted_in"
        )
        assert (
            cursor_native_bridge.arm_completion_receipts(
                bridge, ws, 222, opted_in=False, system_paths=(), **kw
            )
            == "not_opted_in"
        )
        assert status.read_receipt_epoch(bridge) is None

    def _launch(self, tmp_path: Path, bridge: Path, epoch: int) -> str | None:
        """The runner's order: prepare → write_hooks_config → arm."""
        ws = tmp_path / "ws"
        kw = {"home": tmp_path / "home"}
        precheck = cursor_native_bridge.prepare_completion_receipts(
            bridge, ws, opted_in=True, **kw
        )
        cursor_native_bridge.write_hooks_config(ws, bridge, python_executable=self._PY)
        return cursor_native_bridge.arm_completion_receipts(
            bridge, ws, epoch, opted_in=True, precheck=precheck, system_paths=(), **kw
        )

    def test_relaunch_and_new_session_arm_after_owned_replacement(self, tmp_path: Path) -> None:
        from omnigent.harnesses.cursor_native import status

        (tmp_path / "ws").mkdir()
        first, second = tmp_path / "bridge-1", tmp_path / "bridge-2"
        assert self._launch(tmp_path, first, 111) is None
        # Relaunch of the same session: its own project hook is already there.
        assert self._launch(tmp_path, first, 222) is None
        assert status.read_receipt_epoch(first) == 222
        # A new session in the same workspace replaces the prior session's hook.
        assert self._launch(tmp_path, second, 333) is None
        assert status.read_receipt_epoch(second) == 333
        import json

        written = json.loads((tmp_path / "ws" / ".cursor" / "hooks.json").read_text())
        assert [e["command"] for e in written["hooks"]["stop"]] == [self._owned(str(second))]

    def test_malformed_project_file_holds_although_the_rewrite_cleans_it(
        self, tmp_path: Path
    ) -> None:
        from omnigent.harnesses.cursor_native import status

        path = self._write(tmp_path / "ws" / ".cursor" / "hooks.json", "{not json")
        bridge = tmp_path / "bridge"
        status.write_receipt_epoch(bridge, 1)
        assert self._launch(tmp_path, bridge, 111) == f"hooks_config_malformed:{path}"
        assert status.read_receipt_epoch(bridge) is None

    def test_shared_user_hook_holds_at_launch_and_is_left_alone(self, tmp_path: Path) -> None:
        from omnigent.harnesses.cursor_native import status

        (tmp_path / "ws").mkdir()
        bridge = tmp_path / "bridge"
        user = self._write(
            tmp_path / "home" / ".cursor" / "hooks.json",
            {"version": 1, "hooks": {"stop": [{"command": self._owned(str(bridge))}]}},
        )
        before = user.read_bytes()
        assert self._launch(tmp_path, bridge, 111) == f"foreign_stop_hook:{user}"
        assert status.read_receipt_epoch(bridge) is None
        assert user.read_bytes() == before

    def test_arm_not_opted_in_ignores_hooks(self, tmp_path: Path) -> None:
        from omnigent.harnesses.cursor_native import status

        bridge = tmp_path / "bridge"
        status.write_receipt_epoch(bridge, 111)
        self._write(tmp_path / "ws" / ".cursor" / "hooks.json", "{not json")
        kw = {"home": tmp_path / "home", "system_paths": ()}
        assert (
            cursor_native_bridge.arm_completion_receipts(
                bridge, tmp_path / "ws", 222, opted_in=False, **kw
            )
            == "not_opted_in"
        )
        assert status.read_receipt_epoch(bridge) is None
