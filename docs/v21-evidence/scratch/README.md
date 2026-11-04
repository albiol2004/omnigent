# v21 scratch consumer compatibility

Reproducible harness: an isolated Omnigent **server + host** from this
worktree, then read-only imports of trio `broker_http.py` and App Control
`dev_processes.py` / `omnigent_titles.py`.

## How to run

From the worktree root:

```bash
bash scripts/v21_consumer_compat.sh
```

That starts the stack (`scripts/v21_scratch_stack.sh start`), runs
`compat_checks.py`, then **always** stops the stack (`trap EXIT/INT/TERM`).
Overall wall clock is capped at 300 s.

Transcript:

- Without `V21_SCRATCH_TRANSCRIPT`, the script tees into the scratch dir
  (`/var/tmp/v21s.*/transcript.txt`) and prints `TRANSCRIPT: <path>` (then
  removes the scratch tree). It does **not** write any tracked file.
- To commit a passing run:

```bash
V21_SCRATCH_TRANSCRIPT=docs/v21-evidence/scratch/transcript.txt \
  bash scripts/v21_consumer_compat.sh
```

Stack only:

```bash
bash scripts/v21_scratch_stack.sh start   # prints SCRATCH_PORT: <n>
bash scripts/v21_scratch_stack.sh status
bash scripts/v21_scratch_stack.sh stop
```

State lives in `$V21_SCRATCH_STATE` (default `/var/tmp/v21s.state`).

## Isolation

Scratch root `S=$(mktemp -d /var/tmp/v21s.XXXXXX)` (short path for tmux
AF_UNIX). Server and host are exec'd under `env -i` with:

| var | value |
| --- | --- |
| PATH | `/usr/bin:/bin:/usr/local/bin:<venv>/bin` |
| LANG / LC_ALL | `C.UTF-8` |
| HOME | `$S/home` |
| OMNIGENT_DATA_DIR | `$S/data` |
| OMNIGENT_CONFIG_HOME | `$S/config` |
| TMPDIR | `$S/tmp` |

**Also set (necessary, not inherited OMNIGENT_TOKEN/URL):** `USER`,
`LOGNAME` (passwd/uid display), `PYTHONUNBUFFERED`, `PYTHONNOUSERSITE`,
`TERM=dumb`, `XDG_{CACHE,CONFIG,DATA,HOME,RUNTIME_DIR}` under `$S`,
`GIT_CONFIG_NOSYSTEM=1` + `GIT_CONFIG_GLOBAL=/dev/null` so git init in
`$S/ws` does not touch the operator config, `OMNIGENT_LOCAL_SINGLE_USER=1`
so token-less loopback auth matches the CLI default.

The venv is resolved **first** with the real `HOME` (`uv sync --frozen
--extra all --group dev` / `uv run ... print(sys.executable)`), then
`.venv/bin/omnigent` is exec'd under `env -i`.

Port: bind `127.0.0.1:0`, reject `{6767,6768,7456,8443}`, print
`SCRATCH_PORT: <n>`. No requests are sent to those ports; the check
process wraps `urlopen` / `OpenerDirector.open` and counts violations.

Kill policy: only PIDs this harness started, their `/proc` ppid
descendants, processes whose environ has
`OMNIGENT_DATA_DIR=<this run's data dir>` exactly, and `tmux -S` on
sockets under this run's TMPDIR. SIGTERM, wait, SIGKILL.

## Consumers (read-only)

Imported with `python -I -B`, `sys.dont_write_bytecode = True`,
`importlib.util.spec_from_file_location` (never writing into their trees):

- `/home/coder/personal/trio-agent-loop/omnigent/broker_http.py`
- `~/.local/share/trio-agent-loop/current/omnigent/trio-omnigent-roles/*/config.yaml`
  (copied into `$S/roles` before use)
- `/home/coder/personal/agent-platform/template/build/dev_processes.py`
- `/home/coder/personal/agent-platform/template/build/omnigent_titles.py`

`dev_processes` imports `op_control`; that module is stubbed in
`sys.modules` so we do not load 1Password helpers. Parser functions do not
need it.

After import, `_OMNIGENT_SESSIONS` / `_OMNIGENT_SESSION` are rewritten to
the scratch base. Titles calls pass `base=`. `BrokerClient(base_url=...)`
plus `OMNIGENT_URL`; `OMNIGENT_TOKEN` unset and `HOME=$S/home` so
`auth_token()` finds nothing.

## Facts relied on (worktree)

- Server flags `--host 127.0.0.1 --port N --no-open`: `omnigent/cli.py`
  4496–4561.
- Loopback bind without auth flags sets `OMNIGENT_LOCAL_SINGLE_USER=1`:
  `_apply_bind_auth_defaults`, `omnigent/cli.py` 1424–1480.
- Token-less requests act as user `local`: `omnigent/server/auth.py` 752–756.
- `omnigent host --server http://127.0.0.1:N --non-interactive --no-open`:
  `omnigent/cli.py` 9724–3762; identity under config/data dir
  `omnigent/host/connect.py` 6130–6162.
