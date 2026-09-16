"""Tests for the native-pane idle reaper (issue #1349)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from omnigent.entities.session_resources import terminal_resource_id
from omnigent.harnesses.claude_native import bridge as claude_native_bridge
from omnigent.native import native_cost_popup
from omnigent.runner.app import create_runner_app
from omnigent.runner.resource_registry import SessionResourceRegistry
from omnigent.terminals.pane_reaper import (
    _DEFAULT_IDLE_TIMEOUT_S,
    _IDLE_TIMEOUT_ENV,
    NativePaneReaper,
    PaneRef,
    _pane_is_busy_after_harness,
    resolve_native_pane_idle_timeout_s,
)
from omnigent.terminals.registry import TerminalRegistry
from tests.runner.helpers import NullServerClient


def _pane(conv: str, name: str = "claude") -> PaneRef:
    return PaneRef(conv, f"terminal:{name}:main", name, Path(f"/tmp/omni-test/{conv}.sock"))


class _Fakes:
    """Mutable test doubles so a test can flip busy/panes between scans."""

    def __init__(self) -> None:
        self.panes: list[PaneRef] = []
        self.busy: set[str] = set()
        self.reaped: list[str] = []
        # Optional per-call override: (pane, call_index) -> bool. Lets a test make
        # is_busy answer differently on the classify pass vs the re-check pass.
        self.busy_override: Callable[[PaneRef, int], bool] | None = None
        self.busy_calls = 0

    async def is_busy(self, pane: PaneRef) -> bool:
        self.busy_calls += 1
        if self.busy_override is not None:
            return self.busy_override(pane, self.busy_calls)
        return pane.conversation_id in self.busy

    async def reap(self, pane: PaneRef) -> None:
        self.reaped.append(pane.conversation_id)
        self.panes = [p for p in self.panes if p.conversation_id != pane.conversation_id]


def _make(fakes: _Fakes, *, timeout: float = 100.0, interval: float = 0.01) -> NativePaneReaper:
    return NativePaneReaper(
        list_native_panes=lambda: list(fakes.panes),
        is_busy=fakes.is_busy,
        reap=fakes.reap,
        idle_timeout_s=timeout,
        reaper_interval_s=interval,
    )


# ── Pure idle-clock decision (_classify) ────────────────────────────────────


def test_classify_reaps_only_after_full_window() -> None:
    f = _Fakes()
    p = _pane("conv_a")
    f.panes = [p]
    r = _make(f, timeout=100.0)
    assert r._classify(1000.0, [p], busy_convs=set()) == []  # first obs: grace
    assert r._classify(1099.0, [p], busy_convs=set()) == []  # 99s < 100s
    assert r._classify(1100.0, [p], busy_convs=set()) == [p]  # window elapsed


def test_classify_busy_rearms_clock() -> None:
    f = _Fakes()
    p = _pane("conv_a")
    r = _make(f, timeout=10.0)
    r._classify(0.0, [p], busy_convs={"conv_a"})
    assert r._classify(1000.0, [p], busy_convs={"conv_a"}) == []  # busy re-arms
    r._classify(1000.0, [p], busy_convs=set())  # now idle, grace
    assert r._classify(1010.0, [p], busy_convs=set()) == [p]


def test_classify_first_observation_grace() -> None:
    f = _Fakes()
    p = _pane("conv_a")
    r = _make(f, timeout=0.001)
    assert r._classify(5.0, [p], busy_convs=set()) == []  # clock seeded this pass


def test_classify_forgets_gone_panes() -> None:
    f = _Fakes()
    p = _pane("conv_a")
    r = _make(f, timeout=10.0)
    r._classify(0.0, [p], busy_convs=set())
    assert "conv_a" in r._last_busy_at
    r._classify(1.0, [], busy_convs=set())  # pane gone
    assert "conv_a" not in r._last_busy_at


# ── Scan behaviour (_scan_once): reap, skip-busy, TOCTOU re-check ────────────


async def test_scan_reaps_idle_unbusy_pane() -> None:
    f = _Fakes()
    p = _pane("conv_a")
    f.panes = [p]
    r = _make(f, timeout=10.0)
    r._last_busy_at["conv_a"] = time.monotonic() - 1000  # already idle past window
    await r._scan_once()
    assert f.reaped == ["conv_a"]


async def test_scan_skips_busy_pane() -> None:
    f = _Fakes()
    p = _pane("conv_a")
    f.panes = [p]
    f.busy = {"conv_a"}
    r = _make(f, timeout=10.0)
    r._last_busy_at["conv_a"] = time.monotonic() - 1000
    await r._scan_once()
    assert f.reaped == []  # busy → not reaped, clock re-armed


async def test_scan_recheck_spares_pane_that_became_busy() -> None:
    """TOCTOU guard: a pane idle at selection but busy at the pre-reap re-check
    must NOT be reaped (a turn/client/autonomous run started in between)."""
    f = _Fakes()
    p = _pane("conv_a")
    f.panes = [p]
    # is_busy: False on the classify-phase call (call 1), True on the re-check
    # call (call 2) — simulating a turn starting between selection and teardown.
    f.busy_override = lambda pane, n: n >= 2
    r = _make(f, timeout=10.0)
    r._last_busy_at["conv_a"] = time.monotonic() - 1000
    await r._scan_once()
    assert f.reaped == []  # spared by the re-check
    assert f.busy_calls == 2  # classify + re-check


# ── Env resolver ────────────────────────────────────────────────────────────


def test_resolve_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_IDLE_TIMEOUT_ENV, raising=False)
    assert resolve_native_pane_idle_timeout_s() == float(_DEFAULT_IDLE_TIMEOUT_S)


def test_resolve_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_IDLE_TIMEOUT_ENV, "120")
    assert resolve_native_pane_idle_timeout_s() == 120.0


def test_resolve_zero_disables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_IDLE_TIMEOUT_ENV, "0")
    assert resolve_native_pane_idle_timeout_s() == 0.0


@pytest.mark.parametrize("bad", ["abc", "-5", ""])
def test_resolve_invalid_falls_back(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv(_IDLE_TIMEOUT_ENV, bad)
    assert resolve_native_pane_idle_timeout_s() == float(_DEFAULT_IDLE_TIMEOUT_S)


# ── Loop smoke (start/shutdown + disable) ───────────────────────────────────


async def test_loop_reaps_idle_pane() -> None:
    f = _Fakes()
    f.panes = [_pane("conv_a")]
    r = _make(f, timeout=0.0001, interval=0.01)
    await r.start()
    try:
        for _ in range(100):
            if f.reaped:
                break
            await asyncio.sleep(0.01)
    finally:
        await r.shutdown()
    assert f.reaped == ["conv_a"]


async def test_loop_disabled_when_timeout_non_positive() -> None:
    f = _Fakes()
    f.panes = [_pane("conv_a")]
    r = _make(f, timeout=0.0, interval=0.01)  # 0 disables
    await r.start()
    try:
        await asyncio.sleep(0.1)
    finally:
        await r.shutdown()
    assert f.reaped == []


def test_kimi_is_exempt_from_pane_reaping() -> None:
    # kimi records no resumable chat id, so a reaped pane cannot be re-created
    # with its context; the name filter must never offer kimi panes to the reaper.
    from omnigent.terminals.pane_reaper import NATIVE_PANE_TERMINAL_NAMES

    assert "kimi" not in NATIVE_PANE_TERMINAL_NAMES
    assert "claude" in NATIVE_PANE_TERMINAL_NAMES


async def test_runner_busy_check_spares_a_pane_parked_on_an_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The runner's busy check treats a fresh approval-wait marker as busy.

    A pane parked on a permission prompt has no active turn, no ``running``
    status, no attached client and no output, so every other signal reads idle
    and the reaper would kill the prompt under a still-answerable card.
    """
    # Bound by name when the app is built, so stub before building: no tmux here.
    monkeypatch.setattr(native_cost_popup, "_list_tmux_clients", lambda *_args: [])
    monkeypatch.setattr(native_cost_popup, "_tmux_window_activity_at", lambda *_args: None)
    monkeypatch.setattr(claude_native_bridge, "_APPROVAL_WAIT_ROOT", tmp_path / "approval-waits")
    registry = TerminalRegistry()
    app = create_runner_app(
        terminal_registry=registry,
        resource_registry=SessionResourceRegistry(terminal_registry=registry),
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    reaper = app.state.native_pane_reaper
    assert reaper is not None
    pane = PaneRef(
        "conv_parked", terminal_resource_id("claude", "main"), "claude", tmp_path / "tmux.sock"
    )

    assert not await reaper._is_busy(pane)

    marker = claude_native_bridge.approval_wait_marker_path("conv_parked")
    marker.parent.mkdir(parents=True)
    claude_native_bridge.touch_approval_wait_marker(marker)
    assert await reaper._is_busy(pane)
    # Another session's parked prompt does not spare this pane.
    other = PaneRef("conv_other", pane.terminal_id, "claude", pane.socket_path)
    assert not await reaper._is_busy(other)
# ── Busy predicate (_pane_is_busy_after_harness) ───────────────────────────
#
# The busy logic was extracted from the 10k-line runner app so it can be tested
# in isolation with a fake process manager + fake tmux probes. The core fix:
# once the harness subprocess is gone (release() only pops the PM entry, it
# does NOT close the native tmux pane), a stale "running" status and the TUI's
# redraw-driven window_activity must NOT pin the leaked pane — only an
# attached tmux client (a human) should spare it.


class _FakePM:
    """Minimal HarnessProcessManager double: just has_session + has_active_turn."""

    def __init__(self, *, has_session: bool = True, has_active_turn: bool = False) -> None:
        self._has_session = has_session
        self._has_active_turn = has_active_turn

    def has_session(self, conversation_id: str) -> bool:
        return self._has_session

    def has_active_turn(self, conversation_id: str) -> bool:
        return self._has_active_turn


def _tmux_fakes(
    *, clients: list[object] | None = None, activity_at: float | None = None
) -> tuple[Callable[[str, str], list[object]], Callable[[str, str], float | None]]:
    """Return (list_clients, window_activity_at) sync fakes with canned answers."""
    canned_clients = clients if clients is not None else []

    def list_clients(socket: str, pane: str) -> list[object]:
        return list(canned_clients)

    def window_activity(socket: str, pane: str) -> float | None:
        return activity_at

    return list_clients, window_activity


async def test_busy_orphaned_stale_running_fresh_activity_no_clients_is_reapable() -> None:
    """Orphaned pane (harness gone) with stale "running" + fresh activity but
    no attached client must NOT be busy — the TUI redraw must not pin it."""
    list_clients, window_activity = _tmux_fakes(
        clients=[], activity_at=1000.0  # fresh relative to now=1001 (< 120s)
    )
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=_FakePM(has_session=False, has_active_turn=False),
        native_pane_status={"conv_a": "running"},  # stale
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1001.0,
    )
    assert busy is False


