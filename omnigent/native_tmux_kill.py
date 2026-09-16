"""Shared leftover-pane SIGKILL escalation for native tmux bridges.

The native agent bridges (claude, cursor, codex) each run their TUI inside a
tmux pane on a per-session socket. ``kill_session`` tears the pane down with
``tmux kill-session``, but the foreground process inside the pane can survive
that teardown. This module owns the small shared helper that SIGKILLs such a
leftover pane process after ``kill-session`` returns.

The kill protocol is the one Claude already used: read the pane pid recorded
in ``tmux.json`` (fall back to ``tmux list-panes``), run ``kill-session``, then
SIGKILL the pane pid's process group via :mod:`omnigent.inner._proc` and wait
briefly for it to vanish. No new kill protocol is invented here.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from omnigent.inner import _proc

# Filename the runner writes into the bridge dir after launching the terminal.
_TMUX_FILE = "tmux.json"

# Per-command tmux budget for the list-panes pid lookup. Matches every native
# bridge's own _TMUX_SEND_TIMEOUT_S (10s) so the lookup behaves identically.
_TMUX_SEND_TIMEOUT_S = 10.0

# How long to wait for a SIGKILLed pane process to vanish, and how often to
# poll. Short on purpose: SIGKILL is immediate, we only confirm the reaping.
_TMUX_KILL_VERIFY_TIMEOUT_S = 1.0
_TMUX_KILL_VERIFY_POLL_INTERVAL_S = 0.05


def recorded_tmux_pid(bridge_dir: Path, *, tmux_file: str = _TMUX_FILE) -> int | None:
    """Read a valid pane pid recorded in ``tmux.json``, or ``None``.

    The runner records the pane's foreground pid when it advertises the tmux
    target. Missing/malformed file or non-int pid means no recording — the
    caller falls back to :func:`tmux_pane_pid`. ``bool`` is excluded so a stray
    ``true``/``false`` is not treated as ``1``/``0``.
    """
    try:
        raw = (bridge_dir / tmux_file).read_text(encoding="utf-8")
    except OSError:
        # Missing, unreadable, or a torn write — treat as "no pid recorded".
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
        return pid
    return None


def tmux_pane_pid(socket_path: str, tmux_target: str) -> int | None:
    """Read the foreground pane pid via ``tmux list-panes``, or ``None``.

    Used when ``tmux.json`` has no recorded pid. Any tmux/subprocess failure is
    treated as "no pid available" rather than raised — the caller still
    attempts ``kill-session`` and only escalates if it got a pid somehow.
    """
    try:
        proc = subprocess.run(
            [
                "tmux",
                "-S",
                socket_path,
                "list-panes",
                "-t",
                tmux_target,
                "-F",
                "#{pane_pid}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=_TMUX_SEND_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        pid = int(proc.stdout.split()[0])
    except (IndexError, ValueError):
        return None
    return pid if pid > 0 else None


def kill_leftover_tmux_process(pid: int) -> None:
    """SIGKILL a pane process that survived tmux teardown, with a deadline.

    Reuses :mod:`omnigent.inner._proc` exactly the way Claude did inline:
    ``process_alive`` probes liveness, ``_killpg`` signals the target's whole
    process group (and refuses our own group, so it can't take down the
    harness/pytest). After the signal we poll briefly until the pid is gone.
    """
    if not _proc.process_alive(pid):
        return
    # _killpg resolves the target's group and rejects this process's own group.
    if not _proc._killpg(pid, _proc._SIGKILL):
        return
    deadline = time.monotonic() + _TMUX_KILL_VERIFY_TIMEOUT_S
    while time.monotonic() < deadline:
        if not _proc.process_alive(pid):
            return
        time.sleep(_TMUX_KILL_VERIFY_POLL_INTERVAL_S)


def kill_session_with_escalation(
    bridge_dir: Path,
    *,
    socket_path: str,
    tmux_target: str,
    kill_session_fn: Callable[[str, str], None],
) -> None:
    """Resolve the pane pid, run ``kill-session``, then SIGKILL any leftover.

    Shared hard-stop used by the claude/cursor/codex native bridges. The caller
    passes its own ``kill_session_fn`` so the bridge's local ``_run_tmux`` (and
    its error messages) stay authoritative — this helper only owns the
    pid-resolution and leftover-escalation that is identical across bridges.

    If ``kill-session`` reports the session/server already gone, the stop is
    treated as successful and any leftover pane pid is still escalated.
    """
    pane_pid = recorded_tmux_pid(bridge_dir)
    if pane_pid is None:
        pane_pid = tmux_pane_pid(socket_path, tmux_target)
    try:
        kill_session_fn(socket_path, tmux_target)
    except RuntimeError as exc:
        detail = str(exc).lower()
        # tmux already gone — nothing to kill, but escalate any leftover pane.
        if "can't find session" in detail or "no server running on" in detail:
            if pane_pid is not None:
                kill_leftover_tmux_process(pane_pid)
            return
        raise
    if pane_pid is not None:
        kill_leftover_tmux_process(pane_pid)
