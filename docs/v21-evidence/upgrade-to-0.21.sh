#!/usr/bin/env bash
# Adopt the Omnigent fork branch trio-v0.21.0-fixes in the live editable install,
# with a full snapshot (including sqlite3 .backup of chat.db) and automatic
# rollback when the server/host do not come back healthy.
#
# Adapted from ~/.local/state/omnigent-upgrade/upgrade-to-0.14.sh (read-only).
# DOCUMENTATION ONLY in the v21-risks slice: do not execute against the live
# install unless a human sets CONFIRM_LIVE_UPGRADE=1.
#
#   CONFIRM_LIVE_UPGRADE=1 upgrade-to-0.21.sh            upgrade
#   CONFIRM_LIVE_UPGRADE=1 upgrade-to-0.21.sh rollback   newest snapshot
set -u
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

if [ "${CONFIRM_LIVE_UPGRADE:-}" != "1" ]; then
  echo "refuses to run unless CONFIRM_LIVE_UPGRADE=1" >&2
  exit 1
fi

STATE="$HOME/.local/state/omnigent-upgrade"
LIVE="$HOME/omnigent"
TOOL_ENV="$HOME/.local/share/uv/tools/omnigent"
DATA="${OMNIGENT_DATA_DIR:-$HOME/.omnigent}"
UI_REL="omnigent/server/static/web-ui"
OLD_REF="trio-v0.17.0-fixes"
NEW_REF="trio-v0.21.0-fixes"
BASE="http://127.0.0.1:6767"
# Head revision after v0.17.0..v0.21.0rc1 migrations (docs/v21-report.md §7.1).
EXPECT_ALEMBIC="d0a1f879a01d"

LOG="$STATE/upgrade-0.21.log"
say() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }
result() { printf '%s\n' "$1" > "$STATE/RESULT"; say "RESULT: $1"; }

wait_health() {
  local deadline=$((SECONDS + $1))
  while [ $SECONDS -lt $deadline ]; do
    curl -s -m 3 "$BASE/health" | grep -q '"ok"' && return 0
    sleep 3
  done
  return 1
}

wait_host_online() {
  local deadline=$((SECONDS + $1))
  while [ $SECONDS -lt $deadline ]; do
    curl -s -m 5 "$BASE/v1/hosts" | python3 -c '
import sys, json
hosts = json.load(sys.stdin).get("hosts", [])
sys.exit(0 if any(h.get("status") == "online" for h in hosts) else 1)' 2>/dev/null && return 0
    sleep 3
  done
  return 1
}

stop_services() {
  svc stop omnigent-host >>"$LOG" 2>&1 || true
  svc stop omnigent >>"$LOG" 2>&1 || true
  for _ in $(seq 1 20); do
    ss -ltn 2>/dev/null | grep -q '127.0.0.1:6767 ' || return 0
    sleep 1
  done
  say "port 6767 still bound after stop"
  return 1
}

start_services() {
  svc start omnigent >>"$LOG" 2>&1
  wait_health "$1" || { say "server did not become healthy"; return 1; }
  svc start omnigent-host >>"$LOG" 2>&1
  wait_host_online 120 || { say "host did not come online"; return 1; }
  return 0
}

snapshot_db() {
  local snap="$1"
  mkdir -p "$snap"
  if [ ! -f "$DATA/chat.db" ]; then
    say "no chat.db at $DATA/chat.db"
    return 1
  fi
  # Consistent copy of chat.db including WAL contents (mandatory: forward-only migrations).
  sqlite3 "$DATA/chat.db" ".backup '$snap/chat.db'"
  cp -a "$DATA/chat.db-wal" "$DATA/chat.db-shm" "$snap/" 2>/dev/null || true
  [ -f "$snap/chat.db" ]
}

restore_db() {
  local snap="$1"
  rm -f "$DATA/chat.db" "$DATA/chat.db-wal" "$DATA/chat.db-shm"
  cp -a "$snap/chat.db" "$DATA/chat.db"
  cp -a "$snap"/chat.db-wal "$DATA/" 2>/dev/null || true
  cp -a "$snap"/chat.db-shm "$DATA/" 2>/dev/null || true
}

