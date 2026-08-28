"""Reproduce the missed native passthrough the way the Web UI forks."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

import httpx

ROOT = Path("/home/alex/omnigent-fixes")
EV = ROOT / "loop-fork-async/evidence/iter1/passthrough-why"
SOURCE_HEX = "e34847899b7d47b3ad322948d4ea6002"
PORT = 18021
SCRATCH = Path("/tmp/fork-async-passthrough-why-iter1")

_spec = importlib.util.spec_from_file_location(
    "cli_real_e2e",
    ROOT / "loop-fork-cli/evidence/iter1/real-e2e/run_e2e.py",
)
assert _spec is not None and _spec.loader is not None
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

cli.PORT = PORT
cli.SCRATCH = SCRATCH
cli.EV = EV
cli.ROOT = ROOT


def _last_response_id(db: Path) -> str | None:
    cid = bytes.fromhex(SOURCE_HEX)
    con = sqlite3.connect(str(db))
    try:
        row = con.execute(
            "SELECT response_id FROM conversation_items "
            "WHERE conversation_id=? AND response_id IS NOT NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (cid,),
        ).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _grep_skip(log: Path) -> list[str]:
    return [
        line for line in log.read_text(errors="replace").splitlines()
        if "fork passthrough skipped" in line or "Fork compaction" in line
    ]


def main() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    before = cli._isolation_before()
    if SCRATCH.exists():
        shutil.rmtree(SCRATCH)
    (SCRATCH / "data" / "artifacts").mkdir(parents=True)
    cli._strip_keys(cli.LIVE_CONFIG, SCRATCH / "config" / "config.yaml")
    cli._copy_agent_artifacts(SCRATCH / "data" / "artifacts")
    proj = SCRATCH / "claude-projects" / "-home-alex-omnigent"
    proj.mkdir(parents=True)
    shutil.copy2(cli.LIVE_JSONL, proj / f"{cli.SOURCE_EXT}.jsonl")

    proc = cli._start_server(SCRATCH)
    result: dict = {
        "port": PORT,
        "scratch": str(SCRATCH),
        "isolation_before": before,
    }
    try:
        cli._wait_health(f"http://127.0.0.1:{PORT}")
        counts, file_ids = cli._copy_rows(SCRATCH / "data" / "chat.db")
        result["copy_counts"] = counts
        result["file_blobs"] = cli._copy_file_blobs(
            SCRATCH / "data" / "artifacts", file_ids
        )
        last_rid = _last_response_id(SCRATCH / "data" / "chat.db")
        result["last_response_id"] = last_rid
        cli._stop_server(proc)
        # Compact off: we only need the skip-reason log, not a 56s LLM call.
        proc = cli._start_server(SCRATCH, {"OMNIGENT_FORK_COMPACT": "0"})
        cli._wait_health(f"http://127.0.0.1:{PORT}")
        base = f"http://127.0.0.1:{PORT}"

        t0 = time.monotonic()
        full = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json={"title": "diag-full-no-point"},
            timeout=120.0,
        )
        result["full_wall_s"] = round(time.monotonic() - t0, 3)
        result["full_status"] = full.status_code
        (EV / "full_fork.txt").write_text(f"{full.status_code}\n{full.text[:4000]}\n")

        t1 = time.monotonic()
        web_body: dict = {"title": "diag-web-ui"}
        if last_rid:
            web_body["up_to_response_id"] = last_rid
        web = httpx.post(
            f"{base}/v1/sessions/{SOURCE_HEX}/fork",
            json=web_body,
            timeout=120.0,
        )
        result["web_wall_s"] = round(time.monotonic() - t1, 3)
        result["web_status"] = web.status_code
        (EV / "web_fork.txt").write_text(f"{web.status_code}\n{web.text[:4000]}\n")

        skips = _grep_skip(SCRATCH / "server.log")
        result["skip_lines"] = skips[-20:]
        real_log = next(
            (SCRATCH / "data" / "logs" / "server").glob("server-*.log"),
            None,
        )
        if real_log is not None:
            lines = real_log.read_text(errors="replace").splitlines()
            (EV / "server.log.tail.txt").write_text("\n".join(lines[-80:]) + "\n")
            shutil.copy2(real_log, EV / "server.log")

    finally:
        cli._stop_server(proc)

    after = cli._isolation_before()
    result["isolation_after"] = after
    result["isolation_ok"] = (
        before["6767"] == 200
        and after["6767"] == 200
        and before["config_mtime"] == after["config_mtime"]
        and before["chat_db_mtime"] == after["chat_db_mtime"]
        and after["projects_count"] == before["projects_count"]
    )
    (EV / "REPRO.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
