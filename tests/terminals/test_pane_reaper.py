"""Tests for the native-pane idle reaper (issue #1349)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from omnigent.entities.session_resources import terminal_resource_id
from omnigent.harnesses.claude_native import bridge as claude_native_bridge
from omnigent.inner.terminal import TerminalInstance
from omnigent.native import native_cost_popup
from omnigent.runner.app import create_runner_app
from omnigent.runner.resource_registry import SessionResourceRegistry
from omnigent.terminals.pane_reaper import (
    _DEFAULT_IDLE_TIMEOUT_S,
    _IDLE_TIMEOUT_ENV,
    PANE_OUTPUT_BUSY_WINDOW_S,
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
    monkeypatch.setattr(native_cost_popup, "_tmux_last_client_input_at", lambda *_args: None)
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


async def test_runner_busy_check_counts_a_viewer_only_on_recent_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    An attached viewer spares the pane only while a human recently drove it.

    A CLI tab's keypress (tmux ``client_activity``) or a web-bridge event (the
    terminal's interaction stamp) inside the busy window reads busy; an idle
    attached viewer, or stale input, does not — a tab left open overnight must
    not keep the native stack resident.
    """
    tmux_input_at: dict[str, float | None] = {"value": None}
    monkeypatch.setattr(
        native_cost_popup, "_tmux_last_client_input_at", lambda *_args: tmux_input_at["value"]
    )
    monkeypatch.setattr(native_cost_popup, "_tmux_window_activity_at", lambda *_args: None)
    monkeypatch.setattr(claude_native_bridge, "_APPROVAL_WAIT_ROOT", tmp_path / "approval-waits")
    registry = TerminalRegistry()
    instance = TerminalInstance(
        name="claude",
        session_key="main",
        socket_path=tmp_path / "tmux.sock",
        private_dir=tmp_path,
        running=True,
    )
    registry._by_conversation["conv_viewed"] = {("claude", "main"): instance}
    app = create_runner_app(
        terminal_registry=registry,
        resource_registry=SessionResourceRegistry(terminal_registry=registry),
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    reaper = app.state.native_pane_reaper
    assert reaper is not None
    pane = PaneRef(
        "conv_viewed", terminal_resource_id("claude", "main"), "claude", tmp_path / "tmux.sock"
    )

    # Attached but idle on both signals: not busy.
    assert not await reaper._is_busy(pane)
    # A CLI keypress inside the window spares the pane; a stale one does not.
    tmux_input_at["value"] = time.time() - 1.0
    assert await reaper._is_busy(pane)
    tmux_input_at["value"] = time.time() - PANE_OUTPUT_BUSY_WINDOW_S - 1.0
    assert not await reaper._is_busy(pane)
    # A web-bridge event on the pane's terminal spares it; a stale one does not.
    instance.note_client_interaction()
    assert await reaper._is_busy(pane)
    instance._last_client_interaction_at = time.monotonic() - PANE_OUTPUT_BUSY_WINDOW_S - 1.0
    assert not await reaper._is_busy(pane)


# ── Busy predicate (_pane_is_busy_after_harness) ───────────────────────────
#
# The busy logic was extracted from the 10k-line runner app so it can be tested
# in isolation with a fake process manager + fake tmux probes. The core fix:
# once the harness subprocess is gone (release() only pops the PM entry, it
# does NOT close the native tmux pane), a stale "running" status and the TUI's
# redraw-driven window_activity must NOT pin the leaked pane — only a human who
# recently drove the pane (CLI keypress / web-bridge event) should spare it.


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
    *, input_at: float | None = None, activity_at: float | None = None
) -> tuple[Callable[[str, str], float | None], Callable[[str, str], float | None]]:
    """Return (last_client_input_at, window_activity_at) sync fakes with canned answers."""

    def last_client_input(socket: str, pane: str) -> float | None:
        return input_at

    def window_activity(socket: str, pane: str) -> float | None:
        return activity_at

    return last_client_input, window_activity


