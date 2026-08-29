#!/usr/bin/env python3
"""Throwaway two-turn cursor-native e2e for loop-cursor2 iter 1.

Port >= 18500, scratch data/config, torn down. Does not touch :6767.
"""

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

REPO = Path("/home/alex/omnigent-cursor2")
EVIDENCE = REPO / "loop-cursor2/evidence/iter1/e2e"
sys.path[:0] = [str(REPO)]

from tests._helpers.compat import apply_server_env  # noqa: E402
from tests.e2e._native_resume_helpers import (  # noqa: E402
    cli_env,
    inject_user_message,
    omnigent_console_script,
    spawn_cli_background,
    wait_for_terminal_ready,
)


def _port() -> int:
    for candidate in range(18500, 18600):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError("no free port in 18500-18599")


def _sse_worker(url: str, dest: Path, stop: threading.Event) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle, httpx.Client(timeout=None) as client:
        with client.stream("GET", url) as resp:
            for chunk in resp.iter_bytes():
                handle.write(chunk)
                handle.flush()
                if stop.is_set():
                    break


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    port = _port()
    base = f"http://127.0.0.1:{port}"
    root = Path(tempfile.mkdtemp(prefix="omnigent-cursor2-e2e-"))
    data = root / "data"
    config = root / "config"
    artifacts = root / "artifacts"
    db = root / "e2e.db"
    for path in (data, config, artifacts):
        path.mkdir()
    (config / "config.yaml").write_text("auth:\n  type: none\n", encoding="utf-8")
    server_log = EVIDENCE / "server.log"
    env = dict(os.environ)
    env.pop("OMNIGENT_PROCESS_LOG_FILE", None)
    env["OMNIGENT_DATA_DIR"] = str(data)
    env["OMNIGENT_CONFIG_HOME"] = str(config)
    env["OPENAI_API_KEY"] = env.get("OPENAI_API_KEY") or "sk-e2e-unused"
    env.pop("OMNIGENT_RUNNER_TUNNEL_TOKEN", None)
    apply_server_env(env, REPO)
    env["PYTHONPATH"] = f"{REPO}{os.pathsep}{env.get('PYTHONPATH', '')}"
    log_handle = server_log.open("w")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "omnigent.cli",
            "server",
            "--port",
            str(port),
            "--database-uri",
            f"sqlite:///{db}",
            "--artifact-location",
            str(artifacts),
        ],
        env=env,
        cwd=str(REPO),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    cli = None
    stop_sse = threading.Event()
    sse_thread = None
    started: list[int] = [proc.pid]
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None:
                raise RuntimeError(f"server died: {server_log.read_text()[-4000:]}")
            time.sleep(0.2)
        else:
            raise RuntimeError("health timeout")
        (EVIDENCE / "port.txt").write_text(f"{port}\n{base}\n", encoding="utf-8")
        cli_env_map = cli_env(profile=None)
        cli_env_map["OMNIGENT_DATA_DIR"] = str(data)
        cli_env_map["OMNIGENT_CONFIG_HOME"] = str(config)
        cli_env_map["PYTHONPATH"] = f"{REPO}{os.pathsep}{cli_env_map.get('PYTHONPATH', '')}"
        cli_env_map.pop("OMNIGENT_PROCESS_LOG_FILE", None)
        omni = str(omnigent_console_script())
        ws = EVIDENCE / "scratch-ws"
        ws.mkdir(exist_ok=True)
        cli = spawn_cli_background(
            [omni, "cursor", "--server", base, "-f", "--trust"],
            env=cli_env_map,
            cwd=str(ws),
        )
        deadline = time.monotonic() + 120
        conv = ""
        while time.monotonic() < deadline:
            match = re.search(r"/c/([0-9a-f]{32})", cli.output())
            if match:
                conv = match.group(1)
                break
            time.sleep(0.2)
        if not conv:
            raise RuntimeError(f"no conversation id in CLI output:\n{cli.output()[-2000:]}")
        (EVIDENCE / "conversation_id.txt").write_text(conv, encoding="utf-8")
        with httpx.Client(base_url=base, timeout=60) as client:
            wait_for_terminal_ready(
                client, conversation_id=conv, harness="cursor", timeout=90
            )
            sse_path = EVIDENCE / "sse.raw"
            sse_thread = threading.Thread(
                target=_sse_worker,
                args=(f"{base}/v1/sessions/{conv}/stream", sse_path, stop_sse),
                daemon=True,
            )
            sse_thread.start()
            time.sleep(0.5)
            inject_user_message(
                client,
                conversation_id=conv,
                text=(
                    "Spend at least twenty seconds thinking, then reply with "
                    "exactly the word ALPHAONE and a short sentence."
                ),
            )
            t1 = time.monotonic() + 180
            while time.monotonic() < t1:
                raw = sse_path.read_bytes() if sse_path.exists() else b""
                if b"ALPHAONE" in raw:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("turn 1 marker missing from SSE")
            inject_user_message(
                client,
                conversation_id=conv,
                text=(
                    "Spend at least twenty seconds thinking, then reply with "
                    "exactly the word BETATWO and a short sentence."
                ),
            )
            t2 = time.monotonic() + 180
            while time.monotonic() < t2:
                raw = sse_path.read_bytes()
                if b"BETATWO" in raw:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("turn 2 marker missing from SSE")
            opts = client.get(f"/v1/sessions/{conv}/cursor-model-options")
            (EVIDENCE / "model-options.json").write_text(opts.text, encoding="utf-8")
            bogus = client.patch(
                f"/v1/sessions/{conv}",
                json={"model_override": "definitely-not-a-cursor-model-zzz"},
            )
            (EVIDENCE / "bogus-model.json").write_text(
                json.dumps({"status": bogus.status_code, "body": bogus.text}),
                encoding="utf-8",
            )
            chosen = "cursor-grok-4.6-medium"
            ids = [
                m.get("id")
                for m in (opts.json().get("models") or [])
                if isinstance(m, dict)
            ]
            if chosen not in ids and ids:
                chosen = str(ids[0])
            ok = client.patch(
                f"/v1/sessions/{conv}", json={"model_override": chosen}
            )
            (EVIDENCE / "model-change.json").write_text(
                json.dumps({"status": ok.status_code, "model": chosen, "body": ok.text}),
                encoding="utf-8",
            )
        (EVIDENCE / "RESULT.txt").write_text(
            f"port={port} conv={conv} turn1=ALPHAONE turn2=BETATWO "
            f"bogus={bogus.status_code} change={ok.status_code} model={chosen}\n",
            encoding="utf-8",
        )
        return 0
    finally:
        stop_sse.set()
        if cli is not None:
            cli.terminate()
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        log_handle.close()
        (EVIDENCE / "pids.txt").write_text(
            "started " + ",".join(str(p) for p in started) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
