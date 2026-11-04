#!/usr/bin/env bash
# v21 disposition checker: docs/v21-report.md §1 table vs git history.
# Usage: bash scripts/v21_disposition_check.sh [REPORT]   (default docs/v21-report.md)
# Exit 0 iff every v17 commit in v0.17.0..v17/trio-v0.17.0-fixes has exactly one row (in order),
# every product commit carries 0 or 1 `-x` trailers on HEAD, picks are in v17 order, every
# ported/adapted row's new sha is on HEAD and carries that row's trailer, and every dropped row
# cites an upstream commit that is an ancestor of v0.21.0rc1. Exit 1 on any failure (each printed).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
REPORT="${1:-docs/v21-report.md}"
exec python3 -I - "$REPORT" <<'PY'
import re
import subprocess
import sys

BASE, SRC_FROM, SRC_TO = "v0.21.0rc1", "v0.17.0", "v17/trio-v0.17.0-fixes"


def git(*a, ok=False):
    r = subprocess.run(["git", *a], capture_output=True, text=True)
    if r.returncode != 0 and not ok:
        print(f"error: git {' '.join(a)}: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return r


def is_ancestor(a, b):
    return git("merge-base", "--is-ancestor", a, b, ok=True).returncode == 0


fails = []
# --- source commits, classified ---
src = []
for line in git("rev-list", "--reverse", "--parents", f"{SRC_FROM}..{SRC_TO}").stdout.split("\n"):
    if not line:
        continue
    sha, *parents = line.split()
    if len(parents) > 1:
        cls = "merge"
    else:
        paths = [p for p in git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).stdout.split("\n") if p]
        cls = "loop-only" if paths and all(p.startswith(("loop/", "loop-archive")) for p in paths) else "product"
    src.append((sha, cls))
product = [s for s, c in src if c == "product"]

# --- -x trailers on HEAD, in HEAD's topological order ---
log = git("log", "--reverse", "--topo-order", "--format=%H%x00%B%x1e", f"{BASE}..HEAD").stdout
picks = {}  # v17 sha -> [new sha]
pick_order = []
want = set(product)
for rec in log.split("\x1e"):
    rec = rec.strip("\n")
    if not rec:
        continue
    new, body = rec.split("\x00", 1)
    for v in re.findall(r"\(cherry picked from commit ([0-9a-f]{40})\)", body):
        if v in want:
            picks.setdefault(v, []).append(new)
            pick_order.append(v)
for v in product:
    if len(picks.get(v, [])) > 1:
        fails.append(f"v17 {v[:9]}: {len(picks[v])} -x picks on HEAD (expect 0 or 1)")
order_ok = pick_order == [v for v in product if v in picks]

# --- report §1 rows ---
try:
    text = open(sys.argv[1], encoding="utf-8").read()
except OSError as e:
    print(f"error: {e}", file=sys.stderr)
    sys.exit(2)
m = re.search(r"^## 1\..*?(?=^## 2\.)", text, re.S | re.M)
if not m:
    print(f"error: {sys.argv[1]}: no '## 1.' section before '## 2.'", file=sys.stderr)
    sys.exit(2)
rows = []
for line in m.group(0).split("\n"):
    if not line.startswith("|"):
        continue
    cols = [c.strip() for c in line.strip().strip("|").split("|")]
    if len(cols) != 7 or not re.fullmatch(r"[0-9a-f]{7,40}", cols[1]):
        continue
    rows.append(cols)
if len(rows) != len(src):
    fails.append(f"report §1 has {len(rows)} rows, expected {len(src)} (one per v17 commit)")
ported = dropped = 0
for i, (sha, cls) in enumerate(src):
    if i >= len(rows):
        fails.append(f"row for v17 {sha[:9]} missing")
        continue
    num, rsha, _subj, rcls, disp, new, notes = rows[i]
    tag = f"row #{num} (v17 {rsha})"
    if not sha.startswith(rsha):
        fails.append(f"{tag}: out of order or wrong sha, expected v17 {sha[:9]} at position {i + 1}")
        continue
    if rcls != cls:
        fails.append(f"{tag}: class '{rcls}', expected '{cls}'")
    if cls != "product":
        if disp != "not-ported":
            fails.append(f"{tag}: {cls} row must be 'not-ported', got '{disp}'")
        continue
    n = len(picks.get(sha, []))
    if n == 1:
        if disp not in ("ported", "adapted"):
            fails.append(f"{tag}: has one -x pick on HEAD but disposition '{disp}'")
            continue
        ported += 1
        r = git("rev-parse", "--verify", "--quiet", f"{new}^{{commit}}", ok=True)
        if r.returncode != 0:
            fails.append(f"{tag}: new sha '{new}' does not resolve to a commit")
            continue
        full = r.stdout.strip()
        if not is_ancestor(full, "HEAD"):
            fails.append(f"{tag}: new sha {new} is not on HEAD")
        body = git("log", "-1", "--format=%B", full).stdout
        if f"cherry picked from commit {sha})" not in body:
            fails.append(f"{tag}: new sha {new} does not carry the trailer 'cherry picked from commit {sha}'")
    elif n == 0:
        if disp != "dropped":
            fails.append(f"{tag}: no -x pick on HEAD but disposition '{disp}' (expect 'dropped')")
            continue
        dropped += 1
        ev = [s for s in re.findall(r"\b[0-9a-f]{7,40}\b", notes) if not sha.startswith(s)]
        good = False
        for s in ev:
            r = git("rev-parse", "--verify", "--quiet", f"{s}^{{commit}}", ok=True)
            if r.returncode == 0 and is_ancestor(r.stdout.strip(), BASE):
                good = True
                break
        if not good:
            fails.append(f"{tag}: dropped without an upstream commit (ancestor of {BASE}) cited in notes")
for f in fails:
    print("FAIL:", f)
p = ported
print(
    f"DISPOSITION: {len(product)} product commits — ported+adapted={p}, dropped={dropped}, "
    f"p+d={p + dropped}; trailers in v17 order: {'yes' if order_ok else 'no'}"
)
ok = not fails and order_ok and p + dropped == len(product)
print(f"TARGETED_CHECK: {'PASS 1' if ok else 'FAILED ' + str(len(fails)) + ' failure(s)'}")
sys.exit(0 if ok else 1)
PY
