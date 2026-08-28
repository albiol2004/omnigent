# REPORT — iter 1 Lead (cursor-native streaming)

Mailbox `loop-cursor-stream/`. Product HEAD after this pass:
`9beb255aa` on `trio-v0.10.0-fixes` (worktree `/home/alex/omnigent-fixes`).
Probe had no product commit. Luna workers: `gpt-5.6-luna-max`
(`trioctl omnigent resolve builder`). Captured `trioctl` stdout under
`loop-cursor-stream/evidence/iter1/_trioctl/`.

`python3 /home/alex/pruebas/agent-trio-template/metrics/trio-shadow.py --mailbox loop-cursor-stream --require-commits` → **exit 0**.

## slice 0 probe-partial-text — evidence only

Command:
`trioctl omnigent run builder --prompt-file loop-cursor-stream/briefs/probe.md --workspace /home/alex/omnigent-fixes --timeout 1800`
→ exit 0 (~328s). Luna id in DECISION: `gpt-5.6-luna`.

Evidence: `loop-cursor-stream/evidence/iter1/probe/`.
231 paired samples, ~100 ms cadence.

- Store: **complete-only**. First assistant blob at **21700 ms**,
  rowid 11, 21631 bytes / 6434 chars. No in-place growth.
- Pane: first `🤖` assistant text at **16300 ms**; pane led store by
  **5.4 s**.
- **CHOICE: `pane-diff`** (justified: no partial store blobs).

Deviation: none vs GOAL prefer-store-if-partial. Weakness: 100 ms
cadence cannot prove a sub-interval store write.

## slice 1 cursor-delta-source — `87482f1f8`

Command:
`trioctl omnigent run builder --prompt-file loop-cursor-stream/briefs/cursor-delta-source.md --workspace /home/alex/omnigent-fixes --timeout 1800`
→ exit 0 (~555s). Luna: `gpt-5.6-luna`. Lead then kept fast poll
while Working, rewind-on-POST-fail.

Paths: `omnigent/cursor_native_stream.py`,
`omnigent/_native_output_text_delta.py`,
`omnigent/cursor_native_forwarder.py`,
`omnigent/cursor_native_bridge.py` (`capture_cursor_pane_for_stream`),
`omnigent/claude_native_forwarder.py` (shared POST),
`omnigent/inner/cursor_native_executor.py` (doc only;
`supports_streaming()` stays **False**, same as claude-native).
`chatStore.ts` **not** changed — existing `live:<messageId>` splice
handles hand-off (`chatStore.ts` ~4230-4648).

Env: `OMNIGENT_CURSOR_STREAM` default on; `0` skips pane deltas.

Tests (Lead):
```
uv run pytest -q tests/test_cursor_native_stream.py \
  tests/test_cursor_native_forwarder.py \
  tests/inner/test_cursor_native_executor.py \
  tests/test_claude_native_forwarder.py::test_post_external_output_text_delta_sends_expected_payload
# 110 passed (+ 1 claude POST test)
```
Builder also ran the full claude forwarder file (260 passed).
`pre-commit run --files` on those Python files: passed.
No vitest (store untouched).

## slice 2 cursor-stream-e2e — `9beb255aa`

Command:
`uv run python loop-cursor-stream/evidence/iter1/e2e/run_e2e.py`
Throwaway: port **17201**, scratch `/tmp/cursor-stream-e2e-oy655atu`,
real `cursor-agent`.

Final `NUMBERS.json`:
- `delta_count`: **26**
- `byte_equal`: **true** (4901 bytes)
- inject → first delta: **71.005 s** (model TTFT, not poll lag)
- first delta → complete item: **5.875 s** (~226 ms/delta, **< 1.5 s**
  after generation is visible)
- no duplicate complete-item vs live preview in unit tests; e2e SSE
  showed deltas then the complete item

Fixes the e2e revealed: stream even before the store row exists;
keep `🤖` and unwrap pane wrap-newlines so concat == store text.

```
uv run pytest -q tests/test_cursor_native_forwarder.py \
  tests/test_claude_native_forwarder.py \
  tests/test_cursor_native_stream.py \
  tests/inner/test_cursor_native_executor.py
# 262 passed in 27.76s

uv run pytest -q tests/tools/builtins/test_spawn.py \
  tests/runner/test_runner_dispatch.py \
  tests/server/integration/test_sessions_child_sessions.py \
  -k 'reasoning_effort or session_create_spawns_child_under_caller or registered_native_agent_create_derives_launch_args_from_root_spec'
# 5 passed, 250 deselected in 2.77s
```
pre-commit on slice-2 files: passed.

Deviations: first e2e used `/c/<32hex>` ids (not `conv_*`); `-f` still
showed Workspace Trust — `--force --trust` required. User host
websocket briefly attached to the throwaway server (inbound); testdb
mtime unchanged.

## Isolation audit (GOAL Acceptance 4)

| Check | Baseline | After |
|---|---|---|
| `curl` `:6767/health` | 200 | **200** |
| `stat -c %Y /home/alex/omnigent-fixes-data/chat.db` | 1787905289 | **1787905289** |
| listeners `:17200-17299` | n/a | **none** |

`find ~/.cursor -newer loop-cursor-stream/GOAL.md -type f | head`
lists Cursor **runtime** files only (agent transcripts, `chats/*/store.db*`,
throwaway workspace trust). We did not edit `~/.cursor` by hand.
Did not touch `~/.omnigent`, `~/.claude/projects`, `:17067` data,
`/home/alex/omnigent`. Did not kill `:6767` (pid 1270937 left running).
Default user tmux session `main` left untouched.

## iter 1 repair 1 — replay, marker, and tool-chrome fixes

The final throwaway rerun used port **17200**, scratch
`/tmp/cursor-stream-e2e-kmmrisji`, and conversation
`6c1e5743e96e4b639773f8c8065e0e37`.

- First turn: **17** deltas, joined/complete lengths **4979 / 4979**,
  `byte_equal: true`.
- Complete item observed at **60.981 s**; the post-completion watch lasted
  **10.009 s** and observed **0** deltas.
- The second prompt produced **1** delta under
  `cursor-live-6c1e5743e96e4b639773f8c8065e0e37-1`;
  `second_message_id_is_new: true`.
- `ss -ltnp | rg ':172'` was empty after teardown.

Verification:

```text
uv run pytest -q tests/test_cursor_native_forwarder.py tests/test_cursor_native_stream.py
77 passed in 1.27s
uv run pre-commit run --files <scoped files>
exit 0
uv run python loop-cursor-stream/evidence/iter1/e2e/run_e2e.py
exit 0
```

## Operator steps (GOAL Acceptance 5)

On the **test instance** (`:17067`, data dir
`/home/alex/omnigent-fixes-data`) — Lead did not restart it:

1. Web rebuild is **not** required (chatStore unchanged). Restart the
   test **server and runner** so they load the repaired cursor stream code.
2. Open a cursor-native session and send a long prompt. Assistant
   text should appear in the web transcript while Cursor is still
   generating, then snap to the same complete item.
3. Optional: `OMNIGENT_CURSOR_STREAM=0` restores complete-item-only.
   Poll knobs: `OMNIGENT_CURSOR_POLL_FAST_S` / `_IDLE_S`.

Live deploy/rollback (same as `loop-fixes/REPORT.md`): deploy into
`/home/alex/omnigent` (or the running checkout), **not** this
worktree; restart server and runner (no web rebuild). Rollback:
previous live ref, restart. Env `OMNIGENT_CURSOR_STREAM=0` is a
behavior rollback without reverting the commit.
