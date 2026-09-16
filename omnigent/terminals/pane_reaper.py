"""Idle reaper for native-harness terminal panes (issue #1349).

Native CLI sessions (``claude-native`` / ``codex-native`` / ``cursor-native`` /
...) run their vendor CLI plus a full MCP fleet inside a persistent tmux pane
held for the whole conversation lifetime. Unlike the SDK harness proxies — which
``HarnessProcessManager._idle_reaper_loop`` reaps after an idle window — these
panes have no idle reaper, so on a shared/multi-conversation runner memory grows
without bound as idle conversations accumulate, independent of how many are
actually active (#1349).

This reaps a single native pane only when it is genuinely unused. "Busy" is the
disjunction of three signals (any one spares the pane):

  * an in-flight runner turn (``has_active_turn``), OR
  * the pane's PTY watcher currently reports ``running`` — i.e. the vendor CLI is
    working autonomously *between* runner turns (native turns clear the runner's
    ``_active_turns`` right after the prompt is pasted, so this is the load-bearing
    signal for a long autonomous turn), OR
  * a tmux client is attached (a human is watching the pane).

A pane idle on all three for longer than the window is reaped, with a **second
busy re-check immediately before teardown** to close the select→reap race. The
tmux client probe is a blocking ``subprocess`` call, so it runs off the event
loop via ``asyncio.to_thread``.

Teardown is **pane-scoped** (``reap`` closes only the one native terminal, not
the conversation's other terminals), leaving the session's primary OSEnv +
server-side transcript intact — the next message re-creates the pane and the
vendor CLI resumes via its own ``--resume``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Callable, Collection, Mapping
from pathlib import Path
from typing import NamedTuple, Protocol

_logger = logging.getLogger(__name__)

# A pane whose window emitted output this recently counts as busy. tmux's own
# activity clock is evidence independent of the harness status pipeline, whose
# silent stall must not get a live, producing terminal reaped. Two reaper scan
# intervals, so any output between scans re-arms the idle clock.
PANE_OUTPUT_BUSY_WINDOW_S = 120.0

# Native CLI panes are keyed (conversation_id, <harness short name>, "main") in
# the terminal registry. These short names match the ``terminal_name`` the
# per-harness ``_auto_create_<harness>_terminal`` paths launch with. This is the
# cheap name pre-filter; the wiring additionally confirms the registry resource
# ROLE is a native harness (so a user terminal that merely shares the name is not
# reaped — see ``create_runner_app``).
NATIVE_PANE_TERMINAL_NAMES: frozenset[str] = frozenset(
    {
        "claude",
        "codex",
        "cursor",
        "goose",
        "hermes",
        "kiro",
        "qwen",
        "kimi",
        "pi",
        "antigravity",
        "opencode",
    }
)

# Default idle window before an unused native pane is reaped. Mirrors
# ``HarnessProcessManager``'s 1-hour SDK-proxy default for consistency.
_DEFAULT_IDLE_TIMEOUT_S = 60 * 60
_DEFAULT_REAPER_INTERVAL_S = 60.0
_IDLE_TIMEOUT_ENV = "OMNIGENT_NATIVE_PANE_IDLE_TIMEOUT_S"


class PaneRef(NamedTuple):
    """A live native CLI pane the reaper may reclaim.

    :param conversation_id: AP-allocated conversation id, e.g. ``"conv_abc123"``.
    :param terminal_id: Resource id of the native terminal, e.g.
        ``terminal_resource_id("claude", "main")`` — used for pane-scoped close.
    :param terminal_name: Harness short-name, e.g. ``"claude"``.
    :param socket_path: tmux socket for the attached-client probe.
    """

    conversation_id: str
    terminal_id: str
    terminal_name: str
    socket_path: Path


class _ProcessManagerLike(Protocol):
    """Subset of ``HarnessProcessManager`` the busy predicate consults.

    A narrow protocol keeps the helper testable with a fake and decouples it
    from the runtime harness module, so tests never import the 10k-line app.
    """

    def has_session(self, conversation_id: str) -> bool:
        """``True`` if a harness subprocess entry is registered for the id."""

    def has_active_turn(self, conversation_id: str) -> bool:
        """``True`` if an in-flight harness turn is streaming for the id."""


async def _pane_is_busy_after_harness(
    *,
    conv_id: str,
    socket_path: Path,
    active_turns: Collection[str],
    process_manager: _ProcessManagerLike | None,
    native_pane_status: Mapping[str, str],
    list_tmux_clients: Callable[[str, str], list[object]],
    tmux_window_activity_at: Callable[[str, str], float | None],
    now: float,
) -> bool:
    """Decide whether a native pane is busy enough to spare from reaping.

    Order matters: an in-flight turn is checked first and always wins, even
    for a pane whose harness subprocess has already been released — a turn
    can outlive the PM entry it rides on.

    Once the harness subprocess is gone (``has_session`` is False), ``release``
    only popped the PM entry; it did NOT close the native tmux pane. The vendor
    TUI (notably ``cursor``) keeps redrawing, which would otherwise pin the
    leaked pane two ways: a stale ``"running"`` status (only cleared on full
    ``delete_session``) and fresh tmux ``window_activity``. For such an
    orphaned pane only an attached human — a tmux client — should spare it;
    the redraw noise must not defeat the reaper.

    When ``process_manager`` is ``None`` (tests / runners without a PM) the
    original busy signals are kept: ``"running"`` status, an attached client,
    or recent ``window_activity`` (which covers a silently-stalled status
    pipeline so a live, producing terminal is never reaped).
    """
    # In-flight runner turn: always busy, even for an orphaned pane whose PM
    # entry is gone — a turn can outlive the entry it rides on.
    if conv_id in active_turns or (
        process_manager is not None and process_manager.has_active_turn(conv_id)
    ):
        return True
    # Harness subprocess is gone. release() only pops the PM entry; it does NOT
    # close the native tmux pane, and the vendor TUI keeps redrawing. A stale
    # "running" status (cleared only on delete_session) or fresh window_activity
    # would pin this leaked pane forever — only an attached human spares it.
    if process_manager is not None and not process_manager.has_session(conv_id):
        clients = await asyncio.to_thread(list_tmux_clients, str(socket_path), "main")
        return bool(clients)
    # Harness still alive, or no PM at all (tests / runners without one): keep
    # the original signals. "running" covers an autonomous turn between runner
    # turns; window_activity covers a silently-stalled status pipeline.
    if native_pane_status.get(conv_id) == "running":
        return True
    clients = await asyncio.to_thread(list_tmux_clients, str(socket_path), "main")
    if clients:
        return True
    activity_at = await asyncio.to_thread(tmux_window_activity_at, str(socket_path), "main")
    return activity_at is not None and now - activity_at < PANE_OUTPUT_BUSY_WINDOW_S


def resolve_native_pane_idle_timeout_s() -> float:
    """Resolve the native-pane idle window in seconds.

    Honors :envvar:`OMNIGENT_NATIVE_PANE_IDLE_TIMEOUT_S` (``0`` disables pane
    reaping); otherwise the 1-hour default. An unparseable or negative value
    logs a warning and falls back to the default rather than failing the runner
    at boot — an env typo shouldn't take the runner down or (worse) make the
    reaper act on a bogus window.
    """
    raw = os.environ.get(_IDLE_TIMEOUT_ENV)
    if not raw:
        return float(_DEFAULT_IDLE_TIMEOUT_S)
    try:
        value = float(raw)
    except ValueError:
        _logger.warning(
            "%s=%r is not a number; using default %ss",
            _IDLE_TIMEOUT_ENV,
            raw,
            _DEFAULT_IDLE_TIMEOUT_S,
        )
        return float(_DEFAULT_IDLE_TIMEOUT_S)
    if value < 0:
        _logger.warning(
            "%s=%r is negative; using default %ss",
            _IDLE_TIMEOUT_ENV,
            raw,
            _DEFAULT_IDLE_TIMEOUT_S,
        )
        return float(_DEFAULT_IDLE_TIMEOUT_S)
    return value


class NativePaneReaper:
    """Background task that reaps idle, unattended native terminal panes.

    :param list_native_panes: Returns the currently-live native panes (already
        role-confirmed by the caller) as :class:`PaneRef` values.
    :param is_busy: ``async`` predicate — ``True`` if the pane has an in-flight
        turn, is reporting ``running``, or has an attached tmux client. Async so
        the (blocking) tmux probe runs off the event loop.
    :param reap: ``async`` pane-scoped teardown — closes only this one native
        terminal, leaving the session resumable.
    :param idle_timeout_s: Idle window before reaping. ``None`` resolves the env
        knob; ``<= 0`` disables reaping.
    :param reaper_interval_s: Seconds between scans.
    """

    def __init__(
        self,
        *,
        list_native_panes: Callable[[], list[PaneRef]],
        is_busy: Callable[[PaneRef], Awaitable[bool]],
        reap: Callable[[PaneRef], Awaitable[None]],
        idle_timeout_s: float | None = None,
        reaper_interval_s: float = _DEFAULT_REAPER_INTERVAL_S,
    ) -> None:
        self._list_native_panes = list_native_panes
        self._is_busy = is_busy
        self._reap = reap
        self._idle_timeout_s = (
            idle_timeout_s if idle_timeout_s is not None else resolve_native_pane_idle_timeout_s()
        )
        self._reaper_interval_s = reaper_interval_s
        # conversation_id -> monotonic time it was last observed busy.
        self._last_busy_at: dict[str, float] = {}
        self._task: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        """Spawn the reaper loop (idempotent)."""
        if self._started:
            return
        self._started = True
        self._task = asyncio.create_task(self._reap_loop(), name="native-pane-idle-reaper")
        _logger.info(
            "native pane reaper started (idle_timeout=%ss, interval=%ss%s)",
            self._idle_timeout_s,
            self._reaper_interval_s,
            "; DISABLED" if self._idle_timeout_s <= 0 else "",
        )

    async def shutdown(self) -> None:
        """Cancel the reaper loop."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._started = False

    def _classify(self, now: float, panes: list[PaneRef], busy_convs: set[str]) -> list[PaneRef]:
        """Pure idle-clock decision: which panes are reapable right now.

        Given the set of conversation ids observed busy this scan, maintain the
        per-conversation idle clock and return the panes idle for at least
        ``idle_timeout_s``. A busy pane re-arms its clock; a newly-observed idle
        pane gets one full window of grace before it is eligible. No I/O, so it is
        unit-testable with an injected ``now`` and ``busy_convs``.
        """
        live: set[str] = set()
        reapable: list[PaneRef] = []
        for pane in panes:
            conv = pane.conversation_id
            live.add(conv)
            if conv in busy_convs:
                self._last_busy_at[conv] = now
                continue
            last = self._last_busy_at.get(conv)
            if last is None:
                self._last_busy_at[conv] = now
                continue
            if now - last >= self._idle_timeout_s:
                reapable.append(pane)
        # Forget conversations whose pane is gone so the clock map can't grow.
        for gone in self._last_busy_at.keys() - live:
            del self._last_busy_at[gone]
        return reapable

    async def _reap_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._reaper_interval_s)
            except asyncio.CancelledError:
                return
            # ``<= 0`` disables reaping entirely (mirrors the SDK reaper guard).
            if self._idle_timeout_s <= 0:
                continue
            try:
                await self._scan_once()
            except Exception:  # never let a scan error kill the loop
                _logger.exception("native pane reaper: scan failed")

    async def _scan_once(self) -> None:
        panes = self._list_native_panes()
        now = time.monotonic()
        busy_convs = {p.conversation_id for p in panes if await self._is_busy(p)}
        for pane in self._classify(now, panes, busy_convs):
            # Re-check immediately before teardown: selection happened above with
            # possibly-stale signals, and a turn / client / autonomous run may
            # have started since (the select→reap race). Re-arm and skip if so.
            if await self._is_busy(pane):
                self._last_busy_at[pane.conversation_id] = time.monotonic()
                continue
            _logger.info(
                "reaping idle native pane for conversation %s (%s; idle > %.0fs)",
                pane.conversation_id,
                pane.terminal_name,
                self._idle_timeout_s,
            )
            # Drop the clock entry up front: a reap failure then re-arms the grace
            # window next scan instead of permanently skipping the conversation.
            self._last_busy_at.pop(pane.conversation_id, None)
            try:
                await self._reap(pane)
            except Exception:
                _logger.exception(
                    "native pane reaper: reap failed for conversation %s", pane.conversation_id
                )