async def test_busy_live_harness_running_is_busy() -> None:
    """Live harness subprocess reporting "running" stays busy (autonomous turn)."""
    list_clients, window_activity = _tmux_fakes(clients=[], activity_at=None)
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=_FakePM(has_session=True, has_active_turn=False),
        native_pane_status={"conv_a": "running"},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,
    )
    assert busy is True


async def test_busy_orphaned_with_attached_client_is_busy() -> None:
    """Orphaned pane with an attached human (tmux client) is spared."""
    list_clients, window_activity = _tmux_fakes(
        clients=["user@host"], activity_at=1000.0
    )
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=_FakePM(has_session=False, has_active_turn=False),
        native_pane_status={"conv_a": "running"},  # stale but irrelevant
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1001.0,
    )
    assert busy is True


async def test_busy_in_flight_turn_busy_without_session_entry() -> None:
    """An in-flight turn is busy even when the PM has no session entry."""
    list_clients, window_activity = _tmux_fakes(clients=[], activity_at=None)
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),  # not in local active_turns
        process_manager=_FakePM(has_session=False, has_active_turn=True),  # PM turn in flight
        native_pane_status={},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,
    )
    assert busy is True


async def test_busy_local_active_turn_busy_without_pm() -> None:
    """A locally-tracked in-flight turn (no PM at all) is busy."""
    list_clients, window_activity = _tmux_fakes(clients=[], activity_at=None)
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns={"conv_a"},  # local turn in flight
        process_manager=None,
        native_pane_status={},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,
    )
    assert busy is True


