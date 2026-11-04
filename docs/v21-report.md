# Omnigent fork re-port onto v0.21.0rc1 — report

Branch: `trio/loop` → lands on `trio-v0.21.0-fixes` (base: upstream tag `v0.21.0rc1` = `20e15700f`, first release
candidate of 0.21, tagged 2026-11-03; the loop's mailbox-only base commit is `1b72ac3af`, `loop: mailbox for v0.21.0rc1
re-port`). Port source: `v17/trio-v0.17.0-fixes` (tip `2e62ffd54`), range `v0.17.0..v17/trio-v0.17.0-fixes` =
**90 commits** (`git rev-list v0.17.0..v17/trio-v0.17.0-fixes | wc -l`): 78 product commits, 9 worker merge commits,
3 mailbox-only (`loop/`) commits. Method: the v17 method (`docs/v17-report.md`, `docs/v17-evidence/`) — `git cherry-pick -x`
in original order, conflicts resolved keeping upstream v0.21.0rc1 behaviour with the fork layered on top, adaptation work
committed as `slice(<id>): …`; per-slice conflict narratives in `docs/v21-evidence/dispositions/v21-port-*.md`.

Totals (90 v17 commits): **61 ported** (clean pick), **17 adapted** (conflicts resolved, or the pick needed a
v0.21-specific follow-up), **0 dropped**, **12 not ported** (9 worker merges + 3 loop-only). 61 + 17 + 0 + 12 = 90; the 78
product commits are the 61 + 17. Numbers are from `bash scripts/v21_disposition_check.sh` (§1.1) and the table below,
which was generated from the `(cherry picked from commit …)` trailers on HEAD (new sha) and the six disposition notes
(ported/adapted + notes), not typed.

All pytest runs in this report used `TMPDIR=/var/tmp/pytest-of-coder` (the driver's TMPDIR pushes tmux socket paths past
the 108-byte AF_UNIX limit). Server-integration test files (`tests/server/integration/`) hang under pytest's default
fd-level capture on pristine v0.21.0rc1 as well as at the tip; they are run with `--capture=sys` (§3.3).

Scope: GOAL DoD 1, 2, 3, 6 (iteration 1, re-recorded at the final tip in iteration 2) and DoD 4, 5, 7 (iteration 2:
behaviour checks §5, scratch-server consumer compatibility §6, risks/migrations, rebase and install/rollback steps §7).

## 1. Disposition table (all 90 v17 commits, original order)

Columns: `#` = product number 1–78 in `git rev-list --reverse --no-merges v0.17.0..v17/trio-v0.17.0-fixes` order minus
loop-only commits (`m<n>` = merge, `l<n>` = loop-only); `v17 sha` = commit on `v17/trio-v0.17.0-fixes` (9 chars);
`class` ∈ product / merge / loop-only; `disposition` ∈ ported / adapted / dropped / not-ported; `new sha` = the `-x`
cherry-pick on this branch; notes name the per-slice note under `docs/v21-evidence/dispositions/`.

| # | v17 sha | subject | class | disposition | new sha | notes |
|---|---|---|---|---|---|---|
| l1 | b52507b70 | loop: mailbox for v0.17.0 re-port | loop-only | not-ported | — | mailbox-only commit (`loop/`), not product code (GOAL) |
| 1 | 4f1fc58f8 | slice(v17-baseline): add v17 focused-suite runner | product | ported | 8493f640c | Historical evidence script, unchanged. (`v21-port-close.md`) |
| 2 | 8f7f924c2 | slice(kill-on-close): stop the target harness on sys_session_close. | product | adapted | ba43bd520 | Conflicts in bridge.py / test_runner_dispatch.py resolved as above; follow-up f6fc77242 (+ c9e200827 format). (`v21-port-close.md`) |
| 3 | fb38228b0 | slice(port-v14-close): adapt kill-on-close pick to v0.16 (wrapper label import, bridge module path) | product | ported | d56bf2d8e | Clean. (`v21-port-close.md`) |
| 4 | 033e6837e | slice(codex-bridge-owner): serve Codex model options from a labeled live bridge | product | adapted | 177b7a77f | Follow-up 27da4e27e for upstream's (state, bridge_dir) refactor. (`v21-port-close.md`) |
| 5 | 561681c55 | slice(compact-on-fork-cross-harness): replay summary-only Codex compaction markers | product | ported | cb5c7c492 | Clean. (`v21-port-close.md`) |
| 6 | 669e05bfd | slice(session-contract): alias _resolve_agent_spec to _resolve_subagent_spec | product | ported | c366fd184 | Clean; re-export still present on rc1. (`v21-port-close.md`) |
| 7 | ab9d2c7cb | slice(close-guard): close tree-scoped children with unparsable titles | product | ported | c1ab67984 | Clean. (`v21-port-close.md`) |
| 8 | 2eed26a21 | slice(port-v14-close): disposition notes for v14 close slice | product | ported | 9d4b414e8 | Clean (v16 evidence note). (`v21-port-close.md`) |
| 9 | 2f74c179a | slice(v17-port-close): ruff-format fork hunks in runner/app.py and tool_dispatch.py | product | ported | 2837f48a0 | Clean. (`v21-port-close.md`) |
| 10 | 88344b862 | slice(v17-port-close): disposition notes | product | ported | 7ab19d2e1 | Clean (v17 evidence note). (`v21-port-close.md`) |
| 11 | b1c8373de | slice(v17-baseline): focused-suite runner and pristine v0.17.0 baseline | product | ported | 5f1b63f04 | Historical evidence, unchanged. (`v21-port-close.md`) |
| m1 | ecd6d0f3f | merge(worker): v17-baseline-0c9aad2d slice v17-baseline | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| m2 | bc433e1b2 | merge(worker): v17-port-close-a4f3aa87 slice v17-port-close | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 12 | 30764d7e9 | slice(stop-routing): hard-stop Claude, Codex and Cursor on close | product | adapted | 46480dd27 | interrupt.py opencode/side-chat kept; `_codex_stop` added; follow-up 61ff5dbdf (`v21-port-stop.md`) |
| 13 | 150efd6ff | slice(kill-escalation): share leftover-pane SIGKILL across native bridges | product | adapted | 665c6ce2c | claude kill_session now delegates to `native_tmux_kill`; upstream kill markers kept (`v21-port-stop.md`) |
| 14 | a526deb64 | slice(port-v14-stop): drop unused _proc import and fix pre-split codex bridge test import after kill-escalation pick | product | adapted | 3093f32b4 | `in_managed_sandbox` import kept (`v21-port-stop.md`) |
| 15 | 958ee4c24 | slice(reaper): reap native panes after harness subprocess release | product | adapted | 0bb8d876b | helper extended with upstream screen-diff + server-confirm; #12200 idle timeout intact (`v21-port-stop.md`) |
| 16 | 54f5172bf | slice(codex-advertise-guard): do not abort Codex auto-create when tmux advertise is missing | product | adapted | e21133d27 | options test: upstream `/clear` test kept (`v21-port-stop.md`) |
| 17 | c69e6e76f | slice(readme): note trio-v0.14.0-fixes until live adopt | product | ported | 230289c25 | clean (`v21-port-stop.md`) |
| 18 | 7e50a304d | docs(v14-report): summarize the 0.14.0 re-port disposition | product | ported | 0dfc26c9c | clean (`v21-port-stop.md`) |
| 19 | 477b2e2e8 | slice(port-v14-stop): README adapted for v0.16.0 and disposition notes | product | ported | d173a98d0 | clean (`v21-port-stop.md`) |
| 20 | 3c16f63ee | slice(port-v14-stop): clarify disposition note | product | ported | 2bc192c1f | clean (`v21-port-stop.md`) |
| 21 | 9d7976a0d | slice(v17-port-stop): README for v0.17.0 | product | ported | 58fd53ffb | picked clean by the Lead after the builder's cherry-pick was denied (header of v21-port-stop.md; its table row still reads NOT DONE) (`v21-port-stop.md`) |
| 22 | 48757757d | slice(v17-port-stop): disposition notes | product | ported | 9bbbc9552 | picked clean by the Lead after the builder's cherry-pick was denied (header of v21-port-stop.md; its table row still reads NOT DONE) (`v21-port-stop.md`) |
| m3 | 79fcc12e6 | merge(worker): v17-port-stop-8c96f720 slice v17-port-stop | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 23 | b110581d4 | feat(cursor-native): opt-in completion receipts and durable input fence | product | adapted | f43bf418e | 4 conflicts, see below (`v21-port-receipts.md`) |
| 24 | 0a0489d45 | slice(baseline-suite): focused-suite runner and pristine v0.16.0 baseline | product | ported | db3580761 | historical evidence (`v21-port-receipts.md`) |
| 25 | 6dfb7d57c | fix(cursor-native): bind receipt turn ends to prompts; durable skipped rows | product | adapted | e89407bd7 | 1 conflict, see below (`v21-port-receipts.md`) |
| 26 | 966a8e8ee | test(cursor-native): serialize mixed binding reasons in e2e evidence dumps | product | ported | 05774790e | clean (`v21-port-receipts.md`) |
| 27 | e0849ba33 | fix(cursor-native): withhold completion receipts when a foreign stop hook is configured | product | ported | 4b2b72d26 | clean (`v21-port-receipts.md`) |
| 28 | e90741969 | fix(cursor-native): bind receipt stops to this chat; scope owned stop hooks | product | ported | cf37c9605 | clean (`v21-port-receipts.md`) |
| 29 | c2d486a61 | fix(cursor-native): abort launch when a stale receipt epoch cannot be removed | product | ported | b0ec78f26 | clean (`v21-port-receipts.md`) |
| 30 | f824ffc1d | slice(port-cursor-receipts): disposition notes | product | ported | c41d695ba | historical evidence (`v21-port-receipts.md`) |
| 31 | 74ee1aa8b | slice(patch-refresh): child-reasoning-effort patch for v0.16.0 | product | ported | b6850163c | historical patch (`v21-port-receipts.md`) |
| 32 | cdff1f729 | slice(v17-port-receipts): adapt receipt tests to v0.17.0 APIs | product | ported | d2e81b624 | clean (`v21-port-receipts.md`) |
| 33 | 68355aa71 | slice(v17-port-receipts): post receipt kwarg only when a receipt exists | product | ported | 6b9bf6bf1 | clean (`v21-port-receipts.md`) |
| 34 | 5ce00dcde | slice(v17-port-receipts): disposition notes | product | ported | 610e8fa07 | historical evidence (`v21-port-receipts.md`) |
| m4 | d5f485f7f | merge(worker): v17-port-receipts-a0f065ed slice v17-port-receipts | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 35 | cf7e01b4a | fix(cursor-native): no Backspace into an empty composer; stable readiness before the first paste | product | ported | 173de1e84 | clean (`v21-port-isocompact.md`) |
| 36 | c34b373b0 | fix(cursor-native): never write a session stop hook into the user hooks.json | product | adapted | 0a60a0f50 | test import conflict (`v21-port-isocompact.md`) |
| 37 | c91564c23 | fix(cursor-native): never register a session MCP server in the user mcp.json | product | ported | 2291b0b23 | clean (`v21-port-isocompact.md`) |
| 38 | 4a5f7c704 | fix(cursor-native): refuse Cursor launches whose project config is the user ~/.cursor | product | adapted | 7039bb81c | start-error payload conflict (`v21-port-isocompact.md`) |
| 39 | 1363b3692 | fix(cursor-native): refuse Cursor launches from a repository subfolder | product | ported | 61aab49ac | clean (`v21-port-isocompact.md`) |
| 40 | e4877b51d | test(cursor-native): keep the repo-subfolder refusal test's bridge under the launch root | product | ported | c159ff675 | clean (`v21-port-isocompact.md`) |
| 41 | fd369ae8c | slice(port-cursor-isolation): disposition notes; adapt ensure-response test to session_id kwarg | product | ported | a9b417e3f | clean (`v21-port-isocompact.md`) |
| 42 | 913919d7f | slice(port-cursor-isolation): fix keep pytest tmp_path out of a stray .git ancestor | product | ported | 7d3d30ad3 | clean (`v21-port-isocompact.md`) |
| 43 | f1676480c | fix(codex-native): compact via app-server thread/compact/start, not tmux keys | product | adapted | c9de4f254 | 3 conflicts, see below (`v21-port-isocompact.md`) |
| 44 | c52ecff7b | fix(codex-native): keep the manual-compact guard until Codex reports an outcome | product | ported | fb268f6de | clean (`v21-port-isocompact.md`) |
| 45 | d0a486bd2 | slice(port-cursor-isolation): fix disposition new-sha column to the trio/loop commits | product | ported | 01890d219 | historical evidence (`v21-port-isocompact.md`) |
| 46 | 6fd4ca632 | slice(port-codex-compact): disposition notes for the app-server manual compact port | product | ported | bde75aed4 | historical evidence (`v21-port-isocompact.md`) |
| 47 | 604ab387b | slice(v17-port-isolation-compact): move manual-compact tests to tests/harnesses/codex_native | product | ported | b4f61eb59 | clean (`v21-port-isocompact.md`) |
| 48 | f5f90ca43 | slice(v17-port-isolation-compact): disposition notes | product | ported | f5df68e41 | historical evidence (`v21-port-isocompact.md`) |
| m5 | a13bf28a6 | merge(worker): v17-port-isolation-compact-6b4be251 slice v17-port-isolation-compact | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 49 | 9f7220a42 | fix(cursor-native): never bind a session to another workspace's chat store | product | ported | c8251c6e6 | clean (`v21-port-binding.md`) |
| 50 | 24508959a | fix(cursor-native): pin each fresh launch to a pre-minted chat id | product | adapted | 78893d289 | permissions.py import+conftest (`v21-port-binding.md`) |
| 51 | 433df86ae | fix(cursor-native): bind a discovered chat only when this session's pane owns it | product | adapted | 2dc5c82e1 | elicitation store resolver (`v21-port-binding.md`) |
| 52 | 197a2cb17 | fix(cursor-native): warn when a launch overwrites a live sibling's hooks/MCP slot | product | ported | c9c439770 | clean (`v21-port-binding.md`) |
| 53 | b6962e4af | slice(port-cursor-binding): disposition notes for the chat-binding port | product | ported | 47b2acb05 | historical evidence (`v21-port-binding.md`) |
| 54 | 3c7252f3a | feat(cursor-native): opt-in per-launch --plugin-dir hooks/MCP config | product | ported | a99ce6d28 | clean (`v21-port-binding.md`) |
| 55 | a4269368c | fix(cursor-native): let OMNIGENT_CURSOR_PLUGIN_DIR reach host-spawned runners | product | adapted | 975d358fd | runner env allowlist (`v21-port-binding.md`) |
| 56 | bab692622 | fix(cursor-native): never delete the project mcp.json when clearing a dead entry | product | ported | 6dcba7ce0 | clean (`v21-port-binding.md`) |
| 57 | 10ce2b158 | fix(cursor-native): refuse plugin-route launches cursor-agent would run without the plugin | product | adapted | 38fabe41f | start error payload import (`v21-port-binding.md`) |
| 58 | 1ee4c7d22 | fix(cursor-native): a plugin-route turn no longer fires a live sibling's project usage hook | product | ported | 413f52e4e | clean (`v21-port-binding.md`) |
| 59 | 4596497c7 | fix(cursor-native): owner-only bridge dir recreation; grace for mid-launch siblings | product | ported | a42a212a1 | clean (`v21-port-binding.md`) |
| 60 | af4c6a098 | test(cursor-native): fix the pyrefly errors in the plugin-dir unit tests | product | ported | 9e468428a | clean (`v21-port-binding.md`) |
| 61 | cec186bc5 | test(cursor-native): gate the plugin-dir real-CLI e2e; cover the sibling-hook skip | product | ported | 229bc198f | clean (`v21-port-binding.md`) |
| 62 | 69b9e324d | fix(cursor-native): cursor_project_key matches the CLI's directory mangling (r17 N16) | product | ported | 39981432e | clean (`v21-port-binding.md`) |
| 63 | 7c66bd251 | fix(cursor-native): bridge MCP refuses a parent bound to another bridge (r17 N11) | product | ported | e629e50d6 | clean (`v21-port-binding.md`) |
| 64 | 66471010f | fix(cursor-native): receipt gate scans passthrough and installed plugin stop hooks (r17 N12) | product | ported | 1f3426fd3 | clean (`v21-port-binding.md`) |
| 65 | e64f72d1b | slice(port-cursor-plugin-dir): disposition notes for the plugin-dir/r17 port | product | ported | 2656897c6 | historical evidence (`v21-port-binding.md`) |
| 66 | 0cd5d45b4 | slice(v16-report): v0.16.0 re-port report and after-port evidence | product | ported | 978ba26b6 | historical evidence (`v21-port-binding.md`) |
| 67 | 06aa68a25 | slice(v17-port-binding-plugin): disposition notes | product | ported | 31e97ccbb | historical evidence (`v21-port-binding.md`) |
| m6 | 5ad14e711 | merge(worker): v17-port-binding-plugin-c453af6d slice v17-port-binding-plugin | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 68 | 31236382c | slice(v17-patch): child-reasoning-effort patch for v0.17.0 | product | ported | 0c9333f73 | historical evidence (`patches/`, `docs/v17-evidence/patch-check.txt`) (`v21-port-tail.md`) |
| m7 | bec4ae12d | merge(worker): v17-patch-7b5b0e57 slice v17-patch | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 69 | bf6c3a8d2 | slice(v17-afterport): after-port suite and upstream-overlap check | product | ported | f2e33720e | historical evidence (`scripts/v17_overlap_check.sh`, `docs/v17-evidence/`) (`v21-port-tail.md`) |
| m8 | 903c3aeab | merge(worker): v17-afterport-da238cd4 slice v17-afterport | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 70 | 2d5655b6b | slice(v17-report): v0.17.0 re-port report | product | ported | 1c2cbdc73 | historical evidence (`docs/v17-report.md`) (`v21-port-tail.md`) |
| m9 | 33d3c2b56 | merge(worker): v17-report-61328491 slice v17-report | merge | not-ported | — | worker merge commit on the v17 branch; its slice commits are ported individually |
| 71 | c2bedad97 | slice(v17-port-stop): fix ruff format of ported stop/kill hunks for v0.17.0 line length | product | adapted | b87d0cf23 | empty after conflict resolution — v17 reformatted stop/kill hunks for v0.17.0 line length; those files were already ruff-formatted on v0.21.0rc1 by `1febb04f9`. `git range-diff c2bedad97^! b87d0cf23^!` shows the v17 tree rewrite with no corresponding pick hunks. Pick still carries `-x` from `c2bedad974cab7fca6cb7ecbf481b4ab68352149`. (`v21-port-tail.md`) |
| 72 | 8001e9de9 | slice(v17-port-receipts): fix ruff format and unused noqa (RUF100) in receipt/fence tests | product | ported | c11e2c181 | clean (`v21-port-tail.md`) |
| 73 | 250f4c3e5 | slice(v17-port-receipts): fix pyrefly errors in the cursor receipt/turn-outcome block | product | ported | 491f01e85 | clean (`v21-port-tail.md`) |
| 74 | 7470ce929 | slice(v17-afterport): fix overlap check counting lines quoted in docs/v17-report.md as moved | product | ported | 4957673f4 | historical evidence (`scripts/v17_overlap_check.sh`) (`v21-port-tail.md`) |
| 75 | c813e0b82 | slice(v17-afterport): fix evidence: final-tip suite re-run, overlap check refreshed at tip | product | ported | c25404f26 | historical evidence (`docs/v17-evidence/`, `docs/v17-report.md`) (`v21-port-tail.md`) |
| l2 | cfe851ec9 | loop: iteration 1 — SHIP | loop-only | not-ported | — | mailbox-only commit (`loop/`), not product code (GOAL) |
| l3 | ef825e7a0 | loop: land loop (iteration 1) | loop-only | not-ported | — | mailbox-only commit (`loop/`), not product code (GOAL) |
| 76 | 7c04ae6a5 | fix(cursor-native): receipt re-post keeps the turn's failed outcome | product | ported | d29c61e72 | clean (`v21-port-tail.md`) |
| 77 | 503a80a41 | fix(cursor-native): server keeps a failed child turn and dedups repeated terminal posts | product | ported | 11a604d98 | clean (`v21-port-tail.md`) |
| 78 | 2e62ffd54 | fix(cursor-native): only an authorised receipt caller records the turn marker; correct v17 report knob names | product | ported | 4dddf165d | clean (`v21-port-tail.md`) |

### 1.1 Trailer / ancestry check

`bash scripts/v21_disposition_check.sh` re-derives everything from git: it classifies the 90 source commits
(merge = >1 parent; loop-only = every path under `loop/`/`loop-archive*`; else product), counts
`(cherry picked from commit <full v17 sha>)` trailers in `git log v0.21.0rc1..HEAD` (must be 0 or 1 per product commit),
checks that the picks appear in v17 order (`git log --reverse --topo-order`), and checks every §1 row: one row per
source commit in order, class matches, merge/loop-only rows are `not-ported`, every ported/adapted row's new sha resolves,
is an ancestor of HEAD and carries that row's v17 trailer, and every `dropped` row cites an upstream commit that is an
ancestor of `v0.21.0rc1`. Exit 0 only if all hold; each failure is printed with its row (`FAIL: row #<n> (v17 <sha>): …`).

```
$ bash scripts/v21_disposition_check.sh
DISPOSITION: 78 product commits — ported+adapted=78, dropped=0, p+d=78; trailers in v17 order: yes
TARGETED_CHECK: PASS 1
# exit 0
```

Refusal check (temporary local edit, restored by hand): setting row #50's new sha to `2dc5c82e1` (the pick of #51) →
`FAIL: row #50 (v17 24508959a): new sha 2dc5c82e1 does not carry the trailer 'cherry picked from commit 24508959a600…'`,
exit 1; additionally marking loop-only row `l1` as `ported` → `FAIL: row #l1 (v17 b52507b70): loop-only row must be
'not-ported', got 'ported'`, exit 1.

Manual cross-check (GOAL A2 shape):

```sh
for v in $(git rev-list --reverse --no-merges v0.17.0..v17/trio-v0.17.0-fixes); do
  git log --format=%B 1b72ac3af..HEAD | grep -c "cherry picked from commit $v"; done | sort | uniq -c
     3 0
    78 1
```

(81 non-merge source commits: the 78 product commits have exactly one pick each; the 3 zeros are the loop-only commits.)

Note: rows #21/#22 read `NOT DONE` in the table of `docs/v21-evidence/dispositions/v21-port-stop.md` (written by the denied
builder); that note's header records that the Lead picked them clean (`58fd53ffb`, `9bbbc9552`), and the trailers confirm
it. This report's table is authoritative.

