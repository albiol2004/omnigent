"""Real e2e for native fork passthrough + CLI compact (port >= 17900)."""

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
EV = ROOT / "loop-fork-cli/evidence/iter1/real-e2e"
SOURCE_HEX = "e34847899b7d47b3ad322948d4ea6002"
AGENT_HEX = "58a1bc5bf0bba6d31ceeb7661f8d751c"
CODEX_AGENT_HEX = "16a06503889b0c3034496821afd41b9e"
SOURCE_EXT = "f4bd03c9-3c11-46fd-b0df-fdc7952301c2"
LIVE_JSONL = (
    Path.home()
    / ".claude/projects/-home-alex-omnigent"
    / f"{SOURCE_EXT}.jsonl"
)
PORT = 17911
LIVE_DB = Path.home() / ".omnigent" / "chat.db"
LIVE_CONFIG = Path.home() / ".omnigent" / "config.yaml"
LIVE_ARTIFACTS = Path.home() / ".omnigent" / "artifacts"
SCRATCH = Path("/tmp/fork-cli-e2e-iter1")
PY = "/home/alex/omnigent/.venv/bin/python"


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


def _start_server(scratch: Path, env_extra: dict[str, str] | None = None) -> subprocess.Popen[str]:
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


def _copy_table(live: sqlite3.Connection, dest: sqlite3.Connection, sql: str, params: tuple, table: str) -> int:
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


def _copy_rows(scratch_db: Path) -> dict[str, int]:
    cid = bytes.fromhex(SOURCE_HEX)
    live = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
    dest = sqlite3.connect(str(scratch_db))
    counts: dict[str, int] = {}
    try:
        live.row_factory = sqlite3.Row
        dest.execute("PRAGMA foreign_keys=OFF")
        counts["users"] = _copy_table(live, dest, "SELECT * FROM users WHERE id='local'", (), "users")
        for hex_id in (AGENT_HEX, CODEX_AGENT_HEX):
            n = _copy_table(
                live, dest, "SELECT * FROM agents WHERE id=?",
                (bytes.fromhex(hex_id),), "agents",
            )
            counts[f"agents_{hex_id[:8]}"] = n
        counts["conversations"] = _copy_table(
            live, dest, "SELECT * FROM conversations WHERE id=?", (cid,), "conversations",
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
            "SELECT external_session_id FROM omnigent_conversation_metadata WHERE id=?",
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
            live, dest, "SELECT * FROM files WHERE session_id=?", (cid,), "files",
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
    hist = httpx.get(f"{base}/v1/sessions/{session_id}/items", params={"limit": 2000}, timeout=120)
    payload = hist.json() if hist.status_code == 200 else {}
    return payload.get("data") or payload.get("items") or []


def _isolation_before() -> dict:
    projects = Path.home() / ".claude" / "projects"
    return {
        "6767": httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code,
        "config_mtime": LIVE_CONFIG.stat().st_mtime,
        "chat_db_mtime": LIVE_DB.stat().st_mtime,
        "projects_count": sum(1 for _ in projects.rglob("*")) if projects.is_dir() else 0,
    }


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    before = _isolation_before()
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
        "port": PORT, "scratch": str(SCRATCH),
        "source_jsonl_bytes": jsonl_bytes, "isolation_before": before,
    }
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        counts, file_ids = _copy_rows(SCRATCH / "data" / "chat.db")
        result["copy_counts"] = counts
        result["file_blobs"] = _copy_file_blobs(SCRATCH / "data" / "artifacts", file_ids)
        _stop_server(proc)
        proc = _start_server(SCRATCH)
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"

        t0 = time.monotonic()
        fork = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-native-passthrough"},
            timeout=60.0,
        )
        result["a_wall_s"] = round(time.monotonic() - t0, 3)
        result["a_status"] = fork.status_code
        fork_json = fork.json() if fork.status_code == 201 else {}
        fork_id = fork_json.get("id")
        result["a_fork_id"] = fork_id
        (EV / "a_fork.txt").write_text(f"{fork.status_code}\n{fork.text[:4000]}\n")
        if fork.status_code == 201 and fork_id:
            fdata = _items(base, fork_id)
            types = [item.get("type") for item in fdata]
            result["a_has_compaction"] = "compaction" in types
            result["a_item_count"] = len(fdata)
            os.environ["OMNIGENT_CLAUDE_PROJECTS_DIR"] = str(SCRATCH / "claude-projects")
            from omnigent.claude_native import _clone_claude_transcript

            cloned = _clone_claude_transcript(
                source_external_session_id=SOURCE_EXT,
                target_external_session_id="22222222-2222-2222-2222-222222222222",
                clone_workspace=Path("/home/alex/omnigent"),
            )
            result["a_clone_path"] = str(cloned) if cloned else None
            result["a_clone_bytes"] = cloned.stat().st_size if cloned else 0
            result["a_resume"] = ["claude", "--resume", "22222222-2222-2222-2222-222222222222"]

        t1 = time.monotonic()
        fork_b = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-cross-family", "agent_id": CODEX_AGENT_HEX},
            timeout=360.0,
        )
        result["b_wall_s"] = round(time.monotonic() - t1, 3)
        result["b_status"] = fork_b.status_code
        (EV / "b_fork.txt").write_text(f"{fork_b.status_code}\n{fork_b.text[:8000]}\n")
        if fork_b.status_code == 201:
            bid = fork_b.json().get("id")
            bdata = _items(base, bid)
            compaction = next((item for item in bdata if item.get("type") == "compaction"), None)
            result["b_has_compaction"] = compaction is not None
            if compaction:
                cdata = compaction.get("data") or {}
                result["b_model"] = cdata.get("model")
                result["b_summary_len"] = len(str(cdata.get("summary") or ""))
        log_text = (SCRATCH / "server.log").read_text(errors="replace")
        result["b_api_hits"] = [
            line for line in log_text.splitlines()
            if "api.openai.com" in line or "api.anthropic.com" in line
        ]
    finally:
        _stop_server(proc)

    empty_bin = SCRATCH / "empty-bin"
    empty_bin.mkdir(exist_ok=True)
    proc = _start_server(SCRATCH, {"PATH": f"{empty_bin}:{PY.rsplit('/', 2)[0]}/bin:/usr/bin:/bin"})
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"
        fork_c = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "e2e-missing-cli", "agent_id": CODEX_AGENT_HEX},
            timeout=60.0,
        )
        result["c_status"] = fork_c.status_code
        result["c_body"] = fork_c.text[:2000]
        (EV / "c_fork.txt").write_text(f"{fork_c.status_code}\n{fork_c.text[:4000]}\n")
        clog = (SCRATCH / "server.log").read_text(errors="replace")
        result["c_in_progress"] = any("in_progress" in line and "compact" in line.lower() for line in clog.splitlines())
        result["c_names_cli"] = "claude CLI not found" in fork_c.text
    finally:
        _stop_server(proc)

    after = _isolation_before()
    result["isolation_after"] = after
    result["isolation_ok"] = (
        before["6767"] == 200 and after["6767"] == 200
        and before["config_mtime"] == after["config_mtime"]
        and before["chat_db_mtime"] == after["chat_db_mtime"]
        and after["projects_count"] == before["projects_count"]
    )
    (EV / "E2E.json").write_text(json.dumps(result, indent=2) + "\n")
    (EV / "ISOLATION.json").write_text(json.dumps({
        "before": before, "after": after, "ok": result["isolation_ok"],
        "throwaway_port": PORT,
    }, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
