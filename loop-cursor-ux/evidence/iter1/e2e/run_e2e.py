"""Throwaway top-level cursor-native e2e (port >= 18300)."""

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

ROOT = Path("/home/alex/omnigent-cursor")
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
PROMPT = "Write 600 words about tmux. Do not use tools. Do not edit files."
OUT = ROOT / "loop-cursor-ux/evidence/iter1/e2e"


def _wait_conv(handle, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        match = _CONV_URL_RE.search(handle.output())
        if match:
            return match.group(1)
        time.sleep(0.2)
    raise AssertionError(
        f"no conversation id within {timeout}s; tail:\n{handle.output()[-2000:]}"
    )


def _bind_port() -> int:
    for port in range(18300, 18400):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError("no free port in 18300-18399")


def _parse_sse(chunk: str, events: list[dict]) -> str:
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
        events.append({"event": event_name, "t": time.monotonic(), "data": payload})
    return leftover


def _item_role(row: dict) -> str | None:
    if row.get("role"):
        return str(row["role"])
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    role = data.get("role")
    return str(role) if role else None


def _item_text(row: dict) -> str:
    data = row.get("data") if isinstance(row.get("data"), dict) else row
    parts: list[str] = []
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, list):
        content = row.get("content") if isinstance(row.get("content"), list) else []
    for block in content:
        if isinstance(block, dict) and block.get("text"):
            parts.append(str(block["text"]))
    return "".join(parts)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="cursor-ux-e2e-"))
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
    env.pop("OMNIGENT_PROCESS_LOG_FILE", None)
    env.pop("OMNIGENT_RUNNER_TUNNEL_TOKEN", None)
    env.setdefault("OPENAI_API_KEY", "sk-e2e-unused")
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
    result: dict[str, object] = {
        "port": port,
        "scratch": str(scratch),
        "server_pid": server.pid,
    }
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
        cli_e.pop("OMNIGENT_PROCESS_LOG_FILE", None)
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
            # View-open burst (GETs only) before any send.
            for path in (
                f"/v1/sessions/{conv}",
                f"/v1/sessions/{conv}/agent",
                f"/v1/sessions/{conv}/terminals",
                f"/v1/sessions/{conv}/child_sessions",
                f"/v1/sessions/{conv}/items?limit=50",
            ):
                client.get(path)
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
            time.sleep(1.0)
            open_error_codes = []
            for ev in events:
                data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                err = data.get("error") if isinstance(data.get("error"), dict) else {}
                code = err.get("code") or data.get("code")
                et = data.get("type") or ev.get("event")
                if et in {"error", "response.error"} or code:
                    open_error_codes.append(code or et)
            result["view_open_error_codes"] = open_error_codes

            t0 = time.monotonic()
            inject_user_message(client, conversation_id=conv, text=PROMPT)
            first_delta_s: float | None = None
            deltas_after_15 = 0
            deltas: list[str] = []
            complete_text = ""
            seen = 0
            while time.monotonic() - t0 < 240:
                while seen < len(events):
                    ev = events[seen]
                    seen += 1
                    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    et = data.get("type") or ev.get("event")
                    if et == "response.output_text.delta" and data.get("message_id"):
                        elapsed = time.monotonic() - t0
                        if first_delta_s is None:
                            first_delta_s = elapsed
                        if elapsed > 15:
                            deltas_after_15 += 1
                        deltas.append(str(data.get("delta") or ""))
                    if et == "response.output_item.done":
                        item = data.get("item") or {}
                        if item.get("role") == "assistant":
                            parts = []
                            for block in item.get("content") or []:
                                if isinstance(block, dict) and block.get("text"):
                                    parts.append(str(block["text"]))
                            complete_text = "".join(parts)
                if not complete_text:
                    items_resp = client.get(f"/v1/sessions/{conv}/items?limit=50")
                    if items_resp.status_code == 200:
                        rows = items_resp.json().get("data") or []
                        for row in rows:
                            if _item_role(row) == "assistant":
                                text = _item_text(row)
                                if text:
                                    complete_text = text
                if complete_text and deltas:
                    break
                time.sleep(0.05)

            items_resp = client.get(f"/v1/sessions/{conv}/items?limit=50")
            rows = items_resp.json().get("data") or [] if items_resp.status_code == 200 else []
            roles = [_item_role(row) for row in rows]
            user_before_asst = False
            if "user" in roles and "assistant" in roles:
                user_before_asst = roles.index("user") < roles.index("assistant")

            stop.set()
            joined = "".join(deltas)
            result.update(
                {
                    "ttfd_s": first_delta_s,
                    "delta_count": len(deltas),
                    "deltas_after_15s": deltas_after_15,
                    "joined_len": len(joined),
                    "complete_len": len(complete_text),
                    "byte_equal": joined == complete_text if complete_text else False,
                    "sse_event_count": len(events),
                    "item_roles": roles,
                    "user_before_assistant": user_before_asst,
                    "elapsed_s": time.monotonic() - t0,
                }
            )
            (OUT / "NUMBERS.json").write_text(json.dumps(result, indent=2) + "\n")
            (OUT / "DELTAS.txt").write_text(joined)
            (OUT / "COMPLETE.txt").write_text(complete_text)
            (OUT / "SSE.jsonl").write_text(
                "\n".join(json.dumps(e, default=str) for e in events) + "\n"
            )
        print(json.dumps(result, indent=2))
        ok = (
            bool(result.get("delta_count", 0) >= 1)
            and first_delta_s is not None
            and bool(result.get("user_before_assistant"))
            and not result.get("view_open_error_codes")
        )
        return 0 if ok else 1
    finally:
        if handle is not None:
            (OUT / "CLI.txt").write_text(handle.output()[-8000:])
            handle.terminate()
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
