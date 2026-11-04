#!/usr/bin/env bash
# Start scratch stack, run consumer checks, always tear down.
# Hard overall timeout 300s. Default transcript is inside the scratch dir
# (untracked). Set V21_SCRATCH_TRANSCRIPT to a path to copy/tee there.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
START_MONO="$SECONDS"
DEADLINE=290
PASSED=0
FAILED=0
KEEP_SCRATCH=0
TRANSCRIPT_COPY="${V21_SCRATCH_TRANSCRIPT:-}"
TMP_TRANSCRIPT=""
WATCHDOG_PID=""
STATE_FILE=""
SCRATCH_DIR=""

die_timeout() {
  echo "overall timeout reached" >&2
  kill -TERM "$$" 2>/dev/null || true
}

cleanup() {
  local rc=$?
  if [[ -n "$WATCHDOG_PID" ]]; then
    kill "$WATCHDOG_PID" 2>/dev/null || true
    wait "$WATCHDOG_PID" 2>/dev/null || true
  fi
  if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then
    V21_SCRATCH_KEEP=1 V21_SCRATCH_STATE="$STATE_FILE" \
      bash "$ROOT/scripts/v21_scratch_stack.sh" stop >/dev/null 2>&1 || true
  fi
  # teardown-clean check (best-effort; prints CHECK)
  if [[ -n "$SCRATCH_DIR" ]]; then
    python3 - "$SCRATCH_DIR" "${V21_GUARD_FILE:-$SCRATCH_DIR/guard_count}" <<'PY' || true
import os, sys
scratch = sys.argv[1]
guard_path = sys.argv[2]
data = scratch + "/data"
want = "OMNIGENT_DATA_DIR=" + data
live = []
try:
    names = os.listdir("/proc")
except OSError:
    names = []
for name in names:
    if not name.isdigit():
        continue
    try:
        with open(f"/proc/{name}/status", encoding="utf-8", errors="replace") as fh:
            state = ""
            for line in fh:
                if line.startswith("State:"):
                    state = line.split()[1]
                    break
        if state == "Z":
            continue
        with open(f"/proc/{name}/environ", "rb") as fh:
            raw = fh.read()
    except OSError:
        continue
    if want.encode() in raw.split(b"\0") or want.encode() in raw:
        live.append(name)
tmux_live = []
tmp = os.path.join(scratch, "tmp")
if os.path.isdir(tmp):
    for dirpath, _, filenames in os.walk(tmp):
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            # leftover socket file is not a live server after kill-server
            if "tmux" in path:
                tmux_live.append(path)
violations = 0
try:
    violations = int(open(guard_path, encoding="utf-8").read().strip() or "0")
except OSError:
    violations = 0
ok = (not live) and violations == 0
reason = f"live={live} tmux_paths={len(tmux_live)} violations={violations}"
print(f"CHECK teardown-clean: {'PASS' if ok else 'FAIL ' + reason}")
sys.exit(0 if ok else 1)
PY
    tc_rc=$?
    if [[ "$tc_rc" -eq 0 ]]; then
      PASSED=$((PASSED + 1))
    else
      FAILED=$((FAILED + 1))
    fi
  fi
  if [[ -n "$TRANSCRIPT_COPY" && -n "$TMP_TRANSCRIPT" && -f "$TMP_TRANSCRIPT" ]]; then
    if [[ "$(realpath "$TMP_TRANSCRIPT" 2>/dev/null || echo "$TMP_TRANSCRIPT")" != "$(realpath "$TRANSCRIPT_COPY" 2>/dev/null || echo "$TRANSCRIPT_COPY")" ]]; then
      mkdir -p "$(dirname "$TRANSCRIPT_COPY")"
      cp -f "$TMP_TRANSCRIPT" "$TRANSCRIPT_COPY" || true
    fi
  fi
  if [[ -z "$TRANSCRIPT_COPY" && -n "$TMP_TRANSCRIPT" ]]; then
    echo "TRANSCRIPT: $TMP_TRANSCRIPT"
  fi
  if [[ -n "$SCRATCH_DIR" && -d "$SCRATCH_DIR" && "${V21_KEEP_SCRATCH:-0}" != "1" ]]; then
    rm -rf "$SCRATCH_DIR" || true
  fi
  local elapsed=$((SECONDS - START_MONO))
  echo "$PASSED passed, $FAILED failed in ${elapsed}s"
  # preserve original failure
  if [[ "$FAILED" -gt 0 ]]; then
    exit 1
  fi
  exit "$rc"
}

trap cleanup EXIT INT TERM

# Watchdog: TERM this script before 300s so EXIT trap still tears down.
( sleep "$DEADLINE"; die_timeout ) &
WATCHDOG_PID=$!

# Prepare an isolated state file under a short /var/tmp path.
SCRATCH_HOLDER="$(mktemp -d /var/tmp/v21s.XXXXXX)"
STATE_FILE="$SCRATCH_HOLDER/stack.env"
export V21_SCRATCH_STATE="$STATE_FILE"

if [[ -n "$TRANSCRIPT_COPY" ]]; then
  mkdir -p "$(dirname "$TRANSCRIPT_COPY")"
  TMP_TRANSCRIPT="$TRANSCRIPT_COPY"
  : >"$TMP_TRANSCRIPT"
  exec > >(tee "$TMP_TRANSCRIPT") 2>&1
else
  TMP_TRANSCRIPT="$SCRATCH_HOLDER/transcript.txt"
  : >"$TMP_TRANSCRIPT"
  exec > >(tee "$TMP_TRANSCRIPT") 2>&1
fi

bash "$ROOT/scripts/v21_scratch_stack.sh" start
# shellcheck disable=SC1090
source "$STATE_FILE"
SCRATCH_DIR="${SCRATCH_DIR}"
KEEP_SCRATCH=1  # stack stop in cleanup uses V21_SCRATCH_KEEP then we rm
export V21_SCRATCH_DIR="$SCRATCH_DIR"
export V21_SCRATCH_PORT="$SCRATCH_PORT"
export V21_SCRATCH_DATA="$SCRATCH_DATA"
export V21_SERVER_PID="$SERVER_PID"
export V21_HOST_PID="$HOST_PID"
export V21_GUARD_FILE="$SCRATCH_DIR/guard_count"
unset OMNIGENT_TOKEN OMNIGENT_REMOTE_AUTH_TOKEN OMNIGENT_URL OMNIGENT_BASE_URL || true

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(HOME="${HOME:-/home/coder}" uv run --frozen --extra all --group dev python -c 'import sys; print(sys.executable)')"
fi

set +e
"$PY" -I -B "$ROOT/docs/v21-evidence/scratch/compat_checks.py"
check_rc=$?
set -e

sleep 0.2
while IFS= read -r line; do
  case "$line" in
    "CHECK teardown-clean:"*) ;;
    "CHECK "*" PASS") PASSED=$((PASSED + 1)) ;;
    "CHECK "*" FAIL"*) FAILED=$((FAILED + 1)) ;;
  esac
done < <(grep -E '^CHECK ' "$TMP_TRANSCRIPT" || true)

exit "$check_rc"
