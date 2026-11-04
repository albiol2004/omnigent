#!/usr/bin/env bash
# Upstream-overlap line-presence check (v0.21 re-port).
# Usage: scripts/v21_overlap_check.sh
# For each upstream PR commit, takes every non-trivial '+' line the commit added
# that is still present in the same file at tag v0.21.0rc1, and counts how many
# are absent from that file at HEAD. A line absent from its file but found
# elsewhere in the HEAD tree (git grep -F; docs/v17-evidence, docs/v21-evidence
# and docs/*-report.md excluded) is "moved".
# docs/v21-evidence/overlap-allow.txt lists absent-not-moved lines the fork
# deliberately dropped: `<pr>\t<path>\t<stripped line>\t<reason>` ('#' comments).
# Prints a markdown table, then every absent (not moved) line and every moved
# line. Exits 1 if an absent-not-moved line is not allow-listed, else 0.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 2

PRS="10251:7a682c4b6 12200:cdb863459 12153:f7d67db5b 12150:34960c7ad 9908:7eee19341 10861:64dc6d4a4 11485:4f796ba44 11816:ac1737e1c 11821:98967aa31 10850:f93be3274 10906:60a5f61f7 9844:d2e077a1e"

PRS="$PRS" TAG="v0.21.0rc1" ALLOW="docs/v21-evidence/overlap-allow.txt" python3 -I - <<'PY'
import os
import subprocess
import sys

TAG = os.environ["TAG"]
PRS = [p.split(":") for p in os.environ["PRS"].split()]
TRIVIAL = {"pass", "else:", ")", "]", "}", "),", "],", "},", "(", "[", "{"}


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def file_lines(rev, path):
    rc, out = git("show", f"{rev}:{path}")
    if rc != 0:
        return None
    return {ln.strip() for ln in out.splitlines()}


def trivial(s):
    return len(s) < 8 or s in TRIVIAL or set(s) <= set("()[]{},;")


def added_by_file(commit):
    _, out = git("diff-tree", "-p", "--no-renames", "--no-commit-id", "-r", "-U0", "--root", commit)
    cur = None
    res = {}
    for ln in out.splitlines():
        if ln.startswith("+++ "):
            cur = ln[6:] if ln.startswith("+++ b/") else None
        elif ln.startswith("+") and cur:
            s = ln[1:].strip()
            if s and not trivial(s):
                res.setdefault(cur, set()).add(s)
    return res


def moved_to(line):
    rc, out = git(
        "grep", "-F", "-l", "-e", line, "HEAD", "--", ".",
        ":(exclude)docs/v17-evidence", ":(exclude)docs/v21-evidence",
        ":(exclude)docs/*-report.md",
    )
    if rc != 0:
        return None
    paths = sorted(p.split(":", 1)[1] for p in out.splitlines() if ":" in p)
    return paths[0] if paths else None


def load_allow(path):
    allow = {}
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return allow
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 4 or not parts[3].strip():
            print(f"BAD allow-list entry (need 4 tab fields incl. reason): {raw[:120]}", file=sys.stderr)
            continue
        allow[(parts[0].lstrip("#"), parts[1], parts[2])] = parts[3]
    return allow


allow = load_allow(os.environ["ALLOW"])
rows = []
absent_lines = []
moved_lines = []
for pr, commit in PRS:
    checked = absent = moved = allowed = 0
    files = set()
    for path, lines in sorted(added_by_file(commit).items()):
        tagset = file_lines(TAG, path)
        if tagset is None:
            continue
        files.add(path)
        headset = file_lines("HEAD", path)
        for s in sorted(lines):
            if s not in tagset:
                continue
            checked += 1
            if headset is not None and s in headset:
                continue
            m = moved_to(s)
            if m:
                moved += 1
                moved_lines.append((pr, commit, path, s, m))
            else:
                absent += 1
                reason = allow.get((pr, path, s))
                if reason:
                    allowed += 1
                absent_lines.append((pr, commit, path, s, reason))
    rows.append((pr, commit, len(files), checked, absent, moved, allowed))

print("| PR | commit | files | lines checked | absent at tip | moved | allow-listed |")
print("|---|---|---|---|---|---|---|")
for pr, commit, nf, c, a, m, al in rows:
    print(f"| #{pr} | {commit} | {nf} | {c} | {a} | {m} | {al} |")
print()
print(f"absent lines (not moved): {len(absent_lines)}")
for pr, commit, path, s, reason in sorted(absent_lines, key=lambda t: t[:4]):
    tag = f"  [allow-listed: {reason}]" if reason else "  [NOT ALLOW-LISTED]"
    print(f"#{pr} {commit} {path}: {s}{tag}")
print()
print(f"moved lines: {len(moved_lines)}")
for pr, commit, path, s, m in sorted(moved_lines):
    print(f"#{pr} {commit} {path}: {s}  -> moved: {m}")
bad = [a for a in absent_lines if not a[4]]
print()
print(f"unallowed absent lines: {len(bad)}")
sys.exit(1 if bad else 0)
PY
