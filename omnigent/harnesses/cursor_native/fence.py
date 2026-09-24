"""Runner side of the opt-in input fence for cursor-native sessions.

The server forwards ``input_fence`` events here. ``close`` installs the pane
fence and answers with the counters and the turn binding read in the same
critical section, so the server can verify that no prompt landed after the
receipt it was given and that every injected prompt's turn has ended.
"""

from __future__ import annotations

from pathlib import Path

from omnigent.harnesses.cursor_native import status as cursor_native_status
from omnigent.harnesses.cursor_native.forwarder import read_bound_chat_id, turn_binding


def handle_runner_fence_request(bridge_dir: Path, data: object) -> tuple[int, dict[str, object]]:
    """Apply a fence ``close``/``open`` to *bridge_dir*.

    :returns: ``(http_status, json_body)``.
    """
    action = data.get("action") if isinstance(data, dict) else None
    fence_id = data.get("fence_id") if isinstance(data, dict) else None
    if action not in ("close", "open") or not isinstance(fence_id, str) or not fence_id:
        return 400, {"error": "invalid_input", "detail": "input_fence needs action and fence_id"}
    if action == "open":
        if not cursor_native_status.open_input_fence(bridge_dir, fence_id):
            return 409, {"error": "fence_id_mismatch"}
        return 200, {"opened": True}
    if cursor_native_status.read_receipt_epoch(bridge_dir) is None:
        return 409, {"error": "capability_unsupported"}
    result = cursor_native_status.close_input_fence(
        bridge_dir,
        fence_id,
        lambda turn_ends, injects: turn_binding(bridge_dir, turn_ends, injects),
    )
    result["chat_id"] = read_bound_chat_id(bridge_dir)
    return 200, result