### 1.2 Commits on this branch with no v17 counterpart

`git log --no-merges --format='%h %s' v0.21.0rc1..HEAD` minus the 78 picks:

| new sha | subject | kind |
|---|---|---|
| 1b72ac3af, c7f4cf09a, cdd6e1b71 | loop: … (mailbox for the re-port, abandon run 1, restart run 2) | mailbox (`loop/`) |
| 85fd9c151 | slice(v21-baseline): v0.21 focused-suite runner and pristine v0.21.0rc1 baseline | evidence (`scripts/v21_focused_suite.sh`, `docs/v21-evidence/baseline-v0.21.0rc1.txt`) |
| c9e200827 | slice(v21-port-close): ruff-format fork test hunks (line-length reflow) | adaptation (format only) |
| 27da4e27e | slice(v21-port-close): adapt codex-bridge-owner hunk to upstream's (state, bridge_dir) helper | adaptation (code) |
| f6fc77242 | slice(v21-port-close): scope expected-close ordering test to the kill-session call | adaptation (test) |
| 1febb04f9 | slice(v21-port-stop): ruff format picked stop/kill/reaper hunks and keep screen-diff + server-confirm busy checks in the reaper helper | adaptation (format + keep upstream reaper checks) |
| 61ff5dbdf | slice(v21-port-stop): resolve the codex hard-stop bridge through the label-aware lookup and settle idle | adaptation (code) |
| 83fc04a14 | slice(v21-port-stop): README for v0.21.0rc1 | adaptation (README) |
| f0813e6d6 | slice(v21-port-isocompact): give the manual-compact forwarder fake the v0.21 is_subscribed_to_thread probe | adaptation (test fake) |
| 6c7541a83 | slice(v21-port-tail): fix ruff at the ported tip — drop BLE001 noqa that v0.21 per-file ignores make unused (RUF100), one blank line in native_controls | adaptation (lint only) |
| 61cc99c4d, f46002565, 1efc4a8f1, 4cfe3a3d7, 1b0283bd6, cee4eaf0f | slice(v21-port-*): disposition notes (+ binding's pristine-proven deselect, stop note fix) | evidence (`docs/v21-evidence/dispositions/`, `deselects/`) |
| 00930adbe | evidence: keep run-1 port-tail deselect args | evidence (`docs/v21-evidence/deselects/v21-port-tail.args`) |
| 4554fa9b8 | slice(v21-patch): child-reasoning-effort patch for v0.21.0rc1 | patch (`patches/child-reasoning-effort.v0.21.0rc1.patch`, `docs/v21-evidence/patch-check.txt`) |
| 1a8cdb8db, afc642cd7, f9fd80cf4 | slice(v21-afterport): add opt-in V21_PER_FILE / V21_TT_FRESH / V21_PYTEST_ARGS knobs to the focused-suite runner | evidence tooling (`scripts/v21_focused_suite.sh`) |
| 9256be8f4 | slice(v21-afterport): after-port suite, suite comparison and upstream-overlap check | evidence (`after-port*.txt`, `overlap-*.txt`, `scripts/v21_compare_suites.py`, `scripts/v21_overlap_check.sh`) |
| c902b4b1e, be6bb75ac | slice(v21-afterport): fix ruff format/check of v21_compare_suites.py; print a pytest-shaped counts line | evidence tooling (lint / output only) |
| 0bf3e94ec, 76e88481b | slice(v21-port-tail): disposition notes for v17 #68-78 (Lead take-over) + order-dependent hang evidence | evidence (`docs/v21-evidence/dispositions/v21-port-tail.md`) |
| d36535047, 91c6e04c4, 8c1acf729 (+ the §1.2 fix commit after them) | slice(v21-report): report §1–4, disposition checker, its counts line, §3.3 | this report + `scripts/v21_disposition_check.sh` |

Worker merge commits on this branch: `f2541b6d3`, `1608dac98`, `00019b87e`, `7ef68e8eb`, `6aa37f3cf` (`merge(worker): …`).

### 1.3 Dropped commits — evidence

None. Every one of the 78 v17 product commits is on HEAD as exactly one `-x` pick (61 clean, 17 adapted). In particular
no v17 fork patch turned out to be superseded by v0.21.0rc1: the overlap check (§2) shows the upstream lines kept and the
fork lines layered on top, and `docs/v21-evidence/dispositions/v21-port-*.md` record, per conflict, which upstream
behaviour was kept. One v17 commit, #71 `c2bedad97` (ruff format of the v17 stop/kill hunks for v0.17.0 line length), is
recorded as *adapted* rather than dropped: its pick `b87d0cf23` is an empty-tree commit kept for the `-x` trailer because
those hunks were already formatted for v0.21.0rc1 by `1febb04f9` (`v21-port-tail.md`, row 71).

## 2. Upstream v0.21.0rc1 overlaps kept (GOAL DoD 2)

`bash scripts/v21_overlap_check.sh` (record: `docs/v21-evidence/overlap-check.txt`, at rev `f9fd80cf4`; no `omnigent/` or
`tests/` file changed after it) takes each upstream PR commit listed in GOAL Context, collects the lines it added
(non-trivial, stripped) and checks each is still present in its file at the tip; an absent line counts as *moved* if it
appears elsewhere in the tree, otherwise it must be allow-listed in `docs/v21-evidence/overlap-allow.txt` with a reason
(script exits 1 otherwise).

| PR | commit | files | lines checked | absent at tip | moved | allow-listed |
|---|---|---|---|---|---|---|
| #10251 | 7a682c4b6 | 6 | 310 | 0 | 0 | 0 |
| #12200 | cdb863459 | 5 | 55 | 0 | 0 | 0 |
| #12153 | f7d67db5b | 2 | 90 | 0 | 0 | 0 |
| #12150 | 34960c7ad | 2 | 67 | 0 | 0 | 0 |
| #9908 | 7eee19341 | 3 | 148 | 0 | 0 | 0 |
| #10861 | 64dc6d4a4 | 2 | 10 | 0 | 0 | 0 |
| #11485 | 4f796ba44 | 6 | 258 | 0 | 0 | 0 |
| #11816 | ac1737e1c | 4 | 81 | 0 | 0 | 0 |
| #11821 | 98967aa31 | 3 | 60 | 0 | 0 | 0 |
| #10850 | f93be3274 | 58 | 1398 | 0 | 0 | 0 |
| #10906 | 60a5f61f7 | 48 | 340 | 0 | 0 | 0 |
| #9844 | d2e077a1e | 22 | 719 | 0 | 0 | 0 |

Result: `absent lines (not moved): 0`, `moved lines: 0`, `unallowed absent lines: 0`, `exit: 0`. The allow-list is empty
(comment lines only). The breaking-change PRs #10850 (`f93be3274`, session-ownership / project-config restrictions),
#10906 (`60a5f61f7`, HTTP bundle-upload restrictions) and #9844 (`d2e077a1e`, shell-policy gating) are kept verbatim
(above); their effect on the trio driver / App Control is evaluated against a scratch server in iteration 2 (§6).

**#10251 (keep a sub-agent's shared host runner alive) vs the fork's kill-on-close** — they act on different layers and
coexist (`docs/v21-evidence/dispositions/v21-afterport.md`): `sys_session_close` → `_session_close_via_rest`
(`omnigent/runner/tool_dispatch.py`) posts `stop_session`/`interrupt` to the child's `/events`; the server delivers it to
the runner serving the child, whose native interrupt path calls the bridge `kill_session` →
`native_tmux_kill.kill_session_with_escalation` (`omnigent/native_tmux_kill.py`; tmux kill + SIGKILL of the leftover pane
group). That kills the **child's pane/harness** and is not gated by #10251. Only the subsequent **host-level runner stop**
is gated by #10251's `_owns_host_runner` (`omnigent/server/routes/_sessions/helpers.py`), so a child riding its parent's
shared runner leaves the runner up while its own pane is already gone. Tests: upstream
`tests/server/integration/test_session_host_launch.py::test_stopping_child_does_not_stop_parents_shared_runner` and
`tests/server/test_host_runner_ownership.py` (108 passed with `--capture=sys`); fork
`tests/harnesses/claude_native/test_claude_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill`,
`tests/runner/test_runner_dispatch.py::test_session_close_routes_native_wrappers_to_stop_session` and
`::test_session_close_tombstones_when_target_stop_fails`. An end-to-end check that a trio child's runner/zygotes are gone
after close is part of the scratch-server run (§6, iteration 2).

## 3. Baseline (pristine v0.21.0rc1) vs after-port (GOAL DoD 3)

Runner: `scripts/v21_focused_suite.sh` (the v17 runner with the same 11 groups; files listed per group in the records).
Baseline: `docs/v21-evidence/baseline-v0.21.0rc1.txt` (rev `1b72ac3af`, tree equal to `v0.21.0rc1` outside `loop/`).
After-port: `docs/v21-evidence/after-port.txt` (re-recorded at the final tip `8d00e6eb6` by the Lead, iteration 2; `omnigent/` is unchanged since the first record at `afc642cd7`, `tests/` gained only the two iteration-2 tests, so claude-native goes 2328 → 2330 passed and the fail set is identical).
Comparison: `python3 -I scripts/v21_compare_suites.py docs/v21-evidence/baseline-v0.21.0rc1.txt docs/v21-evidence/after-port.txt`.

### 3.1 Per group

| group | pristine v0.21.0rc1 | after port | FAILED baseline | FAILED after |
|---|---|---|---|---|
| dispatch | 313 passed, 1 skipped | 317 passed, 1 skipped | 0 | 0 |
| interrupt | 25 passed | 28 passed | 0 | 0 |
| runner-native | 51 failed, 704 passed | 42 failed, 792 passed | 51 | 42 |
| sys-session | 60 passed | 61 passed | 0 | 0 |
| terminals | 177 passed, 2 skipped | 188 passed, 2 skipped | 0 | 0 |
| claude-native | 2327 passed, 1 skipped | 2330 passed, 1 skipped | 0 | 0 |
| codex-native | 1895 passed | 1925 passed | 0 | 0 |
| cursor-native | 267 passed | 561 passed | 0 | 0 |
| inner-proc | 45 passed, 8 skipped | 46 passed, 8 skipped | 0 | 0 |
| host | 1 failed, 407 passed | 1 failed, 408 passed | 1 | 1 |
| sessions-routes | PYTEST-TIMEOUT-HANG | PYTEST-TIMEOUT-HANG (excused, §3.3) | — | — |

Compare script result: `REGRESSIONS: 0` (exit 0). New failures: **0**. A negative check (an appended invented `FAILED`
id in the `host` group of a copy of the after-port record) prints `REGRESSIONS: 1`.

### 3.2 Pre-existing upstream failures (fail on pristine v0.21.0rc1 too — not regressions)

- 42 `runner-native` ids in `tests/runner/test_app_sessions_native_events_lifecycle.py` (40 Codex-native settings /
  stop / side-chat ids and 2 `test_claude_native_model_options_*` ids; typical line `AssertionError: codex-native model_change must return 204; got 503:
  {"error":"codex_native_settings_update_failed","detail":"Codex-native settings update requires a loaded Codex bridge."}`)
  — together with the host id below, the compare script's `PRE-EXISTING: 43` list.
- `tests/host/test_connect.py::test_run_host_process_announces_session_log_dir_on_start` (host group; the host's
  structlog output in this environment carries no `This host's log:` line).
- 9 ids fail on pristine and pass at the tip (compare script `FIXED BY PORT: 9`, codex-native stop/interrupt/settings
  paths the v17 commits rework). Not claimed as intended fixes.

Targeted-check deselects (`docs/v21-evidence/deselects/<slice>.args`, each id proven failing on pristine in the slice
note): `v21-port-close.args` / `v21-port-tail.args` 50 ids (pristine
`tests/runner/test_app_sessions_native_events_lifecycle.py` → `50 failed, 64 passed`, `v21-port-close.md`),
`v21-port-stop.args` 42 ids (pristine → `42 failed`, `v21-port-stop.md`), `v21-port-binding.args` the host id above
(`v21-port-binding.md`), receipts/isocompact none. The focused suite itself runs without deselects.

### 3.3 sessions-routes: environmental hang under fd capture

The group hangs on pristine v0.21.0rc1 (baseline) and at the tip. Per-file records
(`docs/v21-evidence/after-port-perfile.txt`, `--timeout=60`, default capture): pristine — all 3 files hang; tip — the
same 3 plus the fork-added `test_input_fence.py`, `test_cursor_receipt_binding_e2e.py`, `test_cursor_receipt_epoch_clear_e2e.py`
hang, `test_cursor_cold_start_prompt.py` passes (6 passed). Cause (located, `v21-afterport.md`): only under pytest's
fd-level capture, a request that solves a *sync* FastAPI dependency in the AnyIO threadpool
(`require_json_or_multipart_content_type` on `POST /v1/sessions`) never gets its worker-thread wake-up back to the
event loop. With `--capture=sys` (records `pristine-capsys` / `tip-capsys`) every file completes: pristine 21 passed
(3 files); tip 66 passed, 0 failed (7 files, incl. `test_input_fence` 17 and the cursor receipt e2e files). The compare
script excuses the group only because every tip hang also occurs on pristine, every fork-added file passes at the tip
(with `--capture=sys`), and the `tip-capsys` record has no new failure. The hang is also order-dependent: with `--capture=sys`,
`tests/runner/test_app_sessions_native_events_options.py` followed by `test_sessions_compact.py` in one process hangs in
the first compact test on the tip and on pristine v0.21.0rc1 alike, while the compact file alone passes (14 passed;
`docs/v21-evidence/dispositions/v21-port-tail.md`). The port slices' targeted checks that include
`tests/server/integration/` files therefore run those files in their own pytest process with `--capture=sys`; e.g. the tail slice's check at the Lead's
HEAD: `TRIO_TEST: PASS rc=0 passed=695 failed=0 skipped=1 errors=0`. The trio driver uploads bundles to a real server
process, not through pytest's in-process ASGI client, so this capture artefact does not apply to it (re-checked
end-to-end in §6).

