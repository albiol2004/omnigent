# Builder brief — slice codex-writer-resume

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent`. Mailbox `loop-stability/`. Iteration 1.

Do NOT read whole large files. Use grep/Read with the line ranges
below. Do NOT commit (Lead commits). Do NOT amend/rebase/push.
Do NOT start a live Codex login. Do NOT edit orchestration.py in
this slice (reads only).

PATH: `PATH=/home/alex/omnigent/.venv/bin:$PATH`

## Writes (only)

- `omnigent/codex_native_app_server.py`
- `tests/test_codex_native.py`

## Line ranges (HEAD 6ed9800e3)

- `CodexAppServerClient.request` 524–600
  (`raise RuntimeError(str(error))` at 551–552)
- `preload_codex_thread_for_resume` 2645–2683
  (`thread/resume` with `excludeTurns: True`)
- Existing test `test_preload_codex_thread_for_resume_resumes_and_closes`
  in `tests/test_codex_native.py` ~460–517
- Fake client `_FakeCodexAppServerClient` ~360–429
  (`error=` already raises from `request`)

## Failure (Azure log, no live repro required)

`loop-stability/evidence/azure-runner-4ada6cb3-codex-start-failure.log`

Preload raises:

`RuntimeError: {'code': -32600, 'message': 'thread 01a07b94-6560-7623-af8b-ddfec31fee57 already has an active writer'}`

That aborts `_auto_create_codex_terminal` before `write_bridge_state`.
`_ensure_native_terminal` retries and fails the same way.

## Required behavior (test-first)

1. Add a unit test that configures `_FakeCodexAppServerClient(error=RuntimeError("{'code': -32600, 'message': 'thread 01a07b94-6560-7623-af8b-ddfec31fee57 already has an active writer'}"))`, monkeypatches `CodexAppServerClient` like the existing preload test, calls `preload_codex_thread_for_resume`, and asserts: does **not** raise; `connected` and `closed` are True; `thread/resume` was still attempted.
2. Add a unit test that a different error (e.g. code -32601 or message `thread not found`) **does** raise, and the client still closes.
3. Run the new tests and confirm they **fail** on current code; then implement; then they pass.
4. Implementation: in `preload_codex_thread_for_resume` only (do not change generic `request()` for all methods), treat JSON-RPC -32600 + "already has an active writer" as success (thread already loaded by an existing writer). Keep `finally: close()`. Parse the RuntimeError string robustly (dict-repr as in the log).
5. Keep `test_preload_codex_thread_for_resume_resumes_and_closes` passing.

## Test command

```
cd /home/alex/omnigent && uv run pytest -q tests/test_codex_native.py -k preload_codex
```

Capture stdout/stderr to
`loop-stability/evidence/iter1/codex-writer-resume/pytest.txt`
(mkdir -p that dir). Write a 5–10 line
`loop-stability/evidence/iter1/codex-writer-resume/NOTES.md`
with what you changed and why.

Keep files focused. Lots of short comments on the new helper/tests.
Lines < 88 chars. `dict`/`list`/`type` not typing.Dict/List/Type.
