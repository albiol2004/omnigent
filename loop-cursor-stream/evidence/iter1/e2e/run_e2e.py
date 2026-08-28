"""Throwaway cursor-native stream e2e (port >= 17200)."""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path("/home/alex/omnigent-fixes")
sys.path.insert(0, str(ROOT))

from tests._helpers.compat import apply_server_env, server_executable  # noqa: E402
from tests.e2e._native_resume_helpers import (  # noqa: E402
    cli_env,
    inject_user_message,
    omnigent_console_script,
    spawn_cli_background,
    wait_for_terminal_ready,
)

_CONV_URL_RE = re.compile(r"/c/([0-9a-f]{32})")


def _wait_conv(handle, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        match = _CONV_URL_RE.search(handle.output())
        if match:
            return match.group(1)
        time.sleep(0.2)
    raise AssertionError(
        f"no conversation id printed within {timeout}s; output tail:\n{handle.output()[-2000:]}"
    )


PROMPT = (
    "Write 800 words explaining how a mechanical clock works, with no tools and no file edits."
)
SECOND_PROMPT = "In one short paragraph, name the main parts of that clock."
OUT = ROOT / "loop-cursor-stream/evidence/iter1/e2e"


def _bind_port() -> int:
    for port in range(17200, 17300):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port in 17200-17299")


def _parse_sse(chunk: str, events: list[dict]) -> str:
    """Parse complete SSE frames; return leftover bytes as text."""
    parts = chunk.split("\n\n")
    leftover = parts.pop() if parts else ""
    for frame in parts:
        event_name = "message"
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        raw = "\n".join(data_lines)
        if not raw or raw == "[DONE]":
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        events.append({"event": event_name, "data": payload})
    return leftover


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="cursor-stream-e2e-"))
    data_dir = scratch / "data"
    config_dir = scratch / "config"
    artifacts = scratch / "artifacts"
    pwd = scratch / "pwd"
    for path in (data_dir, config_dir, artifacts, pwd):
        path.mkdir()
    port = _bind_port()
    base_url = f"http://127.0.0.1:{port}"
    db_path = data_dir / "e2e.db"
    env = dict(os.environ)
    env["OMNIGENT_DATA_DIR"] = str(data_dir)
    env["OMNIGENT_CONFIG_HOME"] = str(config_dir)
    env["OMNIGENT_SKIP_ONBOARD"] = "1"
    env["OMNIGENT_NO_UPDATE_CHECK"] = "1"
    env["OMNIGENT_CURSOR_STREAM"] = "1"
    env.setdefault("OPENAI_API_KEY", "sk-e2e-unused")
    env.pop("OMNIGENT_RUNNER_TUNNEL_TOKEN", None)
    apply_server_env(env, ROOT)
    log_path = OUT / "server.log"
    log_handle = open(log_path, "w")  # noqa: SIM115
    server = subprocess.Popen(
        [
            server_executable(),
            "-m",
            "omnigent.cli",
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--database-uri",
            f"sqlite:///{db_path}",
            "--artifact-location",
            str(artifacts),
        ],
        env=env,
        cwd=str(ROOT),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    handle = None
    result: dict[str, object] = {"port": port, "scratch": str(scratch)}
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if server.poll() is not None:
                raise RuntimeError(log_path.read_text()[-3000:])
            time.sleep(0.2)
        else:
            raise RuntimeError("server health timeout")

        cli_e = cli_env()
        cli_e["OMNIGENT_DATA_DIR"] = str(data_dir)
        cli_e["OMNIGENT_CONFIG_HOME"] = str(config_dir)
        cli_e["OMNIGENT_CURSOR_STREAM"] = "1"
        omni = str(omnigent_console_script())
        handle = spawn_cli_background(
            [omni, "cursor", "--server", base_url, "--", "--force", "--trust"],
            env=cli_e,
            cwd=str(pwd),
        )
        conv = _wait_conv(handle, 120)
        result["conversation_id"] = conv
        with httpx.Client(base_url=base_url, timeout=30) as client:
            wait_for_terminal_ready(client, conversation_id=conv, harness="cursor", timeout=90)
            events: list[dict] = []
            stop = threading.Event()

            def _tail() -> None:
                with (
                    httpx.Client(base_url=base_url, timeout=None) as stream_client,
                    stream_client.stream("GET", f"/v1/sessions/{conv}/stream") as resp,
                ):
                    buf = ""
                    for raw in resp.iter_text():
                        if stop.is_set():
                            break
                        buf = _parse_sse(buf + raw, events)

            thread = threading.Thread(target=_tail, daemon=True)
            thread.start()
            time.sleep(0.4)
            t0 = time.monotonic()
            inject_user_message(client, conversation_id=conv, text=PROMPT)
            first_delta_s: float | None = None
            complete_s: float | None = None
            deltas: list[str] = []
            first_message_ids: set[str] = set()
            complete_text = ""
            complete_event_index: int | None = None
            seen = 0
            while time.monotonic() - t0 < 180:
                while seen < len(events):
                    event_index = seen
                    ev = events[seen]
                    seen += 1
                    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    et = data.get("type") or ev.get("event")
                    if et == "response.output_text.delta" and data.get("message_id"):
                        if first_delta_s is None:
                            first_delta_s = time.monotonic() - t0
                        deltas.append(str(data.get("delta") or ""))
                        first_message_ids.add(str(data["message_id"]))
                    if et == "response.output_item.done":
                        item = data.get("item") or {}
                        if item.get("role") == "assistant":
                            complete_s = time.monotonic() - t0
                            complete_event_index = event_index
                            parts = []
                            for block in item.get("content") or []:
                                if isinstance(block, dict) and block.get("text"):
                                    parts.append(str(block["text"]))
                            complete_text = "".join(parts)
                if not complete_text:
                    items_resp = client.get(f"/v1/sessions/{conv}/items?limit=50")
                    if items_resp.status_code == 200:
                        for row in items_resp.json().get("data") or []:
                            if row.get("role") == "assistant":
                                parts = []
                                for block in row.get("content") or []:
                                    if isinstance(block, dict) and block.get("text"):
                                        parts.append(str(block["text"]))
                                text = "".join(parts)
                                if text:
                                    complete_text = text
                                    if complete_s is None:
                                        complete_s = time.monotonic() - t0
                if complete_text and deltas and complete_event_index is not None:
                    break
                time.sleep(0.05)
            post_complete_start = time.monotonic()
            post_complete_delta_count = 0
            while time.monotonic() - post_complete_start < 10:
                while seen < len(events):
                    event_index = seen
                    ev = events[seen]
                    seen += 1
                    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    et = data.get("type") or ev.get("event")
                    if et == "response.output_text.delta" and event_index > (
                        complete_event_index if complete_event_index is not None else -1
                    ):
                        post_complete_delta_count += 1
                time.sleep(0.05)
            post_complete_watch_s = time.monotonic() - post_complete_start

            second_t0 = time.monotonic()
            inject_user_message(client, conversation_id=conv, text=SECOND_PROMPT)
            second_deltas: list[str] = []
            second_message_ids: set[str] = set()
            while time.monotonic() - second_t0 < 180:
                while seen < len(events):
                    ev = events[seen]
                    seen += 1
                    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    et = data.get("type") or ev.get("event")
                    if et == "response.output_text.delta" and data.get("message_id"):
                        second_deltas.append(str(data.get("delta") or ""))
                        second_message_ids.add(str(data["message_id"]))
                if second_deltas:
                    break
                time.sleep(0.05)

            stop.set()
            joined = "".join(deltas)
            result.update(
                {
                    "ttfd_s": first_delta_s,
                    "complete_s": complete_s,
                    "delta_count": len(deltas),
                    "joined_len": len(joined),
                    "complete_len": len(complete_text),
                    "byte_equal": joined == complete_text,
                    "sse_event_count": len(events),
                    "post_complete_watch_s": post_complete_watch_s,
                    "post_complete_delta_count": post_complete_delta_count,
                    "second_delta_count": len(second_deltas),
                    "second_message_ids": sorted(second_message_ids),
                    "second_message_id_is_new": bool(second_message_ids)
                    and not first_message_ids.intersection(second_message_ids),
                }
            )
            (OUT / "REPLAY-CHECK.json").write_text(
                json.dumps(
                    {
                        "conversation_id": conv,
                        "first_message_ids": sorted(first_message_ids),
                        "complete_event_observed": complete_event_index is not None,
                        "post_complete_watch_s": post_complete_watch_s,
                        "post_complete_delta_count": post_complete_delta_count,
                        "second_prompt": SECOND_PROMPT,
                        "second_message_ids": sorted(second_message_ids),
                        "second_delta_count": len(second_deltas),
                        "second_message_id_is_new": bool(second_message_ids)
                        and not first_message_ids.intersection(second_message_ids),
                    },
                    indent=2,
                )
                + "\n"
            )
            (OUT / "NUMBERS.json").write_text(json.dumps(result, indent=2) + "\n")
            (OUT / "DELTAS.txt").write_text(joined)
            (OUT / "COMPLETE.txt").write_text(complete_text)
            (OUT / "SSE.jsonl").write_text("\n".join(json.dumps(e) for e in events[-80:]) + "\n")
        print(json.dumps(result, indent=2))
        return (
            0
            if (
                result.get("delta_count", 0) >= 5
                and first_delta_s
                and result.get("post_complete_watch_s", 0) >= 10
                and result.get("post_complete_delta_count") == 0
                and result.get("second_delta_count", 0) > 0
                and result.get("second_message_id_is_new") is True
            )
            else 1
        )
    finally:
        if handle is not None:
            (OUT / "CLI.txt").write_text(handle.output()[-8000:])
            handle.terminate()
        subprocess.run(["pkill", "-f", "cursor-stream-e2e"], check=False)
        if server.poll() is None:
            server.send_signal(signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