## 4. Refreshed trio patch `patches/child-reasoning-effort.v0.21.0rc1.patch` (GOAL DoD 6)

Record: `docs/v21-evidence/patch-check.txt` (at rev `00930adbe`; re-run at the final tip `9407b0b63` in iteration 2 — the PLAN targeted check, `71 passed`, see the file's last section; `omnigent/` unchanged since `00930adbe`).

| check | exit |
|---|---|
| `GIT_INDEX_FILE=$I git read-tree v0.21.0rc1 && GIT_INDEX_FILE=$I git apply --check --cached patches/child-reasoning-effort.v0.21.0rc1.patch` (pristine rc1) | 0 |
| `git apply --check patches/child-reasoning-effort.v0.21.0rc1.patch` (port tip) | 0 |
| same two checks with the old `child-reasoning-effort.v0.17.0.patch` | 1 (`tool_dispatch.py:119`, `_sessions/helpers.py:9663` do not apply) |
| patch applied: `tests/tools/builtins/test_child_reasoning_effort.py tests/tools/builtins/test_sys_session.py tests/runtime/test_reasoning_effort_validation.py` | `76 passed`; patch reversed afterwards |

Hunks re-anchored: the `tool_dispatch.py` import (upstream inserted a ui import at the old context) and the
`_build_session_create_body` / `_execute_session_create` hunks (call site keeps rc1's `message`); `helpers.py` keeps
adding `_resolve_agent_spec` (+ `__all__`, `sessions/__init__.py` re-export); the v0.17 `_resolve_subagent_spec` refactor
hunk is dropped because rc1's function already has the needed shape (details in `patch-check.txt`). The patch is
re-checked against the final tip in iteration 2.

v0.21.0rc1 already forwards `reasoning_effort` to children (8 of the 10
patch tests pass without the patch's code — Evaluator it1 base-revert probe),
so the patch's remaining value is invalid-effort rejection and
`_resolve_agent_spec` loading; the human decides whether it is still needed
on 0.21.

## 5. Behaviour checks → tests (GOAL DoD 4)

Map: `docs/v21-evidence/behaviour-map.md` (the v17 §4 structure, updated for v0.21.0rc1 paths and class names).
Runner: `bash scripts/v21_behaviour_check.sh` — collects every listed node id first (a missing id exits 1 naming it),
then runs them in one pytest process with `TMPDIR=/var/tmp/pytest-of-coder` and prints one `BEHAVIOUR <name>: PASS|FAIL`
line per behaviour. Record: `docs/v21-evidence/behaviour-check.txt` → `75 passed, 0 failed` (59 listed ids; some are parametrised), all six behaviours PASS.

| behaviour (GOAL DoD 4) | ids | example id | result |
|---|---|---|---|
| cursor receipt gate | 10 | `tests/test_cursor_native_completion_receipt.py::test_receipt_binds_prompt_hash_and_counts` | PASS |
| cursor isolation | 15 | `tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_user_mcp_has_omnigent_server` | PASS |
| input fence | 7 | `tests/server/integration/test_input_fence.py::test_verified_fence_rejects_every_input_api_and_persists` | PASS |
| stop-routing + kill escalation (#10251) | 12 | `tests/server/test_v21_shared_runner_kill_on_close.py::test_stop_subagent_child_kills_native_harness_without_stopping_shared_host_runner` | PASS |
| Codex manual compact | 8 | `tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_sends_thread_compact_start_and_reports_accepted_not_completed` | PASS |
| claude_native hook bridge + hook TMPDIR | 7 | `tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_always_registered_hook_commands_match_hook_cli_parser` | PASS |

**#10251 vs kill-on-close** (new test `tests/server/test_v21_shared_runner_kill_on_close.py`): a sub-agent child that
inherits its parent's host `runner_id` is stopped through the real server teardown helpers
(`_stop_session_via_runner_impl`, then the #10251 `_owns_host_runner` host gate). The runner receives the child's
`stop_session` (the fork's native hard-stop / SIGKILL escalation runs runner-side, covered by the
`test_kill_session_escalates_live_pane_after_tmux_kill` ids for claude/codex/cursor), and the host `stop_runner` is
**not** sent, so the shared runner stays up for the parent. A top-level host session still stops the runner it owns.
Revert sanity (Lead, it2 review): `_owns_host_runner` forced `True` → the child test fails (`1 failed, 1 passed`);
`_stop_session_via_runner_impl` returning without POSTing → both fail (`2 failed`). No product defect, no `omnigent/` change.
The test re-creates the route's two-step teardown in a helper, not by calling the HTTP route (Known limitation: a later
upstream change to the route's order would not be seen by it; the runner-side ids above cover the kill itself).

**claude_native hook CLI contract** (new test `tests/harnesses/claude_native/test_v21_hook_cli_contract.py`, also GOAL
DoD 5c, §6.3): every hook command the bridge injects (`build_hook_settings`, `augment_claude_args` with policy/routing on)
is `env TMPDIR=<trusted dir> <python> -I -m omnigent.harnesses.claude_native.hook [subcommand] --bridge-dir <abs dir>`
and parses with the hook module's own argparse (PreCompact plus every always-registered event; `permission-request`,
`evaluate-policy`, `route-turn`, `observe-tool`).

Excluded id: `test_claude_native_bridge.py::test_http_ingress_advertises_absolute_socket_path` (upstream, cwd-depth
artifact — `docs/v21-evidence/env-artifacts.txt`); the hook/TMPDIR behaviour keeps 7 depth-independent ids.

All 59 listed node ids (the runner's input, copied from the map):

```text
# cursor receipt gate
tests/test_cursor_native_completion_receipt.py::test_receipt_binds_prompt_hash_and_counts
tests/test_cursor_native_completion_receipt.py::test_turn_end_is_stamped_with_the_store_position
tests/test_cursor_native_completion_receipt.py::test_matching_stops_bind_a_clean_turn_and_queued_turns
tests/test_cursor_native_completion_receipt.py::test_skip_is_persisted_before_the_cursor_passes_it
tests/server/integration/test_input_fence.py::test_reserved_labels_cannot_be_forged
tests/server/integration/test_input_fence.py::test_receipt_binding_is_stored_in_its_own_label
tests/server/integration/test_input_fence.py::test_receipt_persisted_for_owner_and_monotonic
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_queued_repost_verifies_only_after_both_copies_end
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_single_late_turn_verifies_once_it_ends
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_restart_mid_pass_keeps_the_lost_row_unacked
# cursor isolation
tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_user_mcp_has_omnigent_server
tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_project_file_aliasing_the_user_file_is_never_written
tests/test_cursor_native_bridge.py::TestSharedMcpScope::test_account_home_is_never_written
tests/test_cursor_native_bridge.py::TestHooksConfig::test_write_hooks_config_preserves_existing_hooks
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_write_hooks_config_skips_home_workspace
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_write_hooks_config_skips_account_home
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_arm_refused_drops_stale_epoch_and_keeps_user_hooks
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_workspace_that_is_home_refuses_receipts
tests/test_cursor_native_bridge.py::TestCompletionReceiptHookGate::test_account_home_is_refused_even_when_home_env_differs
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_home_workspace_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_repo_subfolder_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_alias_to_a_repo_subfolder_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_folder_inside_home_repo_is_refused
tests/test_cursor_native_bridge.py::TestCursorLaunchAdmission::test_own_repo_inside_home_repo_is_admitted
tests/server/integration/test_cursor_receipt_binding_e2e.py::test_workspace_that_is_home_holds
# input fence
tests/server/integration/test_input_fence.py::test_verified_fence_rejects_every_input_api_and_persists
tests/server/integration/test_input_fence.py::test_new_input_racing_a_close_is_refused
tests/server/integration/test_input_fence.py::test_open_is_runner_first_and_fails_closed
tests/server/integration/test_input_fence.py::test_injection_after_receipt_fails_verification
tests/server/integration/test_input_fence.py::test_crash_mid_close_reconciles_on_retry
tests/test_cursor_native_completion_receipt.py::test_fenced_pane_refuses_injection_before_touching_tmux
tests/test_cursor_native_completion_receipt.py::test_fence_close_linearizes_against_concurrent_injections
# stop-routing + kill escalation (#10251)
tests/server/test_v21_shared_runner_kill_on_close.py::test_stop_subagent_child_kills_native_harness_without_stopping_shared_host_runner
tests/server/test_v21_shared_runner_kill_on_close.py::test_stop_top_level_host_session_stops_owned_host_runner
tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_codex_native_hard_stops_without_marker
tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_native_kills_tmux_and_publishes_idle
tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_native_returns_503_when_kill_fails
tests/runner/test_native_interrupt_runner.py::test_uniform_stop_kills_tears_down_and_goes_idle
tests/runner/test_native_interrupt_runner.py::test_uniform_stop_kill_failure_returns_503_without_idle
tests/tools/builtins/test_sys_session.py::test_close_accepts_child_with_unparsable_title
tests/tools/builtins/test_sys_session.py::test_close_marks_closed_and_tombstones_internal_title
tests/test_cursor_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill
tests/harnesses/codex_native/test_codex_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill
tests/harnesses/claude_native/test_claude_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill
# Codex manual compact
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_sends_thread_compact_start_and_reports_accepted_not_completed
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_completion_event_resolves_completed
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_missing_completion_times_out_uncertain_without_resend
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_active_turn_is_busy_and_sends_nothing
tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_forwarder_live_stream_settles_manual_compact_and_still_mirrors
tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_sends_thread_compact_start
tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_409_while_turn_active
tests/runner/test_app_sessions_native_events_options.py::test_codex_native_compact_failure_clears_spinner_without_completion
# claude_native hook bridge + hook TMPDIR
tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_always_registered_hook_commands_match_hook_cli_parser
tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_injected_optional_hook_commands_match_hook_cli_parser
tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_defaults_to_unix_socket
tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_refuses_symlinked_socket_root
tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_reaps_sockets_of_dead_owners
tests/harnesses/claude_native/test_claude_native_bridge.py::test_generated_claude_subprocesses_pin_runner_tmpdir
tests/harnesses/claude_native/test_claude_native_bridge.py::test_augment_claude_args_injects_mcp_and_hooks
```

## 6. Consumer compatibility vs a scratch server + host (GOAL DoD 5)

Harness: `bash scripts/v21_consumer_compat.sh` (stack: `scripts/v21_scratch_stack.sh`; checks:
`docs/v21-evidence/scratch/compat_checks.py`; method and isolation: `docs/v21-evidence/scratch/README.md`). It starts an
`omnigent server` + `omnigent host` from this tree under `env -i` with an isolated `HOME`, `OMNIGENT_DATA_DIR`,
`OMNIGENT_CONFIG_HOME`, `TMPDIR` and XDG dirs below a fresh `/var/tmp/v21s.*`, on a random loopback port that is never
6767/6768/7456/8443; the scratch host connects only to the scratch server. Consumers are imported read-only by path
(`python -I -B`, no bytecode), with `urlopen`/`OpenerDirector.open` wrapped so any request to another host/port is
refused and counted. Teardown (always, via trap) kills only the PIDs it started, their descendants, processes whose
environ carries this run's exact `OMNIGENT_DATA_DIR`, and tmux servers on sockets under its own TMPDIR; then it removes
the scratch tree. Auth: loopback single-user (no auth flags → `OMNIGENT_LOCAL_SINGLE_USER=1`), exactly how the live
`omni server` runs and how trio then talks to it (no `OMNIGENT_TOKEN`, no `auth_tokens.json`).

Transcript (Lead it2 review run, port 48623): `docs/v21-evidence/scratch/transcript.txt` → `7 passed, 0 failed`.

| CHECK | result | what it proves |
|---|---|---|
| `trio-broker` | PASS | 5a: `broker_http.register_agent_bundle` + `update_agent_bundle` for every installed trio role bundle; `BrokerClient.create_session` host-launches a session; GET one, POST `/events` (202), GET `/items`, GET list (`kind=any`) contain it |
| `bundle-restrictions-10906` | PASS | 5a/#10906: unregistered `type: function` handler, absolute `os_env.cwd`, `..` cwd → HTTP 400 with the #10906 messages; unmodified trio bundles accepted (`blast_radius` is a registered shim) |
| `ownership-10850` | PASS | 5a/#10850: the token-less creator owns the session — GET, POST `/events`, GET `/items` and DELETE all succeed |
| `runner-gone-after-delete` | PASS | 5a: trioctl's close (archive → `runner_online: false` → DELETE) leaves no runner, zygote-forked harness, tmux or session-env process within 60 s, server+host still up |
| `appcontrol-dev-processes` | PASS | 5b: `dev_processes._zygote_log_session_id` maps the runner's log fd `runner-<32hex>-<YYYYMMDD>-<HHMMSS>-<n>.log` to the API session id; `_read_environ` sees `OMNIGENT_RUNNER_PRIMARY_SESSION_ID`, `OMNIGENT_TERMINAL_LAUNCH_SESSION_ID`, `OMNIGENT_RUNNER_WORKSPACE`; `_is_zygote_proc` + ppid chain reach the scratch host pid; `snapshot()` runs |
| `appcontrol-titles` | PASS | 5b: `omnigent_titles.http_fetch_one` (`?include_items=false`) and `http_fetch_list` (`limit&sort_by=updated_at&order=desc`) parse to the same id and title as the API |
| `teardown-clean` | PASS | no live process with the scratch data dir; 0 guarded-opener violations |

### 6.1 (5a) trio broker_http

Evidence: `docs/v21-evidence/scratch/transcript.txt` (rows `trio-broker`, `bundle-restrictions-10906`, `ownership-10850`,
`runner-gone-after-delete`). Source read: `/home/coder/personal/trio-agent-loop/omnigent/broker_http.py`; bundles:
`~/.local/share/trio-agent-loop/current/omnigent/trio-omnigent-roles/<role>/config.yaml` (copied into the scratch dir
before upload). Observations, none needing a consumer change:
- `/v1/sessions/{id}/events` is POST-only on v0.21 (reads go through `/items` and the `/stream` SSE route); trio only
  POSTs it (`send_message`, `input_fence`).
- **DELETE alone does not stop a host-launched session's runner** (upstream behaviour: the `delete_session` route in
  `omnigent/server/routes/sessions/routes_events.py` has no fork hunk and never calls `_stop_host_runner_intentionally`;
  only the archive path in `omnigent/server/routes/_sessions/orchestration.py` does). Observed in the Lead's it2 run:
  the forked runner survived a bare DELETE for 61 s until teardown. trioctl already archives first
  (installed `omnigent/trioctl` `_prune_broker_sessions` → `_stop_session_runner`, comment at trioctl:5135), so trio is
  unaffected; any other caller that only DELETEs leaves the runner to its idle reaper.
- PATCH `permission_mode` on a cursor-native session → 400 (`only supported for claude-native and devin-native`);
  trio never sends it.
- In the scratch HOME cursor-agent has no credentials, so `create_session` reports `PromptDeliveryUncertain` for the
  first prompt (session kept); the session, its runner and harness are real, which is what the checks need.

### 6.2 (5b) App Control parsers

Evidence: `docs/v21-evidence/scratch/transcript.txt` (rows `appcontrol-dev-processes`, `appcontrol-titles`). Source read:
`/home/coder/personal/agent-platform/template/build/dev_processes.py` (its `_OMNIGENT_SESSIONS` / `_OMNIGENT_SESSION`
constants point at 6767 and are overridden in memory to the scratch port) and `omnigent_titles.py`. The runner log name
(`omnigent/host/connect.py` `runner-{session_slug}` + `%Y%m%d-%H%M%S-%f`) still matches App Control's
`^runner-([0-9a-f]{32})-\d{8}-\d{6}-\d+\.log$`; the fd is held by the zygote-forked runner (argv
`python -P -m omnigent.runner._zygote`), whose parent is the host's `_zygote` forkserver under `omni host`. The env keys
sit on the tmux/harness processes, where App Control already reads them. No change needed.

### 6.3 (5c) claude_native hook CLI args

Evidence: `docs/v21-evidence/behaviour-check.txt` (behaviour `claude_native hook bridge + hook TMPDIR`, incl.
`tests/harnesses/claude_native/test_v21_hook_cli_contract.py::test_always_registered_hook_commands_match_hook_cli_parser`
and `::test_injected_optional_hook_commands_match_hook_cli_parser`), described in §5. The runner-injected argv
(`env TMPDIR=<dir> <python> -I -m omnigent.harnesses.claude_native.hook [subcommand] --bridge-dir <abs dir>`) parses with
the hook CLI. No change needed.

Incompatibilities requiring a fork or consumer change: **none** (no `KNOWN-INCOMPAT:` line).

## 7. Risks, migrations, not-verifiable items, rebase to final v0.21.0, install/rollback (GOAL DoD 7)

Template: `docs/v17-report.md` §6–§8. Every claim below is a command or
file:line read in this tree at `07292095d`.

### 7.1 Database migrations since v0.17.0

`git diff --name-only --diff-filter=A v0.17.0 HEAD -- omnigent/db/migrations/versions`
lists **6 new files** (v0.17.0 head is `mm1a2b3c4d5e`). Chain (Lead recon,
verified by reading each file's `revision` / `down_revision`):
`nf12ab34cd56` (revises `mm1a2b3c4d5e`) → `c8e4f2a6b901` →
`{9e82957bd115, d3f7a1c9e2b4}` → `b2e4f6a8c013` (merge) → `d0a1f879a01d`.

| revision id | file | revises | what it does |
|---|---|---|---|
| `nf12ab34cd56` | `omnigent/db/migrations/versions/nf12ab34cd56_index_conversations_by_host.py` | `mm1a2b3c4d5e` | Additive index `ix_conversation_metadata_host_id` on `omnigent_conversation_metadata(workspace_id, host_id, id)` for host-bound session recovery. PostgreSQL: `CREATE INDEX CONCURRENTLY` in an autocommit block; drops an INVALID leftover first (`nf12ab34cd56_index_conversations_by_host.py:21-46`). Other dialects: `op.create_index`. `downgrade()` = `op.drop_index` (`:49-50`). No data change. |
| `c8e4f2a6b901` | `omnigent/db/migrations/versions/c8e4f2a6b901_add_scheduled_task_dispatch_fields.py` | `nf12ab34cd56` | Widens scheduled-task/run timestamps Integer→BigInteger; adds `next_run_at`, `project_id`, `delegation_ref`, due index; run `trigger_key`/`host_id`/`lease_expires_at`, uniqueness, expired-claim index; check constraint now allows status `6` (`:30-78`). Docstring: deploy before consumers; reserve status 6 until readers support starting. `downgrade()` is **online-only** (`context.is_offline_mode()` raises `:83-86`) and **guarded**: refuses if any run has status 6 or timestamps outside signed 32-bit (`:87-104`); then **discards** the new columns (`:106-141`). |
| `9e82957bd115` | `omnigent/db/migrations/versions/9e82957bd115_add_scheduled_task_completed_state.py` | `c8e4f2a6b901` | Replaces `ck_scheduled_tasks_state` with `ck_scheduled_tasks_lifecycle_state` allowing state `4` (completed) (`:24-31`). `downgrade()` online-only and **guarded**: refuses while any task is completed (`:34-41`). No row rewrite on upgrade. |
| `d3f7a1c9e2b4` | `omnigent/db/migrations/versions/d3f7a1c9e2b4_add_pull_requests_to_conversation_metadata.py` | `c8e4f2a6b901` | Adds nullable compressed `pull_requests` LargeBinary on `omnigent_conversation_metadata` (`:31-33`). Additive, no backfill. `downgrade()` drops the column (**discards** stored copies; hosts re-report) (`:36-39`). Parallel branch with `9e82957bd115`. |
| `b2e4f6a8c013` | `omnigent/db/migrations/versions/b2e4f6a8c013_merge_completed_state_and_pull_requests.py` | `9e82957bd115`, `d3f7a1c9e2b4` | Alembic merge only. `upgrade()`/`downgrade()` are empty (`:18-23`); no schema or data change. |
| `d0a1f879a01d` | `omnigent/db/migrations/versions/d0a1f879a01d_add_scheduled_task_session_mode.py` | `b2e4f6a8c013` | Adds `session_mode` (NOT NULL, server_default `"1"`, check IN (1,2)) and nullable `session_id` on `scheduled_tasks`; new index `ix_scheduled_task_runs_conversation_status` (`:33-45`). Existing tasks default to a new session per run. `downgrade()` drops the index and both columns (`:48-54`) — continued tasks would start a new session each run again. Not a row-delete; default backfill only. |

Head revision: `d0a1f879a01d`

The fork adds **no** migration: `git diff --name-only --diff-filter=A v0.21.0rc1 HEAD -- omnigent/db` is empty.

How the server applies them on start (`omnigent/db/utils.py`):
- `_initialize_or_verify_schema` (`:768`): fresh DB → `_run_migrations`; at head → no-op; **Behind head** → warning `"Omnigent database schema is out of date … attempting automatic migration"` (`:805-812`) then `_run_migrations`.
- `_run_migrations` (`:561`) always calls Alembic `command.upgrade(..., "head")` (`:606`).
- Manual path still exists: `omnigent debug db-upgrade` (error text at `:819`).

**Downgrade is not supported.** `_verify_db_revision_is_supported` (`:745-765`) raises
`RuntimeError("Omnigent database schema is newer than this version of Omnigent … Upgrade Omnigent before using this database.")`
when this build does not know the stamped revision. There is no `command.downgrade` CLI.
`c8e4f2a6b901` / `9e82957bd115` downgrades are guarded/online-only; `d3f7a1c9e2b4` discards PR copies.

A live DB still on v0.17.0 (`mm1a2b3c4d5e`) gets **all six** revisions in one start
(behind-head path above). Snapshot `chat.db` first (§7.5).

### 7.2 Config / preference / API changes

- **#10850 (`f93be3274`, `fix: sync runtime and session validation improvements`)**:
  session-ownership for permission/approval-mode changes, terminal launch args,
  terminal transfers, external transcript / native mode-change events; native
  approval hooks need edit access. Project `.omnigent/config.yaml` can no longer
  set `server` or per-harness `command`/`args`: `omnigent/config.py::_merge_effective_config`
  (`:82-114`) copies project keys except `server` and `harness`, then allows only
  `harness.default`; `_ignored_project_harness_keys` (`:74-79`) logs ignored
  per-harness names without printing their command/args.
  Consumers (key **names** / line numbers only — values not recorded):
  `find /home/coder/personal -maxdepth 4 -path '*/.omnigent/config.yaml'` found
  **no** files. `~/.omnigent/config.yaml` exists; `grep -nE '^\s*(server|command|args)\s*:'`
  matched key `server` at line 4 (no `command` / `args` keys).
- **#10906 (`60a5f61f7`)**: HTTP bundle restrictions in
  `omnigent/server/bundles.py` (`validate_agent_bundle` `:102-171`,
  `_reject_uploaded_callable_tools` `:36-65`, `_reject_uploaded_escaping_cwd`
  `:92-99`) and `omnigent/spec/__init__.py::load` (`enforce_handler_allowlist`
  `:164-201`, applied `:303`). Untrusted uploads: no server-side callable /
  `.py`/`.ts` source-file tools, no unregistered `type: function` policy
  handlers, no absolute/`..` working dirs. Trio's
  `omnigent.inner.nessie.policies.blast_radius` guardrail is a **registered
  shim**: `omnigent/policies/builtins/__init__.py` `BUILTIN_POLICY_MODULES`
  (`:37-52`) includes `"omnigent.inner.nessie.policies"`; that module
  (`omnigent/inner/nessie/policies.py:1-22`) re-exports
  `omnigent.policies.builtins.orchestration` (including `blast_radius` at
  `orchestration.py:352`) under the legacy handler prefix.
- **#9844 (`d2e077a1e`)**: tighter shell-policy gating — preserve shell groups
  and quoted arguments (`omnigent/policies/builtins/_shell.py:307`) and Git
  global options that consume a following token
  (`omnigent/policies/builtins/working_dir.py:74`). Bundles/runtime tool
  validation aligned in the same commit.
- **Python client pagination**: `sdks/python-client/omnigent_client/_sessions.py`
  `list_items()` (`:953-992`) and `child_sessions()` (`:994-1031`) now return
  `PaginatedList`. `git show v0.17.0:sdks/python-client/omnigent_client/_sessions.py`
  shows `list_items` `:880` → `builtins.list[dict[str, Any]]` and
  `child_sessions` `:920` → `builtins.list[dict[str, Any]]`. Callers that
  iterate the return value as a list must use `.data`.
- **Feature flags** (`git diff v0.17.0 HEAD -- omnigent/server/feature_flags.py`):
  **removed / renamed:** `Feature.HARNESS_SETTINGS_UI = "harness_settings_ui"`
  is gone (`e0f7d2e73` #10459: "Deployments that still list harness_settings_ui
  in OMNIGENT_FEATURES must remove it: unknown names fail startup.").
  **Added:** `sandbox_profiles`, `session_orchestration`, `codex_plan_at_launch`,
  `arca_shutdown_warnings`, `import_review`, `custom_agents_settings_ui`,
  `sidebar_grouping_ui`, `claude_osc_status`, `workspace_content_search`,
  `grid_sessions_display_ui`, `automations_v2`, `splittable_terminal_view_ui`
  (`omnigent/server/feature_flags.py:23-40`). Unset env now uses
  `default_enabled` rather than "all off". Unknown names still fail startup
  (`resolve_feature_flags` docstring `:205` and `ValueError` `:236-240`).
- **GET `/v1/sessions` and GET `/v1/sessions/{id}` query params**
  (`omnigent/server/routes/sessions/routes_core.py`):
  - GET by id (`get_session` `:1647-1655`): v0.17.0 had `include_items`,
    `include_liveness`, `refresh_state`, `include_usage`
    (`git show v0.17.0:…routes_core.py:1200-1203`). **New:** `include_live_status`
    (default `True`, `:1653`).
  - List (`list_sessions` `:1797-1812`): v0.17.0 already had `limit`, `after`,
    `before`, `agent_id`, `agent_name`, `order`, `sort_by`, `search_query`,
    `include_archived`, `kind`, `project`, `pinned`, `visibility`
    (`v0.17.0:1315-1327`). **New:** `search_scope` (default `"all"`,
    pattern `all|title|content`, `:1807`). App Control already uses
    `?include_items=false` and `?limit&sort_by=updated_at&order=desc` (GOAL);
    those params still exist.
- **Notable removals** (`git log --oneline v0.17.0..v0.21.0rc1 | grep -iE 'break|!:|remove|retire|rename'`),
  HTTP/CLI/config only:
  - `e0f7d2e73` retire `harness_settings_ui` (env; see flags above).
  - `8a1df12d8` Rename AI Gateway to Unity Gateway (#8812) — branding/API naming.
  - `3ab97433c` `omnigent agent add` / list / remove user agents (#8677) — new CLI,
    not a removal.
  - Most other hits are tests, owners, Vitest/Tinypool, iOS keyboard, lab
    connections, or internal pollers — not HTTP/CLI/config contracts.
- **`uv.lock` / `pyproject.toml`**: `git diff --stat v0.17.0 v0.21.0rc1 -- pyproject.toml uv.lock`
  → `pyproject.toml | 72 ++-`, `uv.lock | 1848 +++++++++++++++++++++++++++++++-------------------------`,
  `2 files changed, 1075 insertions(+), 845 deletions(-)`. `pyproject.toml`
  version `0.17.0` → `0.21.0rc1` (and matching `omnigent-client` /
  `omnigent-ui-sdk` pins); floors/caps move for rich, pillow, cachetools,
  argon2-cffi, packaging, certifi. `uv sync --frozen` on this tag needs the
  lock that ships with rc1 (do not keep a v0.17 lock).

### 7.3 Not verifiable without the live server

Scratch-server checks (other slices, isolated HOME/port ≠ 6767) cannot show:

- Real `cursor-agent` / `codex` / `claude` turns (receipts, plugin-dir, compact,
  hook Unix-socket MCP, hook TMPDIR). Gated e2e:
  `tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py` and related, need
  `OMNIGENT_E2E_*=1` plus a logged-in CLI.
- Live migration of the real `~/.omnigent/chat.db` (this slice only **read**
  Alembic files; no copy of the live DB was migrated).
- Live host under load: kill escalation, pane reaper, viewer-attached busy
  rule, runner/zygote env (`OMNIGENT_CURSOR_PLUGIN_DIR`) through the real host.
- Web UI (Harnesses/custom-agents/settings, grids, automations v2).
- `trioctl omnigent doctor` import of `_resolve_agent_spec` (alias is in the
  tree — `c366fd184` / `v21-port-close.md`; the import was not exercised from
  the installed trio release).
- The child-reasoning-effort patch driving **real Trio loops** (only apply-check
  + unit tests + Evaluator it1 base-revert probe).
- Gated e2e / skipped focused-group tests and anything that needs the live
  `omni server` on 127.0.0.1:6767 (GOAL forbids contacting it).

### 7.4 Rebase onto final v0.21.0

Chosen method: **new branch + `git cherry-pick -x`** of
`v0.21.0rc1..trio-v0.21.0-fixes`, skipping `loop/`-only commits. Justification:
this port already used `-x` in original v17 order; `git rebase --onto v0.21.0
v0.21.0rc1 trio-v0.21.0-fixes` would rewrite those commits and re-open the
version/lock conflicts the Lead resolved by keeping upstream. Cherry-pick
keeps trailers and lets `loop/`-only commits stay dropped.

Exact commands (documentation; this slice does not run them):

```sh
git fetch upstream --tags
git rev-parse v0.21.0^{}          # verify the tag object
git merge-base --is-ancestor v0.21.0rc1 v0.21.0   # expect 0 if rc1 is ancestor
git switch -c trio-v0.21.0-final v0.21.0
# product commits only (exclude paths that are only loop/ / loop-archive-*):
git log --reverse --pretty=%H v0.21.0rc1..trio-v0.21.0-fixes |
  while read -r c; do
    paths=$(git diff-tree --no-commit-id --name-only -r "$c")
    echo "$paths" | grep -qvE '^(loop/|loop-archive)' || continue
    git cherry-pick -x "$c"
  done
```

Conflict policy: keep **upstream** `omnigent/version.py`, `pyproject.toml`,
`uv.lock`, and `sdks/*/pyproject.toml` / `integrations/slack/pyproject.toml`.
Re-layer fork hunks on top of the v0.21.0 files (same as the rc1 port).

Then re-run (after retargeting rc1 literals):

```sh
scripts/v21_focused_suite.sh          # on pristine v0.21.0 (new baseline) and on the rebased tip
python3 -I scripts/v21_compare_suites.py docs/v21-evidence/baseline-v0.21.0.txt docs/v21-evidence/after-port.txt
scripts/v21_overlap_check.sh
scripts/v21_disposition_check.sh
# patch apply checks (same GIT_INDEX_FILE read-tree pattern as docs/v21-evidence/patch-check.txt, retargeted to v0.21.0)
scripts/v21_consumer_compat.sh        # not in this tree yet; run when that slice lands
```

`v0.21.0rc1` literals that must become `v0.21.0` (or a new baseline filename):

| file:line | current literal |
|---|---|
| `scripts/v21_disposition_check.sh:7` | comment "ancestor of v0.21.0rc1" |
| `scripts/v21_disposition_check.sh:19` | `BASE, SRC_FROM, SRC_TO = "v0.21.0rc1", ...` |
| `scripts/v21_focused_suite.sh:5` | comment "v0.21.0rc1 test tree" |
| `scripts/v21_focused_suite.sh:39` | `git diff --quiet v0.21.0rc1 HEAD` |
| `scripts/v21_focused_suite.sh:40` | `emit "pristine-vs-v0.21.0rc1: yes"` |
| `scripts/v21_focused_suite.sh:42` | `emit "pristine-vs-v0.21.0rc1: no"` |
| `scripts/v21_overlap_check.sh:5` | comment "tag v0.21.0rc1" |
| `scripts/v21_overlap_check.sh:18` | `TAG="v0.21.0rc1"` |
| `scripts/v21_compare_suites.py` | no `v0.21.0rc1` literal (paths are caller-supplied) |
| `scripts/v21_consumer_compat.sh` | file absent on this revision |

Also rename `docs/v21-evidence/baseline-v0.21.0rc1.txt` when a new baseline is
recorded. Patch filename `patches/child-reasoning-effort.v0.21.0rc1.patch`
needs a v0.21.0 counterpart if the hunks still apply.

### 7.5 Install and rollback for the live editable install (documentation only — not run)

The live install is the editable `/home/coder/omnigent` (GOAL: currently
branch `trio-v0.17.0-fixes`, v0.17.0 + fork, with the child-reasoning-effort
patch as uncommitted edits). **This loop did not run any command in
`/home/coder/omnigent`** (not even `git status`). Method reused from
`~/.local/state/omnigent-upgrade/upgrade-to-0.14.sh` (read-only): stop
services, snapshot `chat.db` (+ `-wal`/`-shm` via `sqlite3 .backup`) + tool
env + git HEAD/branch/working-tree diff, switch, health-check, auto-rollback
on failure. DB snapshot is **mandatory** (migrations are forward-only, §7.1).

Delivered script: `docs/v21-evidence/upgrade-to-0.21.sh` (adapted from
upgrade-to-0.14.sh). It **refuses to run** unless `CONFIRM_LIVE_UPGRADE=1`,
contains the rollback path, and was only syntax-checked (`bash -n`; **never
executed**).

DB location (cite):
- `omnigent/host/local_server.py::_local_data_dir` (`:80-102`):
  `$OMNIGENT_DATA_DIR` if set, else `~/.omnigent`.
- `omnigent/cli.py::_default_db_uri` (`:1296-1312`):
  `sqlite:///<data_dir>/chat.db`. `--database-uri` / config still override.

**Pre-flight (human, before stopping anything)**

```sh
D="${OMNIGENT_DATA_DIR:-$HOME/.omnigent}"; TS=$(date +%Y%m%dT%H%M%S)
B="$HOME/omnigent-backups/pre-v0.21.0-$TS"; mkdir -p "$B"
# 1. HUMAN: stop server/host/runner the way you normally stop them.
# 2. consistent DB copy (WAL folded in):
sqlite3 "$D/chat.db" ".backup '$B/chat.db'"
sqlite3 "$B/chat.db" "select version_num from alembic_version"   # expect mm1a2b3c4d5e
# 3. record checkout (human, in /home/coder/omnigent — not this loop):
# git rev-parse HEAD; git branch --show-current  # expect trio-v0.17.0-fixes
# git diff > "$B/working-tree.diff"               # trio patch if applied
```

**Install (human; or `CONFIRM_LIVE_UPGRADE=1 docs/v21-evidence/upgrade-to-0.21.sh`)**

Stop services → snapshot (script uses `sqlite3 .backup`) → switch live
checkout to the verified `trio-v0.21.0-fixes` tip → `uv tool install --editable`
→ start; first start migrates `mm1a2b3c4d5e` → `d0a1f879a01d`.

**Verify**

```sh
sqlite3 "${OMNIGENT_DATA_DIR:-$HOME/.omnigent}/chat.db" "select version_num from alembic_version"
# must equal Head revision from 7.1: d0a1f879a01d
omnigent --version    # 0.21.0rc1 (or 0.21.0 after the final rebase)
```

**Rollback** (script `upgrade-to-0.21.sh rollback`, or the same steps by hand):
stop services; restore the snapshot `chat.db` (replace live `chat.db` +
`-wal`/`-shm`); restore tool-env and git `trio-v0.17.0-fixes` + working-tree
diff; start. Do **not** switch the branch without restoring the DB: v0.17.0
code hits the "schema is newer" guard (§7.1) on a DB stamped `d0a1f879a01d`.
