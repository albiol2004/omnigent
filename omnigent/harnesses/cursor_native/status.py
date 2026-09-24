"""Authoritative turn outcome from the cursor-native ``stop`` hook.

cursor-agent fires its ``stop`` hook when a turn completes, aborts, or fails (see
:func:`omnigent.harnesses.cursor_native.bridge.build_hooks_config`, which registers the
:mod:`omnigent.harnesses.cursor_native.usage` recorder). That hook is the ONLY
authoritative "this turn just finished" signal cursor-agent exposes: its SQLite
chat store (tailed by :mod:`omnigent.harnesses.cursor_native.forwarder`) carries no
turn-boundary marker, and the runner's PTY-activity watcher only drives the web
"Working…" spinner (a ``session.status`` edge) — which never wakes a parent
orchestrator.

So the stop hook ALSO appends a turn-end marker line here (alongside its usage
line), and the runner-owned
:func:`omnigent.harnesses.cursor_native.forwarder.forward_cursor_store_to_session` poll
loop tails it and POSTs an ``external_session_status`` event with its outcome — the SAME
server contract claude-/codex-/opencode-native use to mark a sub-agent turn
terminal and wake its parent's inbox. Without this a cursor-native sub-agent
finished silently and never notified the orchestrator.

Stdlib-only (no httpx) so importing it from the stop hook keeps the hook fast —
cursor blocks the turn end on the hook.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from pathlib import Path

#: Append-only log of per-turn outcomes written by the cursor ``stop`` hook.
TURN_END_FILE = "cursor_turn_end.jsonl"

#: Durable poster state: how many turn-end markers the forwarder has already
#: turned into an ``external_session_status`` post. Persisted so a
#: supervisor restart never re-wakes the parent for a turn it already reported.
_STATE_FILE = "cursor_status_forwarder.json"

#: Opt-in completion-receipt epoch (``{"v": 1, "epoch": <launch_epoch_ms>}``),
#: written by the runner at terminal launch only for opted-in sessions. Its
#: absence keeps every function here on the legacy, receipt-free path.
RECEIPT_EPOCH_FILE = "receipt_epoch.json"

#: Append-only per-epoch log of prompts pasted into the pane (receipts only).
INJECT_FILE = "cursor_inject.jsonl"

#: Durable input fence; while present every pane injection is refused. Never
#: cleared by a terminal relaunch — only by an explicit fence ``open``.
INPUT_FENCE_FILE = "input_fence.json"

_RECEIPT_LOCK_FILE = "receipt.lock"

#: The forwarder's durable cursor (``forwarder._STATE_FILE``); the stop hook
#: reads only its ``store_path`` so each turn end is stamped with a store position.
_FORWARDER_STATE_FILE = "cursor_forwarder.json"

#: Called under ``receipt.lock`` with this epoch's ``(turn_ends, injects)`` to
#: bind turn ends to transcript user rows (see ``forwarder.turn_binding``).
TurnBinder = Callable[[list[dict[str, object]], list[dict[str, object]]], dict[str, object]]

#: Session label that opts a cursor-native session in to receipts + fencing.
COMPLETION_RECEIPTS_LABEL = "omnigent.cursor_native.completion_receipts"
COMPLETION_RECEIPTS_VERSION = "v1"

#: Maximum injection records carried in one receipt (newest kept).
MAX_RECEIPT_INJECTIONS = 64

_STOP_REASONS = frozenset({"completed", "aborted", "error"})


class InputFencedError(RuntimeError):
    """Raised when a pane injection is attempted while the input fence is closed."""

    def __init__(self) -> None:
        super().__init__("cursor session input is fenced; no new input is accepted")


@contextlib.contextmanager
def receipt_lock(bridge_dir: Path) -> Iterator[None]:
    """Hold the cross-process lock that orders injections, turn ends, and fencing."""
    bridge_dir.mkdir(parents=True, exist_ok=True)
    with open(bridge_dir / _RECEIPT_LOCK_FILE, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_json_atomic(path: Path, data: object) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def write_receipt_epoch(bridge_dir: Path, epoch: int) -> None:
    """Opt this terminal launch in to completion receipts under *epoch*."""
    bridge_dir.mkdir(parents=True, exist_ok=True)
    with receipt_lock(bridge_dir):
        _write_json_atomic(bridge_dir / RECEIPT_EPOCH_FILE, {"v": 1, "epoch": epoch})


class ReceiptEpochClearError(RuntimeError):
    """A prior launch's receipt epoch could not be removed; the launch must not start."""


