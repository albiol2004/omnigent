"""Real fork-compaction e2e on a throwaway server (port >= 17700)."""
from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path("/home/alex/omnigent-fixes")
EV = ROOT / "loop-fork-real/evidence/iter1/e2e"
SOURCE_HEX = "e34847899b7d47b3ad322948d4ea6002"
AGENT_HEX = "58a1bc5bf0bba6d31ceeb7661f8d751c"
PORT = 17701
LIVE_DB = Path.home() / ".omnigent" / "chat.db"
LIVE_CONFIG = Path.home() / ".omnigent" / "config.yaml"
LIVE_ARTIFACTS = Path.home() / ".omnigent" / "artifacts"


def _wait_health(base: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{base}/health", timeout=2.0)
            if resp.status_code == 200:
                return
            last = resp.status_code
        except httpx.HTTPError as exc:
            last = str(exc)
        time.sleep(0.25)
    raise SystemExit(f"health not ready: {last}")


def _start_server(scratch: Path, config_home: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    env["OMNIGENT_CONFIG_HOME"] = str(config_home)
    env["OMNIGENT_FORK_COMPACT"] = "1"
    env.pop("OMNIGENT_FORK_COMPACT_MODEL", None)
    # Do not inherit the live session's process log (it points at ~/.omnigent).
    env.pop("OMNIGENT_PROCESS_LOG_FILE", None)
    env.pop("OMNIGENT_LOG_TTY_FD", None)
    env["OMNIGENT_LOG_TO_STDERR"] = "1"
    db = scratch / "data" / "chat.db"
    artifacts = scratch / "data" / "artifacts"
    log = scratch / "server.log"
    cmd = [
        "/home/alex/omnigent/.venv/bin/python",
        "-m",
        "omnigent",
        "server",
        "--host",
        "127.0.0.1",
        "--port",
        str(PORT),
        "--database-uri",
        f"sqlite:///{db}",
        "--artifact-location",
        str(artifacts),
    ]
    handle = log.open("w")
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    proc._omnigent_log = handle  # type: ignore[attr-defined]
    return proc


def _stop_server(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
    log = getattr(proc, "_omnigent_log", None)
    if log:
        log.close()


def _copy_rows(scratch_db: Path) -> tuple[dict[str, int], list[bytes]]:
    cid = bytes.fromhex(SOURCE_HEX)
    aid = bytes.fromhex(AGENT_HEX)
    live = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    dest = sqlite3.connect(str(scratch_db))
    counts: dict[str, int] = {}
    try:
        live.row_factory = sqlite3.Row
        dest.execute("PRAGMA foreign_keys=OFF")

        def copy(sql: str, params: tuple, table: str, columns: str | None = None) -> int:
            rows = list(live.execute(sql, params))
            if not rows:
                return 0
            if columns is None:
                columns = ",".join(rows[0].keys())
            placeholders = ",".join("?" for _ in rows[0].keys())
            dest.executemany(
                f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
                [tuple(row) for row in rows],
            )
            return len(rows)

        counts["users"] = copy(
            "SELECT * FROM users WHERE id='local'",
            (),
            "users",
        )
        counts["agents"] = copy(
            "SELECT * FROM agents WHERE id=?",
            (aid,),
            "agents",
        )
        counts["conversations"] = copy(
            "SELECT * FROM conversations WHERE id=?",
            (cid,),
            "conversations",
        )
        counts["metadata"] = copy(
            "SELECT * FROM omnigent_conversation_metadata WHERE id=?",
            (cid,),
            "omnigent_conversation_metadata",
        )
        dest.execute(
            "UPDATE omnigent_conversation_metadata "
            "SET runner_id=NULL, host_id=NULL, external_session_id=NULL, "
            "live_status=NULL WHERE id=?",
            (cid,),
        )
        counts["labels"] = copy(
            "SELECT * FROM conversation_labels WHERE conversation_id=?",
            (cid,),
            "conversation_labels",
        )
        counts["items"] = copy(
            "SELECT * FROM conversation_items WHERE conversation_id=?",
            (cid,),
            "conversation_items",
        )
        counts["permissions"] = copy(
            "SELECT * FROM session_permissions WHERE conversation_id=?",
            (cid,),
            "session_permissions",
        )
        counts["files"] = copy(
            "SELECT * FROM files WHERE session_id=?",
            (cid,),
            "files",
        )
        dest.commit()
        file_ids = [
            bytes(row[0])
            for row in live.execute("SELECT id FROM files WHERE session_id=?", (cid,))
        ]
    finally:
        live.close()
        dest.close()
    return counts, file_ids


def _copy_file_blobs(dest_art: Path, file_ids: list[bytes]) -> int:
    copied = 0
    dest_art.mkdir(parents=True, exist_ok=True)
    for fid in file_ids:
        hex_id = fid.hex()
        src = LIVE_ARTIFACTS / hex_id
        if src.is_dir():
            shutil.copytree(src, dest_art / hex_id, dirs_exist_ok=True)
            copied += 1
        elif src.is_file():
            shutil.copy2(src, dest_art / hex_id)
            copied += 1
    return copied


def _strip_keys(src: Path, dest: Path) -> None:
    raw = yaml.safe_load(src.read_text()) or {}
    providers = raw.get("providers") or {}
    if isinstance(providers, dict):
        for name in list(providers):
            body = providers[name]
            if isinstance(body, dict) and body.get("kind") == "key":
                del providers[name]
    dest.write_text(yaml.safe_dump(raw))
    dest.chmod(0o400)


def _copy_agent_artifacts(dest_art: Path) -> None:
    src = LIVE_ARTIFACTS / AGENT_HEX
    if src.is_dir():
        shutil.copytree(src, dest_art / AGENT_HEX, dirs_exist_ok=True)


def _measure(items: list[dict], harness: str, session_id: str) -> int:
    from omnigent.fork_context import estimate_fork_context_bytes
    from omnigent.server.routes.sessions.routes_core import _fork_context_renderer

    renderer = _fork_context_renderer(
        harness,
        session_id=session_id,
        workspace="/tmp/fork-e2e-ws",
        terminal_launch_args=None,
    )
    return estimate_fork_context_bytes(items, renderer=renderer)


def _fake_resume(items: list[dict], session_id: str, out_dir: Path) -> dict:
    from omnigent.server.routes.sessions.routes_core import _fork_context_renderer

    renderer = _fork_context_renderer(
        "claude-native",
        session_id=session_id,
        workspace="/tmp/fork-e2e-ws",
        terminal_launch_args=None,
    )
    lines: list[str] = []
    if renderer is not None:
        rendered = renderer(items)
        if isinstance(rendered, list):
            for row in rendered:
                lines.append(json.dumps(row, ensure_ascii=False))
        elif isinstance(rendered, str):
            lines.append(rendered)
    transcript = out_dir / "fork.jsonl"
    blob = "\n".join(lines) + ("\n" if lines else "")
    transcript.write_bytes(blob.encode("utf-8"))
    argv = ["claude", "--resume", session_id]
    return {
        "argv": argv,
        "transcript_bytes": transcript.stat().st_size,
        "transcript_path": str(transcript),
        "has_resume": "--resume" in argv,
        "under_600k": transcript.stat().st_size < 600_000,
    }


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    scratch = Path("/tmp/fork-compact-real-e2e")
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / "data" / "artifacts").mkdir(parents=True)
    (scratch / "config").mkdir()
    shutil.copy2(LIVE_CONFIG, scratch / "config" / "config.yaml")
    (scratch / "config" / "config.yaml").chmod(0o400)
    _copy_agent_artifacts(scratch / "data" / "artifacts")

    live_mtime_before = LIVE_CONFIG.stat().st_mtime
    live_db_mtime_before = LIVE_DB.stat().st_mtime
    health_before = httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code

    proc = _start_server(scratch, scratch / "config")
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        _stop_server(proc)
        counts, file_ids = _copy_rows(scratch / "data" / "chat.db")
        blob_count = _copy_file_blobs(scratch / "data" / "artifacts", file_ids)
        counts["file_blobs"] = blob_count
        proc = _start_server(scratch, scratch / "config")
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"
        src = httpx.get(f"{base}/v1/sessions/{SOURCE_HEX}/history", timeout=60)
        if src.status_code != 200:
            # some servers use items endpoint
            src = httpx.get(f"{base}/v1/sessions/{SOURCE_HEX}", timeout=60)
        (EV / "source_get.json").write_text(
            json.dumps({"status": src.status_code, "text": src.text[:2000]}, indent=2)
        )
        hist = httpx.get(
            f"{base}/v1/sessions/{SOURCE_HEX}/items",
            params={"limit": 1000},
            timeout=120,
        )
        if hist.status_code != 200:
            hist = httpx.get(
                f"{base}/v1/conversations/{SOURCE_HEX}/items",
                timeout=120,
            )
        items_payload = hist.json() if hist.headers.get("content-type", "").startswith("application/json") else {}
        (EV / "source_items_status.txt").write_text(
            f"{hist.status_code}\n{hist.text[:1500]}\n"
        )
        data = items_payload.get("data") or items_payload.get("items") or []
        bytes_before = _measure(data, "claude-native", SOURCE_HEX) if data else 0

        fork = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-fork-compact-real"},
            timeout=300.0,
        )
        (EV / "fork_response.txt").write_text(f"{fork.status_code}\n{fork.text[:8000]}\n")
        fork_json = fork.json() if fork.headers.get("content-type", "").startswith("application/json") else {}
        fork_id = fork_json.get("id") or fork_json.get("session_id")
        result: dict = {
            "port": PORT,
            "scratch": str(scratch),
            "copy_counts": counts,
            "fork_status": fork.status_code,
            "fork_id": fork_id,
            "bytes_before": bytes_before,
            "source_item_http": hist.status_code,
            "source_item_count": len(data),
        }
        if fork.status_code == 201 and fork_id:
            fitems = httpx.get(f"{base}/v1/sessions/{fork_id}/items", timeout=120)
            if fitems.status_code != 200:
                fitems = httpx.get(
                    f"{base}/v1/conversations/{fork_id}/items",
                    timeout=120,
                )
            fdata = fitems.json().get("data") or fitems.json().get("items") or []
            result["fork_item_count"] = len(fdata)
            result["bytes_after"] = _measure(fdata, "claude-native", fork_id)
            types = [item.get("type") for item in fdata]
            result["has_compaction_item"] = "compaction" in types
            compaction = next((item for item in fdata if item.get("type") == "compaction"), None)
            if compaction:
                cdata = compaction.get("data") or compaction
                result["summary_len"] = len(str(cdata.get("summary") or ""))
                result["resolved_model"] = cdata.get("model")
            result["fake_claude"] = _fake_resume(fdata, fork_id, EV)
        log_text = (scratch / "server.log").read_text(errors="replace")
        result["log_model_line"] = [
            line for line in log_text.splitlines() if "Fork compaction model" in line
        ][-3:]
        result["log_resolution_line"] = [
            line
            for line in log_text.splitlines()
            if "Fork compaction model resolution" in line
        ][-3:]
        (EV / "E2E.json").write_text(json.dumps(result, indent=2) + "\n")
        (EV / "server.log.tail.txt").write_text("\n".join(log_text.splitlines()[-80:]))
        print(json.dumps(result, indent=2))
    finally:
        _stop_server(proc)

    # Failure path: keys stripped.
    nokeys = scratch / "config-nokeys"
    nokeys.mkdir(exist_ok=True)
    _strip_keys(scratch / "config" / "config.yaml", nokeys / "config.yaml")
    proc2 = _start_server(scratch, nokeys)
    fail: dict = {}
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        before_log = (scratch / "server.log").stat().st_size
        resp = httpx.post(
            f"http://127.0.0.1:{PORT}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-fork-nokeys"},
            timeout=60.0,
        )
        log_text = (scratch / "server.log").read_text(errors="replace")
        new_log = log_text[before_log:] if before_log < len(log_text) else log_text
        fail = {
            "status": resp.status_code,
            "body": resp.text[:4000],
            "has_compaction_failed_text": "compaction failed" in resp.text.lower(),
            "in_progress_in_new_log": "compaction.in_progress" in new_log
            or "Summarizing" in new_log,
            "warning_traceback": "Fork compaction failed" in new_log
            or "Traceback" in new_log,
        }
        (EV / "FAIL413.json").write_text(json.dumps(fail, indent=2) + "\n")
        print(json.dumps(fail, indent=2))
    finally:
        _stop_server(proc2)

    audit = {
        "6767_before": health_before,
        "6767_after": httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code,
        "config_mtime_unchanged": LIVE_CONFIG.stat().st_mtime == live_mtime_before,
        "chat_db_mtime_unchanged": LIVE_DB.stat().st_mtime == live_db_mtime_before,
        "throwaway_port": PORT,
    }
    (EV / "ISOLATION.json").write_text(json.dumps(audit, indent=2) + "\n")
    leftover = subprocess.run(
        ["ss", "-ltnp"],
        check=False,
        capture_output=True,
        text=True,
    )
    (EV / "ss.txt").write_text(leftover.stdout)
    if f":{PORT}" in leftover.stdout:
        raise SystemExit(f"port {PORT} still listening")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
