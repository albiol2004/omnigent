"""Opt-in completion receipts and the durable input fence for owned sessions.

Two small server capabilities for cursor-native sessions created with
``omnigent.cursor_native.completion_receipts=v1``:

* the forwarder's ``external_session_status`` post may carry ``data.turn_end``
  (a turn-end receipt); the latest valid one is kept in a server-reserved label;
* an owner-only ``input_fence`` event closes the session to new input. The
  label is durable, the admission gate below refuses every input-bearing event
  while it is present, and the runner installs a matching pane-level fence in
  the same critical section as its injection log.

Sessions without the opt-in label never take any of these paths.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import time
from collections.abc import Iterator
from typing import Any

import httpx

from omnigent.errors import ErrorCode, OmnigentError

_logger = logging.getLogger(__name__)

COMPLETION_RECEIPTS_LABEL = "omnigent.cursor_native.completion_receipts"
COMPLETION_RECEIPTS_VERSION = "v1"
TURN_RECEIPT_LABEL = "omnigent.cursor_native.turn_receipt"
TURN_RECEIPT_DETAIL_LABEL = "omnigent.cursor_native.turn_receipt.detail"
TURN_RECEIPT_BINDING_LABEL = "omnigent.cursor_native.turn_receipt.binding"
INPUT_FENCE_LABEL = "omnigent.input_fence"
INPUT_FENCE_EXPECT_LABEL = "omnigent.input_fence.expect"
INPUT_FENCE_TYPE = "input_fence"

#: Label values are stored in a 256-char column (``LABEL_VALUE_MAX_LEN``) that
#: silently truncates, so every stored record is compact and length-checked.
_LABEL_MAX = 256
_MAX_ID_LEN = 64
_MAX_RAW_STATUS_LEN = 16

#: Deployment declaration that exactly one server process admits input for
#: these sessions. The admission lock is process-local, so without it the
#: fence reports ``capability_unsupported`` instead of assuming one server.
SINGLE_SERVER_ENV = "OMNIGENT_INPUT_FENCE_SINGLE_SERVER"

#: Labels only the server writes; a client write would forge a receipt or
#: lift a fence.
SERVER_RESERVED_LABELS = frozenset(
    {
        TURN_RECEIPT_LABEL,
        TURN_RECEIPT_DETAIL_LABEL,
        TURN_RECEIPT_BINDING_LABEL,
        INPUT_FENCE_LABEL,
        INPUT_FENCE_EXPECT_LABEL,
    }
)

#: Why a receipt's turn ends are not bound to the injected prompts (runner-side
#: ``forwarder.compute_turn_binding``/``turn_binding``).
BIND_REASONS = frozenset(
    {
        "inject_unhashed",
        "user_rows_mismatch",
        "turn_end_foreign",
        "turn_end_unattributed",
        "turn_end_unbound",
        "duplicate_turn_end",
        "turn_open",
        "store_unbound",
    }
)

#: Event types that stay allowed on a fenced session: control and observation
#: only. Everything else is treated as input and refused while fenced.
FENCE_EXEMPT_EVENT_TYPES = frozenset({"interrupt", "stop_session", INPUT_FENCE_TYPE})

_DRAIN_TIMEOUT_S = 15.0
_DRAIN_POLL_S = 0.05
_RUNNER_FENCE_TIMEOUT_S = 10.0
_EXPECT_INT_FIELDS = ("epoch", "turn_seq", "inject_count", "turn_end_count")

_admission_locks: dict[str, asyncio.Lock] = {}
_admitted_inputs: dict[str, int] = {}
#: Sessions whose fence this process is closing or has closed; consulted with
#: the request-start label snapshot so a concurrent close has no TOCTOU gap.
_fenced_sessions: set[str] = set()
_receipt_locks: dict[str, asyncio.Lock] = {}


def is_fence_exempt(event_type: str) -> bool:
    """Whether *event_type* is control/observation rather than input."""
    return event_type in FENCE_EXEMPT_EVENT_TYPES or event_type.startswith("external_")


def is_opted_in(labels: dict[str, str] | None) -> bool:
    """Whether the session opted in to completion receipts and fencing."""
    return (labels or {}).get(COMPLETION_RECEIPTS_LABEL) == COMPLETION_RECEIPTS_VERSION


def _admission_lock(session_id: str) -> asyncio.Lock:
    lock = _admission_locks.get(session_id)
    if lock is None:
        lock = _admission_locks[session_id] = asyncio.Lock()
    return lock


@contextlib.contextmanager
def _mark_admitted(session_id: str) -> Iterator[None]:
    _admitted_inputs[session_id] = _admitted_inputs.get(session_id, 0) + 1
    try:
        yield
    finally:
        remaining = _admitted_inputs.get(session_id, 1) - 1
        if remaining > 0:
            _admitted_inputs[session_id] = remaining
        else:
            _admitted_inputs.pop(session_id, None)


def _parse_json_label(labels: dict[str, str] | None, key: str) -> dict[str, Any] | None:
    raw = (labels or {}).get(key)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        # A present-but-corrupt fence still fences.
        return {"state": "corrupt"}
    return value if isinstance(value, dict) else {"state": "corrupt"}


def _label_json(value: dict[str, Any]) -> str:
    """Serialize a label record, refusing to let the store truncate it."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    if len(text) > _LABEL_MAX:
        raise OmnigentError(
            f"label record exceeds {_LABEL_MAX} chars ({len(text)})",
            code=ErrorCode.INVALID_INPUT,
        )
    return text