def clear_receipt_epoch(bridge_dir: Path) -> None:
    """Turn completion receipts off for this launch (fence state is kept).

    Idempotent when the epoch file (or the bridge dir) is already absent. Any
    other outcome leaves a prior launch's capability readable, so absence is
    verified with ``lstat`` and a failure raises instead of being ignored.

    :raises ReceiptEpochClearError: the epoch file still exists or its
        absence cannot be established.
    """
    path = bridge_dir / RECEIPT_EPOCH_FILE
    try:
        path.unlink()
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as exc:
        unlink_error: OSError | None = exc
    else:
        unlink_error = None
    try:
        path.lstat()
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as exc:
        unlink_error = unlink_error or exc
    detail = f": {unlink_error}" if unlink_error is not None else ""
    raise ReceiptEpochClearError(
        f"could not remove stale completion-receipt epoch {path}{detail}. "
        f"Refusing to start the terminal with a prior launch's receipt "
        f"capability; make {bridge_dir} writable by this user (or delete "
        f"{path}) and relaunch."
    ) from unlink_error


def read_receipt_epoch(bridge_dir: Path) -> int | None:
    """Return the opted-in terminal epoch, or ``None`` when receipts are off."""
    try:
        data = json.loads((bridge_dir / RECEIPT_EPOCH_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    epoch = data.get("epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch <= 0:
        return None
    return epoch


def _epoch_records(path: Path, epoch: int) -> list[dict[str, object]]:
    """Return the JSONL records stamped with *epoch*, in file order."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    records: list[dict[str, object]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("epoch") == epoch:
            records.append(record)
    return records


def read_input_fence(bridge_dir: Path) -> dict[str, object] | None:
    """Return the closed input fence record, or ``None`` when input is open."""
    try:
        data = json.loads((bridge_dir / INPUT_FENCE_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # A present-but-unreadable fence fails closed.
        return {"fence_id": None, "corrupt": True}
    return data if isinstance(data, dict) else {"fence_id": None, "corrupt": True}


def normalize_prompt_text(text: str) -> str:
    """Normalize prompt text before hashing it against a stored ``<user_query>``.

    Drops C0 control bytes except newline and tab (cursor embeds some in stored
    prompts) and surrounding whitespace, identically for the injected content and
    the stored row; any other rewrite by cursor leaves the receipt unbound (hold).
    """
    return "".join(ch for ch in text if ch >= " " or ch in "\n\t").strip()


def prompt_binding_sha(text: str) -> str:
    """Hex SHA-256 of :func:`normalize_prompt_text` applied to *text*."""
    return hashlib.sha256(normalize_prompt_text(text).encode("utf-8")).hexdigest()


def record_injection(bridge_dir: Path, content: str, *, kind: str) -> None:
    """Admit one pane injection: refuse if fenced, else log it for receipts.

    Called before the paste. Sessions that are not opted in and not fenced are
    untouched (no file is written).

    :raises InputFencedError: If the input fence is closed.
    """
    if (
        not (bridge_dir / RECEIPT_EPOCH_FILE).exists()
        and not (bridge_dir / INPUT_FENCE_FILE).exists()
    ):
        return
    with receipt_lock(bridge_dir):
        if read_input_fence(bridge_dir) is not None:
            raise InputFencedError()
        epoch = read_receipt_epoch(bridge_dir)
        if epoch is None:
            return
        records = _epoch_records(bridge_dir / INJECT_FILE, epoch)
        line: dict[str, object] = {
            "epoch": epoch,
            "seq": len(records) + 1,
            # Ordinal among turn-starting injections only; ``None`` for others.
            "message_seq": _message_inject_count(records) + 1 if kind == "message" else None,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            # Hash compared with the transcript's ``<user_query>`` row (messages only).
            "norm_sha256": prompt_binding_sha(content) if kind == "message" else None,
            "kind": kind,
        }
        with open(bridge_dir / INJECT_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True) + "\n")


def _counts_locked(
    bridge_dir: Path, epoch: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    return (
        _epoch_records(bridge_dir / TURN_END_FILE, epoch),
        _epoch_records(bridge_dir / INJECT_FILE, epoch),
    )


def _message_inject_count(injects: list[dict[str, object]]) -> int:
    return sum(1 for record in injects if record.get("kind") == "message")


def normalize_stop_reason(raw: object) -> str:
    """Map a raw stop-hook status to ``completed|aborted|error|unknown``."""
    return raw if isinstance(raw, str) and raw in _STOP_REASONS else "unknown"


def build_turn_end_receipt(
    bridge_dir: Path, binder: TurnBinder | None = None
) -> dict[str, object] | None:
    """Build the per-epoch receipt fields owned by the hook/inject logs.

    :param binder: Computes ``binding`` from the same locked snapshot of the
        logs, so the binding and the counts always describe one state.
    :returns: ``None`` when not opted in or no turn has ended this epoch. The
        forwarder adds ``chat_id``, ``transcript``, and ``rev``.
    """
    epoch = read_receipt_epoch(bridge_dir)
    if epoch is None:
        return None
    binding: dict[str, object] | None = None
    with receipt_lock(bridge_dir):
        turn_ends, injects = _counts_locked(bridge_dir, epoch)
        if turn_ends and binder is not None:
            binding = binder(turn_ends, injects)
    if not turn_ends:
        return None
    last = turn_ends[-1]
    injections = [
        {
            "seq": record.get("seq"),
            "message_seq": record.get("message_seq"),
            "sha256": record.get("sha256"),
            "kind": record.get("kind"),
        }
        for record in injects
    ]
    generation_id = last.get("generation_id")
    return {
        "v": 1,
        "epoch": epoch,
        "turn_seq": last.get("turn_seq"),
        "turn_end_count": len(turn_ends),
        "inject_count_at_end": last.get("inject_count_at_end"),
        "inject_count": _message_inject_count(injects),
        "injections": injections[-MAX_RECEIPT_INJECTIONS:],
        "injections_truncated": len(injections) > MAX_RECEIPT_INJECTIONS,
        "stop_status_raw": last.get("stop_status_raw"),
        "stop_reason": normalize_stop_reason(last.get("stop_status_raw")),
        "generation_id": generation_id if isinstance(generation_id, str) else None,
        "hook_conversation_id": last.get("hook_conversation_id"),
        "binding": binding,
    }


def close_input_fence(
    bridge_dir: Path, fence_id: str, binder: TurnBinder | None = None
) -> dict[str, object]:
    """Close the pane input fence and report the state it was closed at.

    The fence write, the counter read and the turn binding share one critical
    section with every injection and turn end, so no injection can land between
    them.

    :returns: ``{fence_id, same_fence, epoch, inject_count, turn_end_count,
        already_closed, bound, bind_reason}``. ``bound`` is ``True`` only when
        *binder* proved every injected prompt's turn ended.
    """
    with receipt_lock(bridge_dir):
        existing = read_input_fence(bridge_dir)
        epoch = read_receipt_epoch(bridge_dir)
        turn_ends, injects = _counts_locked(bridge_dir, epoch) if epoch is not None else ([], [])
        inject_count = _message_inject_count(injects)
        binding = binder(turn_ends, injects) if binder is not None and epoch is not None else None
        if existing is None:
            _write_json_atomic(
                bridge_dir / INPUT_FENCE_FILE,
                {
                    "fence_id": fence_id,
                    "epoch": epoch,
                    "closed_at_inject_count": inject_count,
                    "closed_at_turn_end_count": len(turn_ends),
                },
            )
        return {
            "fence_id": existing.get("fence_id") if existing is not None else fence_id,
            "same_fence": existing is None or existing.get("fence_id") == fence_id,
            "epoch": epoch,
            "inject_count": inject_count,
            "turn_end_count": len(turn_ends),
            "already_closed": existing is not None,
            "bound": binding is not None and binding.get("bound") is True,
            "bind_reason": binding.get("reason") if binding is not None else "no_binder",
        }


def open_input_fence(bridge_dir: Path, fence_id: str) -> bool:
    """Remove the pane input fence if *fence_id* matches. Returns whether it was removed."""
    with receipt_lock(bridge_dir):
        existing = read_input_fence(bridge_dir)
        if existing is None:
            return True
        if existing.get("fence_id") != fence_id:
            return False
        with contextlib.suppress(FileNotFoundError):
            (bridge_dir / INPUT_FENCE_FILE).unlink()
        return True


def record_turn_end(bridge_dir: Path, payload: object | None = None) -> None:
    """Append one turn-outcome marker (called from the cursor ``stop`` hook).

    Fires on EVERY ended turn — including turns with no billable token usage,
    which :func:`omnigent.harnesses.cursor_native.usage.record_usage_payload` skips — so the
    parent wake never depends on a turn having produced usage. Best-effort and
    stdlib-only; the caller swallows failures so usage/idle capture never breaks
    the agent turn.

    :param bridge_dir: The cursor-native bridge dir (where the forwarder reads).
    :param payload: The cursor ``stop`` hook payload, if any — its
        ``generation_id`` and authoritative ``status`` are retained when present.
        Under receipts its ``conversation_id`` must equal the tailed chat for the
        turn end to carry a store position; otherwise it is kept unpositioned.
    """
    line: dict[str, object] = {"ts": time.time()}
    if isinstance(payload, dict):
        gen_id = payload.get("generation_id") or payload.get("conversation_id")
        if isinstance(gen_id, str) and gen_id:
            line["generation_id"] = gen_id
        hook_status = payload.get("status")
        if hook_status in ("completed", "aborted", "error"):
            line["status"] = hook_status
    bridge_dir.mkdir(parents=True, exist_ok=True)
    epoch = read_receipt_epoch(bridge_dir)
    if epoch is None:
        # Not opted in to completion receipts: the legacy marker, unchanged.
        # A leading separator isolates this record from a previous short write.
        # Blank lines are ignored by readers, including older forwarders.
        with open(bridge_dir / TURN_END_FILE, "a", encoding="utf-8") as handle:
            handle.write("\n" + json.dumps(line, sort_keys=True) + "\n")
        return
    raw = payload if isinstance(payload, dict) else {}
    status = raw.get("status")
    conversation_id = raw.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        conversation_id = None
    # The store position at hook time binds this turn end to the user rows that
    # exist when it fires (cursor blocks the next turn on this hook).
    store_chat, store_rowid = _hook_store_position(bridge_dir)
    check = _conversation_check(conversation_id, store_chat)
    with receipt_lock(bridge_dir):
        turn_ends = _epoch_records(bridge_dir / TURN_END_FILE, epoch)
        injects = _epoch_records(bridge_dir / INJECT_FILE, epoch)
        line.update(
            {
                "epoch": epoch,
                "turn_seq": len(turn_ends) + 1,
                # Message-injection units, the same units as ``inject_count``.
                "inject_count_at_end": _message_inject_count(injects),
                "stop_status_raw": status if isinstance(status, str) else None,
                "hook_conversation_id": conversation_id,
                "conversation_check": check,
                # A stop that is not provably this chat's gets no local position.
                "store_chat_at_end": store_chat if check == "match" else None,
                "store_rowid_at_end": store_rowid if check == "match" else None,
            }
        )
        if check != "match":
            line["observed_store_chat"] = store_chat
        with open(bridge_dir / TURN_END_FILE, "a", encoding="utf-8") as handle:
            handle.write("\n" + json.dumps(line, sort_keys=True) + "\n")


def _conversation_check(conversation_id: str | None, store_chat: str | None) -> str:
    """Whether a stop's ``conversation_id`` names the chat this bridge tails.

    A shared (user/system) hooks.json can deliver another session's ``stop``
    here, so only ``"match"`` may position a turn end in the local store.
    """
    if conversation_id is None:
        return "missing"
    if store_chat is None:
        return "store_unbound"
    return "match" if conversation_id == store_chat else "mismatch"


def _hook_store_position(bridge_dir: Path) -> tuple[str | None, int | None]:
    """Return ``(chat_id, MAX(rowid))`` of the store the forwarder tails, now.

    ``(None, None)`` when no store is bound yet or it cannot be read; such a
    turn end binds to no user row, so the receipt stays unbound (hold).
    """
    try:
        data = json.loads((bridge_dir / _FORWARDER_STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    store_path = data.get("store_path") if isinstance(data, dict) else None
    if not isinstance(store_path, str) or not store_path or not Path(store_path).is_file():
        return None, None
    # Same open order as ``forwarder._get_current_rowid``: ``mode=ro`` reads the
    # live WAL; a plain connection covers a momentarily absent ``-shm``.
    for uri, use_uri in ((f"file:{store_path}?mode=ro", True), (store_path, False)):
        try:
            con = sqlite3.connect(uri, timeout=2.0, uri=use_uri)
        except sqlite3.Error:
            continue
        try:
            row = con.execute("SELECT MAX(rowid) FROM blobs").fetchone()
        except sqlite3.Error:
            continue
        finally:
            con.close()
        rowid = row[0] if row else None
        if isinstance(rowid, int):
            return Path(store_path).parent.name, rowid
        return None, None
    return None, None


def count_turn_ends(bridge_dir: Path) -> int:
    """Return how many turn-end markers have been recorded (0 if none/unreadable).

    The marker file is append-only, so the line count is the number of turns that
    have ended since the terminal was (re-)created.
    """
    try:
        text = (bridge_dir / TURN_END_FILE).read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for raw in text.splitlines() if raw.strip())


def read_turn_outcome(bridge_dir: Path, turn_end: int) -> str:
    """Read the outcome at a snapshotted marker count, ignoring later appends.

    Legacy markers without a status retain their completed-turn behavior.
    Unreadable or corrupt markers raise so the forwarder can retry delivery.
    """
    if turn_end <= 0:
        raise ValueError("turn-end marker count must be positive")
    lines = (bridge_dir / TURN_END_FILE).read_text(encoding="utf-8").splitlines()
    markers = [raw for raw in lines if raw.strip()]
    marker = json.loads(markers[turn_end - 1])
    if not isinstance(marker, dict):
        raise ValueError("turn-end marker must be an object")
    hook_status = marker.get("status", "completed")
    if hook_status == "aborted":
        return "cancelled"
    if hook_status == "error":
        return "failed"
    if hook_status == "completed":
        return "completed"
    raise ValueError(f"unknown cursor turn outcome: {hook_status!r}")


def read_posted_count(bridge_dir: Path) -> int:
    """Load the count of turn-ends already POSTed (0 on cold/unreadable)."""
    try:
        data = json.loads((bridge_dir / _STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    posted = data.get("posted") if isinstance(data, dict) else None
    return posted if isinstance(posted, int) and posted >= 0 else 0


def write_posted_count(bridge_dir: Path, posted: int) -> None:
    """Atomically persist the count of turn-ends already POSTed.

    Persisted only AFTER a successful status POST so a failed flush is retried (the
    unreported turn-ends stay unreported until the post lands).
    """
    bridge_dir.mkdir(parents=True, exist_ok=True)
    tmp = bridge_dir / (_STATE_FILE + ".tmp")
    tmp.write_text(json.dumps({"posted": posted}), encoding="utf-8")
    os.replace(tmp, bridge_dir / _STATE_FILE)


def clear_cursor_status_state(bridge_dir: Path) -> None:
    """Remove the turn-end marker + poster state so a re-created terminal starts clean.

    Sibling of :func:`omnigent.harnesses.cursor_native.usage.clear_cursor_usage_state`: the
    runner calls this when it re-creates a cursor terminal so a stale marker count
    from a prior terminal can't make the new forwarder skip (or re-fire) idle.
    """
    # INPUT_FENCE_FILE is deliberately kept: a relaunch must not reopen input.
    for name in (TURN_END_FILE, _STATE_FILE, RECEIPT_EPOCH_FILE, INJECT_FILE):
        with contextlib.suppress(OSError):
            (bridge_dir / name).unlink()
