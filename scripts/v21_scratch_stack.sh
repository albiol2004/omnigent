#!/usr/bin/env bash
# Start/stop/status for an isolated SCRATCH Omnigent server + host.
# State file: $V21_SCRATCH_STATE (default /var/tmp/v21s.state).
set -euo pipefail

FORBIDDEN_PORTS="6767 6768 7456 8443"
STATE_FILE="${V21_SCRATCH_STATE:-/var/tmp/v21s.state}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

is_forbidden_port() {
  local p="$1" f
  for f in $FORBIDDEN_PORTS; do
    if [[ "$p" == "$f" ]]; then
      return 0
    fi
  done
  return 1
}

pick_port() {
  local n i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    n="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
    if ! is_forbidden_port "$n"; then
      echo "$n"
      return 0
    fi
  done
  echo "could not pick a non-forbidden loopback port" >&2
  return 1
}

load_state() {
  if [[ ! -f "$STATE_FILE" ]]; then
    return 1
  fi
  # shellcheck disable=SC1090
  source "$STATE_FILE"
}

pid_alive() {
  local p="${1:-}"
  [[ -n "$p" ]] && [[ -d "/proc/$p" ]]
}

# Walk /proc ppid from the given roots; print unique pids (roots included).
descendants_of() {
  python3 - "$1" <<'PY' || true
import os, sys
roots = [int(x) for x in sys.argv[1].split(",") if x.strip().isdigit()]
seen = set()
children = {}
try:
    names = os.listdir("/proc")
except OSError:
    names = []
for name in names:
    if not name.isdigit():
        continue
    pid = int(name)
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8", errors="replace") as fh:
            ppid = 0
            for line in fh:
                if line.startswith("PPid:"):
                    ppid = int(line.split()[1])
                    break
    except (OSError, ValueError):
        continue
    children.setdefault(ppid, []).append(pid)

def walk(pid):
    if pid in seen:
        return
    seen.add(pid)
    for c in children.get(pid, []):
        walk(c)

for r in roots:
    walk(r)
for pid in sorted(seen):
    print(pid)
PY
}

pids_with_data_dir() {
  local want="$1"
  python3 - "$want" <<'PY' || true
import os, sys
want = "OMNIGENT_DATA_DIR=" + sys.argv[1]
try:
    names = os.listdir("/proc")
except OSError:
    names = []
for name in names:
    if not name.isdigit():
        continue
    path = f"/proc/{name}/environ"
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        continue
    for rec in raw.split(b"\0"):
        try:
            if rec.decode("utf-8", "replace") == want:
                print(name)
                break
        except Exception:
            continue
PY
}