def message_injections_digest(shas: list[str]) -> str:
    """Digest of the ordered ``kind=="message"`` injection hashes in one epoch.

    A consumer that sent ``n`` copies of one prompt recomputes this as
    ``message_injections_digest([prompt_sha256] * n)``.
    """
    return hashlib.sha256("\n".join(shas).encode("utf-8")).hexdigest()


def _input_fenced_error() -> OmnigentError:
    return OmnigentError(
        "input_fenced: Session input is fenced; no new input is accepted.",
        code=ErrorCode.CONFLICT,
    )


async def admit_input(
    session_id: str,
    event_type: str,
    labels: dict[str, str] | None,
    stack: contextlib.ExitStack,
) -> None:
    """Refuse input on a fenced session, else count it as admitted for the drain.

    Only fence-capable (opted-in) sessions or sessions this process has fenced
    take the lock, so ordinary sessions keep their existing request path.

    :raises OmnigentError: 409 ``input_fenced``.
    """
    if is_fence_exempt(event_type):
        return
    if not is_opted_in(labels) and INPUT_FENCE_LABEL not in (labels or {}):
        return
    async with _admission_lock(session_id):
        if session_id in _fenced_sessions or INPUT_FENCE_LABEL in (labels or {}):
            raise _input_fenced_error()
        stack.enter_context(_mark_admitted(session_id))


def refuse_if_fenced(session_id: str, event_type: str, labels: dict[str, str] | None) -> None:
    """Refuse an input dispatch to a fenced session, whatever path it came from.

    :raises OmnigentError: 409 ``input_fenced``.
    """
    if is_fence_exempt(event_type):
        return
    if session_id in _fenced_sessions or INPUT_FENCE_LABEL in (labels or {}):
        raise _input_fenced_error()


def _pending_or_in_flight(session_id: str) -> bool:
    from omnigent.runtime import pending_inputs
    from omnigent.server.routes._sessions.orchestration import _dispatch_in_flight

    return (
        _admitted_inputs.get(session_id, 0) > 0
        or _dispatch_in_flight.get(session_id, 0) > 0
        or pending_inputs.has_pending(session_id)
    )


async def _drain(session_id: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while _pending_or_in_flight(session_id):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_DRAIN_POLL_S)
    return True


