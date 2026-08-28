"""Real e2e for native passthrough + async preparing (port >= 18000)."""

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
EV = ROOT / "loop-fork-async/evidence/iter1/e2e"
SOURCE_HEX = "e34847899b7d47b3ad322948d4ea6002"
AGENT_HEX = "58a1bc5bf0bba6d31ceeb7661f8d751c"
CODEX_AGENT_HEX = "16a06503889b0c3034496821afd41b9e"
SOURCE_EXT = "f4bd03c9-3c11-46fd-b0df-fdc7952301c2"
LIVE_JSONL = Path.home() / ".claude/projects/-home-alex-omnigent" / f"{SOURCE_EXT}.jsonl"
PORT = 18117
LIVE_DB = Path.home() / ".omnigent" / "chat.db"
LIVE_CONFIG = Path.home() / ".omnigent" / "config.yaml"
LIVE_ARTIFACTS = Path.home() / ".omnigent" / "artifacts"
SCRATCH = Path("/tmp/fork-async-e2e-iter1")
PY = "/home/alex/omnigent/.venv/bin/python"
PREPARING = "omnigent.fork.preparing"
PREPARING_REASON = "omnigent.fork.preparing_reason"


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


def _start_server(
    scratch: Path, env_extra: dict[str, str] | None = None
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    env["OMNIGENT_CONFIG_HOME"] = str(scratch / "config")
    env["OMNIGENT_FORK_COMPACT"] = "1"
    env["OMNIGENT_CLAUDE_PROJECTS_DIR"] = str(scratch / "claude-projects")
    env.pop("OMNIGENT_FORK_COMPACT_MODEL", None)
    env.pop("OMNIGENT_FORK_COMPACT_ALLOW_API", None)
    env.pop("OMNIGENT_PROCESS_LOG_FILE", None)
    env.pop("OMNIGENT_LOG_TTY_FD", None)
    env["PATH"] = "/home/alex/.local/bin:" + env.get("PATH", "")
    if env_extra:
        env.update(env_extra)
    db = scratch / "data" / "chat.db"
    artifacts = scratch / "data" / "artifacts"
    log = scratch / "server.log"
    cmd = [
        PY, "-m", "omnigent", "server",
        "--host", "127.0.0.1", "--port", str(PORT),
        "--database-uri", f"sqlite:///{db}",
        "--artifact-location", str(artifacts),
    ]
    handle = log.open("w")
    proc = subprocess.Popen(
        cmd, cwd=str(ROOT), env=env,
        stdout=handle, stderr=subprocess.STDOUT,
        start_new_session=True, text=True,
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


def _copy_table(
    live: sqlite3.Connection,
    dest: sqlite3.Connection,
    sql: str,
    params: tuple,
    table: str,
) -> int:
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


def _copy_rows(scratch_db: Path) -> tuple[dict[str, int], list[bytes]]:
    cid = bytes.fromhex(SOURCE_HEX)
    live = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    dest = sqlite3.connect(str(scratch_db))
    counts: dict[str, int] = {}
    try:
        live.row_factory = sqlite3.Row
        dest.execute("PRAGMA foreign_keys=OFF")
        counts["users"] = _copy_table(
            live, dest, "SELECT * FROM users WHERE id='local'", (), "users"
        )
        for hex_id in (AGENT_HEX, CODEX_AGENT_HEX):
            n = _copy_table(
                live, dest, "SELECT * FROM agents WHERE id=?",
                (bytes.fromhex(hex_id),), "agents",
            )
            counts[f"agents_{hex_id[:8]}"] = n
        counts["conversations"] = _copy_table(
            live, dest, "SELECT * FROM conversations WHERE id=?", (cid,),
            "conversations",
        )
        counts["metadata"] = _copy_table(
            live, dest,
            "SELECT * FROM omnigent_conversation_metadata WHERE id=?",
            (cid,), "omnigent_conversation_metadata",
        )
        dest.execute(
            "UPDATE omnigent_conversation_metadata "
            "SET runner_id=NULL, host_id=NULL, live_status=NULL WHERE id=?",
            (cid,),
        )
        ext = dest.execute(
            "SELECT external_session_id FROM omnigent_conversation_metadata "
            "WHERE id=?",
            (cid,),
        ).fetchone()
        counts["kept_external"] = int(bool(ext and ext[0]))
        counts["labels"] = _copy_table(
            live, dest,
            "SELECT * FROM conversation_labels WHERE conversation_id=?",
            (cid,), "conversation_labels",
        )
        counts["items"] = _copy_table(
            live, dest,
            "SELECT * FROM conversation_items WHERE conversation_id=?",
            (cid,), "conversation_items",
        )
        counts["permissions"] = _copy_table(
            live, dest,
            "SELECT * FROM session_permissions WHERE conversation_id=?",
            (cid,), "session_permissions",
        )
        counts["files"] = _copy_table(
            live, dest, "SELECT * FROM files WHERE session_id=?", (cid,),
            "files",
        )
        dest.commit()
        file_ids = [
            bytes(row[0])
            for row in live.execute(
                "SELECT id FROM files WHERE session_id=?", (cid,)
            )
        ]
    finally:
        live.close()
        dest.close()
    return counts, file_ids


def _copy_file_blobs(dest_art: Path, file_ids: list[bytes]) -> int:
    copied = 0
    dest_art.mkdir(parents=True, exist_ok=True)
    wanted = {fid.hex() for fid in file_ids}
    wanted.add("0d1a58e3abff412a9b5b87442879335d")
    for hex_id in wanted:
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
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(raw))
    dest.chmod(0o400)


def _copy_agent_artifacts(dest_art: Path) -> None:
    dest_art.mkdir(parents=True, exist_ok=True)
    for hex_id in (AGENT_HEX, CODEX_AGENT_HEX):
        src = LIVE_ARTIFACTS / hex_id
        if src.is_dir():
            shutil.copytree(src, dest_art / hex_id, dirs_exist_ok=True)


def _items(base: str, session_id: str) -> list[dict]:
    rows: list[dict] = []
    after: str | None = None
    for _ in range(20):
        params: dict[str, str | int] = {"limit": 1000, "order": "asc"}
        if after:
            params["after"] = after
        hist = httpx.get(
            f"{base}/v1/sessions/{session_id}/items",
            params=params,
            timeout=120,
        )
        payload = hist.json() if hist.status_code == 200 else {}
        chunk = payload.get("data") or payload.get("items") or []
        rows.extend(chunk)
        if not chunk or len(chunk) < 1000:
            break
        after = chunk[-1].get("id")
        if not after:
            break
    return rows


def _sqlite_last_response_id(db: Path, session_hex: str) -> str | None:
    cid = bytes.fromhex(session_hex)
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT response_id FROM conversation_items "
            "WHERE conversation_id=? AND response_id IS NOT NULL "
            "AND response_id != '' ORDER BY position DESC LIMIT 1",
            (cid,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _sqlite_item_stats(db: Path, session_hex: str) -> dict:
    cid = bytes.fromhex(session_hex)
    conn = sqlite3.connect(str(db))
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM conversation_items WHERE conversation_id=?",
            (cid,),
        ).fetchone()[0]
        types = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT type FROM conversation_items "
                "WHERE conversation_id=?",
                (cid,),
            )
        ]
        return {"count": n, "types": types}
    finally:
        conn.close()


