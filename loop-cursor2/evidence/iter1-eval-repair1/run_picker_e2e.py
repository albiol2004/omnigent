#!/usr/bin/env python3
"""Independent picker proof: switch AWAY from the current footer."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path("/home/alex/omnigent-cursor2")
EVIDENCE = REPO / "loop-cursor2/evidence/iter1-eval-repair1"
sys.path[:0] = [str(REPO)]

from omnigent._platform import stable_user_id  # noqa: E402
from tests._helpers.compat import apply_server_env  # noqa: E402
from tests.e2e._native_resume_helpers import (  # noqa: E402
    cli_env,
    omnigent_console_script,
    spawn_cli_background,
    wait_for_terminal_ready,
)


def _port() -> int:
    for candidate in range(18800, 18900):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError("no free port in 18800-18899")


def _bridge_dir(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]
    root = Path(tempfile.gettempdir()) / f"omnigent-{stable_user_id()}" / "cursor-native"
    return root / digest


def _tmux_info(conv: str) -> dict[str, str] | None:
    tmux_path = _bridge_dir(conv) / "tmux.json"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if tmux_path.is_file():
            return json.loads(tmux_path.read_text(encoding="utf-8"))
        time.sleep(0.2)
    return None


def _capture_our_pane(info: dict[str, str]) -> str:
    proc = subprocess.run(
        [
            "tmux",
            "-S",
            info["socket_path"],
            "capture-pane",
            "-p",
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


def _footer_model(pane: str) -> str:
    for line in pane.splitlines():
        stripped = line.strip()
        if "Run Everything" in stripped or "Run" in stripped and "Cursor Grok" in stripped:
            return stripped.split("Run")[0].strip()
        if stripped.startswith("Cursor Grok") or stripped.startswith("GPT-"):
            return stripped.split("  ")[0].strip() if "  " in stripped else stripped
        if "Luna" in stripped or "Composer" in stripped:
            return stripped.split("Run")[0].strip()
    return ""


def _kill_our_tmux(info: dict[str, str] | None) -> None:
    if info is None:
        return
    subprocess.run(
        ["tmux", "-S", info["socket_path"], "kill-server"],
        check=False,
        capture_output=True,
    )


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    port = _port()
    base = f"http://127.0.0.1:{port}"
    root = Path(tempfile.mkdtemp(prefix="omnigent-cursor2-eval-r1-"))
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
    tmux_info: dict[str, str] | None = None
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
            raise RuntimeError(f"no conversation id:\n{cli.output()[-2000:]}")
        (EVIDENCE / "conversation_id.txt").write_text(conv, encoding="utf-8")
        with httpx.Client(base_url=base, timeout=90) as client:
            wait_for_terminal_ready(
                client, conversation_id=conv, harness="cursor", timeout=90
            )
            time.sleep(2)
            tmux_info = _tmux_info(conv)
            if tmux_info is None:
                raise RuntimeError("no tmux.json for throwaway session")
            (EVIDENCE / "tmux.json").write_text(
                json.dumps(tmux_info), encoding="utf-8"
            )
            before = _capture_our_pane(tmux_info)
            (EVIDENCE / "pane-before.txt").write_text(before, encoding="utf-8")
            before_footer = _footer_model(before)
            if "Low" in before_footer and "Medium" not in before_footer:
                chosen = "cursor-grok-4.6-medium"
                expect = "Cursor Grok 4.6 Medium"
                sibling = "Low"
            else:
                chosen = "cursor-grok-4.6-low"
                expect = "Cursor Grok 4.6 Low"
                sibling = "Medium"
            ok = client.patch(
                f"/v1/sessions/{conv}", json={"model_override": chosen}
            )
            (EVIDENCE / "model-change.json").write_text(
                json.dumps(
                    {
                        "status": ok.status_code,
                        "model": chosen,
                        "expect": expect,
                        "before_footer": before_footer,
                        "body": ok.text[:4000],
                    }
                ),
                encoding="utf-8",
            )
            time.sleep(2)
            after = _capture_our_pane(tmux_info)
            (EVIDENCE / "pane-after.txt").write_text(after, encoding="utf-8")
            after_footer = _footer_model(after)
            bogus = client.patch(
                f"/v1/sessions/{conv}",
                json={"model_override": "definitely-not-a-cursor-model-zzz"},
            )
            (EVIDENCE / "bogus-model.json").write_text(
                json.dumps({"status": bogus.status_code, "body": bogus.text[:4000]}),
                encoding="utf-8",
            )
            snap = client.get(f"/v1/sessions/{conv}")
            override = None
            if snap.status_code == 200:
                override = snap.json().get("model_override")
            (EVIDENCE / "session-after-bogus.json").write_text(
                json.dumps(
                    {"status": snap.status_code, "model_override": override}
                ),
                encoding="utf-8",
            )
        sibling_ok = sibling not in after_footer
        exact = expect.lower() in after_footer.lower()
        (EVIDENCE / "RESULT.txt").write_text(
            f"port={port} conv={conv} before={before_footer!r} "
            f"requested={chosen} after={after_footer!r} "
            f"real={ok.status_code} bogus={bogus.status_code} "
            f"override_after_bogus={override!r} exact={exact} "
            f"sibling_rejected={sibling_ok}\n",
            encoding="utf-8",
        )
        return 0 if exact and sibling_ok and ok.status_code == 200 else 2
    finally:
        _kill_our_tmux(tmux_info)
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


if __name__ == "__main__":
    raise SystemExit(main())
