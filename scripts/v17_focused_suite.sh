#!/usr/bin/env bash
# Focused v0.17 regression suite recorder.
# Usage: scripts/v17_focused_suite.sh [OUTFILE]
# Runs 11 pytest groups (one process each), prints/records per-group summary
# lines and FAILED/ERROR node ids. Always exits 0; last line is SUITE_DONE.
set -u

OUTFILE="${1:-}"
cd "$(git rev-parse --show-toplevel)" || exit 0
shopt -s nullglob

LOGDIR="${TMPDIR:-}"
if [ -z "$LOGDIR" ] || [ ! -d "$LOGDIR" ]; then
  LOGDIR="$(mktemp -d)"
fi

if [ -n "$OUTFILE" ]; then
  : > "$OUTFILE"
fi

emit() {
  printf '%s\n' "$*"
  if [ -n "$OUTFILE" ]; then
    printf '%s\n' "$*" >> "$OUTFILE"
  fi
}

emit "rev: $(git rev-parse HEAD)"
emit "tmpdir: ${TMPDIR:-}"

GROUPS_SPEC=(
  "dispatch|tests/runner/test_runner_dispatch.py"
  "interrupt|tests/runner/test_native_interrupt_runner.py"
  "runner-native|tests/runner/test_app_sessions_native_*.py tests/runner/test_app_cursor_native_*.py"
  "sys-session|tests/tools/builtins/test_sys_session.py"
  "terminals|tests/terminals"
  "claude-native|tests/harnesses/claude_native"
  "codex-native|tests/harnesses/codex_native"
  "cursor-native|tests/test_cursor_native*.py tests/inner/test_cursor_native_executor.py"
  "inner-proc|tests/inner/test_proc_and_platform.py"
  "host|tests/host/test_connect.py"
  "sessions-routes|tests/server/integration/test_sessions_compact.py tests/server/integration/test_input_fence.py tests/server/integration/test_cursor_*.py tests/server/integration/test_routes_sessions_*.py"
)

for spec in "${GROUPS_SPEC[@]}"; do
  name="${spec%%|*}"
  patterns="${spec#*|}"
  emit "== $name =="

  files=()
  absent=()
  for pat in $patterns; do
    matched=( $pat )   # unquoted: glob expands at run time (nullglob)
    found=0
    for m in "${matched[@]+"${matched[@]}"}"; do
      # nullglob keeps a literal (non-glob) path that does not exist
      if [ -e "$m" ]; then
        files+=( "$m" )
        found=1
      fi
    done
    if [ "$found" -eq 0 ]; then
      absent+=( "$pat" )
    fi
  done

  for a in "${absent[@]+"${absent[@]}"}"; do
    emit "ABSENT $a"
  done

  if [ "${#files[@]}" -eq 0 ]; then
    emit "ABSENT-GROUP"
    continue
  fi

  emit "files: ${files[*]}"

  log="$LOGDIR/v17-suite-$name.log"
  timeout 2400 uv run --frozen pytest -q -p no:cacheprovider -rfE "${files[@]}" > "$log" 2>&1
  rc=$?

  if [ "$rc" -eq 124 ]; then
    emit "TIMEOUT after 2400s"
  else
    summary="$(grep -E '^(=+ )?[0-9]+ (failed|passed|skipped|error|errors|xfailed|xpassed|warnings?|deselected)|^(=+ )?no tests ran' "$log" | tail -n1 | sed -E 's/^=+ //; s/ =+$//')"
    if [ -z "$summary" ]; then
      summary="NO-SUMMARY (pytest exit $rc; see $log)"
    fi
    emit "$summary"
  fi

  # Failed/error node ids from the -rfE short summary, message stripped.
  # Only the section after "short test summary info" (captured log lines can
  # also start with "ERROR "); node ids never contain spaces, so a single
  # space after the keyword excludes "ERROR    logger:..." log lines.
  awk '/short test summary info/ {s=1; next} s' "$log" | grep -E '^(FAILED|ERROR) [^ ]' | sed -E 's/ - .*$//' | sort -u | while IFS= read -r line; do
    emit "$line"
  done
done

emit "SUITE_DONE"
exit 0