def _session(base: str, session_id: str) -> dict:
    resp = httpx.get(f"{base}/v1/sessions/{session_id}", timeout=30)
    return resp.json() if resp.status_code == 200 else {
        "status_code": resp.status_code, "text": resp.text[:500],
    }


def _last_response_id(items: list[dict]) -> str | None:
    for item in reversed(items):
        rid = item.get("response_id")
        if isinstance(rid, str) and rid:
            return rid
    return None


def _wait_preparing(
    base: str, session_id: str, timeout: float
) -> tuple[float, dict]:
    started = time.monotonic()
    last: dict = {}
    while time.monotonic() - started < timeout:
        last = _session(base, session_id)
        labels = last.get("labels") or {}
        if labels.get(PREPARING) != "1":
            return round(time.monotonic() - started, 3), last
        time.sleep(0.5)
    return round(time.monotonic() - started, 3), last


def _isolation_snapshot() -> dict:
    projects = Path.home() / ".claude" / "projects"
    return {
        "6767": httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code,
        "config_mtime": LIVE_CONFIG.stat().st_mtime,
        "chat_db_mtime": LIVE_DB.stat().st_mtime,
        "projects_count": (
            sum(1 for _ in projects.rglob("*")) if projects.is_dir() else 0
        ),
    }


