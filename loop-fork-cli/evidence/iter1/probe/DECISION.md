# Clone vs `--fork-session` (iter 1)

Decision: **keep clone + `claude --resume <clone-id>`**.
Do not switch the same-host fork path to `claude --resume <source>
--fork-session`.

## Why clone+resume is the CLI fork we want

`_clone_claude_transcript` (`claude_native.py:1826-1898`) already is
the CLI fork: it copies the source JSONL into the clone's own
`~/.claude/projects/<enc(clone_cwd)>/<new-uuid>.jsonl`, rewrites
`sessionId`/`cwd`, then launches plain `--resume <new-uuid>`.
Codex mirrors this with `_clone_codex_rollout` + `codex resume`.

That is the same mechanism the source session uses (resume a local
transcript). The CLI still auto-compacts on the next turn.

## Why `--fork-session` on the SOURCE id is rejected

Documented in the clone helper itself (`:1840-1847`):

1. Worktree forks: `--fork-session` is cwd-scoped to the SOURCE
   project dir. The clone often runs in a different worktree, so
   resume would miss the new session file.
2. Forwarder double-render: we need the clone JSONL fully written
   before launch so `start_at_end` seeks past the copied prefix.
   `--fork-session` writes asynchronously via the CLI.
3. Source isolation: GOAL forbids touching the source transcript.
   `--fork-session` on the live source id is the opposite.

A 782 kB clone is fine; the 413s came from `guard_fork_context_bytes`
on the clone, not from `--resume`.

## Route knowledge (same-host native passthrough)

`fork_session` (`routes_core.py:2170+`) already has:

- `source.external_session_id` — native CLI session id
- `switching_agent` + `_same_provider_family` →
  `resume_source_native_session` (False for cross-family)
- `_agent_carries_native_fork_history(base_agent)` →
  `carry_history_into_native`
- truncated forks (`up_to_response_id`) skip the source-external
  label so the runner rebuilds from items

Passthrough = those four say "clone the native transcript", source
harness is claude-native or codex-native, and
`OMNIGENT_FORK_NATIVE_GUARD` is not `1`.
