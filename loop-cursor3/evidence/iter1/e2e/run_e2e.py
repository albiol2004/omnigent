#!/usr/bin/env python3
"""Isolated picker + streaming e2e for loop-cursor3 (port >= 18900)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

REPO = Path("/home/alex/omnigent-cursor3")
EVIDENCE = REPO / "loop-cursor3/evidence/iter1/e2e"
REAL_HOME = Path("/home/alex")
sys.path[:0] = [str(REPO)]

from omnigent._platform import stable_user_id  # noqa: E402
from tests._helpers.compat import apply_server_env  # noqa: E402
from tests.e2e._native_resume_helpers import (  # noqa: E402
    cli_env,
    inject_user_message,
    omnigent_console_script,
    spawn_cli_background,
    wait_for_terminal_ready,
)


def _port() -> int:
    for candidate in range(18900, 19000):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError("no free port in 18900-18999")


def _scratch_home() -> Path:
    home = Path(tempfile.mkdtemp(prefix="trio-c3-e2e-home-"))
    (home / ".cursor").mkdir()
    (home / ".config/cursor").mkdir(parents=True)
    (home / ".cache").mkdir()
    (home / ".local/share").mkdir(parents=True)
    shutil.copy2(REAL_HOME / ".cursor/cli-config.json", home / ".cursor/cli-config.json")
    shutil.copy2(REAL_HOME / ".config/cursor/auth.json", home / ".config/cursor/auth.json")
    return home


def _isolate_env(env: dict[str, str], scratch: Path) -> dict[str, str]:
    env = dict(env)
    env["HOME"] = str(scratch)
    env["XDG_CONFIG_HOME"] = str(scratch / ".config")
    env["XDG_CACHE_HOME"] = str(scratch / ".cache")
    env["XDG_DATA_HOME"] = str(scratch / ".local/share")
    for key in (
        "CURSOR_AGENT",
        "CURSOR_CONVERSATION_ID",
        "CURSOR_ASKPASS_SECRET",
        "CURSOR_ASKPASS_SOCKET",
        "AGENT_TRANSCRIPTS",
        "CURSOR_INVOKED_AS",
        "SUDO_ASKPASS",
        "OMNIGENT_PROCESS_LOG_FILE",
    ):
        env.pop(key, None)
    return env


def _bridge_dir(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    root = Path(tempfile.gettempdir()) / f"omnigent-{stable_user_id()}" / "cursor-native"
    return root / digest


def _capture_our_pane(conv: str) -> str:
    tmux_path = _bridge_dir(conv) / "tmux.json"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if tmux_path.is_file():
            break
        time.sleep(0.2)
    else:
        return f"NO_TMUX_JSON {tmux_path}"
    info = json.loads(tmux_path.read_text(encoding="utf-8"))
    proc = subprocess.run(
        [
            "tmux",
            "-S",
            info["socket_path"],
            "capture-pane",
            "-p",
            "-J",
            "-t",
            info["tmux_target"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return f"CAPTURE_FAILED rc={proc.returncode} {proc.stderr}"
    return proc.stdout


def _footer(pane: str) -> str:
    lines = [line.rstrip() for line in pane.splitlines() if line.strip()]
    return "\n".join(lines[-6:])


def _sse_worker(url: str, dest: Path, stop: threading.Event) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle, httpx.Client(timeout=None) as client:
        with client.stream("GET", url) as resp:
            for chunk in resp.iter_bytes():
                handle.write(chunk)
                handle.flush()
                if stop.is_set():
                    break


def _joined_live_deltas(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    pieces: list[str] = []
    for match in re.finditer(r"data:\s*(\{.*?\})\s*(?:\n\n|\r\n\r\n)", text, re.S):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        event = payload.get("event") or payload
        etype = event.get("type") if isinstance(event, dict) else None
        if etype in {"external_output_text_delta", "output_text_delta"}:
            delta = event.get("delta") or event.get("text") or ""
            if isinstance(delta, str):
                pieces.append(delta)
        data = event.get("data") if isinstance(event, dict) else None
        if isinstance(data, dict) and data.get("delta"):
            pieces.append(str(data["delta"]))
    return "".join(pieces)


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    start_hash = hashlib.sha256(
        (REAL_HOME / ".cursor/cli-config.json").read_bytes()
    ).hexdigest()
    (EVIDENCE / "cli-config.start.sha256").write_text(start_hash + "\n")
    scratch = _scratch_home()
    (EVIDENCE / "scratch-home.txt").write_text(str(scratch) + "\n")
    port = _port()
    base = f"http://127.0.0.1:{port}"
    root = Path(tempfile.mkdtemp(prefix="omnigent-cursor3-e2e-"))
    data = root / "data"
    config = root / "config"
    artifacts = root / "artifacts"
    db = root / "e2e.db"
    for path in (data, config, artifacts):
        path.mkdir()
    (config / "config.yaml").write_text("auth:\n  type: none\n", encoding="utf-8")
    server_log = EVIDENCE / "server.log"
    env = _isolate_env(dict(os.environ), scratch)
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
    started = [proc.pid]
    stop_sse = threading.Event()
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
        cli_env_map = _isolate_env(cli_env(profile=None), scratch)
        cli_env_map["OMNIGENT_DATA_DIR"] = str(data)
        cli_env_map["OMNIGENT_CONFIG_HOME"] = str(config)
        cli_env_map["PYTHONPATH"] = f"{REPO}{os.pathsep}{cli_env_map.get('PYTHONPATH', '')}"
        omni = str(omnigent_console_script())
        ws = EVIDENCE / "scratch-ws"
        ws.mkdir(exist_ok=True)
        cli = spawn_cli_background(
            [omni, "cursor", "--server", base, "-f", "--trust"],
            env=cli_env_map,
            cwd=str(ws),
        )
        started.append(cli.pid)
        deadline = time.monotonic() + 120
        conv = ""
        while time.monotonic() < deadline:
            match = re.search(r"/c/([0-9a-f]{32})", cli.output())
            if match:
                conv = match.group(1)
                break
            time.sleep(0.2)
        if not conv:
            raise RuntimeError(f"no conversation id:\n{cli.output()[-2000:]}")
        (EVIDENCE / "conversation_id.txt").write_text(conv, encoding="utf-8")
        with httpx.Client(base_url=base, timeout=90) as client:
            wait_for_terminal_ready(
                client, conversation_id=conv, harness="cursor", timeout=90
            )
            time.sleep(2)
            before = _capture_our_pane(conv)
            (EVIDENCE / "pane-before.txt").write_text(before, encoding="utf-8")
            glm = client.patch(
                f"/v1/sessions/{conv}", json={"model_override": "glm-5.2-high"}
            )
            (EVIDENCE / "glm-high.json").write_text(
                json.dumps({"status": glm.status_code, "body": glm.text[:4000]}),
                encoding="utf-8",
            )
            time.sleep(3)
            after_glm = _capture_our_pane(conv)
            (EVIDENCE / "pane-after-glm-high.txt").write_text(after_glm, encoding="utf-8")
            glm_max = client.patch(
                f"/v1/sessions/{conv}", json={"model_override": "glm-5.2-max"}
            )
            (EVIDENCE / "glm-max.json").write_text(
                json.dumps({"status": glm_max.status_code, "body": glm_max.text[:4000]}),
                encoding="utf-8",
            )
            time.sleep(3)
            after_max = _capture_our_pane(conv)
            (EVIDENCE / "pane-after-glm-max.txt").write_text(after_max, encoding="utf-8")
            bogus = client.patch(
                f"/v1/sessions/{conv}",
                json={"model_override": "definitely-not-a-cursor-model-zzz"},
            )
            (EVIDENCE / "bogus-model.json").write_text(
                json.dumps({"status": bogus.status_code, "body": bogus.text[:4000]}),
                encoding="utf-8",
            )
            time.sleep(2)
            after_bogus = _capture_our_pane(conv)
            (EVIDENCE / "pane-after-bogus.txt").write_text(after_bogus, encoding="utf-8")
            sse_path = EVIDENCE / "sse.bin"
            sse_thread = threading.Thread(
                target=_sse_worker,
                args=(f"{base}/v1/sessions/{conv}/stream", sse_path, stop_sse),
                daemon=True,
            )
            sse_thread.start()
            time.sleep(0.5)
            started_turn = time.monotonic()
            inject_user_message(
                client,
                conversation_id=conv,
                text=(
                    "Think carefully for at least twenty seconds. Then write a "
                    "detailed six-paragraph explanation of how a mechanical "
                    "clock escapement works, and end with the exact token "
                    "CLOCKMARK."
                ),
            )
            t_end = time.monotonic() + 180
            while time.monotonic() < t_end:
                raw = sse_path.read_bytes() if sse_path.exists() else b""
                if b"CLOCKMARK" in raw:
                    break
                snap = client.get(f"/v1/sessions/{conv}")
                body = snap.json() if snap.status_code == 200 else {}
                items = body.get("items") or []
                blob = json.dumps(items)
                if "CLOCKMARK" in blob:
                    sse_path.write_bytes(raw + b"\n" + blob.encode())
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("CLOCKMARK missing from stream/session")
            elapsed = time.monotonic() - started_turn
            (EVIDENCE / "stream-elapsed.txt").write_text(f"{elapsed:.2f}\n")
            snap = client.get(f"/v1/sessions/{conv}")
            (EVIDENCE / "session-after-stream.json").write_text(snap.text[:200000])
            live = _joined_live_deltas(sse_path.read_bytes() if sse_path.exists() else b"")
            (EVIDENCE / "joined-live.txt").write_text(live)
            items = (snap.json() or {}).get("items") or []
            finals = [
                item
                for item in items
                if item.get("role") == "assistant" or item.get("type") == "assistant"
            ]
            final_text = json.dumps(finals[-1] if finals else {})
            (EVIDENCE / "final-item.json").write_text(final_text)
            prefix_ok = (not live) or live in final_text or final_text.find(live[:80]) >= 0
            (EVIDENCE / "preview-check.txt").write_text(
                f"elapsed={elapsed:.2f} live_len={len(live)} prefix_ok={prefix_ok}\n"
            )
        glm_ok = (
            glm.status_code == 200
            and "GLM 5.2" in after_glm
            and "GLM 5.2 Max" not in after_glm
        )
        max_ok = glm_max.status_code == 200 and "GLM 5.2 Max" in after_max
        bogus_ok = bogus.status_code >= 400
        (EVIDENCE / "RESULT.txt").write_text(
            f"port={port} conv={conv} glm={glm.status_code} "
            f"max={glm_max.status_code} bogus={bogus.status_code} "
            f"glm_ok={glm_ok} max_ok={max_ok} bogus_ok={bogus_ok}\n"
            f"footer_before={_footer(before)!r}\n"
            f"footer_glm={_footer(after_glm)!r}\n"
            f"footer_max={_footer(after_max)!r}\n"
            f"footer_bogus={_footer(after_bogus)!r}\n"
        )
        return 0 if glm_ok and max_ok and bogus_ok else 1
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
        end_hash = hashlib.sha256(
            (REAL_HOME / ".cursor/cli-config.json").read_bytes()
        ).hexdigest()
        (EVIDENCE / "cli-config.end.sha256").write_text(end_hash + "\n")
        (EVIDENCE / "pids.txt").write_text(
            "started " + ",".join(str(p) for p in started) + "\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())
