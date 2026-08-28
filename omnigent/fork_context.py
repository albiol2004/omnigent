"""Size guards and compaction helpers for forked conversation context."""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from omnigent.errors import ErrorCode

FORK_MAX_CONTEXT_BYTES_ENV = "OMNIGENT_FORK_MAX_CONTEXT_BYTES"
DEFAULT_FORK_MAX_CONTEXT_BYTES = 600_000
FORK_JSONL_INFLATION_ENV = "OMNIGENT_FORK_JSONL_INFLATION"
DEFAULT_FORK_JSONL_INFLATION = 1.8
FORK_NATIVE_GUARD_ENV = "OMNIGENT_FORK_NATIVE_GUARD"

# When no pure renderer is available, multiply API JSON bytes by this factor.
# Override with OMNIGENT_FORK_JSONL_INFLATION; 1.8 covers native envelopes.

_logger = logging.getLogger(__name__)


class ForkContextTooLarge(ValueError):
    """Raised when fork history remains over the configured byte limit."""

    code = ErrorCode.FORK_CONTEXT_TOO_LARGE
    http_status = 413

    def __init__(
        self,
        actual_bytes: int,
        threshold_bytes: int,
        *,
        message_suffix: str | None = None,
    ) -> None:
        self.actual_bytes = actual_bytes
        self.threshold_bytes = threshold_bytes
        message = (
            "Fork context too large: "
            f"{actual_bytes} bytes exceeds threshold {threshold_bytes} bytes "
            f"({FORK_MAX_CONTEXT_BYTES_ENV})."
        )
        if message_suffix:
            message = f"{message} {message_suffix}"
        super().__init__(message)


def max_fork_context_bytes() -> int:
    """Return the positive byte limit configured for fork context."""
    raw = os.environ.get(FORK_MAX_CONTEXT_BYTES_ENV)
    if raw is not None:
        try:
            configured = int(raw)
        except ValueError:
            configured = 0
        if configured > 0:
            return configured
    return DEFAULT_FORK_MAX_CONTEXT_BYTES


def fork_native_guard_enabled() -> bool:
    """Return whether native fork clones use the strict size guard."""
    return os.environ.get(FORK_NATIVE_GUARD_ENV, "").strip() == "1"


def serialized_context_bytes(value: object, *, ensure_ascii: bool = False) -> int:
    """Return the UTF-8 bytes used by a JSON-shaped harness payload."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    encoded = json.dumps(
        value,
        ensure_ascii=ensure_ascii,
        separators=(",", ":"),
    )
    return len(encoded.encode("utf-8"))


def fork_jsonl_inflation() -> float:
    """Return the positive finite multiplier for renderer fallback estimates."""
    raw = os.environ.get(FORK_JSONL_INFLATION_ENV)
    if raw is not None:
        try:
            configured = float(raw)
        except ValueError:
            configured = 0.0
        if configured > 0 and math.isfinite(configured):
            return configured
    return DEFAULT_FORK_JSONL_INFLATION


def jsonl_context_bytes(
    records: Sequence[Mapping[str, Any]],
    *,
    ensure_ascii: bool = True,
) -> int:
    """Return the bytes occupied by compact JSONL records."""
    return sum(
        serialized_context_bytes(record, ensure_ascii=ensure_ascii) + 1 for record in records
    )


def estimate_fork_context_bytes(
    value: object,
    *,
    renderer: Callable[[object], Sequence[Mapping[str, Any]]] | None = None,
) -> int:
    """Estimate the bytes the target harness will receive for fork history.

    A pure renderer is preferred because native runners write its records
    directly. If importing or invoking that renderer is unavailable, the
    configured JSONL inflation factor keeps the guard conservative.
    """
    serialized_bytes = serialized_context_bytes(value)
    if renderer is not None:
        try:
            return jsonl_context_bytes(renderer(value))
        except Exception:  # noqa: BLE001 — renderer failure uses safe fallback
            _logger.debug(
                "Fork context renderer unavailable; using inflation fallback",
                exc_info=True,
            )
    return math.ceil(serialized_bytes * fork_jsonl_inflation())


def guard_fork_context_bytes(
    actual_bytes: int,
    *,
    compacted_bytes: int | None = None,
    threshold: int | None = None,
    guard: bool = True,
) -> int:
    """Allow context at the limit, or raise with the final measured size.

    Non-fork resume paths pass ``guard=False`` so oversized history is logged
    and retained instead of being rejected.
    """
    limit = max_fork_context_bytes() if threshold is None else threshold
    if not guard:
        if actual_bytes > limit:
            _logger.info(
                "Skipping fork context size guard for non-fork context: "
                "%d bytes exceeds threshold %d bytes",
                actual_bytes,
                limit,
            )
        return actual_bytes
    if actual_bytes <= limit:
        return actual_bytes
    if compacted_bytes is not None and compacted_bytes <= limit:
        return compacted_bytes
    final_bytes = compacted_bytes if compacted_bytes is not None else actual_bytes
    raise ForkContextTooLarge(final_bytes, limit)


def guard_fork_context(
    value: object,
    *,
    compacted_value: object | None = None,
    threshold: int | None = None,
    guard: bool = True,
) -> int:
    """Measure a payload, retrying once with an optional compacted payload."""
    actual_bytes = serialized_context_bytes(value)
    compacted_bytes = (
        serialized_context_bytes(compacted_value) if compacted_value is not None else None
    )
    return guard_fork_context_bytes(
        actual_bytes,
        compacted_bytes=compacted_bytes,
        threshold=threshold,
        guard=guard,
    )


def summary_only_items(
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Drop items covered by the latest persisted compaction marker.

    ``last_item_id`` is the inclusive summary boundary. A compaction marker
    can be appended after newer items, so those items remain after the marker
    in the returned sequence.
    """
    copied = [dict(item) for item in items]
    latest_index = next(
        (
            index
            for index in range(len(copied) - 1, -1, -1)
            if copied[index].get("type") == "compaction"
        ),
        None,
    )
    if latest_index is None:
        return copied

    marker = copied[latest_index]
    has_summary = isinstance(marker.get("summary"), str) and bool(marker["summary"])
    has_replacement = isinstance(marker.get("compacted_messages"), list) and bool(
        marker["compacted_messages"]
    )
    if not has_summary and not has_replacement:
        return copied
    boundary_id = marker.get("last_item_id")
    boundary_index = latest_index
    if isinstance(boundary_id, str) and boundary_id:
        boundary_index = next(
            (
                index
                for index in range(latest_index - 1, -1, -1)
                if copied[index].get("id") == boundary_id
            ),
            latest_index,
        )

    tail = [
        item
        for index, item in enumerate(copied)
        if index > boundary_index and index != latest_index
    ]
    return [marker, *tail]
