"""Safe fake-tmux evidence for Claude native kill escalation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from omnigent import claude_native_bridge as bridge
from omnigent.inner import _proc


def main() -> None:
    """Show target-only fake tmux teardown and own-group protection."""
    commands: list[list[str]] = []
    killed: list[tuple[int, int]] = []
    alive = iter((True, False))

    def fake_run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="24680\n", stderr="")

    def fake_killpg(pid: int, sig: int) -> bool:
        killed.append((pid, sig))
        return True

    def fake_wait(*_args: object, **_kwargs: object) -> dict[str, str]:
        return {"socket_path": "/tmp/fake.sock", "tmux_target": "main"}

    with (
        patch.object(bridge, "_wait_for_tmux_info", fake_wait),
        patch.object(subprocess, "run", fake_run),
        patch.object(_proc, "process_alive", lambda _pid: next(alive)),
        patch.object(_proc, "_killpg", fake_killpg),
    ):
        bridge.kill_session(Path("/tmp/fake-bridge"))

    own_group_calls: list[tuple[int, int]] = []
    with (
        patch.object(_proc, "_getpgid_fn", lambda _pid: 777),
        patch.object(
            _proc,
            "_killpg_fn",
            lambda pgid, sig: own_group_calls.append((pgid, sig)),
        ),
    ):
        own_pgid_refused = not _proc._killpg(12345, _proc._SIGKILL)

    print(f"tmux_calls={commands!r}")
    print(f"sigkill_calls={killed!r}")
    print(f"own_pgid_refused={own_pgid_refused}, os_killpg_calls={own_group_calls!r}")


if __name__ == "__main__":
    main()