async def _busy(
    *,
    process_manager: _FakePM | None,
    now: float,
    active_turns: set[str] | None = None,
    native_pane_status: dict[str, str] | None = None,
    input_at: float | None = None,
    activity_at: float | None = None,
    web_interaction: bool = False,
) -> bool:
    last_client_input, window_activity = _tmux_fakes(input_at=input_at, activity_at=activity_at)
    return await _pane_is_busy_after_harness(
        conv_id="conv_a",
        socket_path=Path("/tmp/x.sock"),
        active_turns=active_turns if active_turns is not None else set(),
        process_manager=process_manager,
        native_pane_status=native_pane_status if native_pane_status is not None else {},
        tmux_last_client_input_at=last_client_input,
        client_interaction_within=lambda _window: web_interaction,
        tmux_window_activity_at=window_activity,
        now=now,
    )


async def test_busy_orphaned_stale_running_fresh_activity_no_input_is_reapable() -> None:
    """Orphaned pane (harness gone) with stale "running" + fresh activity but
    no recent human input must NOT be busy — the TUI redraw must not pin it."""
    busy = await _busy(
        process_manager=_FakePM(has_session=False, has_active_turn=False),
        native_pane_status={"conv_a": "running"},  # stale
        activity_at=1000.0,  # fresh relative to now=1001 (< 120s)
        now=1001.0,
    )
    assert busy is False


async def test_busy_live_harness_running_is_busy() -> None:
    """Live harness subprocess reporting "running" stays busy (autonomous turn)."""
    busy = await _busy(
        process_manager=_FakePM(has_session=True, has_active_turn=False),
        native_pane_status={"conv_a": "running"},
        now=1000.0,
    )
    assert busy is True


async def test_busy_orphaned_with_recent_cli_input_is_busy() -> None:
    """Orphaned pane a human just typed into (CLI keypress) is spared."""
    busy = await _busy(
        process_manager=_FakePM(has_session=False, has_active_turn=False),
        native_pane_status={"conv_a": "running"},  # stale but irrelevant
        input_at=1000.0,
        now=1001.0,
    )
    assert busy is True


async def test_busy_orphaned_with_recent_web_interaction_is_busy() -> None:
    """Orphaned pane with a recent web-bridge interaction is spared."""
    busy = await _busy(
        process_manager=_FakePM(has_session=False, has_active_turn=False),
        web_interaction=True,
        now=1001.0,
    )
    assert busy is True


async def test_busy_orphaned_with_only_stale_input_is_reapable() -> None:
    """An attached viewer whose last input is outside the window does not spare."""
    busy = await _busy(
        process_manager=_FakePM(has_session=False, has_active_turn=False),
        input_at=800.0,  # 200s ago > 120s window
        now=1000.0,
    )
    assert busy is False


async def test_busy_in_flight_turn_busy_without_session_entry() -> None:
    """An in-flight turn is busy even when the PM has no session entry."""
    busy = await _busy(
        process_manager=_FakePM(has_session=False, has_active_turn=True),  # PM turn in flight
        now=1000.0,
    )
    assert busy is True


async def test_busy_local_active_turn_busy_without_pm() -> None:
    """A locally-tracked in-flight turn (no PM at all) is busy."""
    busy = await _busy(process_manager=None, active_turns={"conv_a"}, now=1000.0)
    assert busy is True


async def test_busy_no_pm_keeps_running_signal() -> None:
    """Without a PM (tests/runners), the original "running" signal still applies."""
    busy = await _busy(process_manager=None, native_pane_status={"conv_a": "running"}, now=1000.0)
    assert busy is True


async def test_busy_no_pm_window_activity_keeps_pane() -> None:
    """Without a PM, fresh window_activity still spares a producing terminal."""
    busy = await _busy(process_manager=None, activity_at=999.0, now=1000.0)  # 1s ago < 120s
    assert busy is True


async def test_busy_no_pm_stale_window_activity_is_reapable() -> None:
    """Without a PM, window_activity older than the busy window is reapable."""
    busy = await _busy(process_manager=None, activity_at=800.0, now=1000.0)  # 200s > 120s
    assert busy is False


async def test_busy_live_harness_no_signals_is_reapable() -> None:
    """Live harness, no running status, no input, no recent activity → reapable."""
    busy = await _busy(
        process_manager=_FakePM(has_session=True, has_active_turn=False), now=1000.0
    )
    assert busy is False
