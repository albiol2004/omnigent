# Builder: sqlite-pool

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`
(branch `trio-v0.10.0-fixes`). Implement **only** this slice.

## HARD isolation (non-negotiable)
This is the user's production machine. Never read/write `~/.omnigent`,
`~/.claude/projects`, `~/.cursor`. Never talk to
`http://127.0.0.1:6767`. Never restart/kill `omni host`, the runner, or
any process you did not start. Never run git in `/home/alex/omnigent`.
Work ONLY under `/home/alex/omnigent-fixes`. If you need a server, use
`OMNIGENT_DATA_DIR=<scratch>` (see `omnigent/cli.py` around `_DATA_DIR_ENV_VAR`
= `OMNIGENT_DATA_DIR`), port ≥ 17000, tear it down yourself. This slice
should need **no server** — temp sqlite only.

Do not edit `loop-fixes/GOAL.md` or `loop-fixes/VERDICT.md`. Do not
touch other slices' files.

## How to read code
NEVER ingest whole files. Use `sed -n 'a,bp'` / `rg -n`. Diagnosed
ranges (do not "read the file"):

- `omnigent/db/utils.py:228-238` — sqlite `create_engine` with only
  `connect_args={"check_same_thread": False, "timeout": 20.0}` and
  **no** pool kwargs. SQLAlchemy defaults = size 5, overflow 10,
  timeout 30 s (matches production QueuePool errors).
- `omnigent/db/utils.py:247-256` — connect hook already sets WAL,
  `busy_timeout=20000`, `synchronous=NORMAL`, `foreign_keys=ON`. Keep it.
- `omnigent/db/utils.py:268-289` — Postgres spirit: `pool_pre_ping`,
  `pool_size`, `max_overflow`, `pool_timeout=10`. Do **not** copy
  `pool_size=200` onto sqlite.

Existing test that will need updating (it currently asserts sqlite
skips server pool settings):
`tests/db/test_utils.py:87-128`
`test_sqlite_engine_skips_server_pool_settings_and_enables_wal`.

## Task
1. Parse env ints with sane defaults (modest vs postgres; sqlite is
   single-writer): e.g. pool_size=32, max_overflow=20,
   pool_timeout=10 (must be ≤ 10). Names:
   `OMNIGENT_SQLITE_POOL_SIZE`, `OMNIGENT_SQLITE_MAX_OVERFLOW`,
   `OMNIGENT_SQLITE_POOL_TIMEOUT_S`. Invalid/empty → defaults.
2. Pass those plus `pool_pre_ping=True` into sqlite `create_engine`.
   Keep `connect_args` and the WAL connect hook.
3. Tests (test-first):
   - Engine kwargs captured (or real engine pool attrs) honor env
     overrides and defaults; timeout ≤ 10.
   - WAL pragmas still applied.
   - Concurrency: 20+ concurrent checkouts (threads or
     `asyncio.to_thread`) against a **temp** sqlite file, holding
     connections briefly, must complete without a 30 s wait and
     without QueuePool TimeoutError under the **new** defaults.
     Put the concurrency test in
     `tests/db/test_sqlite_pool_concurrency.py` (keep new file small).
   Update the old "skips server pool settings" test so it still
   checks WAL but expects explicit sqlite pool kwargs (not postgres
   200).

## Tests / hooks you must run
```
cd /home/alex/omnigent-fixes
uv run pytest -q tests/db/test_utils.py tests/db/test_sqlite_pool_concurrency.py tests/db
pre-commit run --files omnigent/db/utils.py tests/db/test_utils.py tests/db/test_sqlite_pool_concurrency.py
```
Fix until both are clean.

## Evidence
Write under `loop-fixes/evidence/iter1/sqlite-pool/` (you may create
it): a short script log proving 20 concurrent checkouts on temp
sqlite finish well under 30 s (pytest output is enough if you save
it as `PYTEST.txt`). No live server.

## Finish
Do not commit. Print a summary of changed paths and test results.
