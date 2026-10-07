#!/usr/bin/env bash
# Upstream-overlap line-presence check (v0.17 re-port, GOAL DoD 2).
# Usage: scripts/v17_overlap_check.sh
# For each upstream PR commit, takes every non-trivial '+' line the commit added
# that is still present in the same file at tag v0.17.0, and counts how many are
# absent from that file at HEAD. A line absent from its file but found elsewhere
# in the HEAD tree (git grep -F, docs/v17-evidence excluded) is "moved".
# Prints a markdown table, then every absent (not moved) line and every moved line. Always exits 0.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 0

PRS="9048:021d19951 9008:06a055ac1 9005:f651b5d6a 8672:8bb13323f 8572:61d96f74b 8745:56272dfd7 8761:ee3ca7cca 8516:a16334f78 8523:7cbad8613 9025:106e2260b 9020:6f9f8f838 8297:5f0781228"

PRS="$PRS" TAG="v0.17.0" python3 -I - <<'PY'
import os
import subprocess

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
    rc, out = git("grep", "-F", "-l", "-e", line, "HEAD", "--", ".", ":(exclude)docs/v17-evidence")
    if rc != 0:
        return None
    paths = sorted(p.split(":", 1)[1] for p in out.splitlines() if ":" in p)
    return paths[0] if paths else None


rows = []
absent_lines = []
moved_lines = []
for pr, commit in PRS:
    checked = absent = moved = 0
    for path, lines in sorted(added_by_file(commit).items()):
        tagset = file_lines(TAG, path)
        if tagset is None:
            continue
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
                absent_lines.append((pr, commit, path, s))
    rows.append((pr, commit, checked, absent, moved))

print("| PR | commit | lines checked | absent at tip | moved |")
print("|---|---|---|---|---|")
for pr, commit, c, a, m in rows:
    print(f"| #{pr} | {commit} | {c} | {a} | {m} |")
print()
print(f"absent lines (not moved): {len(absent_lines)}")
for pr, commit, path, s in sorted(absent_lines):
    print(f"#{pr} {commit} {path}: {s}")
print()
print(f"moved lines: {len(moved_lines)}")
for pr, commit, path, s, m in sorted(moved_lines):
    print(f"#{pr} {commit} {path}: {s}  -> moved: {m}")
PY
exit 0