rollback() {
  local snap="$1"
  say "ROLLBACK from $snap"
  stop_services
  git -C "$LIVE" checkout -q "$OLD_REF" >>"$LOG" 2>&1 || say "git checkout $OLD_REF failed"
  if [ -f "$snap/working-tree.diff" ] && [ -s "$snap/working-tree.diff" ]; then
    git -C "$LIVE" apply "$snap/working-tree.diff" >>"$LOG" 2>&1 || say "working-tree.diff apply failed"
  fi
  if [ -d "$snap/web-ui" ]; then
    rm -rf "$LIVE/$UI_REL" && cp -a "$snap/web-ui" "$LIVE/$UI_REL"
  fi
  if [ -d "$snap/tool-env" ]; then
    rm -rf "$TOOL_ENV" && cp -a "$snap/tool-env" "$TOOL_ENV"
  fi
  if [ -f "$snap/chat.db" ]; then
    restore_db "$snap"
  fi
  if start_services 180; then
    result "rolled_back ($(omni --version 2>&1 | head -1))"
  else
    result "rollback_failed: services down, see $LOG; snapshot at $snap"
  fi
}

if [ "${1:-}" = "rollback" ]; then
  snap="$(ls -1d "$STATE"/snapshot-0.21-* 2>/dev/null | tail -1)"
  [ -n "$snap" ] || { say "no snapshot to roll back to"; exit 1; }
  rollback "$snap"
  exit 0
fi

: > "$STATE/RESULT"
say "=== upgrade to $NEW_REF starting"

SNAP="$STATE/snapshot-0.21-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$SNAP"

say "stopping services"
stop_services || { svc start omnigent >>"$LOG" 2>&1; svc start omnigent-host >>"$LOG" 2>&1; result "aborted: could not stop services cleanly"; exit 1; }

say "snapshot -> $SNAP"
snapshot_db "$SNAP" || { start_services 120; result "aborted: sqlite3 .backup of chat.db failed"; exit 1; }
cp -a "$TOOL_ENV" "$SNAP/tool-env" 2>/dev/null || true
if [ -d "$LIVE/$UI_REL" ]; then
  cp -a "$LIVE/$UI_REL" "$SNAP/web-ui"
fi
git -C "$LIVE" rev-parse HEAD > "$SNAP/old-head"
git -C "$LIVE" branch --show-current > "$SNAP/old-branch"
git -C "$LIVE" diff > "$SNAP/working-tree.diff"
if [ ! -f "$SNAP/chat.db" ]; then
  say "snapshot incomplete (chat.db)"; start_services 120; result "aborted: snapshot failed"; exit 1
fi

say "switching $LIVE to $NEW_REF"
if ! git -C "$LIVE" checkout -q "$NEW_REF" >>"$LOG" 2>&1; then
  rollback "$SNAP"; exit 1
fi

say "reinstalling the tool environment"
if ! uv tool install --python 3.12 --editable "$LIVE" --force >>"$LOG" 2>&1; then
  say "uv tool install failed"; rollback "$SNAP"; exit 1
fi
ver="$(omni --version 2>&1 | head -1)"
say "installed: $ver"

say "starting services (database migration runs on first start: mm1a2b3c4d5e -> $EXPECT_ALEMBIC)"
if start_services 300; then
  got="$(sqlite3 "$DATA/chat.db" 'select version_num from alembic_version' 2>/dev/null || true)"
  say "alembic_version=$got (expect $EXPECT_ALEMBIC)"
  if [ "$got" != "$EXPECT_ALEMBIC" ]; then
    say "alembic head mismatch"; rollback "$SNAP"; exit 1
  fi
  result "upgraded: $ver; snapshot kept at $SNAP"
else
  rollback "$SNAP"
  exit 1
fi
