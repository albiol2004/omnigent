"""Re-check SDK replay after 7792bcf5f. Scratch dirs only."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from io import StringIO
from pathlib import Path

from omnigent.fork_context import ForkContextTooLarge
from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
from omnigent.runtime.harnesses._executor_adapter import (
    _extract_role_keyed_messages,
)
from omnigent.stores.conversation_store import FORK_CARRY_HISTORY_LABEL_KEY

OUT = Path("/home/alex/omnigent-fixes/loop-fixes/evidence/hotfix/eval2")


def _oversized() -> list[dict[str, object]]:
    """Same 800 kB-class cold replay as the prior ITERATE evidence."""
    return [
        {"role": "user", "content": "x" * 400_000},
        {"role": "assistant", "content": "y" * 400_000},
        {"role": "user", "content": "continue"},
    ]


def _try_build(messages: list[dict[str, object]]) -> dict[str, object]:
    """Call _build_prompt with default is_fork (label sniff)."""
    try:
        prompt = ClaudeSDKExecutor._build_prompt(messages, resume_session=False)
        size = (
            len(prompt.encode())
            if isinstance(prompt, str)
            else len(json.dumps(prompt).encode())
        )
        return {"raised": False, "prompt_bytes": size}
    except ForkContextTooLarge as exc:
        return {
            "raised": True,
            "http_status": exc.http_status,
            "actual_bytes": exc.actual_bytes,
            "threshold_bytes": exc.threshold_bytes,
            "message": str(exc),
        }


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="hotfix-eval2-"))
    os.environ["HOME"] = str(scratch / "home")
    os.environ["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    os.environ["OMNIGENT_CONFIG_HOME"] = str(scratch / "config")
    (scratch / "home").mkdir()

    log_buf = StringIO()
    handler = logging.StreamHandler(log_buf)
    logging.getLogger("omnigent.fork_context").addHandler(handler)
    logging.getLogger("omnigent.fork_context").setLevel(logging.INFO)

    unlabeled = _oversized()
    labeled = _oversized()
    labeled[0]["metadata"] = {"labels": {FORK_CARRY_HISTORY_LABEL_KEY: "1"}}

    # Adapter copies only role+content; fork labels on AP items are dropped.
    ap_items = [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hello"}],
            "metadata": {"labels": {FORK_CARRY_HISTORY_LABEL_KEY: "1"}},
            "labels": {FORK_CARRY_HISTORY_LABEL_KEY: "1"},
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "ok"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "next"}],
        },
    ]
    adapted = _extract_role_keyed_messages(ap_items)

    result = {
        "scratch": str(scratch),
        "non_fork_800k": _try_build(unlabeled),
        "fork_labeled_800k": _try_build(labeled),
        "has_fork_labels_unlabeled": ClaudeSDKExecutor._has_fork_labels(unlabeled),
        "has_fork_labels_labeled": ClaudeSDKExecutor._has_fork_labels(labeled),
        "adapter_keeps_keys": sorted({k for m in adapted for k in m}),
        "adapter_has_fork_labels": ClaudeSDKExecutor._has_fork_labels(adapted),
        "skip_log": log_buf.getvalue(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