def _validate_expect(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise OmnigentError("input_fence close requires data.expect", code=ErrorCode.INVALID_INPUT)
    expect: dict[str, Any] = {}
    for key in _EXPECT_INT_FIELDS:
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OmnigentError(
                f"input_fence expect.{key} must be a non-negative integer",
                code=ErrorCode.INVALID_INPUT,
            )
        expect[key] = value
    chat_id = raw.get("chat_id")
    if not isinstance(chat_id, str) or not chat_id or len(chat_id) > _MAX_ID_LEN:
        raise OmnigentError(
            f"input_fence expect.chat_id must be a 1-{_MAX_ID_LEN} char string",
            code=ErrorCode.INVALID_INPUT,
        )
    expect["chat_id"] = chat_id
    return expect


async def _call_runner(
    runner_client: httpx.AsyncClient | None, session_id: str, data: dict[str, Any]
) -> tuple[int | None, dict[str, Any] | None]:
    if runner_client is None:
        return None, None
    try:
        resp = await runner_client.post(
            f"/v1/sessions/{session_id}/events",
            json={"type": INPUT_FENCE_TYPE, "data": data},
            timeout=_RUNNER_FENCE_TIMEOUT_S,
        )
    except (httpx.HTTPError, ConnectionError):
        _logger.warning("input fence: runner unreachable; session=%s", session_id, exc_info=True)
        return None, None
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    return resp.status_code, payload if isinstance(payload, dict) else None


async def handle_input_fence(
    *,
    session_id: str,
    user_id: str | None,
    labels: dict[str, str] | None,
    data: dict[str, Any],
    conversation_store: Any,
    runner_client: httpx.AsyncClient | None,
    drain_timeout_s: float | None = None,
) -> dict[str, Any]:
    """Close or open the durable input fence (caller has verified owner access).

    ``close`` never rolls back: any failed step leaves the fence closed with
    ``verified: false`` so the caller holds instead of guessing.
    """
    if not is_opted_in(labels) or os.environ.get(SINGLE_SERVER_ENV) != "1":
        raise OmnigentError(
            "capability_unsupported: input_fence requires a session opted in to completion "
            f"receipts on a server declaring {SINGLE_SERVER_ENV}=1",
            code=ErrorCode.CONFLICT,
        )
    action = data.get("action")
    fence_id = data.get("fence_id")
    if (
        action not in ("close", "open")
        or not isinstance(fence_id, str)
        or not fence_id
        or len(fence_id) > _MAX_ID_LEN
    ):
        raise OmnigentError(
            "input_fence requires data.action in {'close','open'} and a data.fence_id "
            f"of 1-{_MAX_ID_LEN} chars",
            code=ErrorCode.INVALID_INPUT,
        )
    if action == "open":
        return await _open_fence(session_id, fence_id, conversation_store, runner_client)
    expect = _validate_expect(data.get("expect"))
    async with _admission_lock(session_id):
        current = await asyncio.to_thread(conversation_store.get_conversation, session_id)
        current_labels = getattr(current, "labels", None)
        existing = _parse_json_label(current_labels, INPUT_FENCE_LABEL)
        stored_expect = _parse_json_label(current_labels, INPUT_FENCE_EXPECT_LABEL)
        if existing is not None and existing.get("fence_id") != fence_id:
            _fenced_sessions.add(session_id)
            raise OmnigentError(
                "fence_exists: A different input fence is already closed on this session.",
                code=ErrorCode.CONFLICT,
            )
        if existing is not None and existing.get("verified") is True:
            _fenced_sessions.add(session_id)
            return {"fenced": True, "fence": {**existing, "expect": stored_expect}}
        if existing is not None and stored_expect != expect:
            raise OmnigentError(
                "fence_expect_changed: a retried close must repeat the original expect.",
                code=ErrorCode.CONFLICT,
            )
        # A first close, or a retry of one that crashed mid-way or ended
        # unverified: the fence stays closed throughout and is re-verified.
        record: dict[str, Any] = {
            "v": 1,
            "fence_id": fence_id,
            "closed_at": int((existing or {}).get("closed_at") or time.time()),
            "state": "closing",
            "attempts": int((existing or {}).get("attempts") or 0) + 1,
        }
        _fenced_sessions.add(session_id)
        # Both labels land in one atomic upsert; the state label alone fences.
        await asyncio.to_thread(
            conversation_store.set_labels,
            session_id,
            {
                INPUT_FENCE_LABEL: _label_json(record),
                INPUT_FENCE_EXPECT_LABEL: _label_json(expect),
            },
        )
    drained = await _drain(
        session_id, _DRAIN_TIMEOUT_S if drain_timeout_s is None else drain_timeout_s
    )
    status, runner_ack = await _call_runner(
        runner_client, session_id, {"action": "close", "fence_id": fence_id}
    )
    reason = _verify(expect, drained, status, runner_ack)
    record.update(
        {
            "state": "closed",
            "drained": drained,
            "runner_status": status,
            "verified": reason is None,
            "reason": reason,
        }
    )
    await asyncio.to_thread(
        conversation_store.set_labels, session_id, {INPUT_FENCE_LABEL: _label_json(record)}
    )
    return {
        "fenced": True,
        "fence": {**record, "expect": expect, "runner_ack": runner_ack, "owner": user_id},
    }


def _verify(
    expect: dict[str, Any],
    drained: bool,
    status: int | None,
    ack: dict[str, Any] | None,
) -> str | None:
    """Return why the fence is unverified, or ``None`` when it proves quiescence."""
    if not drained:
        return "inputs_not_drained"
    if status is None:
        return "runner_unreachable"
    if status != 200 or ack is None:
        return f"runner_rejected_{status}"
    if ack.get("same_fence") is not True:
        return "runner_fence_foreign"
    for key in ("epoch", "inject_count", "turn_end_count", "chat_id"):
        if ack.get(key) != expect[key]:
            return f"mismatch_{key}"
    if ack.get("inject_count") != ack.get("turn_end_count"):
        return "unbalanced_turns"
    if ack.get("bound") is not True:
        # Counts balance, but the runner could not bind every injected prompt's
        # row to its own turn end (a foreign or duplicate stop, or a copy still
        # queued). A runner without binding never sends ``bound`` and fails here.
        return "turns_unbound"
    if expect["turn_seq"] != expect["turn_end_count"]:
        return "expect_turn_seq_not_latest"
    return None


async def _open_fence(
    session_id: str,
    fence_id: str,
    conversation_store: Any,
    runner_client: httpx.AsyncClient | None,
) -> dict[str, Any]:
    """Lift the fence runner-first, so input is never admitted while the pane is fenced
    and the server is not (the reverse state only refuses more)."""
    async with _admission_lock(session_id):
        current = await asyncio.to_thread(conversation_store.get_conversation, session_id)
        existing = _parse_json_label(getattr(current, "labels", None), INPUT_FENCE_LABEL)
        if existing is None:
            _fenced_sessions.discard(session_id)
            return {"opened": True, "runner_opened": None}
        if existing.get("fence_id") != fence_id:
            raise OmnigentError(
                "fence_id_mismatch: fence_id does not match the closed fence.",
                code=ErrorCode.CONFLICT,
            )
        status, _ack = await _call_runner(
            runner_client, session_id, {"action": "open", "fence_id": fence_id}
        )
        if status != 200:
            # Keep the durable fence: the runner still refuses injections, and a
            # server-open/pane-closed split would silently fail every message.
            raise OmnigentError(
                f"runner_open_failed: runner did not lift the pane fence (status={status}); "
                "the fence stays closed.",
                code=ErrorCode.CONFLICT,
            )
        # State label last: while it exists the session stays fenced.
        await asyncio.to_thread(
            conversation_store.delete_label, session_id, INPUT_FENCE_EXPECT_LABEL
        )
        await asyncio.to_thread(conversation_store.delete_label, session_id, INPUT_FENCE_LABEL)
        _fenced_sessions.discard(session_id)
    return {"opened": True, "runner_opened": True}


def _receipt_lock(session_id: str) -> asyncio.Lock:
    lock = _receipt_locks.get(session_id)
    if lock is None:
        lock = _receipt_locks[session_id] = asyncio.Lock()
    return lock


def _valid_receipt(receipt: object) -> dict[str, Any] | None:
    """Return *receipt* when it has the v1 shape, else ``None``."""
    if not isinstance(receipt, dict) or receipt.get("v") != 1:
        return None
    for key in (
        "epoch",
        "turn_seq",
        "turn_end_count",
        "inject_count_at_end",
        "inject_count",
        "rev",
    ):
        value = receipt.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
    if receipt["epoch"] <= 0 or receipt["turn_seq"] < 1 or receipt["rev"] < 1:
        return None
    injections = receipt.get("injections")
    if not isinstance(injections, list) or not isinstance(
        receipt.get("injections_truncated"), bool
    ):
        return None
    for entry in injections:
        if not isinstance(entry, dict) or not isinstance(entry.get("sha256"), str):
            return None
    if receipt.get("stop_reason") not in ("completed", "aborted", "error", "unknown"):
        return None
    transcript = receipt.get("transcript")
    if not isinstance(transcript, dict) or not isinstance(
        transcript.get("observed_max_acked"), bool
    ):
        return None
    for key in ("store_max_rowid", "acked_through_rowid"):
        if not isinstance(transcript.get(key), int):
            return None
    if not isinstance(transcript.get("unacked_rowids"), list):
        return None
    for key in ("chat_id", "stop_status_raw", "generation_id", "hook_conversation_id"):
        if receipt.get(key) is not None and not isinstance(receipt.get(key), str):
            return None
    if receipt.get("chat_id") is not None and len(receipt["chat_id"]) > _MAX_ID_LEN:
        return None
    for entry in injections:
        if entry.get("kind") not in ("message", "model_command"):
            return None
    binding = receipt.get("binding")
    if binding is not None and _valid_binding(binding) is None:
        return None
    return receipt


def _valid_binding(binding: object) -> dict[str, Any] | None:
    """Return *binding* when it has the v1 shape, else ``None``."""
    if not isinstance(binding, dict) or binding.get("v") != 1:
        return None
    if not isinstance(binding.get("bound"), bool):
        return None
    reason = binding.get("reason")
    if (reason is None) != (binding["bound"] is True):
        return None
    if reason is not None and reason not in BIND_REASONS:
        return None
    for key in ("user_rows", "closed_turns"):
        value = binding.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
    return binding


def _receipt_order(receipt: dict[str, Any]) -> tuple[int, int, int]:
    return (int(receipt["epoch"]), int(receipt["turn_seq"]), int(receipt["rev"]))


def _compact_receipt(receipt: dict[str, Any], received_seq: int) -> tuple[str, str, str]:
    """Split a wire receipt into the core, detail and binding label values."""
    injections = receipt["injections"]
    message_shas = [e["sha256"] for e in injections if e.get("kind") == "message"]
    raw_status = receipt.get("stop_status_raw")
    transcript = receipt["transcript"]
    core = {
        "v": 1,
        "epoch": receipt["epoch"],
        "turn_seq": receipt["turn_seq"],
        "turn_end_count": receipt["turn_end_count"],
        "inject_count": receipt["inject_count"],
        "inject_count_at_end": receipt["inject_count_at_end"],
        "rev": receipt["rev"],
        "stop_reason": receipt["stop_reason"],
        "chat_id": receipt.get("chat_id"),
        "received_seq": received_seq,
    }
    detail = {
        "msg_digest": message_injections_digest(message_shas),
        "msg_listed": len(message_shas),
        "truncated": receipt["injections_truncated"],
        "model_cmds": sum(1 for e in injections if e.get("kind") == "model_command"),
        "stop_raw": raw_status[:_MAX_RAW_STATUS_LEN] if isinstance(raw_status, str) else None,
        "observed_max_acked": transcript["observed_max_acked"],
        "store_max": transcript["store_max_rowid"],
        "acked_through": transcript["acked_through_rowid"],
        "unacked": len(transcript["unacked_rowids"]),
    }
    wire_binding = receipt.get("binding")
    # A receipt from a runner without binding stores ``bound: null`` (hold).
    binding = {
        "bound": wire_binding["bound"] if wire_binding is not None else None,
        "reason": wire_binding["reason"] if wire_binding is not None else "no_binding",
        "user_rows": wire_binding["user_rows"] if wire_binding is not None else None,
        "closed_turns": wire_binding["closed_turns"] if wire_binding is not None else None,
    }
    return _label_json(core), _label_json(detail), _label_json(binding)


async def persist_turn_receipt(
    *,
    session_id: str,
    raw_receipt: object,
    caller_authorized: bool,
    conversation_store: Any,
) -> bool:
    """Persist a turn-end receipt as the session's latest, when acceptable.

    Never raises: a rejected receipt is logged and dropped so the idle edge it
    rides on is still delivered and the forwarder never wedges.

    :returns: Whether the receipt was stored.
    """
    if not caller_authorized:
        _logger.warning("turn receipt dropped: caller is not owner/runner; session=%s", session_id)
        return False
    receipt = _valid_receipt(raw_receipt)
    if receipt is None:
        _logger.warning("turn receipt dropped: invalid shape; session=%s", session_id)
        return False
    async with _receipt_lock(session_id):
        conv = await asyncio.to_thread(conversation_store.get_conversation, session_id)
        if conv is None or not is_opted_in(conv.labels):
            return False
        stored = _parse_json_label(conv.labels, TURN_RECEIPT_LABEL)
        if stored is not None and stored.get("state") != "corrupt":
            try:
                if _receipt_order(receipt) <= _receipt_order(stored):
                    return False
            except (KeyError, TypeError, ValueError):
                pass
        received_seq = int((stored or {}).get("received_seq") or 0) + 1
        try:
            core, detail, binding = _compact_receipt(receipt, received_seq)
        except OmnigentError:
            _logger.warning("turn receipt dropped: too large to store; session=%s", session_id)
            return False
        # One atomic upsert, so all three labels always describe the same receipt.
        await asyncio.to_thread(
            conversation_store.set_labels,
            session_id,
            {
                TURN_RECEIPT_LABEL: core,
                TURN_RECEIPT_DETAIL_LABEL: detail,
                TURN_RECEIPT_BINDING_LABEL: binding,
            },
        )
    return True


def reset_for_tests() -> None:
    """Clear process-local fence/admission state."""
    _admission_locks.clear()
    _admitted_inputs.clear()
    _fenced_sessions.clear()
    _receipt_locks.clear()
