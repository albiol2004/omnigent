"""Exercise fork byte guards with a synthetic ~3.9 MB conversation."""

from __future__ import annotations

import json
from pathlib import Path

from omnigent.fork_context import (
    ForkContextTooLarge,
    guard_fork_context,
    serialized_context_bytes,
    summary_only_items,
)

TURNS = 320
CHARS_PER_MESSAGE = 6_000
THRESHOLD = 600_000


def synthetic_items() -> list[dict[str, object]]:
    """Build the same large, local-only shape used by the evidence fixture."""
    body = "x" * CHARS_PER_MESSAGE
    items: list[dict[str, object]] = []
    for index in range(TURNS):
        for role, block_type in (("user", "input_text"), ("assistant", "output_text")):
            items.append(
                {
                    "id": f"message-{index}-{role}",
                    "type": "message",
                    "role": role,
                    "content": [{"type": block_type, "text": body}],
                }
            )
    return items


def main() -> None:
    """Measure refusal, summary-only retry, and the final refusal message."""
    messages = synthetic_items()
    full_bytes = serialized_context_bytes(messages)
    try:
        guard_fork_context(messages, threshold=THRESHOLD)
    except ForkContextTooLarge as exc:
        initial_refusal = str(exc)
    else:
        initial_refusal = "unexpectedly allowed"

    with_marker = [
        *messages,
        {
            "id": "compact-1",
            "type": "compaction",
            "summary": "The synthetic conversation was summarized.",
            "last_item_id": messages[-1]["id"],
        },
    ]
    compacted = summary_only_items(with_marker)
    compacted_bytes = serialized_context_bytes(compacted)
    allowed_bytes = guard_fork_context(
        with_marker,
        compacted_value=compacted,
        threshold=THRESHOLD,
    )

    oversized_compacted = [
        {
            **compacted[0],
            "summary": "y" * (THRESHOLD + 1),
        }
    ]
    try:
        guard_fork_context(
            with_marker,
            compacted_value=oversized_compacted,
            threshold=THRESHOLD,
        )
    except ForkContextTooLarge as exc:
        final_refusal = str(exc)
    else:
        final_refusal = "unexpectedly allowed"

    result = {
        "turns": TURNS,
        "chars_per_message": CHARS_PER_MESSAGE,
        "full_item_count": len(messages),
        "full_context_bytes": full_bytes,
        "compacted_item_count": len(compacted),
        "compacted_context_bytes": compacted_bytes,
        "compaction_retry_allowed_bytes": allowed_bytes,
        "threshold_bytes": THRESHOLD,
        "initial_refusal": initial_refusal,
        "final_refusal": final_refusal,
    }
    output = json.dumps(result, indent=2) + "\n"
    evidence_dir = Path(__file__).resolve().parent
    (evidence_dir / "RESULT.md").write_text(
        "# Fork oversize guard evidence\n\n"
        "The fixture is synthetic and does not access a database or vendor "
        "transcript.\n\n"
        f"```json\n{output}```\n",
        encoding="utf-8",
    )
    print(output, end="")


if __name__ == "__main__":
    main()
