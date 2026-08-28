# Builder brief — passthrough-fix

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`.
`cd /home/alex/omnigent-fixes` for every command. Tests:
`PYTHONPATH=/home/alex/omnigent-fixes`. Pre-commit:
`PATH=/home/alex/omnigent/.venv/bin:$PATH`.

Commit exactly: `slice(passthrough-fix): …` with trailer
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
Never amend/rebase/push/stash/reset/checkout. Never git in
`/home/alex/omnigent`. Never touch `:6767`, `omni host`, or write
`~/.omnigent` / `~/.claude/projects`. Leave mailbox files uncommitted.
Do not edit GOAL.md or VERDICT.md.

Large files (`routes_core.py`, `helpers.py`, `orchestration.py`,
`claude_native.py`, `chatStore.ts`) — grep/sed only, never full-file read.

## Diagnosed cause (do not re-guess)

`loop-fork-async/evidence/iter1/passthrough-why/DECISION.md`:
Web UI always sends `up_to_response_id` (ChatPage.tsx ~3860). Even
the LAST response covers every item (`items_after_cut=0`) but the
predicate at `routes_core.py` (~2352-2415) requires
`up_to_response_id is None`, so it logs
`fork passthrough skipped: up_to_response_id set` and compactes.
A POST with no fork point already passthroughs (201 in 134 ms).

Helper: `_native_clone_passthrough_skip_reasons` (~304-336).
`_items_through_response` ~236-246. Predicate uses that helper now.

## Required fix (smallest)

Treat a requested prefix that is the **entire** source item list as
a full fork for passthrough (last response ≡ no truncation).
Keep `up_to_response_id` on the store call if you want; the skip
check must not treat a full-prefix cut as a skip.

NEVER widen passthrough: cross-family, SDK sources, truncated
prefixes, and `OMNIGENT_FORK_NATIVE_GUARD=1` MUST still compact / 413.

## Tests (write first, watch fail, then implement)

Add to `tests/server/routes/test_fork_passthrough_skip.py` and/or
`tests/server/routes/test_fork_oversize_guard.py`:

1. Claude-native source with `external_session_id`, wrapper-style
   labels not required if harness is stubbed to `claude-native`,
   `up_to_response_id` = last item's response_id, oversized bytes,
   compact on → **201**, `replacement_items is None`, no skip log for
   that condition (or skip log absent).
2. Truncated prefix: `up_to_response_id` of the FIRST of two
   responses, oversized remaining prefix → still compact/413, skip
   log `up_to_response_id set` (or a more precise reason if you add
   one — do not drop the log).
3. SDK source with external id + native target still 413
   (`test_sdk_source_external_id_keeps_preflight_guard` must stay green).
4. Cross-family agent_id switch still compact path.

Commands:
```
cd /home/alex/omnigent-fixes
PYTHONPATH=/home/alex/omnigent-fixes uv run pytest -q \
  tests/server/routes/test_fork_passthrough_skip.py \
  tests/server/routes/test_fork_oversize_guard.py \
  tests/server/routes/test_fork_compact.py \
  tests/runner/test_fork_clone_fallback.py
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files \
  omnigent/server/routes/sessions/routes_core.py \
  tests/server/routes/test_fork_passthrough_skip.py \
  tests/server/routes/test_fork_oversize_guard.py
```

Keep functions small. Short scenario comments, no issue numbers.
Keep new test files focused. Do not start throwaway servers unless
a unit test cannot prove the predicate.
