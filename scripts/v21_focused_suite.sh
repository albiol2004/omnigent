#!/usr/bin/env bash
# Focused v0.21 regression suite recorder (copied from the v17 runner).
# Usage: scripts/v21_focused_suite.sh [OUTFILE]
# Group patterns are identical to v17; every pattern was verified against the
# v0.21.0rc1 test tree (no upstream test moves; fork-only files such as
# tests/server/integration/test_input_fence.py and test_cursor_*.py are ABSENT
# on pristine rc1 and reported as such).
# Env knobs: V21_USE_TRIO_TEST=1 runs each group's pytest through trio-test
# (needed inside a Trio loop; V21_TT_FRESH=1 adds --fresh to skip result reuse); V21_ONLY="g1 g2" restricts to named groups.
# V21_PER_FILE=1 runs one pytest process per file inside each group (section
# header `== <group> :: <file> ==`); default output is unchanged.
# V21_TRIO_TEST_ROLE=<role> sets the trio-test --role label (default builder).
# V21_PYTEST_ARGS="--timeout=60 --capture=sys" appends extra pytest args (split on
# whitespace; empty by default).
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
if git diff --quiet v0.21.0rc1 HEAD -- . ':!loop' ':!scripts/v21_focused_suite.sh' ':!docs/v21-evidence' 2>/dev/null; then
  emit "pristine-vs-v0.21.0rc1: yes"
else
  emit "pristine-vs-v0.21.0rc1: no"
fi
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

# run_group TAG FILE... : run one pytest process over FILE... and emit its
# summary line plus FAILED/ERROR node ids (log/label name derives from TAG).
run_group() {
  local tag="$1"; shift
  log="$LOGDIR/v21-suite-$tag.log"
  if [ "${V21_USE_TRIO_TEST:-0}" = "1" ] && command -v trio-test >/dev/null 2>&1; then
    # Inside a Trio loop: run each group's targeted pytest through trio-test
    # (resume with `trio-test wait` on exit 75) and copy its full log.
    tt_out="$LOGDIR/v21-suite-$tag.tt"
    trio-test run --label "v21-suite-$tag" ${V21_TT_FRESH:+--fresh} --role "${V21_TRIO_TEST_ROLE:-builder}" --foreground-s 600 -- \
      timeout 2400 uv run --frozen pytest -q -p no:cacheprovider -rfE ${V21_PYTEST_ARGS:-} "$@" > "$tt_out" 2>&1
    rc=$?
    while [ "$rc" -eq 75 ]; do
      handle="$(grep -oE 'handle=[^ ]+' "$tt_out" | tail -n1 | cut -d= -f2)"
      trio-test wait "$handle" > "$tt_out" 2>&1
      rc=$?
    done
    ttlog="$(grep -oE 'log=[^ ]+' "$tt_out" | tail -n1 | cut -d= -f2)"
    if [ -n "$ttlog" ] && [ -f "$ttlog" ]; then cp "$ttlog" "$log"; else : > "$log"; fi
  else
    timeout 2400 uv run --frozen pytest -q -p no:cacheprovider -rfE ${V21_PYTEST_ARGS:-} "$@" > "$log" 2>&1
    rc=$?
  fi

  if [ "$rc" -eq 124 ]; then
    emit "TIMEOUT after 2400s"
  else
    summary="$(grep -E '^(=+ )?[0-9]+ (failed|passed|skipped|error|errors|xfailed|xpassed|warnings?|deselected)|^(=+ )?no tests ran' "$log" | tail -n1 | sed -E 's/^=+ //; s/ =+$//')"
    if [ -z "$summary" ] && grep -q '^+\{5,\} Timeout +\{5,\}' "$log"; then
      summary="PYTEST-TIMEOUT-HANG (per-test timeout killed the run; see $log)"
    fi
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
}

for spec in "${GROUPS_SPEC[@]}"; do
  name="${spec%%|*}"
  patterns="${spec#*|}"
  if [ -n "${V21_ONLY:-}" ] && [[ " $V21_ONLY " != *" $name "* ]]; then
    continue
  fi
  emit "== $name =="

  files=()
  absent=()
  for pat in $patterns; do
    matched=( $pat )   # unquoted: glob expands at run time (nullglob)
    found=0
    for m in "${matched[@]+"${matched[@]}"}"; do
      # nullglob keeps a literal (non-glob) path that does not exist
      if [ -d "$m" ]; then
        # Expand directories to explicit test files (same selection pytest
        # makes; also keeps trio-test from refusing a directory as "whole suite").
        while IFS= read -r f; do
          files+=( "$f" )
          found=1
        done < <(find "$m" -name 'test_*.py' -type f | LC_ALL=C sort)
      elif [ -e "$m" ]; then
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

  if [ "${V21_PER_FILE:-0}" = "1" ]; then
    # Opt-in: one pytest process per file; header `== <group> :: <file> ==`.
    for f in "${files[@]}"; do
      emit "== $name :: $f =="
      emit "files: $f"
      run_group "$name--$(basename "$f" .py)" "$f"
    done
  else
    run_group "$name" "${files[@]}"
  fi
done

emit "SUITE_DONE"
exit 0