tmux_kill_ours() {
  local tmp="${SCRATCH_TMPDIR:-}"
  [[ -z "$tmp" || ! -d "$tmp" ]] && return 0
  local sock
  # tmux default socket names under TMPDIR
  shopt -s nullglob
  for sock in "$tmp"/tmux-*/* "$tmp"/tmux-*/default "$tmp"/*.sock; do
    [[ -S "$sock" || -e "$sock" ]] || continue
    tmux -S "$sock" kill-server >/dev/null 2>&1 || true
  done
  shopt -u nullglob
  # also any tmux sockets whose path is under tmp
  python3 - "$tmp" <<'PY' || true
import os, sys, subprocess
root = sys.argv[1]
for dirpath, dirnames, filenames in os.walk(root):
    for name in filenames:
        path = os.path.join(dirpath, name)
        try:
            if os.path.exists(path):
                subprocess.run(["tmux", "-S", path, "kill-server"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
PY
}

signal_pids() {
  local sig="$1"
  shift
  local p
  for p in "$@"; do
    [[ -n "$p" ]] || continue
    if [[ -d "/proc/$p" ]]; then
      kill "-$sig" "$p" 2>/dev/null || true
    fi
  done
}

wait_gone() {
  local timeout_s="$1"
  shift
  local deadline=$((SECONDS + timeout_s))
  local p left
  while (( SECONDS < deadline )); do
    left=0
    for p in "$@"; do
      if [[ -n "$p" && -d "/proc/$p" ]]; then
        # zombies count as gone
        local state
        state="$(awk '/^State:/{print $2}' "/proc/$p/status" 2>/dev/null || true)"
        if [[ "$state" != "Z" ]]; then
          left=1
          break
        fi
      fi
    done
    if (( left == 0 )); then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

collect_kill_set() {
  local data="${SCRATCH_DATA:-}"
  local all=()
  local p
  for p in "${SERVER_PID:-}" "${HOST_PID:-}"; do
    [[ -n "$p" ]] && all+=("$p")
  done
  if [[ ${#all[@]} -gt 0 ]]; then
    ROOTS_CSV="$(IFS=,; echo "${all[*]}")"
    while IFS= read -r p; do
      [[ -n "$p" ]] && all+=("$p")
    done < <(descendants_of "$ROOTS_CSV")
  fi
  if [[ -n "$data" ]]; then
    while IFS= read -r p; do
      [[ -n "$p" ]] && all+=("$p")
    done < <(pids_with_data_dir "$data")
  fi
  printf '%s\n' "${all[@]}" | awk 'NF && !seen[$0]++'
}

do_stop() {
  if ! load_state; then
    echo "scratch stack: not running (no state file $STATE_FILE)"
    return 0
  fi
  tmux_kill_ours
  mapfile -t KILLSET < <(collect_kill_set)
  if [[ ${#KILLSET[@]} -gt 0 ]]; then
    signal_pids TERM "${KILLSET[@]}"
    wait_gone 8 "${KILLSET[@]}" || true
    mapfile -t KILLSET < <(collect_kill_set)
    signal_pids KILL "${KILLSET[@]}"
    wait_gone 3 "${KILLSET[@]}" || true
  fi
  tmux_kill_ours
  if [[ -n "${SCRATCH_DIR:-}" && -d "${SCRATCH_DIR:-}" ]]; then
    # keep dir if caller still needs transcript; only rm when V21_SCRATCH_KEEP is unset
    if [[ -z "${V21_SCRATCH_KEEP:-}" ]]; then
      rm -rf "$SCRATCH_DIR" || true
    fi
  fi
  rm -f "$STATE_FILE"
  echo "scratch stack: stopped"
}

do_status() {
  if ! load_state; then
    echo "scratch stack: stopped"
    return 1
  fi
  local ok=1
  if pid_alive "${SERVER_PID:-}"; then
    echo "server pid=$SERVER_PID alive"
  else
    echo "server pid=${SERVER_PID:-?} dead"
    ok=0
  fi
  if pid_alive "${HOST_PID:-}"; then
    echo "host pid=$HOST_PID alive"
  else
    echo "host pid=${HOST_PID:-?} dead"
    ok=0
  fi
  echo "SCRATCH_PORT: ${SCRATCH_PORT:-}"
  echo "SCRATCH_DIR: ${SCRATCH_DIR:-}"
  echo "OMNIGENT_DATA_DIR: ${SCRATCH_DATA:-}"
  if (( ok == 1 )); then
    return 0
  fi
  return 1
}

do_start() {
  if [[ -f "$STATE_FILE" ]]; then
    echo "state file exists; stopping leftover stack first" >&2
    V21_SCRATCH_KEEP=1 do_stop || true
  fi

  local real_home="${HOME}"
  (
    cd "$ROOT"
    HOME="$real_home" uv sync --frozen --extra all --group dev >/dev/null
  )
  local py
  py="$(cd "$ROOT" && HOME="$real_home" uv run --frozen --extra all --group dev python -c 'import sys; print(sys.executable)')"
  local omnigent
  omnigent="$(dirname "$py")/omnigent"
  if [[ ! -x "$omnigent" ]]; then
    omnigent="$py"
    OMNI_CMD=("$py" -m omnigent.cli)
  else
    OMNI_CMD=("$omnigent")
  fi

  local s
  s="$(mktemp -d /var/tmp/v21s.XXXXXX)"
  mkdir -p "$s/home" "$s/data" "$s/config" "$s/tmp" "$s/cache" "$s/xdg-data" "$s/run" "$s/logs"
  chmod 700 "$s/run"

  local port
  port="$(pick_port)"
  echo "SCRATCH_PORT: $port"

  local path="/usr/bin:/bin:/usr/local/bin:$(dirname "$py")"
  local common=(
    env -i
    "PATH=$path"
    "LANG=${LANG:-C.UTF-8}"
    "LC_ALL=C.UTF-8"
    "USER=${USER:-$(id -un)}"
    "LOGNAME=${LOGNAME:-$(id -un)}"
    "HOME=$s/home"
    "OMNIGENT_DATA_DIR=$s/data"
    "OMNIGENT_CONFIG_HOME=$s/config"
    "TMPDIR=$s/tmp"
    "XDG_CACHE_HOME=$s/cache"
    "XDG_CONFIG_HOME=$s/config"
    "XDG_DATA_HOME=$s/xdg-data"
    "XDG_RUNTIME_DIR=$s/run"
    "PYTHONUNBUFFERED=1"
    "PYTHONNOUSERSITE=1"
    "TERM=dumb"
    "GIT_CONFIG_NOSYSTEM=1"
    "GIT_CONFIG_GLOBAL=/dev/null"
    "OMNIGENT_LOCAL_SINGLE_USER=1"
  )

  "${common[@]}" "${OMNI_CMD[@]}" server --host 127.0.0.1 --port "$port" --no-open \
    >"$s/logs/server.stdout" 2>"$s/logs/server.stderr" &
  local server_pid=$!

  local i ready=0
  for i in $(seq 1 80); do
    if ! pid_alive "$server_pid"; then
      echo "server exited early; stderr:" >&2
      tail -n 40 "$s/logs/server.stderr" >&2 || true
      kill -TERM "$server_pid" 2>/dev/null || true
      rm -rf "$s"
      return 1
    fi
    if python3 - "$port" <<'PY'
import sys, urllib.request
port = sys.argv[1]
url = f"http://127.0.0.1:{port}/health"
try:
    with urllib.request.urlopen(url, timeout=1.5) as resp:
        sys.exit(0 if resp.getcode() == 200 else 1)
except Exception:
    sys.exit(1)
PY
    then
      ready=1
      break
    fi
    sleep 0.25
  done
  if (( ready != 1 )); then
    echo "server did not become healthy" >&2
    tail -n 40 "$s/logs/server.stderr" >&2 || true
    kill -TERM "$server_pid" 2>/dev/null || true
    sleep 1
    kill -KILL "$server_pid" 2>/dev/null || true
    rm -rf "$s"
    return 1
  fi

  "${common[@]}" "${OMNI_CMD[@]}" host --server "http://127.0.0.1:$port" --non-interactive --no-open \
    >"$s/logs/host.stdout" 2>"$s/logs/host.stderr" &
  local host_pid=$!

  ready=0
  for i in $(seq 1 80); do
    if ! pid_alive "$host_pid"; then
      echo "host exited early; stderr:" >&2
      tail -n 80 "$s/logs/host.stderr" >&2 || true
      kill -TERM "$server_pid" "$host_pid" 2>/dev/null || true
      rm -rf "$s"
      return 1
    fi
    if python3 - "$port" <<'PY'
import json, sys, urllib.request
port = sys.argv[1]
url = f"http://127.0.0.1:{port}/v1/hosts"
try:
    with urllib.request.urlopen(url, timeout=2) as resp:
        payload = json.loads(resp.read().decode())
except Exception:
    sys.exit(1)
rows = payload.get("hosts") if isinstance(payload, dict) else payload
if rows is None and isinstance(payload, dict):
    rows = payload.get("data")
online = 0
for row in rows if isinstance(rows, list) else []:
    if not isinstance(row, dict):
        continue
    status = str(row.get("status") or "").lower()
    if row.get("online") is True or status == "online":
        online += 1
sys.exit(0 if online >= 1 else 1)
PY
    then
      ready=1
      break
    fi
    sleep 0.25
  done
  if (( ready != 1 )); then
    echo "host did not come online" >&2
    tail -n 80 "$s/logs/host.stderr" >&2 || true
    kill -TERM "$server_pid" "$host_pid" 2>/dev/null || true
    sleep 1
    kill -KILL "$server_pid" "$host_pid" 2>/dev/null || true
    rm -rf "$s"
    return 1
  fi

  cat >"$STATE_FILE" <<EOF
SCRATCH_DIR=$s
SCRATCH_PORT=$port
SCRATCH_DATA=$s/data
SCRATCH_HOME=$s/home
SCRATCH_CONFIG=$s/config
SCRATCH_TMPDIR=$s/tmp
SERVER_PID=$server_pid
HOST_PID=$host_pid
OMNIGENT_BIN=$omnigent
WORKTREE=$ROOT
EOF
  echo "SCRATCH_DIR: $s"
  echo "SERVER_PID: $server_pid"
  echo "HOST_PID: $host_pid"
  echo "STATE_FILE: $STATE_FILE"
}

cmd="${1:-status}"
case "$cmd" in
  start) do_start ;;
  stop) do_stop ;;
  status) do_status ;;
  *)
    echo "usage: $0 {start|stop|status}" >&2
    exit 2
    ;;
esac
