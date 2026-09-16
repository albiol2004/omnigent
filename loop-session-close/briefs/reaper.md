# Builder: slice(reaper)

You are a GLM 5.2 Trio builder. Workspace:
`/home/coder/omnigent-dev`. Implement this slice only.
No commit/push. Never touch `/home/coder/omnigent`. No omni,
no port 6767. **Never ingest whole `app.py`.** Use sed.

## Scout verdict (iteration 1)

Hypothesis that `process_manager.release` drops
`native_panes()` listing: **DISPROVED**. Listing is
registry-only (`registry.py` 355-377). `release`
(process_manager.py 1040-1109) only pops `_entries`.

**Actual cause:** after the 1h harness idle reaper,
cursor TUIs keep redrawing so `_native_pane_is_busy`
(`app.py` 10641-10661) stays True via:
- `_native_pane_status.get(conv_id) == "running"` (only
  cleared in `delete_session` ~3882)
- tmux `window_activity` within 120s

Fix: once the harness subprocess is gone, only an
attached tmux client should spare the pane.

`HarnessProcessManager.has_session` (~969) is
`conversation_id in self._entries` (scout said
`has_entry`; the real name is `has_session`).

## Code (app.py ONLY the busy function ~10641-10661)

After the `_active_turns` / `has_active_turn` check, if
`process_manager is not None` and
`not process_manager.has_session(conv_id)`, return
whether tmux clients are attached. Do not consult stale
`"running"` or window_activity for that orphaned pane.

Lots of comments explaining why: harness release does not
close native tmux; TUI redraws must not pin leaked panes.

If `process_manager` is None, keep existing busy logic
(tests / runners without a PM).

Do not change pane_reaper.py unless a small comment is
needed. Prefer not to expand `release` to close terminals
(GOAL allowed either; scout's busy-gate is smaller).

## Tests

Add to `tests/terminals/test_pane_reaper.py` (or a new
small test file in `tests/terminals/` if mixing fakes is
cleaner): unit test of the busy predicate with a FakePM
implementing `has_session` + `has_active_turn`:

- orphaned (no session) + stale `"running"` + fresh
  activity + no clients → **not busy** (reapable)
- live harness + `"running"` → busy
- orphaned + attached client → busy
- in-flight turn → busy even if no session entry

Extract the busy helper from `app.py` into a small
testable function in `pane_reaper.py` **only if** you
cannot test the logic otherwise without importing app.
Prefer extracting a tiny `_pane_is_busy_after_harness`
helper into `pane_reaper.py` (<200 extra lines) and
calling it from `app.py` 10641 so tests do not import
the 10k-line app module.

## Verify

```
uv run --project /home/coder/omnigent-dev pytest -q \
  tests/terminals/test_pane_reaper.py
```

Return files changed, summary, pytest output, concerns.
