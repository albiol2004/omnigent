"""Measure synthetic fork prompt/transcript sizes using product renderers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/alex/omnigent")

from omnigent.cursor_native_bridge import wrap_fork_preamble
from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
from omnigent.runner.native.orchestration import (
    _cursor_fork_history_preamble,
)

TURNS = 320
CHARS = 6000
BODY = "x" * CHARS


def messages() -> list[dict]:
    out: list[dict] = []
    for i in range(TURNS):
        out.append({"role": "user", "content": f"U{i} {BODY}"})
        out.append({"role": "assistant", "content": f"A{i} {BODY}"})
    return out


def items() -> list[dict]:
    rows: list[dict] = []
    for i, msg in enumerate(messages()):
        rows.append(
            {
                "type": "message",
                "role": msg["role"],
                "content": [{"type": "text", "text": msg["content"]}],
            }
        )
    return rows


def jsonl_bytes(n: int) -> tuple[int, int]:
    recs = []
    for i, msg in enumerate(messages()):
        recs.append(
            json.dumps(
                {
                    "type": "user" if msg["role"] == "user" else "assistant",
                    "message": {"role": msg["role"], "content": msg["content"]},
                    "sessionId": "00000000-0000-0000-0000-000000000000",
                    "uuid": f"{i:08d}",
                },
                separators=(",", ":"),
            )
        )
    blob = "\n".join(recs) + "\n"
    return len(recs), len(blob.encode())


def sdk_bytes() -> tuple[int, int]:
    prompt = ClaudeSDKExecutor._build_prompt(messages(), resume_session=False)
    if isinstance(prompt, str):
        return 1, len(prompt.encode())
    blob = json.dumps(prompt, separators=(",", ":"))
    return len(prompt), len(blob.encode())


def sdk_warm_bytes() -> int:
    prompt = ClaudeSDKExecutor._build_prompt(messages(), resume_session=True)
    if isinstance(prompt, str):
        return len(prompt.encode())
    return len(json.dumps(prompt).encode())


def cursor_bytes() -> tuple[int, int]:
    preamble = _cursor_fork_history_preamble(items())
    wrapped = wrap_fork_preamble(preamble, "latest")
    return len(preamble.encode()), len(wrapped.encode())


def main() -> None:
    n_jsonl, b_jsonl = jsonl_bytes(TURNS)
    n_sdk, b_sdk = sdk_bytes()
    warm = sdk_warm_bytes()
    pre_b, wrap_b = cursor_bytes()
    result = {
        "turns": TURNS,
        "chars_per_message": CHARS,
        "message_count": TURNS * 2,
        "native_jsonl_records": n_jsonl,
        "native_jsonl_bytes": b_jsonl,
        "sdk_fresh_blocks": n_sdk,
        "sdk_fresh_serialized_bytes": b_sdk,
        "sdk_warm_bytes": warm,
        "cursor_preamble_bytes": pre_b,
        "cursor_wrapped_injection_bytes": wrap_b,
    }
    out = Path(__file__).resolve().parent.parent / "MEASUREMENT.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
