"""Throwaway e2e for native passthrough + CLI rebuild compaction."""
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
EV = ROOT / "loop-fork-cli/evidence/iter1/e2e"
SOURCE_HEX = "e34847899b7d47b3ad322948d4ea6002"
AGENT_HEX = "58a1bc5bf0bba6d31ceeb7661f8d751c"
EXT_ID = "f4bd03c9-3c11-46fd-b0df-fdc7952301c2"
PORT = 17901
LIVE_DB = Path.home() / ".omnigent" / "chat.db"
LIVE_CONFIG = Path.home() / ".omnigent" / "config.yaml"
LIVE_ARTIFACTS = Path.home() / ".omnigent" / "artifacts"
LIVE_JSONL = (
    Path.home()
    / ".claude/projects/-home-alex-omnigent"
    / f"{EXT_ID}.jsonl"
)
PY = str(ROOT / ".venv/bin/python")


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


def _server_env(scratch: Path, config_home: Path, *, path: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    default_path = env.get("PATH", "")
    if "/home/alex/.local/bin" not in default_path:
        default_path = "/home/alex/.local/bin:" + default_path
    env["PATH"] = path or default_path
    env["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    env["OMNIGENT_CONFIG_HOME"] = str(config_home)
    env["OMNIGENT_FORK_COMPACT"] = "1"
    env["OMNIGENT_CLAUDE_PROJECTS_DIR"] = str(scratch / "claude-projects")
    env.pop("OMNIGENT_FORK_COMPACT_MODEL", None)
    env.pop("OMNIGENT_FORK_COMPACT_ALLOW_API", None)
    env.pop("OMNIGENT_FORK_NATIVE_GUARD", None)
    env.pop("OMNIGENT_PROCESS_LOG_FILE", None)
    env.pop("OMNIGENT_LOG_TTY_FD", None)
    env["OMNIGENT_LOG_TO_STDERR"] = "1"
    for key in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(key, None)
    return env


def _start_server(
    scratch: Path, config_home: Path, *, path: str | None = None
) -> subprocess.Popen[str]:
    env = _server_env(scratch, config_home, path=path)
    db = scratch / "data" / "chat.db"
    artifacts = scratch / "data" / "artifacts"
    log = scratch / "server.log"
    cmd = [
        PY,
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
    handle = log.open("a")
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

        def copy(sql: str, params: tuple, table: str) -> int:
            rows = list(live.execute(sql, params))
            if not rows:
                return 0
            columns = ",".join(rows[0].keys())
            placeholders = ",".join("?" for _ in rows[0].keys())
            dest.executemany(
                f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})",
                [tuple(row) for row in rows],
            )
            return len(rows)

        counts["users"] = copy("SELECT * FROM users WHERE id='local'", (), "users")
        counts["agents"] = copy("SELECT * FROM agents WHERE id=?", (aid,), "agents")
        counts["conversations"] = copy(
            "SELECT * FROM conversations WHERE id=?", (cid,), "conversations"
        )
        counts["metadata"] = copy(
            "SELECT * FROM omnigent_conversation_metadata WHERE id=?",
            (cid,),
            "omnigent_conversation_metadata",
        )
        dest.execute(
            "UPDATE omnigent_conversation_metadata "
            "SET runner_id=NULL, host_id=NULL, live_status=NULL WHERE id=?",
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
            "SELECT * FROM files WHERE session_id=?", (cid,), "files"
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


def _measure(items: list[dict], session_id: str) -> int:
    from omnigent.fork_context import estimate_fork_context_bytes
    from omnigent.server.routes.sessions.routes_core import (
        _fork_context_renderer,
    )

    renderer = _fork_context_renderer(
        "claude-native",
        session_id=session_id,
        workspace="/tmp/fork-cli-e2e-ws",
        terminal_launch_args=None,
    )
    return estimate_fork_context_bytes(items, renderer=renderer)


def _source_digest(db: Path) -> str:
    cid = bytes.fromhex(SOURCE_HEX)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = list(
        con.execute(
            "SELECT id, type, data FROM conversation_items "
            "WHERE conversation_id=? ORDER BY created_at, id",
            (cid,),
        )
    )
    con.close()
    def _blob(value: object) -> bytes:
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        return str(value).encode()

    blob = b"|".join(_blob(r[0]) + _blob(r[1]) + _blob(r[2]) for r in rows)
    import hashlib

    return f"{len(rows)}:{hashlib.sha256(blob).hexdigest()}"


def _items(base: str, session_id: str) -> tuple[int, list]:
    hist = httpx.get(
        f"{base}/v1/sessions/{session_id}/items",
        params={"limit": 1000},
        timeout=120,
    )
    payload = hist.json() if hist.status_code == 200 else {}
    data = payload.get("data") or payload.get("items") or []
    return hist.status_code, data


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    scratch = Path("/tmp/fork-compact-cli-e2e")
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / "data" / "artifacts").mkdir(parents=True)
    (scratch / "config").mkdir()
    proj = scratch / "claude-projects" / "-home-alex-omnigent"
    proj.mkdir(parents=True)
    shutil.copy2(LIVE_JSONL, proj / f"{EXT_ID}.jsonl")
    (proj / f"{EXT_ID}.jsonl").chmod(0o400)
    _strip_keys(LIVE_CONFIG, scratch / "config" / "config.yaml")
    src_agent = LIVE_ARTIFACTS / AGENT_HEX
    if src_agent.is_dir():
        shutil.copytree(src_agent, scratch / "data" / "artifacts" / AGENT_HEX)

    live_cfg_mtime = LIVE_CONFIG.stat().st_mtime
    live_db_mtime = LIVE_DB.stat().st_mtime
    health_before = httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code

    proc = _start_server(scratch, scratch / "config")
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        _stop_server(proc)
        counts, file_ids = _copy_rows(scratch / "data" / "chat.db")
        counts["file_blobs"] = _copy_file_blobs(
            scratch / "data" / "artifacts", file_ids
        )
        digest_before = _source_digest(scratch / "data" / "chat.db")
        proc = _start_server(scratch, scratch / "config")
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"
        _, src_items = _items(base, SOURCE_HEX)
        bytes_before = _measure(src_items, SOURCE_HEX) if src_items else 0
        t0 = time.time()
        fork = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-native-passthrough"},
            timeout=60.0,
        )
        native_ms = int((time.time() - t0) * 1000)
        (EV / "native_fork.txt").write_text(f"{fork.status_code}\n{fork.text[:4000]}\n")
        fork_json = fork.json() if fork.status_code == 201 else {}
        fork_id = fork_json.get("id")
        _, fdata = _items(base, fork_id) if fork_id else (0, [])
        native = {
            "port": PORT,
            "fork_status": fork.status_code,
            "fork_id": fork_id,
            "wall_ms": native_ms,
            "bytes_before": bytes_before,
            "source_item_count": len(src_items),
            "fork_item_count": len(fdata),
            "has_compaction": any(i.get("type") == "compaction" for i in fdata),
            "copy_counts": counts,
            "source_jsonl_bytes": LIVE_JSONL.stat().st_size,
        }
        if fork_id:
            os.environ["OMNIGENT_CLAUDE_PROJECTS_DIR"] = str(
                scratch / "claude-projects"
            )
            from omnigent.claude_native import _clone_claude_transcript

            cloned = _clone_claude_transcript(
                source_external_session_id=EXT_ID,
                target_external_session_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                clone_workspace=scratch / "clone-ws",
            )
            native["clone_path"] = str(cloned)
            native["clone_bytes"] = cloned.stat().st_size if cloned else None
            native["resume_argv"] = [
                "claude",
                "--resume",
                "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            ]
        (EV / "NATIVE.json").write_text(json.dumps(native, indent=2) + "\n")
        print(json.dumps(native, indent=2))
    finally:
        _stop_server(proc)

    cid = bytes.fromhex(SOURCE_HEX)
    dest = sqlite3.connect(str(scratch / "data" / "chat.db"))
    dest.execute(
        "UPDATE omnigent_conversation_metadata SET external_session_id=NULL WHERE id=?",
        (cid,),
    )
    dest.commit()
    dest.close()

    slim_path = "/usr/bin:/bin"
    proc = _start_server(scratch, scratch / "config", path=slim_path)
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        before = (scratch / "server.log").stat().st_size
        resp = httpx.post(
            f"http://127.0.0.1:{PORT}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-missing-cli"},
            timeout=60.0,
        )
        log = (scratch / "server.log").read_text(errors="replace")
        new_log = log[before:]
        fail = {
            "status": resp.status_code,
            "body": resp.text[:4000],
            "names_cli": "claude CLI not found" in resp.text,
            "in_progress": "compaction.in_progress" in new_log
            or "Summarizing" in new_log,
        }
        (EV / "FAIL413.json").write_text(json.dumps(fail, indent=2) + "\n")
        (EV / "nokeys.file.log").write_text(new_log[-8000:])
        print(json.dumps(fail, indent=2))
    finally:
        _stop_server(proc)

    proc = _start_server(scratch, scratch / "config")
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        t0 = time.time()
        fork = httpx.post(
            f"http://127.0.0.1:{PORT}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-cli-summary"},
            timeout=360.0,
        )
        wall_ms = int((time.time() - t0) * 1000)
        (EV / "rebuild_fork.txt").write_text(f"{fork.status_code}\n{fork.text[:8000]}\n")
        fork_json = fork.json() if fork.headers.get("content-type", "").startswith("application/json") else {}
        fork_id = fork_json.get("id")
        _, fdata = _items(f"http://127.0.0.1:{PORT}", fork_id) if fork_id else (0, [])
        compaction = None
        for item in fdata:
            payload = item.get("data") if isinstance(item.get("data"), dict) else item
            if item.get("type") in ("compaction", 6) or (
                isinstance(payload, dict) and payload.get("summary") and "last_item_id" in payload
            ):
                compaction = payload
                break
        cdata = compaction or {}
        rebuild = {
            "fork_status": fork.status_code,
            "fork_id": fork_id,
            "wall_ms": wall_ms,
            "fork_item_count": len(fdata),
            "bytes_after": _measure(fdata, fork_id) if fdata and fork_id else None,
            "summary_len": len(str(cdata.get("summary") or "")),
            "resolved_model": cdata.get("model"),
            "has_compaction": compaction is not None,
        }
        log = (scratch / "server.log").read_text(errors="replace")
        (EV / "success.file.log").write_text("\n".join(log.splitlines()[-120:]))
        (EV / "REBUILD.json").write_text(json.dumps(rebuild, indent=2) + "\n")
        print(json.dumps(rebuild, indent=2))
    finally:
        _stop_server(proc)

    digest_after = _source_digest(scratch / "data" / "chat.db")
    audit = {
        "6767_before": health_before,
        "6767_after": httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code,
        "config_mtime_unchanged": LIVE_CONFIG.stat().st_mtime == live_cfg_mtime,
        "chat_db_mtime_unchanged": LIVE_DB.stat().st_mtime == live_db_mtime,
        "source_digest_before": digest_before,
        "source_digest_after": digest_after,
        "source_rows_byte_identical": digest_before == digest_after,
        "jsonl_mtime_unchanged": LIVE_JSONL.stat().st_mtime,
    }
    (EV / "ISOLATION.json").write_text(json.dumps(audit, indent=2) + "\n")
    ss = subprocess.run(["ss", "-ltnp"], check=False, capture_output=True, text=True)
    (EV / "ss.txt").write_text(ss.stdout)
    if f":{PORT}" in ss.stdout:
        raise SystemExit(f"port {PORT} still listening")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