async def test_busy_no_pm_keeps_running_signal() -> None:
    """Without a PM (tests/runners), the original "running" signal still applies."""
    list_clients, window_activity = _tmux_fakes(clients=[], activity_at=None)
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=None,
        native_pane_status={"conv_a": "running"},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,
    )
    assert busy is True


async def test_busy_no_pm_window_activity_keeps_pane() -> None:
    """Without a PM, fresh window_activity still spares a producing terminal."""
    list_clients, window_activity = _tmux_fakes(clients=[], activity_at=999.0)
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=None,
        native_pane_status={},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,  # 1s ago < 120s window
    )
    assert busy is True


async def test_busy_no_pm_stale_window_activity_is_reapable() -> None:
    """Without a PM, window_activity older than the busy window is reapable."""
    list_clients, window_activity = _tmux_fakes(
        clients=[], activity_at=800.0  # 200s ago > 120s window
    )
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=None,
        native_pane_status={},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,
    )
    assert busy is False


async def test_busy_live_harness_no_signals_no_clients_is_reapable() -> None:
    """Live harness, no running status, no clients, no recent activity → reapable."""
    list_clients, window_activity = _tmux_fakes(clients=[], activity_at=None)
    busy = await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=set(),
        process_manager=_FakePM(has_session=True, has_active_turn=False),
        native_pane_status={},
        list_tmux_clients=list_clients,
        tmux_window_activity_at=window_activity,
        now=1000.0,
    )
    assert busy is False
