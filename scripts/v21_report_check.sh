#!/usr/bin/env bash
# v21 report checker. Later slices add §5/§6 functions; this revision checks §7.
# Report path: V21_REPORT (default docs/v21-report.md).
# Exit 1 on any failure. Prints FAIL: <reason> per failure, then
# "<checks ok> passed, <failures> failed in <s>s".
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export V21_REPORT="${V21_REPORT:-docs/v21-report.md}"
exec python3 -I - <<'PY'
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import time
from pathlib import Path

T0 = time.monotonic()
ROOT = Path(".").resolve()
REPORT = Path(os.environ.get("V21_REPORT", "docs/v21-report.md"))
ok = 0
fails: list[str] = []


def record(cond: bool, reason: str) -> None:
    global ok
    if cond:
        ok += 1
        return
    fails.append(reason)
    print(f"FAIL: {reason}")


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"error: git {' '.join(args)}: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return r.stdout


def section(text: str, n: int) -> str:
    nxt = n + 1
    m = re.search(rf"^## {n}\..*?(?=^## {nxt}\.|\Z)", text, re.S | re.M)
    return m.group(0) if m else ""


def parse_rev_assignment(src: str, name: str) -> str | tuple[str, ...] | None:
    m = re.search(
        rf"^{name}\s*(?::[^\n=]+)?=\s*(.+)$",
        src,
        re.M,
    )
    if not m:
        return None
    expr = m.group(1).strip()
    try:
        val = ast.literal_eval(expr)
    except (SyntaxError, ValueError):
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, (tuple, list)):
        return tuple(str(x) for x in val)
    return None


def migration_files() -> list[Path]:
    out = git(
        "diff",
        "--name-only",
        "--diff-filter=A",
        "v0.17.0",
        "HEAD",
        "--",
        "omnigent/db/migrations/versions",
    )
    return [Path(p) for p in out.splitlines() if p]


def check_section_5(_text: str) -> None:
    """Placeholder for a later slice."""
    return


def check_section_6(_text: str) -> None:
    """Placeholder for a later slice."""
    return


def check_section_7(text: str) -> None:
    sec = section(text, 7)
    record(bool(sec), "docs/v21-report.md has no ## 7. section")
    if not sec:
        return

    for heading in (
        "### 7.1 Database migrations since v0.17.0",
        "### 7.2 Config / preference / API changes",
        "### 7.3 Not verifiable without the live server",
        "### 7.4 Rebase onto final v0.21.0",
        "### 7.5 Install and rollback for the live editable install (documentation only — not run)",
    ):
        record(heading in sec, f"§7 missing heading {heading!r}")

    pending = re.findall(r"Pending", sec)
    record(not pending, "Pending inside §7")

    files = migration_files()
    record(bool(files), "no added migration files in git diff v0.17.0 HEAD")
    metas: list[tuple[str, tuple[str, ...], Path]] = []
    for path in files:
        src = path.read_text(encoding="utf-8")
        rev = parse_rev_assignment(src, "revision")
        down = parse_rev_assignment(src, "down_revision")
        if not isinstance(rev, str):
            record(False, f"{path}: could not parse revision")
            continue
        if down is None:
            record(False, f"{path}: could not parse down_revision")
            continue
        downs = (down,) if isinstance(down, str) else down
        metas.append((rev, downs, path))
        row_hit = False
        for line in sec.splitlines():
            if not line.startswith("|"):
                continue
            if not re.match(rf"\|\s*`{re.escape(rev)}`", line):
                continue
            row_hit = True
            missing = [d for d in downs if d not in line]
            record(
                not missing,
                f"§7.1 table row for {rev} missing down_revision {missing}",
            )
            break
        record(row_hit, f"§7.1 table missing revision {rev} ({path})")

    revised: set[str] = set()
    ids = {rev for rev, _, _ in metas}
    for _, downs, _ in metas:
        revised.update(d for d in downs if d in ids)
    heads = sorted(ids - revised)
    m = re.search(r"Head revision:\s+`([^`]+)`", sec)
    named = m.group(1) if m else None
    record(m is not None, "§7 missing Head revision: `<id>` line")
    if len(heads) == 1:
        expect = heads[0]
        record(named == expect, f"Head revision named {named!r}, expected {expect!r}")
    else:
        record(False, f"could not uniquely determine head from files (got {heads})")

    upgrade = ROOT / "docs/v21-evidence/upgrade-to-0.21.sh"
    record(upgrade.is_file(), "docs/v21-evidence/upgrade-to-0.21.sh does not exist")
    if upgrade.is_file():
        body = upgrade.read_text(encoding="utf-8")
        n = subprocess.run(["bash", "-n", str(upgrade)], capture_output=True, text=True)
        record(n.returncode == 0, f"upgrade-to-0.21.sh failed bash -n: {n.stderr.strip()}")
        record(
            ".backup" in body and "chat.db" in body,
            "upgrade-to-0.21.sh missing sqlite3 .backup of chat.db",
        )
        record(
            "CONFIRM_LIVE_UPGRADE" in body,
            "upgrade-to-0.21.sh missing CONFIRM_LIVE_UPGRADE guard",
        )


def main() -> int:
    try:
        text = REPORT.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    check_section_5(text)
    check_section_6(text)
    check_section_7(text)
    dt = time.monotonic() - T0
    print(f"{ok} passed, {len(fails)} failed in {dt:.2f}s")
    return 1 if fails else 0


sys.exit(main())
PY
