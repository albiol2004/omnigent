#!/usr/bin/env bash
# Collect and run the GOAL DoD 4 behaviour node ids listed in
# docs/v21-evidence/behaviour-map.md. Override the map with
# V21_BEHAVIOUR_MAP. Exit 1 naming the first id that does not collect.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 2

MAP="${V21_BEHAVIOUR_MAP:-docs/v21-evidence/behaviour-map.md}"
PY=(uv run --frozen --extra all --group dev pytest -q -p no:cacheprovider)
# AF_UNIX tmux sockets fail when TMPDIR is the driver's long worktree path.
export TMPDIR="/var/tmp/pytest-of-coder"
mkdir -p "$TMPDIR"

python3 -I - "$MAP" "${PY[@]}" <<'PY'
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

map_path = Path(sys.argv[1])
pytest_prefix = sys.argv[2:]
text = map_path.read_text(encoding="utf-8")
try:
    block = text.split("<!-- ids:start -->", 1)[1].split("<!-- ids:end -->", 1)[0]
except IndexError:
    print(f"missing ids markers in {map_path}", file=sys.stderr)
    sys.exit(2)

behaviour = "ungrouped"
groups: dict[str, list[str]] = defaultdict(list)
ids: list[str] = []
for raw in block.splitlines():
    line = raw.strip()
    if not line:
        continue
    if line.startswith("#"):
        behaviour = line[1:].strip()
        continue
    ids.append(line)
    groups[behaviour].append(line)

if not ids:
    print("no node ids listed", file=sys.stderr)
    sys.exit(2)

collect_cmd = [
    *pytest_prefix,
    "--collect-only",
    *ids,
]
collect = subprocess.run(collect_cmd, capture_output=True, text=True)
collected = {
    line.strip()
    for line in collect.stdout.splitlines()
    if line.startswith("tests/") or "::" in line
}
# pytest -q --collect-only prints "<nodeid>" lines; also accept "tests/...".
if collect.returncode != 0:
    # Fall back to per-id collect so we can name the missing one.
    for node_id in ids:
        probe = subprocess.run(
            [*pytest_prefix, "--collect-only", "-q", node_id],
            capture_output=True,
            text=True,
        )
        out = probe.stdout + probe.stderr
        if probe.returncode != 0 or "no tests collected" in out.lower() or "ERROR" in out:
            print(f"id does not collect: {node_id}", file=sys.stderr)
            sys.exit(1)

integration: dict[str, list[str]] = defaultdict(list)
other: list[str] = []
for node_id in ids:
    if node_id.startswith("tests/server/integration/"):
        file_path = node_id.split("::", 1)[0]
        integration[file_path].append(node_id)
    else:
        other.append(node_id)

env = os.environ.copy()
env["TMPDIR"] = "/var/tmp/pytest-of-coder"


def run_pytest(args: list[str]) -> tuple[int, str, int, int]:
    proc = subprocess.run(
        [*pytest_prefix, *args],
        capture_output=True,
        text=True,
        env=env,
    )
    out = proc.stdout + proc.stderr
    passed = failed = 0
    for line in out.splitlines():
        # "<N> passed, <M> failed in <s>s" or "<N> passed in <s>s"
        if " passed" in line and " in " in line and not line.startswith("="):
            # last summary-shaped line wins
            tokens = line.replace(",", " ").split()
            for i, tok in enumerate(tokens):
                if tok == "passed" and i:
                    passed = int(tokens[i - 1])
                if tok == "failed" and i:
                    failed = int(tokens[i - 1])
    if proc.returncode != 0 and passed == 0 and failed == 0:
        failed = 1
    return proc.returncode, out, passed, failed


started = time.monotonic()
total_passed = 0
total_failed = 0
id_failed: set[str] = set()
outputs: list[str] = []

for file_path, file_ids in integration.items():
    rc, out, passed, failed = run_pytest(["--capture=sys", *file_ids])
    outputs.append(out)
    total_passed += passed
    total_failed += failed
    if rc != 0:
        id_failed.update(file_ids)

if other:
    rc, out, passed, failed = run_pytest(other)
    outputs.append(out)
    total_passed += passed
    total_failed += failed
    if rc != 0:
        # Attribute failures to ids named in FAILED lines.
        for line in out.splitlines():
            if line.startswith("FAILED "):
                node = line.split()[1].split(" ")[0]
                id_failed.add(node.split("[")[0] if False else node)

elapsed = time.monotonic() - started
id_failed_bases = {item.split("[", 1)[0] for item in id_failed}

for name, group_ids in groups.items():
    failed_here = False
    for node_id in group_ids:
        if node_id in id_failed or any(
            failed.startswith(node_id) or node_id.split("::")[-1] in failed
            for failed in id_failed
        ):
            failed_here = True
            break
        base = node_id.split("[", 1)[0]
        if any(item.split("[", 1)[0] == base for item in id_failed):
            failed_here = True
            break
    status = "FAIL" if failed_here else "PASS"
    print(f"BEHAVIOUR {name}: {status}")

print(f"{total_passed} passed, {total_failed} failed in {elapsed:.2f}s")
if total_failed:
    sys.stderr.write("\n".join(outputs[-2:]))
    sys.exit(1)
sys.exit(0)
PY
