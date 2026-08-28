# Probe facts (iter 1)

Scratch cwd: `/tmp/fork-cli-probe-scratch2` (never a user workspace).

## Failed probe (inherited API key)

`claude -p --model fable --output-format json "Reply with OK"`
with `ANTHROPIC_API_KEY` set (invalid key in this environment):

- wall_sec=183.39 exit=1
- `apiKeySource`: `ANTHROPIC_API_KEY`
- stderr: claude.ai login overridden by the key
- JSON array; last `type=result`, `is_error=true`,
  `result="Failed to authenticate. API Error: 401 API key is invalid."`

`--mcp-config '{}'` is invalid (`mcpServers` must be a record).
`--bare` must NOT be used: it forces `ANTHROPIC_API_KEY` / apiKeyHelper
and never reads OAuth.

`--setting-sources ''` with no `--safe-mode` hung until killed
(this loop started that process; it was terminated).

## Successful probe (subscription)

```
cd /tmp/fork-cli-probe-scratch2
env -u ANTHROPIC_API_KEY -u CLAUDE_API_KEY -u ANTHROPIC_AUTH_TOKEN \
  claude -p --model fable --output-format json --safe-mode \
  --strict-mcp-config --mcp-config empty-mcp.json \
  --no-session-persistence "Reply with OK"
```

`empty-mcp.json` = `{"mcpServers":{}}`

- wall_sec=2.27 exit=0
- `duration_ms` (inside JSON)=1245
- stdout: JSON **array** (not a single object)
- events: system, rate_limit_event, assistant, rate_limit_event, result
- last `type=result`, `is_error=false`, `result="OK"`
- init `model=claude-fable-5`, `apiKeySource=none`, `mcp_servers=[]`
- `--output-format json` still emits an array; parse last `type==result`

## Flags from `--help` (do not use `--bare`)

Claude: `-p/--print`, `--model`, `--output-format json`,
`--safe-mode`, `--strict-mcp-config`, `--mcp-config`,
`--setting-sources`, `--disable-slash-commands`,
`--no-session-persistence`.

Codex: `codex exec --model <m>`; `--json` is JSONL events;
`-o/--output-last-message FILE`; `--ephemeral`; `--ignore-user-config`;
`--skip-git-repo-check`; `--sandbox read-only`. There is no `-q`.
Do not use `codex exec -p` (`-p` is `--profile`).

## Headless helpers in-tree (do not misuse)

`omnigent/chat.py:2110` `_run_local_headless_prompt` and `:2162`
`_run_headless_prompt` POST to an Omnigent server. They are not
`claude -p` wrappers.

`omnigent/inner/kimi_executor.py:304-336` is the argv pattern:
`--output-format` then `-p <prompt>` last.

`omnigent/inner/_proc.spawn_kwargs()` → `start_new_session=True`.

Layer 2 prompt: `omnigent/llms/summarize.py` `_SUMMARIZATION_BASE_PROMPT`
via `build_summarization_prompt` + `build_summarization_input`.
`extract_summary_text` reads `resp.output[].content[].text`.
