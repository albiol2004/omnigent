"""Manual context compaction for Codex-native sessions via the app-server.

``thread/compact/start`` returns ``{}`` as soon as Codex accepts the request;
progress streams only to connections subscribed to the thread (the transcript
forwarder). So a request is tracked in two phases: *accept* (the RPC response
on a short-lived control connection) and *completion* (a ``contextCompaction``
``item/completed`` or ``thread/compacted`` for the same thread, fed in by the
forwarder through :func:`observe_codex_manual_compact_event`).

An outcome that cannot be confirmed is reported as ``uncertain`` and is never
resent automatically.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import time
from dataclasses import dataclass, field

from omnigent.harnesses.codex_native.app_server import (
    CodexAppServerResponseError,
    CodexMessage,
)

_logger = logging.getLogger(__name__)

CODEX_COMPACT_START_METHOD = "thread/compact/start"
_CODEX_COMPACTION_ITEM_TYPE = "contextCompaction"
_CODEX_THREAD_COMPACTED_METHOD = "thread/compacted"
_CONTROL_CLIENT_NAME = "omnigent-codex-native-runner"

#: Connect + ``initialize`` budget. Nothing compaction-related is sent yet, so
#: a timeout here is a clean "disconnected".
CODEX_COMPACT_CONNECT_TIMEOUT_S = 5.0
#: Budget for the ``thread/compact/start`` response. Kept under the server's
#: 20s runner-forward budget so the runner answers before the server gives up.
CODEX_COMPACT_ACCEPT_TIMEOUT_S = 10.0
#: Budget for the completion event after acceptance (a remote summarization
#: turn). Past it the outcome is ``uncertain``.
CODEX_COMPACT_COMPLETION_TIMEOUT_S = 600.0


class CodexCompactState(enum.StrEnum):
    """Lifecycle states of one manual Codex compaction request."""

    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"
    BUSY = "busy"
    DISCONNECTED = "disconnected"


@dataclass(frozen=True)
class CodexCompactOutcome:
    """
    Result of one phase of a manual compaction.

    :param state: Phase result, e.g. ``CodexCompactState.ACCEPTED``.
    :param thread_id: Codex thread the request targeted.
    :param detail: Human-readable reason, e.g. the JSON-RPC error message.
    :param request_id: JSON-RPC id of the accepted ``thread/compact/start``.
    :param turn_id: Codex turn that ran the compaction, when observed.
    """

    state: CodexCompactState
    thread_id: str
    detail: str | None = None
    request_id: int | str | None = None
    turn_id: str | None = None

    def as_payload(self) -> dict[str, object]:
        """
        Render the outcome for an HTTP body or log line.

        :returns: JSON-serializable mapping without ``None`` fields.
        """
        payload: dict[str, object] = {"state": self.state.value, "thread_id": self.thread_id}
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.turn_id is not None:
            payload["turn_id"] = self.turn_id
        return payload


@dataclass
class CodexCompactInFlight:
    """
    One manual compaction awaiting its completion event.

    :param session_id: Omnigent session id that requested it.
    :param thread_id: Codex thread id events are correlated against.
    """

    session_id: str
    thread_id: str
    started_at: float = field(default_factory=time.monotonic)
    request_id: int | str | None = None
    turn_id: str | None = None
    item_started: bool = False
    done: asyncio.Future[CodexCompactOutcome] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )

    def resolve(self, state: CodexCompactState, detail: str | None = None) -> None:
        """
        Settle the completion phase once; later signals are ignored.

        :param state: Terminal state, e.g. ``CodexCompactState.COMPLETED``.
        :param detail: Optional reason, e.g. a turn error message.
        """
        if self.done.done():
            return
        self.done.set_result(
            CodexCompactOutcome(
                state=state,
                thread_id=self.thread_id,
                detail=detail,
                request_id=self.request_id,
                turn_id=self.turn_id,
            )
        )


class CodexManualCompactTracker:
    """Per-thread registry of in-flight manual compactions (one per thread)."""

    def __init__(self) -> None:
        self._by_thread: dict[str, CodexCompactInFlight] = {}

    def get(self, thread_id: str) -> CodexCompactInFlight | None:
        """
        Return the in-flight compaction for *thread_id*, if any.

        :param thread_id: Codex thread id.
        :returns: The in-flight entry or ``None``.
        """
        return self._by_thread.get(thread_id)

    def begin(self, session_id: str, thread_id: str) -> CodexCompactInFlight | None:
        """
        Register a new compaction, or return ``None`` when one is in flight.

        :param session_id: Omnigent session id.
        :param thread_id: Codex thread id.
        :returns: New entry, or ``None`` if the thread is already compacting.
        """
        if thread_id in self._by_thread:
            return None
        entry = CodexCompactInFlight(session_id=session_id, thread_id=thread_id)
        self._by_thread[thread_id] = entry
        return entry

    def finish(self, entry: CodexCompactInFlight) -> None:
        """
        Drop *entry* if it is still the registered one for its thread.

        :param entry: Entry returned by :meth:`begin`.
        """
        if self._by_thread.get(entry.thread_id) is entry:
            del self._by_thread[entry.thread_id]

    def observe(self, event: CodexMessage) -> None:
        """
        Feed one live app-server notification; ignores other threads.

        :param event: Notification envelope, e.g.
            ``{"method": "item/completed", "params": {...}}``.
        """
        method = event.get("method")
        params = event.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        thread_id = params.get("threadId")
        if not isinstance(thread_id, str):
            return
        entry = self._by_thread.get(thread_id)
        if entry is None or entry.done.done():
            return
        _apply_event(entry, method, params)


def _apply_event(entry: CodexCompactInFlight, method: str, params: dict[str, object]) -> None:
    """Advance *entry* from one same-thread notification."""
    turn_id = params.get("turnId")
    turn_id = turn_id if isinstance(turn_id, str) and turn_id else None
    item = params.get("item")
    is_compaction_item = isinstance(item, dict) and item.get("type") == _CODEX_COMPACTION_ITEM_TYPE
    if method == "item/started" and is_compaction_item:
        entry.item_started = True
        entry.turn_id = turn_id or entry.turn_id
        return
    if method == "item/completed" and is_compaction_item:
        entry.turn_id = turn_id or entry.turn_id
        entry.resolve(CodexCompactState.COMPLETED)
        return
    if method == _CODEX_THREAD_COMPACTED_METHOD:
        entry.turn_id = turn_id or entry.turn_id
        entry.resolve(CodexCompactState.COMPLETED)
        return
    if method == "turn/started":
        # The runner refuses to compact while a turn is active, so the first
        # turn after the request is the compaction turn until an item says so.
        turn = params.get("turn")
        started_id = turn.get("id") if isinstance(turn, dict) else None
        if entry.turn_id is None and isinstance(started_id, str) and started_id:
            entry.turn_id = started_id
        return
    if method == "turn/completed":
        turn = params.get("turn")
        if not isinstance(turn, dict) or entry.turn_id is None or turn.get("id") != entry.turn_id:
            return
        status = turn.get("status")
        if status in {"failed", "interrupted"}:
            entry.resolve(CodexCompactState.FAILED, _turn_error_message(turn) or f"turn {status}")
        elif status == "completed":
            entry.resolve(
                CodexCompactState.UNCERTAIN,
                "compaction turn completed without a compaction completion event",
            )
        return
    if method == "error" and params.get("willRetry") is not True:
        if entry.turn_id is not None and turn_id is not None and turn_id != entry.turn_id:
            return
        entry.resolve(CodexCompactState.FAILED, _turn_error_message(params) or "codex error")


def _turn_error_message(payload: dict[str, object]) -> str | None:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return None


_TRACKER = CodexManualCompactTracker()


def codex_manual_compact_tracker() -> CodexManualCompactTracker:
    """
    Return the process-wide tracker shared by the runner and the forwarder.

    :returns: The singleton tracker.
    """
    return _TRACKER


def observe_codex_manual_compact_event(event: CodexMessage) -> None:
    """
    Forwarder hook: correlate one live notification with in-flight compactions.

    Never raises, so it cannot disturb the transcript mirror.

    :param event: Live app-server notification envelope.
    """
    try:
        _TRACKER.observe(event)
    except Exception:  # noqa: BLE001 - observation must not break forwarding.
        _logger.warning("Codex manual-compact observer failed", exc_info=True)


async def start_codex_manual_compact(
    *,
    session_id: str,
    thread_id: str,
    transport: str,
    active_turn_id: str | None,
    tracker: CodexManualCompactTracker | None = None,
    connect_timeout_s: float = CODEX_COMPACT_CONNECT_TIMEOUT_S,
    accept_timeout_s: float = CODEX_COMPACT_ACCEPT_TIMEOUT_S,
) -> tuple[CodexCompactOutcome, CodexCompactInFlight | None]:
    """
    Send ``thread/compact/start`` once and report the accept phase.

    :param session_id: Omnigent session id, e.g. ``"conv_abc123"``.
    :param thread_id: The session's current Codex thread id.
    :param transport: App-server transport from bridge state, e.g.
        ``"ws://127.0.0.1:9876"``.
    :param active_turn_id: Bridge-recorded active turn; non-``None`` means busy.
    :param tracker: Tracker to register with (defaults to the process one).
    :param connect_timeout_s: Connect + initialize budget.
    :param accept_timeout_s: RPC response budget after the request is sent.
    :returns: ``(outcome, entry)``. ``entry`` is the in-flight record to await
        completion on (for ``ACCEPTED`` and ``UNCERTAIN``), else ``None``.
    """
    from omnigent.harnesses.codex_native import app_server

    tracker = tracker or _TRACKER
    if active_turn_id is not None:
        return (
            CodexCompactOutcome(
                CodexCompactState.BUSY,
                thread_id,
                detail="A Codex turn is in progress; compact after it finishes.",
                turn_id=active_turn_id,
            ),
            None,
        )
    entry = tracker.begin(session_id, thread_id)
    if entry is None:
        return (
            CodexCompactOutcome(
                CodexCompactState.BUSY,
                thread_id,
                detail="A compaction is already in flight for this Codex thread.",
            ),
            None,
        )

    client = app_server.client_for_transport(transport, client_name=_CONTROL_CLIENT_NAME)
    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=connect_timeout_s)
        except Exception as exc:  # noqa: BLE001 - nothing was sent; report disconnected.
            tracker.finish(entry)
            return (
                CodexCompactOutcome(
                    CodexCompactState.DISCONNECTED,
                    thread_id,
                    detail=f"Codex app-server unreachable: {type(exc).__name__}",
                ),
                None,
            )
        try:
            response = await asyncio.wait_for(
                client.request(CODEX_COMPACT_START_METHOD, {"threadId": thread_id}),
                timeout=accept_timeout_s,
            )
        except CodexAppServerResponseError as exc:
            tracker.finish(entry)
            return (
                CodexCompactOutcome(
                    CodexCompactState.REJECTED,
                    thread_id,
                    detail=exc.message or str(exc.error),
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001 - the request may have reached Codex.
            # Keep the entry: a late completion event still resolves it, and a
            # second click is refused as busy rather than double-compacting.
            return (
                CodexCompactOutcome(
                    CodexCompactState.UNCERTAIN,
                    thread_id,
                    detail=(
                        "No thread/compact/start response "
                        f"({type(exc).__name__}); not resent. Codex may still compact."
                    ),
                ),
                entry,
            )
        request_id = response.get("id")
        if isinstance(request_id, int | str) and not isinstance(request_id, bool):
            entry.request_id = request_id
    finally:
        with contextlib.suppress(Exception):
            await client.close()
    return (
        CodexCompactOutcome(
            CodexCompactState.ACCEPTED,
            thread_id,
            request_id=entry.request_id,
            turn_id=entry.turn_id,
        ),
        entry,
    )


async def await_codex_manual_compact(
    entry: CodexCompactInFlight,
    *,
    tracker: CodexManualCompactTracker | None = None,
    completion_timeout_s: float | None = None,
) -> CodexCompactOutcome:
    """
    Wait (bounded) for the completion phase, then release the thread.

    :param entry: In-flight entry from :func:`start_codex_manual_compact`.
    :param tracker: Tracker holding *entry* (defaults to the process one).
    :param completion_timeout_s: Completion budget (default
        :data:`CODEX_COMPACT_COMPLETION_TIMEOUT_S`); past it the result is
        ``UNCERTAIN`` and nothing is resent.
    :returns: Terminal outcome.
    """
    tracker = tracker or _TRACKER
    if completion_timeout_s is None:
        completion_timeout_s = CODEX_COMPACT_COMPLETION_TIMEOUT_S
    try:
        return await asyncio.wait_for(asyncio.shield(entry.done), timeout=completion_timeout_s)
    except TimeoutError:
        return CodexCompactOutcome(
            CodexCompactState.UNCERTAIN,
            entry.thread_id,
            detail=(
                f"No compaction completion event within {completion_timeout_s:.0f}s; not resent."
            ),
            request_id=entry.request_id,
            turn_id=entry.turn_id,
        )
    finally:
        tracker.finish(entry)