- Runner logs `$OMNIGENT_DATA_DIR/logs/runner/`: `omnigent/process_logging.py`
  288–344; host prefix `runner-{session_slug}` at
  `omnigent/host/connect.py` 2152–2322 (`session_slug` = first 32 word
  chars of the session id plus `-`; timestamp `%Y%m%d-%H%M%S-%f`).
- Host `_zygote` forkserver: `omnigent/runner/_zygote.py`,
  `omnigent/host/runner_zygote.py`.
- HTTP bundle allowlist `#10906`: `omnigent/server/bundles.py`
  `validate_agent_bundle`; unregistered `type: function` and
  `os_env.cwd` absolute / `..` refused. Trio's
  `omnigent.inner.nessie.policies.blast_radius` is a registered shim.
- `#10850` owner for PATCH/DELETE; `/events` POST needs edit, `/items` need
  read. `broker_http.py` has **no** `permission_mode` helper (PATCH
  `runner_id` / `archived` only); the check PATCHes `permission_mode`
  directly as the same token-less owner.

## How to read the transcript

Each check prints exactly `CHECK <name>: PASS` or `CHECK <name>: FAIL
<reason>`. Extra diagnostic lines (agent ids, exception class for the
unanswered first prompt, PATCH body, runner pid, log hex relation, environ
allowlist, runner log basenames, guarded-opener count) appear above those
lines. Last line of the script:

```
<passed> passed, <failed> failed in <s>s
```

Exit 0 only if every CHECK passed.

`create_session` waits `prompt_timeout=20` (`TRIO_OMNIGENT_PROMPT_WAIT=20`).
Under the scratch HOME, cursor-agent is **not** logged in; a first-prompt
timeout (`PromptDeliveryUncertain`) is acceptable so long as the session id
exists and a zygote-forked runner launched.

## CHECK → accepts

- `trio-broker` → broker register (every trio role bundle) / host-launched
  session / GET one / POST events / GET items / GET list.
- `runner-gone-after-delete` → DELETE 2xx, then within 60 s the zygote-forked
  runner (the pid holding the runner log fd, which App Control maps to the
  session id) and every process whose environ names the session are gone,
  while scratch server+host stay up. The runner pid must be in the tracked
  set (its environ is the zygote's, so an environ scan alone misses it).
- `bundle-restrictions-10906` → #10906 4xx for unregistered handler,
  absolute and `..` cwd; unmodified trio role bundles accepted.
- `ownership-10850` → the same token-less caller (trio's single-user loopback
  auth) can GET, POST `/events`, GET `/items` and DELETE the session it
  created (emitted after the DELETE).
- `appcontrol-dev-processes`, `appcontrol-titles` → App Control parsers.
- `teardown-clean` → no leftover `OMNIGENT_DATA_DIR` processes; 0 guarded
  opener violations.

## Incompatibilities

(Filled if a CHECK fails because a consumer expectation no longer matches
v0.21, not because of a harness bug.)

- **`/v1/sessions/{id}/events` is POST-only** — trio `broker_http.py` only
  **POST**s this path (`send_message` / `input_fence`). The v0.21 server
  exposes POST `/events` and GET `/stream` (SSE)
  (`omnigent/server/routes/sessions/routes_events.py` `@event_router.post`
  `/sessions/{session_id}/events` and `@router.get` `/sessions/{session_id}/stream`),
  no JSON GET `/events`. The events check therefore drives trio's own
  `BrokerClient.send_message` (POST, expects 202); 401/403/404 always FAIL,
  only a 409/422 session-state refusal is tolerated (route+auth reached).
  Recorded run: `POST /events -> 202`. No consumer change needed.
- **PATCH `permission_mode`** — `broker_http.py` has no helper. Direct
  PATCH as the token-less owner against a **cursor-native** session returns
  HTTP 400 `permission_mode is only supported for claude-native and
  devin-native sessions`. Read `/items` and DELETE still succeed (#10850).
  No consumer change; trio does not PATCH this field.
- **Runner log basename vs App Control `_RUNNER_LOG`**
  (`dev_processes.py` 34–35): regex
  `^runner-([0-9a-f]{32})-\d{8}-\d{6}-\d+\.log$`. With v0.21 32-hex session
  ids the on-disk name
  `runner-<32hex>-<YYYYMMDD>-<HHMMSS>-<microseconds>.log` **matches**. The
  fd lives on the zygote-forked runner (`_zygote` in argv), not on the
  tmux/cursor-agent children. `_read_environ` allowlisted keys
  (`OMNIGENT_RUNNER_PRIMARY_SESSION_ID`, `OMNIGENT_RUNNER_WORKSPACE`,
  `OMNIGENT_TERMINAL_LAUNCH_SESSION_ID`) show up on the **tmux/harness**
  processes, not always on the zygote child itself. App Control already
  falls back from log-fd hex to those env keys (`dev_processes.py`
  823–853). No fork required for 32-hex ids; a regex relaxation would
  still help if session ids ever leave that shape. Do **not** change
  `omnigent/` in this slice; Lead decides.
