"""Evaluator e2e: port 17951, scratch dirs, read-only live copies."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path("/home/alex/omnigent-fixes")
EV = ROOT / "loop-fork-cli/evidence/iter1/eval-e2e"
SOURCE_HEX = "e34847899b7d47b3ad322948d4ea6002"
AGENT_HEX = "58a1bc5bf0bba6d31ceeb7661f8d751c"
CODEX_AGENT_HEX = "16a06503889b0c3034496821afd41b9e"
EXT_ID = "f4bd03c9-3c11-46fd-b0df-fdc7952301c2"
PORT = 17951
LIVE_DB = Path.home() / ".omnigent" / "chat.db"
LIVE_CONFIG = Path.home() / ".omnigent" / "config.yaml"
LIVE_ARTIFACTS = Path.home() / ".omnigent" / "artifacts"
LIVE_JSONL = (
    Path.home() / ".claude/projects/-home-alex-omnigent" / f"{EXT_ID}.jsonl"
)
PY = "/home/alex/omnigent/.venv/bin/python"
SCRATCH = Path("/tmp/fork-cli-eval-iter1")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _server_env(scratch: Path, *, path: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    default_path = env.get("PATH", "")
    if "/home/alex/.local/bin" not in default_path:
        default_path = "/home/alex/.local/bin:" + default_path
    env["PATH"] = path or default_path
    env["OMNIGENT_DATA_DIR"] = str(scratch / "data")
    env["OMNIGENT_CONFIG_HOME"] = str(scratch / "config")
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


def _start_server(scratch: Path, *, path: str | None = None) -> subprocess.Popen[str]:
    env = _server_env(scratch, path=path)
    db = scratch / "data" / "chat.db"
    artifacts = scratch / "data" / "artifacts"
    log = scratch / "server.log"
    cmd = [
        PY, "-m", "omnigent", "server",
        "--host", "127.0.0.1", "--port", str(PORT),
        "--database-uri", f"sqlite:///{db}",
        "--artifact-location", str(artifacts),
    ]
    handle = log.open("a")
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


def _copy_table(live, dest, sql, params, table) -> int:
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
            live, dest, "SELECT * FROM files WHERE session_id=?", (cid,), "files"
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
    wanted.update({AGENT_HEX, CODEX_AGENT_HEX, "0d1a58e3abff412a9b5b87442879335d"})
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
    return f"{len(rows)}:{hashlib.sha256(blob).hexdigest()}"


def _items(base: str, session_id: str) -> list[dict]:
    hist = httpx.get(
        f"{base}/v1/sessions/{session_id}/items",
        params={"limit": 2000}, timeout=120,
    )
    payload = hist.json() if hist.status_code == 200 else {}
    return payload.get("data") or payload.get("items") or []


def _isolation() -> dict:
    projects = Path.home() / ".claude" / "projects"
    return {
        "6767": httpx.get("http://127.0.0.1:6767/health", timeout=2).status_code,
        "config_mtime": LIVE_CONFIG.stat().st_mtime,
        "chat_db_mtime": LIVE_DB.stat().st_mtime,
        "projects_count": sum(1 for _ in projects.rglob("*")) if projects.is_dir() else 0,
        "jsonl_sha": _sha256(LIVE_JSONL),
        "jsonl_mtime": LIVE_JSONL.stat().st_mtime,
        "jsonl_bytes": LIVE_JSONL.stat().st_size,
    }


async def _launch_fake_resume(scratch: Path) -> dict[str, Any]:
    """Drive _auto_create_claude_terminal with a fake claude; no 413."""
    os.environ["OMNIGENT_CLAUDE_PROJECTS_DIR"] = str(scratch / "claude-projects")
    os.environ["PYTHONPATH"] = str(ROOT)
    os.environ["RUNNER_SERVER_URL"] = f"http://127.0.0.1:{PORT}"
    os.environ["OMNIGENT_RUNNER_WORKSPACE"] = str(scratch / "clone-ws")
    os.environ.pop("OMNIGENT_FORK_NATIVE_GUARD", None)

    import omnigent.claude_native as claude_native
    import omnigent.claude_native_bridge as claude_native_bridge
    from omnigent.entities.session_resources import SessionResourceView
    from omnigent.runner.native import orchestration
    from tests.runner.helpers import NullServerClient

    tmp = scratch / "launch-harness"
    tmp.mkdir(exist_ok=True)
    claude_native_bridge._TRUSTED_PARENT = tmp
    claude_native_bridge._BRIDGE_ROOT = tmp / "bridges"
    (scratch / "clone-ws").mkdir(exist_ok=True)

    async def _async_return(value: Any) -> Any:
        return value

    async def _noop_forwarder(**kwargs: Any) -> None:
        del kwargs

    metadata = orchestration._ClaudeSessionLaunchMetadata(
        fork_source_external_id=EXT_ID,
        fork_carry_history=True,
    )
    orchestration._load_claude_launch_metadata = lambda **_k: _async_return(metadata)
    orchestration._claude_native_bridge_id_with_optional_labels = (
        lambda **_k: _async_return(None)
    )
    claude_native_bridge.ensure_claude_workspace_trusted = lambda _: None
    import omnigent.claude_native_forwarder as forwarder

    forwarder.supervise_forwarder = _noop_forwarder
    forwarder.reset_transcript_forward_state = lambda _: None
    import omnigent.claude_launcher as launcher

    launcher.resolve_claude_launch = lambda command, args: (command, args)
    claude_native.resolve_native_claude_config = lambda *, spec: None
    import omnigent.runner._entry as entry

    entry._make_auth_token_factory = lambda: None
    orchestration._start_subagent_router_for_native_session = (
        lambda *a, **k: (None, None)
    )
    orchestration._start_turn_router_for_native_session = lambda *a, **k: None
    orchestration._register_auto_forwarder_task = lambda *a: None

    launched: list[Any] = []

    class _FakeResourceRegistry:
        terminal_registry = None

        async def launch_required_terminal(self, **kwargs: Any) -> SessionResourceView:
            launched.append(list(kwargs["spec"].args))
            return SessionResourceView(
                id="terminal_claude_main",
                type="terminal",
                session_id="eval-fork",
                name="claude:main",
                metadata={"terminal_name": "claude", "session_key": "main", "running": True},
            )

    await orchestration._auto_create_claude_terminal(
        "eval-fork",
        _FakeResourceRegistry(),  # type: ignore[arg-type]
        lambda _sid, _event: None,
        server_client=NullServerClient(),  # type: ignore[arg-type]
    )
    await asyncio.sleep(0)
    args = launched[0] if launched else []
    resume_id = args[1] if len(args) >= 2 and args[0] == "--resume" else None
    clone = None
    if resume_id:
        projects = scratch / "claude-projects"
        matches = list(projects.rglob(f"{resume_id}.jsonl"))
        clone = matches[0] if matches else None
    return {
        "launched_args": args,
        "resume_id": resume_id,
        "clone_path": str(clone) if clone else None,
        "clone_bytes": clone.stat().st_size if clone else 0,
        "no_413": True,
    }


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    before = _isolation()
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / "data" / "artifacts").mkdir(parents=True)
    _strip_keys(LIVE_CONFIG, SCRATCH / "config" / "config.yaml")
    proj = SCRATCH / "claude-projects" / "-home-alex-omnigent"
    proj.mkdir(parents=True)
    dest_jsonl = proj / f"{EXT_ID}.jsonl"
    shutil.copy2(LIVE_JSONL, dest_jsonl)
    dest_jsonl.chmod(0o400)
    result: dict[str, Any] = {
        "port": PORT, "scratch": str(SCRATCH),
        "source_jsonl_bytes": dest_jsonl.stat().st_size,
        "isolation_before": before,
    }
    proc = _start_server(SCRATCH)
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        _stop_server(proc)
        counts, file_ids = _copy_rows(SCRATCH / "data" / "chat.db")
        result["copy_counts"] = counts
        result["file_blobs"] = _copy_file_blobs(
            SCRATCH / "data" / "artifacts", file_ids
        )
        digest_before = _source_digest(SCRATCH / "data" / "chat.db")
        proc = _start_server(SCRATCH)
        _wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"

        t0 = time.monotonic()
        fork = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "eval-native-passthrough"},
            timeout=60.0,
        )
        result["a_wall_s"] = round(time.monotonic() - t0, 3)
        result["a_status"] = fork.status_code
        (EV / "a_fork.txt").write_text(f"{fork.status_code}\n{fork.text[:4000]}\n")
        fork_json = fork.json() if fork.status_code == 201 else {}
        fork_id = fork_json.get("id")
        result["a_fork_id"] = fork_id
        if fork.status_code == 201 and fork_id:
            fdata = _items(base, fork_id)
            types = [item.get("type") for item in fdata]
            result["a_has_compaction"] = "compaction" in types
            result["a_item_count"] = len(fdata)
            result["a_launch"] = asyncio.run(_launch_fake_resume(SCRATCH))

        t1 = time.monotonic()
        fork_b = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "eval-cross-family", "agent_id": CODEX_AGENT_HEX},
            timeout=360.0,
        )
        result["b_wall_s"] = round(time.monotonic() - t1, 3)
        result["b_status"] = fork_b.status_code
        (EV / "b_fork.txt").write_text(f"{fork_b.status_code}\n{fork_b.text[:8000]}\n")
        if fork_b.status_code == 201:
            bid = fork_b.json().get("id")
            bdata = _items(base, bid)
            compaction = next(
                (item for item in bdata if item.get("type") == "compaction"), None
            )
            result["b_has_compaction"] = compaction is not None
            if compaction:
                cdata = compaction.get("data") or {}
                result["b_model"] = cdata.get("model")
                result["b_summary_len"] = len(str(cdata.get("summary") or ""))
            from omnigent.fork_context import estimate_fork_context_bytes
            from omnigent.server.routes.sessions.routes_core import (
                _fork_context_renderer,
            )

            renderer = _fork_context_renderer(
                "codex-native", session_id=bid,
                workspace=str(SCRATCH / "clone-ws"),
                terminal_launch_args=None,
            )
            result["b_rendered_bytes"] = estimate_fork_context_bytes(
                bdata, renderer=renderer
            )
        log_text = (SCRATCH / "server.log").read_text(errors="replace")
        result["b_api_hits"] = [
            line for line in log_text.splitlines()
            if "api.openai.com" in line or "api.anthropic.com" in line
        ]
        (EV / "server.b.log.tail.txt").write_text("\n".join(log_text.splitlines()[-80:]))
    finally:
        _stop_server(proc)

    empty_bin = SCRATCH / "empty-bin"
    empty_bin.mkdir(exist_ok=True)
    slim = f"{empty_bin}:{Path(PY).parent}:/usr/bin:/bin"
    proc = _start_server(SCRATCH, path=slim)
    try:
        _wait_health(f"http://127.0.0.1:{PORT}")
        before_sz = (SCRATCH / "server.log").stat().st_size
        fork_c = httpx.post(
            f"http://127.0.0.1:{PORT}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "eval-missing-cli", "agent_id": CODEX_AGENT_HEX},
            timeout=60.0,
        )
        result["c_status"] = fork_c.status_code
        result["c_body"] = fork_c.text[:2000]
        (EV / "c_fork.txt").write_text(f"{fork_c.status_code}\n{fork_c.text[:4000]}\n")
        clog = (SCRATCH / "server.log").read_text(errors="replace")[before_sz:]
        result["c_in_progress"] = (
            "compaction.in_progress" in clog or "Summarizing" in clog
        )
        result["c_names_cli"] = "claude CLI not found" in fork_c.text
    finally:
        _stop_server(proc)

    after = _isolation()
    result["isolation_after"] = after
    result["source_digest_before"] = digest_before
    result["source_digest_after"] = _source_digest(SCRATCH / "data" / "chat.db")
    result["source_rows_byte_identical"] = (
        result["source_digest_before"] == result["source_digest_after"]
    )
    result["live_jsonl_unchanged"] = (
        before["jsonl_sha"] == after["jsonl_sha"]
        and before["jsonl_mtime"] == after["jsonl_mtime"]
    )
    result["isolation_ok"] = (
        before["6767"] == 200 and after["6767"] == 200
        and before["config_mtime"] == after["config_mtime"]
        and before["projects_count"] == after["projects_count"]
        and result["live_jsonl_unchanged"]
    )
    ss = subprocess.run(["ss", "-ltnp"], check=False, capture_output=True, text=True)
    result["port_lingering"] = f":{PORT}" in ss.stdout
    (EV / "ss.txt").write_text(ss.stdout)
    (EV / "E2E.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result.get("port_lingering"):
        raise SystemExit(f"port {PORT} still listening")


if __name__ == "__main__":
    sys.exit(main() or 0)