def _record_fork(path: Path, response: httpx.Response) -> None:
    path.write_text(f"{response.status_code}\n{response.text[:8000]}\n")


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    before = _isolation_snapshot()
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / "data" / "artifacts").mkdir(parents=True)
    _strip_keys(LIVE_CONFIG, SCRATCH / "config" / "config.yaml")
    _copy_agent_artifacts(SCRATCH / "data" / "artifacts")
    proj = SCRATCH / "claude-projects" / "-home-alex-omnigent"
    proj.mkdir(parents=True)
    shutil.copy2(LIVE_JSONL, proj / f"{SOURCE_EXT}.jsonl")
    jsonl_bytes = (proj / f"{SOURCE_EXT}.jsonl").stat().st_size

    proc = _start_server(SCRATCH)
    result: dict = {
        "port": PORT,
        "scratch": str(SCRATCH),
        "source_jsonl_bytes": jsonl_bytes,
        "isolation_before": before,
        "lead_model": "cursor-grok-4.6",
    }
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        counts, file_ids = _copy_rows(SCRATCH / "data" / "chat.db")
        result["copy_counts"] = counts
        result["file_blobs"] = _copy_file_blobs(
            SCRATCH / "data" / "artifacts", file_ids
        )
        _stop_server(proc)
        proc = _start_server(SCRATCH)
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"
        db = SCRATCH / "data" / "chat.db"
        last_rid = _sqlite_last_response_id(db, SOURCE_HEX)
        source_stats = _sqlite_item_stats(db, SOURCE_HEX)
        result["source_item_count"] = source_stats["count"]
        result["last_response_id"] = last_rid
        if not last_rid:
            raise SystemExit("source has no response_id for the web-UI a2 case")

        t0 = time.monotonic()
        fork_a = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-native-passthrough"},
            timeout=10.0,
        )
        result["a_wall_s"] = round(time.monotonic() - t0, 3)
        result["a_status"] = fork_a.status_code
        a_json = fork_a.json() if fork_a.status_code == 201 else {}
        a_id = a_json.get("id")
        result["a_fork_id"] = a_id
        result["a_labels"] = a_json.get("labels") or {}
        _record_fork(EV / "a_fork.txt", fork_a)
        if fork_a.status_code == 201 and a_id:
            a_stats = _sqlite_item_stats(db, a_id)
            result["a_has_compaction"] = any(
                "compaction" in str(t).lower() for t in a_stats["types"]
            )
            result["a_item_count"] = a_stats["count"]
            os.environ["OMNIGENT_CLAUDE_PROJECTS_DIR"] = str(
                SCRATCH / "claude-projects"
            )
            from omnigent.claude_native import _clone_claude_transcript

            cloned = _clone_claude_transcript(
                source_external_session_id=SOURCE_EXT,
                target_external_session_id="22222222-2222-2222-2222-222222222222",
                clone_workspace=Path("/tmp/fork-async-e2e-iter1/ws"),
            )
            result["a_clone_path"] = str(cloned) if cloned else None
            result["a_clone_bytes"] = cloned.stat().st_size if cloned else 0
            result["a_resume"] = [
                "claude", "--resume", "22222222-2222-2222-2222-222222222222",
            ]

        t_a2 = time.monotonic()
        fork_a2 = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={
                "title": "e2e-web-ui-last-response",
                "up_to_response_id": last_rid,
            },
            timeout=10.0,
        )
        result["a2_wall_s"] = round(time.monotonic() - t_a2, 3)
        result["a2_status"] = fork_a2.status_code
        a2_json = fork_a2.json() if fork_a2.status_code == 201 else {}
        result["a2_fork_id"] = a2_json.get("id")
        result["a2_labels"] = a2_json.get("labels") or {}
        result["a2_preparing"] = (a2_json.get("labels") or {}).get(PREPARING)
        _record_fork(EV / "a2_fork.txt", fork_a2)
        if fork_a2.status_code == 201 and result["a2_fork_id"]:
            result["a2_item_count"] = _sqlite_item_stats(
                db, result["a2_fork_id"]
            )["count"]
        log_after_a2 = (SCRATCH / "server.log").read_text(errors="replace")
        result["a2_skip_log"] = [
            line for line in log_after_a2.splitlines()
            if "fork passthrough skipped" in line
        ][-3:]

        t1 = time.monotonic()
        fork_b = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-cross-family", "agent_id": CODEX_AGENT_HEX},
            timeout=10.0,
        )
        result["b_wall_s"] = round(time.monotonic() - t1, 3)
        result["b_status"] = fork_b.status_code
        b_json = fork_b.json() if fork_b.status_code == 201 else {}
        b_id = b_json.get("id")
        result["b_fork_id"] = b_id
        result["b_labels_on_201"] = b_json.get("labels") or {}
        _record_fork(EV / "b_fork.txt", fork_b)
        if fork_b.status_code == 201 and b_id:
            bg_s, b_done = _wait_preparing(base, b_id, timeout=240.0)
            result["b_bg_s"] = bg_s
            result["b_labels_done"] = b_done.get("labels") or {}
            bdata = _items(base, b_id)
            from omnigent.fork_context import estimate_fork_context_bytes

            b_stats = _sqlite_item_stats(db, b_id)
            result["b_item_count"] = b_stats["count"]
            result["b_http_item_count"] = len(bdata)
            result["b_rendered_bytes"] = estimate_fork_context_bytes(bdata)
            result["b_has_compaction"] = any(
                item.get("type") == "compaction" for item in bdata
            ) or any("compaction" in str(t).lower() for t in b_stats["types"])
        log_text = (SCRATCH / "server.log").read_text(errors="replace")
        result["b_api_hits"] = [
            line for line in log_text.splitlines()
            if "api.openai.com" in line or "api.anthropic.com" in line
        ]
    finally:
        _stop_server(proc)

    empty_bin = SCRATCH / "empty-bin"
    empty_bin.mkdir(exist_ok=True)
    proc = _start_server(
        SCRATCH,
        {"PATH": f"{empty_bin}:{PY.rsplit('/', 2)[0]}/bin:/usr/bin:/bin"},
    )
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"
        t2 = time.monotonic()
        fork_c = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-missing-cli", "agent_id": CODEX_AGENT_HEX},
            timeout=10.0,
        )
        result["c_wall_s"] = round(time.monotonic() - t2, 3)
        result["c_status"] = fork_c.status_code
        c_json = fork_c.json() if fork_c.status_code == 201 else {}
        c_id = c_json.get("id")
        result["c_fork_id"] = c_id
        result["c_labels_on_201"] = c_json.get("labels") or {}
        _record_fork(EV / "c_fork.txt", fork_c)
        if fork_c.status_code == 201 and c_id:
            cg_s, c_done = _wait_preparing(base, c_id, timeout=60.0)
            result["c_bg_s"] = cg_s
            result["c_labels_done"] = c_done.get("labels") or {}
            deleted = httpx.delete(f"{base}/v1/sessions/{c_id}", timeout=30)
            result["c_delete_status"] = deleted.status_code
    finally:
        _stop_server(proc)

    after = _isolation_snapshot()
    result["isolation_after"] = after
    result["isolation_ok"] = (
        before["6767"] == 200
        and after["6767"] == 200
        and before["config_mtime"] == after["config_mtime"]
        and before["chat_db_mtime"] == after["chat_db_mtime"]
        and after["projects_count"] == before["projects_count"]
    )
    (EV / "E2E.json").write_text(json.dumps(result, indent=2) + "\n")
    (EV / "ISOLATION.json").write_text(
        json.dumps(
            {
                "before": before,
                "after": after,
                "ok": result["isolation_ok"],
                "throwaway_port": PORT,
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
