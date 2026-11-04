#!/usr/bin/env bash
# v21 report checker: §5 (behaviour map), §6 (scratch consumer checks), §7 (risks/migrations),
# and no "Pending" anywhere in the report.
# Report path: V21_REPORT (default docs/v21-report.md); behaviour map: V21_BEHAVIOUR_MAP;
# scratch transcript: V21_SCRATCH_TRANSCRIPT_FILE.
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


BEHAVIOUR_MAP = Path(os.environ.get("V21_BEHAVIOUR_MAP", "docs/v21-evidence/behaviour-map.md"))
BEHAVIOUR_REC = Path("docs/v21-evidence/behaviour-check.txt")
TRANSCRIPT = Path(
    os.environ.get("V21_SCRATCH_TRANSCRIPT_FILE", "docs/v21-evidence/scratch/transcript.txt")
)
SCRATCH_CHECKS = (
    "trio-broker",
    "bundle-restrictions-10906",
    "ownership-10850",
    "runner-gone-after-delete",
    "appcontrol-dev-processes",
    "appcontrol-titles",
    "teardown-clean",
)
FORBIDDEN_PORTS = {"6767", "6768", "7456", "8443"}


def subsection(sec: str, heading: str) -> str:
    i = sec.find(heading)
    if i < 0:
        return ""
    j = sec.find("\n### ", i + len(heading))
    return sec[i:] if j < 0 else sec[i:j]


def map_ids() -> list[str]:
    try:
        text = BEHAVIOUR_MAP.read_text(encoding="utf-8")
        block = text.split("<!-- ids:start -->", 1)[1].split("<!-- ids:end -->", 1)[0]
    except (OSError, IndexError):
        record(False, f"{BEHAVIOUR_MAP}: unreadable or no ids markers")
        return []
    return [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def check_section_5(text: str) -> None:
    sec = section(text, 5)
    record(bool(sec), "docs/v21-report.md has no ## 5. section")
    if not sec:
        return
    record("Pending" not in sec, "Pending inside §5")
    ids = map_ids()
    record(bool(ids), "behaviour map lists no node ids")
    for nid in ids:
        record(nid in sec, f"§5 does not list behaviour-map id {nid}")
    try:
        rec = BEHAVIOUR_REC.read_text(encoding="utf-8")
    except OSError:
        record(False, f"{BEHAVIOUR_REC} missing")
        return
    lines = [ln for ln in rec.splitlines() if ln.startswith("BEHAVIOUR ")]
    record(len(lines) >= 6, f"{BEHAVIOUR_REC}: expected >=6 BEHAVIOUR lines, got {len(lines)}")
    bad = [ln for ln in lines if not ln.endswith(": PASS")]
    record(not bad, f"{BEHAVIOUR_REC}: non-PASS behaviour lines {bad}")
    m = re.search(r"^(\d+) passed, (\d+) failed in ", rec, re.M)
    record(
        # parametrised ids expand, so passed >= listed ids
        bool(m) and m.group(2) == "0" and int(m.group(1)) >= len(ids),
        f"{BEHAVIOUR_REC}: counts line must be '>= {len(ids)} passed, 0 failed' (map ids)",
    )


def check_section_6(text: str) -> None:
    sec = section(text, 6)
    record(bool(sec), "docs/v21-report.md has no ## 6. section")
    if not sec:
        return
    record("Pending" not in sec, "Pending inside §6")
    for heading in (
        "### 6.1 (5a) trio broker_http",
        "### 6.2 (5b) App Control parsers",
        "### 6.3 (5c) claude_native hook CLI args",
    ):
        sub = subsection(sec, heading)
        record(bool(sub), f"§6 missing heading {heading!r}")
        paths = re.findall(r"`(docs/v21-evidence/[^`\s]+)`", sub)
        record(bool(paths), f"{heading}: cites no docs/v21-evidence/ transcript path")
        for path in paths:
            record(Path(path).exists(), f"{heading}: cited path {path} does not exist")
    record(
        "test_v21_hook_cli_contract.py" in subsection(sec, "### 6.3 (5c) claude_native hook CLI args"),
        "§6.3 does not cite the hook CLI contract test",
    )
    for name in SCRATCH_CHECKS:
        record(f"`{name}`" in sec, f"§6 does not name CHECK {name}")
    try:
        tr = TRANSCRIPT.read_text(encoding="utf-8")
    except OSError:
        record(False, f"{TRANSCRIPT} missing")
        return
    record(str(TRANSCRIPT) in sec, f"§6 does not cite {TRANSCRIPT}")
    # an explicit write-up line (start of line), never a mention inside prose
    known = re.search(r"^KNOWN-INCOMPAT: \S", sec, re.M) is not None
    for name in SCRATCH_CHECKS:
        passed = f"CHECK {name}: PASS" in tr
        record(passed or known, f"{TRANSCRIPT}: CHECK {name} is not PASS")
    ports = re.findall(r"^SCRATCH_PORT: (\d+)$", tr, re.M)
    record(bool(ports), f"{TRANSCRIPT}: no SCRATCH_PORT line")
    record(
        not (set(ports) & FORBIDDEN_PORTS),
        f"{TRANSCRIPT}: scratch port in the forbidden set {sorted(set(ports) & FORBIDDEN_PORTS)}",
    )
    m = re.search(r"^(\d+) passed, (\d+) failed in ", tr, re.M)
    record(
        bool(m) and m.group(1) == str(len(SCRATCH_CHECKS)) and m.group(2) == "0",
        f"{TRANSCRIPT}: counts line must be '{len(SCRATCH_CHECKS)} passed, 0 failed'",
    )


def check_no_pending(text: str) -> None:
    hits = [n for n, ln in enumerate(text.splitlines(), 1) if "Pending" in ln]
    record(not hits, f"Pending left in the report at line(s) {hits}")


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
    check_no_pending(text)
    dt = time.monotonic() - T0
    print(f"{ok} passed, {len(fails)} failed in {dt:.2f}s")
    return 1 if fails else 0


sys.exit(main())
PY
