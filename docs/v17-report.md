# Omnigent fork re-port onto v0.17.0 — report

Branch: `trio/loop` → lands on `trio-v0.17.0-fixes` (base: upstream tag `v0.17.0` = `12b5f67d2`;
the loop's mailbox-only base commit is `b52507b70`, `loop: mailbox for v0.17.0 re-port`).
Port source: `v16/trio-v0.16.0-fixes` (tip `3dd44be0f`), range `v0.16.0..v16/trio-v0.16.0-fixes` =
**66 commits** (`git log --oneline v0.16.0..v16/trio-v0.16.0-fixes | wc -l`). Original fork
`fork/release/omnigent-2a84483a` (tip `318264335`) is referenced only through the `(cherry picked
from commit …)` trailers that the v16 commits carry. Method: the v16 method — `git cherry-pick -x`
in original order, conflicts resolved keeping upstream v0.17.0 behaviour with the fork layered on
top, adaptation work committed as `slice(<id>): …`. Product commits on this branch at the time of
this report: `git log --oneline b52507b70..903c3aeab` = 77 (55 cherry-picks, 14 adaptation/notes/
evidence commits, 8 worker merges; listed in §1.2).

Totals (66 v16 commits): **43 ported** (clean pick), **12 adapted** (conflicts resolved or code/test
changed for v0.17.0), **3 dropped** (superseded by v0.17.0, with evidence), **8 not ported**
(5 worker merge commits + 3 loop-mailbox-only commits). 43 + 12 + 3 + 8 = 66; the 58 product
commits are the 43 + 12 + 3.

All pytest runs in this report used `TMPDIR=/var/tmp/pytest-of-coder`: the driver's TMPDIR is long
and tmux socket paths under it exceed the 108-byte AF_UNIX limit (same quirk as v16 §3).

## 1. Disposition table (all 66 v16 commits, original order)

Columns: `v16 sha` = commit on `v16/trio-v0.16.0-fixes` (9 chars); `original fork sha` = the trailer in
the v16 commit message that is an ancestor of `fork/release/omnigent-2a84483a` (v16-only commits
have none); `new sha` = the cherry-pick on this branch. Per-slice notes (conflicts, which upstream
change was kept, pristine-proven deselects) are in `docs/v17-evidence/dispositions/<slice>.md`
(the `note` in each row). v16 commits whose message carries two fork trailers (rows 13, 14, 16, 17)
list the one that is an ancestor of the fork tip; the other is an older v14-chain sha that is not on
`fork/release/omnigent-2a84483a`.

| # | v16 sha | original fork sha | subject | disposition | new sha on this branch | evidence |
|---|---|---|---|---|---|---|
| 1 | ca5b07c04 | — | loop: mailbox for v0.16.0 re-port | not ported | — | loop-only mailbox commit (`loop/` files); not product code (GOAL) |
| 2 | 48d792284 | 5837d559d | slice(kill-on-close): stop the target harness on sys_session_close. | adapted | 8f7f924c2 | `-x` trailer `cherry picked from commit 48d7922849190fe11663269bf1950c1dd55d70ba` on 8f7f924c2; note `v17-port-close.md` |
| 3 | 1da2e0ee1 | — (v16-authored) | slice(port-v14-close): adapt kill-on-close pick to v0.16 (wrapper label import, bridge module path) | ported | fb38228b0 | `-x` trailer `cherry picked from commit 1da2e0ee1aaabf84f9b596e6eec41e62484469f3` on fb38228b0; note `v17-port-close.md` |
| 4 | de03a352c | 49da161cd | fix(cursor-native): queue-aware yolo auto-accept for batched tools. | dropped | — | superseded by upstream #8516 `a16334f78` (`auto_accept_available`/`approval_waiting` gate: one accept per poll, non-visible gates never spend retry budget); covered by `tests/test_cursor_native_permissions.py::test_supervise_transcript_yolo_waits_through_stale_pending_burst[prompt/transcript/backoff]`; note `v17-port-close.md` |
| 5 | d69671640 | a60a600d7 | fix(cursor-native): drop phantom cards for stale yolo markers. | dropped | — | superseded by upstream #8516 `a16334f78` (pending marker with no visible accept hint -> no key, no card); covered by `tests/test_cursor_native_permissions.py::test_supervise_transcript_yolo_never_types_when_no_prompt_on_screen` and the burst test above; note `v17-port-close.md` |
| 6 | d8aa8058d | 3444f699f | slice(codex-bridge-owner): serve Codex model options from a labeled live bridge | adapted | 033e6837e | `-x` trailer `cherry picked from commit d8aa8058d29330586be48611ee29483c1daede3d` on 033e6837e; note `v17-port-close.md` |
| 7 | ff86cbba7 | 4dfbe128d | slice(compact-on-fork-cross-harness): replay summary-only Codex compaction markers | ported | 561681c55 | `-x` trailer `cherry picked from commit ff86cbba7674f8071f9fb7ae2ecdff7b9d95508f` on 561681c55; note `v17-port-close.md` |
| 8 | 39e45d8d4 | 69db59457 | fix(sessions): re-export _resolve_agent_spec from the sessions package | dropped | — | `_resolve_agent_spec` no longer exists in `server/routes/_sessions/helpers.py` on v0.17.0 (re-export would be an ImportError); the alias is delivered by `d4f6816bf` -> `669e05bfd` (`omnigent/server/routes/sessions/__init__.py:785`); note `v17-port-close.md` |
| 9 | d4f6816bf | 70d652bbc | slice(session-contract): alias _resolve_agent_spec to _resolve_subagent_spec | adapted | 669e05bfd | `-x` trailer `cherry picked from commit d4f6816bf55bad2e58108c0cfa78a5f126911133` on 669e05bfd; note `v17-port-close.md` |
| 10 | cfeb9ee10 | c7a454a78 | slice(close-guard): close tree-scoped children with unparsable titles | ported | ab9d2c7cb | `-x` trailer `cherry picked from commit cfeb9ee1055c1f9d0568eaf0c2bba82bb13ee80d` on ab9d2c7cb; note `v17-port-close.md` |
| 11 | a902a5ddc | — (v16-authored) | slice(port-v14-close): disposition notes for v14 close slice | ported | 2eed26a21 | `-x` trailer `cherry picked from commit a902a5ddcc19c0847066561a5584769c3b708128` on 2eed26a21; note `v17-port-close.md` |
| 12 | 36b923881 | — | merge(worker): port-v14-close-504ef5d3 slice port-v14-close | not ported | — | worker merge commit (bookkeeping/merge); no product change of its own |
| 13 | ecfd01174 | 41d82337d | slice(stop-routing): hard-stop Claude, Codex and Cursor on close | adapted | 30764d7e9 | `-x` trailer `cherry picked from commit ecfd01174f917e9e05fd51ef3fbf9e1d1f8494a6` on 30764d7e9; note `v17-port-stop.md` |
| 14 | cb7807e2f | 4e4b88928 | slice(kill-escalation): share leftover-pane SIGKILL across native bridges | adapted | 150efd6ff | `-x` trailer `cherry picked from commit cb7807e2fd85eb9b858fa2cf89936aa8ffd21665` on 150efd6ff; note `v17-port-stop.md` |
| 15 | 2ed8634c8 | — (v16-authored) | slice(port-v14-stop): drop unused _proc import and fix pre-split codex bridge test import after kill-escalation pick | adapted | a526deb64 | `-x` trailer `cherry picked from commit 2ed8634c82f1a6657f052ea782083921a04862f8` on a526deb64; note `v17-port-stop.md` |
| 16 | 9734887b3 | 642b879d7 | slice(reaper): reap native panes after harness subprocess release | ported | 958ee4c24 | `-x` trailer `cherry picked from commit 9734887b3da7446b3b0bd068b90d7613f8d56cb6` on 958ee4c24; note `v17-port-stop.md` |
| 17 | 10887f8ed | 305ac7cf7 | slice(codex-advertise-guard): do not abort Codex auto-create when tmux advertise is missing | adapted | 54f5172bf | `-x` trailer `cherry picked from commit 10887f8ed395dd0d03005d7dba9e53fe99e06860` on 54f5172bf; note `v17-port-stop.md` |
| 18 | b44be221b | c20f65e54 | slice(readme): note trio-v0.14.0-fixes until live adopt | ported | c69e6e76f | `-x` trailer `cherry picked from commit b44be221b8ac782751469a46823044ed72d2b94c` on c69e6e76f; note `v17-port-stop.md` |
| 19 | fb483202e | 139c74a18 | docs(v14-report): summarize the 0.14.0 re-port disposition | ported | 7e50a304d | `-x` trailer `cherry picked from commit fb483202e45291c137955a24bdb653cba058133e` on 7e50a304d; note `v17-port-stop.md` |
| 20 | 9ab5c600d | — (v16-authored) | slice(port-v14-stop): README adapted for v0.16.0 and disposition notes | ported | 477b2e2e8 | `-x` trailer `cherry picked from commit 9ab5c600d94891ad717407db6093fd5c2ff0565b` on 477b2e2e8; note `v17-port-stop.md` |
| 21 | aa1568f22 | — (v16-authored) | slice(port-v14-stop): clarify disposition note | ported | 3c16f63ee | `-x` trailer `cherry picked from commit aa1568f226d93fccbdd2a117476713e6ce939148` on 3c16f63ee; note `v17-port-stop.md` |
| 22 | edc49c021 | — | merge(worker): port-v14-stop-bf8825fc slice port-v14-stop | not ported | — | worker merge commit (bookkeeping/merge); no product change of its own |
| 23 | 5f21ceaf5 | 99d8a5884 | feat(cursor-native): opt-in completion receipts and durable input fence | adapted | b110581d4 | `-x` trailer `cherry picked from commit 5f21ceaf59af4c345046b5465077795ab58344b8` on b110581d4; note `v17-port-receipts.md` |
| 24 | 1cff84c5b | — (v16-authored) | slice(baseline-suite): focused-suite runner and pristine v0.16.0 baseline | ported | 0a0489d45 | `-x` trailer `cherry picked from commit 1cff84c5b81a0c9bb8d191bdf22336aec45403de` on 0a0489d45; note `v17-port-receipts.md` |
| 25 | a6d5f9b84 | — | merge(worker): baseline-suite-b89c3461 slice baseline-suite | not ported | — | worker merge commit (bookkeeping/merge); no product change of its own |
| 26 | 1ecb111fc | 6bc9c6923 | fix(cursor-native): bind receipt turn ends to prompts; durable skipped rows | ported | 6dfb7d57c | `-x` trailer `cherry picked from commit 1ecb111fc0e70fefb0be0e7afe164af001f23fa9` on 6dfb7d57c; note `v17-port-receipts.md` |
| 27 | 2ed704fc8 | 0944602eb | test(cursor-native): serialize mixed binding reasons in e2e evidence dumps | ported | 966a8e8ee | `-x` trailer `cherry picked from commit 2ed704fc8425f37cb04d779873650d57a65f3e25` on 966a8e8ee; note `v17-port-receipts.md` |
| 28 | 61812adf7 | 3b45e5573 | fix(cursor-native): withhold completion receipts when a foreign stop hook is configured | ported | e0849ba33 | `-x` trailer `cherry picked from commit 61812adf7e0303af44b8ebfddc827f00655b18e8` on e0849ba33; note `v17-port-receipts.md` |
| 29 | 4b580b109 | fa16a055d | fix(cursor-native): bind receipt stops to this chat; scope owned stop hooks | adapted | e90741969 | `-x` trailer `cherry picked from commit 4b580b109535bc8598a36b9d50797b410a8661e5` on e90741969; note `v17-port-receipts.md` |
| 30 | d0db96552 | fb085ca12 | fix(cursor-native): abort launch when a stale receipt epoch cannot be removed | ported | c2d486a61 | `-x` trailer `cherry picked from commit d0db96552c4b388f2b2c6fedd7c3b984e97db3a0` on c2d486a61; note `v17-port-receipts.md` |
| 31 | b19f3fbf2 | — (v16-authored) | slice(port-cursor-receipts): disposition notes | ported | f824ffc1d | `-x` trailer `cherry picked from commit b19f3fbf2c5a3f2b258a9964a73066a739a8c5a2` on f824ffc1d; note `v17-port-receipts.md` |
| 32 | a78169ed8 | — | merge(worker): port-cursor-receipts-e61f7cd6 slice port-cursor-receipts | not ported | — | worker merge commit (bookkeeping/merge); no product change of its own |
| 33 | f51c5e01f | — (v16-authored) | slice(patch-refresh): child-reasoning-effort patch for v0.16.0 | ported | 74ee1aa8b | `-x` trailer `cherry picked from commit f51c5e01fc56a5b8c053d31e392ac04332bf9209` on 74ee1aa8b; note `v17-port-receipts.md` |
| 34 | d71cbd37d | — | merge(worker): patch-refresh-d97b26f8 slice patch-refresh | not ported | — | worker merge commit (bookkeeping/merge); no product change of its own |
| 35 | 37c5ca35e | 4de324dde | fix(cursor-native): no Backspace into an empty composer; stable readiness before the first paste | ported | cf7e01b4a | `-x` trailer `cherry picked from commit 37c5ca35e3c1f28b916617c0585ed8ee9993ee06` on cf7e01b4a; note `v17-port-isolation-compact.md` |
| 36 | cef70d04d | c5444087c | fix(cursor-native): never write a session stop hook into the user hooks.json | ported | c34b373b0 | `-x` trailer `cherry picked from commit cef70d04dab934b33369e19ed55cf78e0de150cd` on c34b373b0; note `v17-port-isolation-compact.md` |
| 37 | c40055f88 | af775e159 | fix(cursor-native): never register a session MCP server in the user mcp.json | ported | c91564c23 | `-x` trailer `cherry picked from commit c40055f88a754518cdc49cd6329abe163e3e6434` on c91564c23; note `v17-port-isolation-compact.md` |
| 38 | 09488293f | a04516b21 | fix(cursor-native): refuse Cursor launches whose project config is the user ~/.cursor | ported | 4a5f7c704 | `-x` trailer `cherry picked from commit 09488293ff908d774a40cad9645bf049b1dca7b2` on 4a5f7c704; note `v17-port-isolation-compact.md` |
| 39 | eef83cd9e | 510511735 | fix(cursor-native): refuse Cursor launches from a repository subfolder | ported | 1363b3692 | `-x` trailer `cherry picked from commit eef83cd9ebf059b7c3a2ef5982df2b9fa81406e1` on 1363b3692; note `v17-port-isolation-compact.md` |
| 40 | f62033d62 | 5a782783f | test(cursor-native): keep the repo-subfolder refusal test's bridge under the launch root | ported | e4877b51d | `-x` trailer `cherry picked from commit f62033d6290f7a1422b588d25481902f77165fdb` on e4877b51d; note `v17-port-isolation-compact.md` |
| 41 | 34315a4ff | — (v16-authored) | slice(port-cursor-isolation): disposition notes; adapt ensure-response test to session_id kwarg | ported | fd369ae8c | `-x` trailer `cherry picked from commit 34315a4ff199ef64805e999d812888d10ac6ea53` on fd369ae8c; note `v17-port-isolation-compact.md` |
| 42 | 8920030c4 | — (v16-authored) | slice(port-cursor-isolation): fix keep pytest tmp_path out of a stray .git ancestor | ported | 913919d7f | `-x` trailer `cherry picked from commit 8920030c4d40e6920cf636f7738a8e2dcc06eaaa` on 913919d7f; note `v17-port-isolation-compact.md` |
| 43 | 0b90fce3e | 0b2c6ce82 | fix(codex-native): compact via app-server thread/compact/start, not tmux keys | adapted | f1676480c | `-x` trailer `cherry picked from commit 0b90fce3ecf2de3187741ec27dde766e203c9ead` on f1676480c; note `v17-port-isolation-compact.md` |
| 44 | da17fdc20 | 2a84483a5 | fix(codex-native): keep the manual-compact guard until Codex reports an outcome | ported | c52ecff7b | `-x` trailer `cherry picked from commit da17fdc20e1f73453832aec3facf4febfa3ebc81` on c52ecff7b; note `v17-port-isolation-compact.md` |
| 45 | ece706e7f | — (v16-authored) | slice(port-cursor-isolation): fix disposition new-sha column to the trio/loop commits | ported | d0a486bd2 | `-x` trailer `cherry picked from commit ece706e7fa2a5e2164fdb298bcd31b2319b04ba1` on d0a486bd2; note `v17-port-isolation-compact.md` |
| 46 | 5aee0eee0 | — (v16-authored) | slice(port-codex-compact): disposition notes for the app-server manual compact port | ported | 6fd4ca632 | `-x` trailer `cherry picked from commit 5aee0eee0e3c51fc27bd1672829c13e976f8cba3` on 6fd4ca632; note `v17-port-isolation-compact.md` |
| 47 | 8264557b8 | 354163318 | fix(cursor-native): never bind a session to another workspace's chat store | ported | 9f7220a42 | `-x` trailer `cherry picked from commit 8264557b8d75b9f13e3fe08ae580256cb8dfbb30` on 9f7220a42; note `v17-port-binding-plugin.md` |
| 48 | 80eb3acbe | e3778c9bf | fix(cursor-native): pin each fresh launch to a pre-minted chat id | adapted | 24508959a | `-x` trailer `cherry picked from commit 80eb3acbe46e09bf095b5e5b051e99a28381901d` on 24508959a; note `v17-port-binding-plugin.md` |
| 49 | 2a6546fc9 | 041d74306 | fix(cursor-native): bind a discovered chat only when this session's pane owns it | ported | 433df86ae | `-x` trailer `cherry picked from commit 2a6546fc9004624abf6302ac72eddae5f1bd4753` on 433df86ae; note `v17-port-binding-plugin.md` |
| 50 | 512d4d4a6 | 4032dde9d | fix(cursor-native): warn when a launch overwrites a live sibling's hooks/MCP slot | ported | 197a2cb17 | `-x` trailer `cherry picked from commit 512d4d4a651cfac1e1e8062e500192500e8e9d6b` on 197a2cb17; note `v17-port-binding-plugin.md` |
| 51 | 8c4a4290c | — (v16-authored) | slice(port-cursor-binding): disposition notes for the chat-binding port | ported | b6962e4af | `-x` trailer `cherry picked from commit 8c4a4290c4103121c367bcc0461f94c632a4a034` on b6962e4af; note `v17-port-binding-plugin.md` |
| 52 | f910eac65 | da6045a2e | feat(cursor-native): opt-in per-launch --plugin-dir hooks/MCP config | ported | 3c7252f3a | `-x` trailer `cherry picked from commit f910eac65c9709478b476a3a9c501b4ca30019ab` on 3c7252f3a; note `v17-port-binding-plugin.md` |
| 53 | 62baa7157 | dd33637ec | fix(cursor-native): let OMNIGENT_CURSOR_PLUGIN_DIR reach host-spawned runners | ported | a4269368c | `-x` trailer `cherry picked from commit 62baa71572de76d4d40ed1984df4ce9bc0270d7f` on a4269368c; note `v17-port-binding-plugin.md` |
| 54 | 523b64788 | d5bd4eb95 | fix(cursor-native): never delete the project mcp.json when clearing a dead entry | ported | bab692622 | `-x` trailer `cherry picked from commit 523b6478871f50c2643bc2584b791dc1da9277bb` on bab692622; note `v17-port-binding-plugin.md` |
| 55 | a11446be3 | 93cbb7314 | fix(cursor-native): refuse plugin-route launches cursor-agent would run without the plugin | ported | 10ce2b158 | `-x` trailer `cherry picked from commit a11446be3d221b8fbd89c5cc83ffa03822a615ab` on 10ce2b158; note `v17-port-binding-plugin.md` |
| 56 | dfd54048c | b5d69a50c | fix(cursor-native): a plugin-route turn no longer fires a live sibling's project usage hook | ported | 1ee4c7d22 | `-x` trailer `cherry picked from commit dfd54048c9dbcc78d3e82112508ada0d86859977` on 1ee4c7d22; note `v17-port-binding-plugin.md` |
| 57 | 5f71a8390 | 3dd01eab0 | fix(cursor-native): owner-only bridge dir recreation; grace for mid-launch siblings | adapted | 4596497c7 | `-x` trailer `cherry picked from commit 5f71a8390e928c2cac5a2280d68aadda14bbffb7` on 4596497c7; note `v17-port-binding-plugin.md` |
| 58 | d70bafafc | b9f3291bf | test(cursor-native): fix the pyrefly errors in the plugin-dir unit tests | ported | af4c6a098 | `-x` trailer `cherry picked from commit d70bafafc7d63a81e57759099fbb915d54b1e3bb` on af4c6a098; note `v17-port-binding-plugin.md` |
| 59 | fa967d38b | 1c1dcd7e2 | test(cursor-native): gate the plugin-dir real-CLI e2e; cover the sibling-hook skip | ported | cec186bc5 | `-x` trailer `cherry picked from commit fa967d38bbf35469f7a9b7ec791fe9dbde0c9b85` on cec186bc5; note `v17-port-binding-plugin.md` |
| 60 | 53901f3ec | ec2e5f2fc | fix(cursor-native): cursor_project_key matches the CLI's directory mangling (r17 N16) | ported | 69b9e324d | `-x` trailer `cherry picked from commit 53901f3ec38c7a6428e63886ce6f2982387c0826` on 69b9e324d; note `v17-port-binding-plugin.md` |
| 61 | 3add21910 | e74900a77 | fix(cursor-native): bridge MCP refuses a parent bound to another bridge (r17 N11) | ported | 7c66bd251 | `-x` trailer `cherry picked from commit 3add219101bc4760df2458310697d0a0499154a1` on 7c66bd251; note `v17-port-binding-plugin.md` |
| 62 | 0a2b9b236 | 318264335 | fix(cursor-native): receipt gate scans passthrough and installed plugin stop hooks (r17 N12) | ported | 66471010f | `-x` trailer `cherry picked from commit 0a2b9b236a4309656865fa59784c44b477b5c36c` on 66471010f; note `v17-port-binding-plugin.md` |
| 63 | 855d54cbd | — (v16-authored) | slice(port-cursor-plugin-dir): disposition notes for the plugin-dir/r17 port | ported | e64f72d1b | `-x` trailer `cherry picked from commit 855d54cbd3442e9933bc2b3432bdb0838e16bc31` on e64f72d1b; note `v17-port-binding-plugin.md` |
| 64 | cef9794cf | — (v16-authored) | slice(v16-report): v0.16.0 re-port report and after-port evidence | ported | 0cd5d45b4 | `-x` trailer `cherry picked from commit cef9794cf745e9b18310a3b83649a15d8ce5a661` on 0cd5d45b4; note `v17-port-binding-plugin.md` |
| 65 | a55e74db9 | — | loop: iteration 1 — SHIP | not ported | — | loop-only mailbox commit (`loop/` files); not product code (GOAL) |
| 66 | 3dd44be0f | — | loop: land loop (iteration 1) | not ported | — | loop-only mailbox commit (`loop/` files); not product code (GOAL) |

### 1.1 Trailer / ancestry check

Every ported/adapted row's new sha contains `(cherry picked from commit <full v16 sha>)`; the
mapping above was generated from the trailers, not typed. Re-check:

```sh
for v in $(git log --reverse --format=%H v0.16.0..v16/trio-v0.16.0-fixes); do
  n=$(git log --format=%B b52507b70..HEAD | grep -c "cherry picked from commit $v")
  echo "$v $n"; done | awk '{c[$2]++} END{for(k in c) print "commits with "k" pick(s): "c[k]}'
# expect: 55 with 1 pick, 11 with 0 (3 dropped + 5 merges + 3 loop-only)
# fork trailer is on the fork branch:
git merge-base --is-ancestor <fork sha> fork/release/omnigent-2a84483a && echo ok
```

The Targeted check of this slice does the same for every `cherry picked from commit <v16 sha>` on the
branch (`git merge-base --is-ancestor <sha> v16/trio-v0.16.0-fixes` and `v0.16.0 <sha>`) and greps the
report for the 9-char sha.

### 1.2 Commits on this branch with no v16 counterpart

| new sha | subject | kind |
|---|---|---|
| 4f1fc58f8 | slice(v17-baseline): add v17 focused-suite runner | evidence (`scripts/`) |
| b1c8373de | slice(v17-baseline): focused-suite runner and pristine v0.17.0 baseline | evidence (`docs/v17-evidence/baseline-v0.17.0.txt`) |
| 2f74c179a | slice(v17-port-close): ruff-format fork hunks in runner/app.py and tool_dispatch.py | adaptation (format only) |
| cdff1f729 | slice(v17-port-receipts): adapt receipt tests to v0.17.0 APIs | adaptation (tests) |
| 68355aa71 | slice(v17-port-receipts): post receipt kwarg only when a receipt exists | adaptation (forwarder call shape) |
| 604ab387b | slice(v17-port-isolation-compact): move manual-compact tests to tests/harnesses/codex_native | adaptation (test layout, `git mv`) |
| 9d7976a0d | slice(v17-port-stop): README for v0.17.0 | adaptation (README) |
| 88344b862, 5ce00dcde, f5f90ca43, 06aa68a25, 48757757d | slice(v17-port-*): disposition notes | evidence (`docs/v17-evidence/dispositions/`) |
| 31236382c | slice(v17-patch): child-reasoning-effort patch for v0.17.0 | patch (`patches/child-reasoning-effort.v0.17.0.patch`) |
| bf6c3a8d2 | slice(v17-afterport): after-port suite and upstream-overlap check | evidence (`after-port.txt`, `overlap-check.txt`) |
| bc433e1b2, ecd6d0f3f, 79fcc12e6, d5f485f7f, a13bf28a6, 5ad14e711, bec4ae12d, 903c3aeab | merge(worker): … | worker merge commits |

### 1.3 Dropped commits — evidence

- `de03a352c` (queue-aware yolo auto-accept) and `d69671640` (phantom cards for stale yolo markers):
  upstream #8516 (`a16334f78`, "preserve sub-agent outcomes after interrupts") rewrote the same
  yolo accept path and already delivers both behaviours. Covered on this branch by
  `tests/test_cursor_native_permissions.py::test_supervise_transcript_yolo_waits_through_stale_pending_burst`
  (parametrised `prompt`/`transcript`/`backoff`) and `::test_supervise_transcript_yolo_never_types_when_no_prompt_on_screen`
  — both in the `cursor-native` group, which has 0 failures (§3). Note: `docs/v17-evidence/dispositions/v17-port-close.md`.
- `39e45d8d4` (re-export `_resolve_agent_spec` from the sessions package): `_resolve_agent_spec`
  does not exist in `server/routes/_sessions/helpers.py` on v0.17.0 (`git grep -n "_resolve_agent_spec"
  v0.17.0 -- omnigent/server/routes/_sessions` has no definition; the function is `_resolve_subagent_spec`),
  so the re-export would be an `ImportError`. The net result is the alias added by `d4f6816bf` →
  `669e05bfd`: `omnigent/server/routes/sessions/__init__.py:785 _resolve_agent_spec = _resolve_subagent_spec`.
  See §6 (alias status).

## 2. Upstream v0.17.0 overlaps kept (GOAL DoD 2)

Check: for every upstream PR below, every line it added that is still present at `v0.17.0` must still
be present at the branch tip. Evidence: `docs/v17-evidence/overlap-check.txt` (tip
`5ad14e711`, i.e. all port slices merged; v0.17.0 = `12b5f67d2`).

| upstream PR | commit | lines checked | absent at tip | moved |
|---|---|---|---|---|
| #9048 claude_native child transcripts through transient outages | 021d19951 | 221 | 0 | 0 |
| #9008 claude_native turn-failure evidence | 06a055ac1 | 970 | 0 | 0 |
| #9005 claude_native shutdown lifecycle evidence | f651b5d6a | 1207 | 0 | 0 |
| #8672 in-process subagent StopFailure ignored | 8bb13323f | 16 | 0 | 0 |
| #8572 hook TMPDIR differs keeps conversations | 61d96f74b | 22 | 0 | 0 |
| #8745 codex cold-resume MCP refresh | 56272dfd7 | 83 | 0 | 0 |
| #8761 Harnesses settings page | ee3ca7cca | 713 | 0 | 0 |
| #8516 cursor sub-agent outcomes after interrupts | a16334f78 | 587 | 6 | 1 |
| #8523 `native_input_ready` provider probe | 7cbad8613 | 406 | 0 | 0 |
| #9025 propagate intentional runner stops to subagents | 106e2260b | 1380 | 0 | 0 |
| #9020 recover session sends when an offline host reconnects | 6f9f8f838 | 503 | 0 | 0 |
| #8297 child terminal edge replaces launch reaper guess | 5f0781228 | 329 | 0 | 0 |

Only #8516 has lines not verbatim at the tip, all in `omnigent/harnesses/cursor_native/forwarder.py`
(the fork's receipt layer re-shaped the same call, semantics kept; checked with
`git diff v0.17.0 HEAD -- omnigent/harnesses/cursor_native/forwarder.py`):

- **6 absent lines** — the `_post_external_session_status(client, *, session_id, status, turn_outcome: str)`
  signature is now `turn_outcome: str | None = None, turn_end=None` and builds `data = {"status": …}` then
  adds `turn_outcome` only when not `None`; the `data: {"status": status, "turn_outcome": turn_outcome}` literal
  moved into that variable. The inline `if not retrying_items and pending_turn_end is not None:` became
  `idle_due = not retrying_items and pending_turn_end is not None` (forwarder.py:1900), and the reflowed
  `read_turn_outcome` / `write_posted_count` executor calls and `status="failed" if outcome == "failed" else "idle"`
  (now `post_status = "failed" if outcome == "failed" else "idle"`, forwarder.py:1944) still run, post
  `turn_outcome=outcome` (forwarder.py:1950/1957) and write the posted count (forwarder.py:1962) for every stop marker.
- **1 moved line** — `"type": "external_session_status",` is now inside `json={"type": "external_session_status", "data": data}`;
  the same line exists in `omnigent/harnesses/claude_native/forwarder.py`, which is what the checker
  reported as the move target.

Behavioural cover: the upstream status tests (`tests/test_cursor_native_status.py`) pass with the
forwarder passing `turn_end=` only when a receipt exists (`68355aa71`), cursor-native group 556 passed (§3).

## 3. Baseline (pristine v0.17.0) vs after-port (GOAL DoD 3)

Evidence: `docs/v17-evidence/baseline-v0.17.0.txt` (rev `12b5f67d2`, tag `v0.17.0`) and
`docs/v17-evidence/after-port.txt` (rev `5ad14e711`, all port slices merged), both produced by the
11-group focused-suite runner (one pytest process each; the v17 runner was added in `4f1fc58f8`).
Both runs used `TMPDIR=/var/tmp/pytest-of-coder` (header line `tmpdir:` of each file) because of the
108-byte AF_UNIX limit. The after-port run covers more files than the baseline in `cursor-native` and
`sessions-routes` (fork-added test files that do not exist on pristine v0.17.0; the baseline records
`ABSENT tests/server/integration/test_input_fence.py`).

| group | pristine v0.17.0 | after port | baseline FAILED | after-port FAILED |
|---|---|---|---|---|
| dispatch | 280 passed, 1 skipped in 32.88s | 284 passed, 1 skipped in 46.02s | 0 | 0 |
| interrupt | 21 passed in 0.94s | 24 passed in 1.21s | 0 | 0 |
| runner-native | 16 failed, 495 passed in 594.75s (0:09:54) | 7 failed, 583 passed in 617.19s (0:10:17) | 16 | 7 |
| sys-session | 44 passed in 49.50s | 45 passed in 50.30s | 0 | 0 |
| terminals | 98 passed, 2 skipped in 31.77s | 109 passed, 2 skipped in 32.92s | 0 | 0 |
| claude-native | 2 failed, 1546 passed, 6 warnings in 184.42s (0:03:04) | 1 failed, 1548 passed, 6 warnings in 187.70s (0:03:07) | 2 | 1 |
| codex-native | 1454 passed, 2 warnings in 44.16s | 1484 passed, 2 warnings in 50.56s | 0 | 0 |
| cursor-native | 266 passed in 12.64s | 556 passed in 28.14s | 0 | 0 |
| inner-proc | 39 passed, 8 skipped in 0.39s | 40 passed, 8 skipped in 0.42s | 0 | 0 |
| host | 6 failed, 256 passed, 73 warnings in 38.53s | 6 failed, 257 passed, 74 warnings in 31.03s | 6 | 6 |
| sessions-routes | 19 passed in 10.14s | 64 passed in 190.37s (0:03:10) | 0 | 0 |

**New failures (in after-port, not in baseline): 0** (`after-port.txt` comparison block; no flakiness reruns needed).

**Fixed by the port (failing on pristine v0.17.0, passing after): 10 ids**
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_codex_native_settings_change_uses_thread_settings_update[effort_change|model_change|plan_mode_change]` (pristine: `codex-native model_change must return 204; got 503 codex_native_settings_update_failed`),
  `::test_events_interrupt_on_codex_native_uses_turn_interrupt_without_marker`,
  `::test_events_interrupt_on_codex_native_with_turn_and_mcp_stops_both`,
  `::test_events_stop_on_codex_native_cancels_mcp_startup_without_active_turn[interrupt|stop_session]`,
  `::test_events_stop_session_on_codex_native_uses_turn_interrupt_without_marker` — the lifecycle file is changed by the
  ported stop-routing / codex-advertise-guard commits (`30764d7e9`, `54f5172bf`; the last test no longer exists under that
  name, it is renamed `…_hard_stops_without_marker`). v16 §3 attributed the same ids to the fork's terminal-registry stub
  hunks; that attribution was not re-bisected here.
- `tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_returns_503_when_no_terminal` —
  the tmux-keys compact test is replaced by the app-server RPC tests of `f1676480c`
  (`…_503_without_bridge`, `…_sends_thread_compact_start`, …).
- `tests/harnesses/claude_native/test_claude_native_status_file.py::test_poller_publishes_edges_only` — the file is unchanged by the port
  (`git diff v0.17.0 HEAD -- tests/harnesses/claude_native/test_claude_native_status_file.py` is empty); this is the
  timing-sensitive poller test, so it is a flake on pristine, not a port fix.

**Pre-existing upstream failures (same 14 node ids fail on pristine v0.17.0 and after the port; NOT regressions):**
- `tests/harnesses/claude_native/test_claude_native_status_file.py::test_unknown_status_clears_dedup_so_next_read_publishes` (timing-sensitive)
- `tests/host/test_connect.py::test_handle_model_options_claude_sdk_rides_the_probe_when_endpoints_list_nothing`
- `tests/host/test_connect.py::test_handle_model_options_serves_claude_sdk_endpoint_listing`
- `tests/host/test_connect.py::test_handle_model_options_serves_codex_probe_rows_and_caches`
- `tests/host/test_connect.py::test_handle_model_options_serves_the_claude_catalog`
- `tests/host/test_connect.py::test_model_options_frame_replies_off_the_receive_loop`
- `tests/host/test_connect.py::test_run_host_process_announces_session_log_dir_on_start`
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_claude_native_model_options_serves_probe_rows_after_pending`
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_claude_native_model_options_use_session_launch_catalog[False]`
- `tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_interrupt_codex_side_chat_leaves_parent_turn_running[idle|missing_turn|newer_turn|rpc_failure|running]` (5 ids)

The per-slice runs additionally proved these same ids on a detached pristine v0.17.0 worktree
(`v17-port-close.md`: `15 failed, 50 passed`; `v17-port-stop.md`: `7 failed, 7 passed, 51 deselected`;
`v17-port-binding-plugin.md`: `tests/host/test_connect.py` `6 failed, 256 passed`).

## 4. Behaviour checks → tests (GOAL DoD 4)

"Result" is from `docs/v17-evidence/after-port.txt` (only failing ids are listed there; every id below
is outside the 14 pre-existing failures, so it passed in its group). Node ids were found by grep in
this tree (`grep -nE "def test_" <file>`); none of these ids is in the FAILED lists.

| behaviour | covering tests (node ids) | group → result in after-port.txt |
|---|---|---|
| **Cursor receipt gate** — `completion_receipts` labels, prompt binding, skipped rows | `tests/test_cursor_native_completion_receipt.py::test_receipt_binds_prompt_hash_and_counts`, `::test_turn_end_is_stamped_with_the_store_position`, `::test_matching_stops_bind_a_clean_turn_and_queued_turns`, `::test_skip_is_persisted_before_the_cursor_passes_it`; `tests/server/integration/test_input_fence.py::test_reserved_labels_cannot_be_forged`, `::test_receipt_binding_is_stored_in_its_own_label`, `::test_receipt_persisted_for_owner_and_monotonic`; `tests/server/integration/test_cursor_receipt_binding_e2e.py::test_queued_repost_verifies_only_after_both_copies_end`, `::test_single_late_turn_verifies_once_it_ends`, `::test_restart_mid_pass_keeps_the_lost_row_unacked` | cursor-native 556 passed; sessions-routes 64 passed |
| **Plugin-dir route** (`OMNIGENT_CURSOR_PLUGIN_DIR`) incl. plugin-route refusal and sibling-hook skip | `tests/test_cursor_native_plugin_dir.py::test_missing_plugin_hooks_hold`, `::test_live_sibling_project_hook_holds`, `::test_foreign_bridge_in_plugin_holds`, `::test_plugins_off_flags_refuse`, `::test_own_plugin_hook_is_foreign_in_another_launch`, `::test_keeps_live_sibling_and_foreign_omnigent`; host env passthrough: `tests/host/test_connect.py` (62baa7157; group host: the 6 failing ids are the unrelated model-options/log-dir tests) | cursor-native 556 passed; host 257 passed / same 6 pre-existing failures |
| **Foreign stop-hook refusal** (`e0849ba33`) | `tests/server/integration/test_cursor_receipt_binding_e2e.py::test_foreign_project_followup_hook_holds`, `::test_foreign_user_followup_hook_holds`, `::test_owned_shaped_user_hook_holds`, `::test_shared_user_hook_from_another_session_cannot_close_a_running_turn`, `::test_malformed_project_hooks_config_holds`; `tests/test_cursor_native_bridge.py::test_shared_user_hook_holds_at_launch_and_is_left_alone`, `::test_legacy_usage_module_hook_in_user_file_holds`; `tests/test_cursor_native_completion_receipt.py::test_unattributed_or_foreign_stop_gets_no_local_position`, `::test_shared_hook_stop_cannot_close_a_still_running_turn` | sessions-routes 64 passed; cursor-native 556 passed |
| **Passthrough + installed plugin stop-hook scan (r17 N12, `0a2b9b236`)** | `tests/test_cursor_native_plugin_dir.py::test_passthrough_plugin_stop_hook_holds`, `::test_passthrough_plugin_holds_on_the_project_route`, `::test_claude_format_plugin_stop_hook_holds`, `::test_manifest_inline_and_path_hooks_hold`, `::test_plugin_without_stop_hooks_is_fine` | cursor-native 556 passed |
| **Cursor isolation** — no session MCP / stop hook in user files | `tests/test_cursor_native_bridge.py::test_user_mcp_has_omnigent_server`, `::test_project_file_aliasing_the_user_file_is_never_written`, `::test_write_hooks_config_skips_home_workspace`, `::test_write_hooks_config_skips_account_home`, `::test_arm_refused_drops_stale_epoch_and_keeps_user_hooks`, `::test_write_hooks_config_preserves_existing_hooks` | cursor-native 556 passed |
| **Refuse user `~/.cursor` / home workspace** | `tests/test_cursor_native_bridge.py::test_home_workspace_is_never_written`, `::test_account_home_is_never_written`, `::test_home_workspace_is_refused`, `::test_account_home_is_refused_even_when_home_env_differs`, `::test_workspace_that_is_home_refuses_receipts`; `tests/server/integration/test_cursor_receipt_binding_e2e.py::test_workspace_that_is_home_holds` | cursor-native 556 passed; sessions-routes 64 passed |
| **Refuse repository subfolder** | `tests/test_cursor_native_bridge.py::test_repo_subfolder_is_refused`, `::test_alias_to_a_repo_subfolder_is_refused`, `::test_folder_inside_home_repo_is_refused`, `::test_own_repo_inside_home_repo_is_admitted` | cursor-native 556 passed |
| **Cursor chat binding / cold-start input** (no Backspace into empty composer, stable readiness) | `tests/server/integration/test_cursor_cold_start_prompt.py::test_cold_start_first_prompt_waits_for_ready_and_lands_once`, `::test_nonempty_composer_is_still_cleared`, `::test_readiness_timeout_fails_before_typing_and_does_not_retry`; `tests/test_cursor_native_completion_receipt.py::test_late_foreign_marker_unbalances_instead_of_binding` | sessions-routes 64 passed |
| **Input fence** | `tests/server/integration/test_input_fence.py::test_verified_fence_rejects_every_input_api_and_persists`, `::test_new_input_racing_a_close_is_refused`, `::test_open_is_runner_first_and_fails_closed`, `::test_injection_after_receipt_fails_verification`, `::test_crash_mid_close_reconciles_on_retry`; `tests/test_cursor_native_completion_receipt.py::test_fenced_pane_refuses_injection_before_touching_tmux`, `::test_fence_close_linearizes_against_concurrent_injections` | sessions-routes 64 passed; cursor-native 556 passed |
| **Stop-routing** (hard stop Claude/Codex/Cursor), kill-on-close, close-guard | `tests/runner/test_app_sessions_native_events_lifecycle.py::test_events_stop_session_on_codex_native_hard_stops_without_marker`, `::test_events_stop_session_on_native_kills_tmux_and_publishes_idle`, `::test_events_stop_session_on_native_returns_503_when_kill_fails`; `tests/runner/test_native_interrupt_runner.py::test_uniform_stop_kills_tears_down_and_goes_idle`, `::test_uniform_stop_kill_failure_returns_503_without_idle`; `tests/tools/builtins/test_sys_session.py::test_close_accepts_child_with_unparsable_title`, `::test_close_marks_closed_and_tombstones_internal_title` | runner-native: lifecycle ids not in the 7 failures; interrupt 24 passed; sys-session 45 passed |
| **Kill escalation** (`omnigent/native_tmux_kill.py`) and pane reaper | `tests/test_cursor_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill`; `tests/harnesses/codex_native/test_codex_native_bridge.py::test_kill_session_escalates_live_pane_after_tmux_kill`; `tests/inner/test_proc_and_platform.py`; `tests/terminals/test_pane_reaper.py` (incl. upstream #8297/#8320 `test_runner_busy_check_counts_a_viewer_only_on_recent_input` in the runner-native/dispatch groups) | cursor-native 556 passed; codex-native 1484 passed; inner-proc 40 passed, 8 skipped; terminals 109 passed, 2 skipped |
| **Codex manual compact via app-server** `thread/compact/start`, guard until outcome | `tests/harnesses/codex_native/test_codex_native_manual_compact.py::test_sends_thread_compact_start_and_reports_accepted_not_completed`, `::test_completion_event_resolves_completed`, `::test_missing_completion_times_out_uncertain_without_resend`, `::test_active_turn_is_busy_and_sends_nothing`, `::test_forwarder_live_stream_settles_manual_compact_and_still_mirrors`; `tests/runner/test_app_sessions_native_events_options.py::test_events_compact_on_codex_native_sends_thread_compact_start`, `::test_events_compact_on_codex_native_409_while_turn_active`, `::test_codex_native_compact_failure_clears_spinner_without_completion`; `tests/server/integration/test_sessions_compact.py` | codex-native 1484 passed; runner-native options ids not in the 7 failures; sessions-routes 64 passed |
| **claude_native hook bridge** — Unix-socket MCP ingress and hook TMPDIR (upstream #8079/#8572 kept; fork `3add21910` N11 added beside it) | `tests/harnesses/claude_native/test_claude_native_bridge.py::test_http_ingress_defaults_to_unix_socket`, `::test_http_ingress_advertises_absolute_socket_path`, `::test_http_ingress_refuses_symlinked_socket_root`, `::test_http_ingress_reaps_sockets_of_dead_owners`, `::test_generated_claude_subprocesses_pin_runner_tmpdir`, `::test_augment_claude_args_injects_mcp_and_hooks`; `tests/harnesses/claude_native/test_claude_native_hook.py` | claude-native 1548 passed, 1 failed (`test_unknown_status_clears_dedup_so_next_read_publishes`, pre-existing, unrelated to the bridge) |

Gated, not run here (see §7): `tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py` collects (11 e2e tests collect per `v17-port-binding-plugin.md`) but needs `OMNIGENT_E2E_CURSOR_NATIVE=1` + `cursor-agent login`.

## 5. Refreshed trio patch `patches/child-reasoning-effort.v0.17.0.patch` (GOAL DoD 5)

Evidence: `docs/v17-evidence/patch-check.txt` (rev `5ad14e711`):

- `git apply --check` on a pristine `v0.17.0` index (`GIT_INDEX_FILE=$I git read-tree v0.17.0 && git apply --check --cached …`) → `exit=0`.
- `git apply --check` on the port tip → `exit=0`.
- The old `child-reasoning-effort.v0.16.0.patch` fails on both (`omnigent/server/routes/_sessions/helpers.py` and `omnigent/server/routes/sessions/__init__.py` hunks: upstream dropped `_reset_runner_resources_after_switch(_impl)` from the `__all__`/import-list context) → `exit=1`; the new patch re-anchors those hunks.
- Patched tree: `tests/tools/builtins/test_child_reasoning_effort.py tests/tools/builtins/test_sys_session.py tests/runtime/test_reasoning_effort_validation.py` → `60 passed in 61.80s`, then the patch is reversed (`git apply -R`) so it is not left applied.
- Note recorded in the evidence: on the tip, `sessions/__init__.py` also carries the fork alias `_resolve_agent_spec = _resolve_subagent_spec` after the import, which shadows the patch's import there (harmless; tests pass).

Re-check:

```sh
I=$(mktemp -u /var/tmp/pytest-of-coder/idx.XXXXXX); GIT_INDEX_FILE=$I git read-tree v0.17.0 && GIT_INDEX_FILE=$I git apply --check --cached patches/child-reasoning-effort.v0.17.0.patch; echo $?; rm -f $I
git apply --check patches/child-reasoning-effort.v0.17.0.patch; echo $?
```

The patch is **not** installed into `~/.local/share/trio-agent-loop/` (out of scope, forbidden by GOAL); when the trio release is next updated, ship it as that release's `omnigent/patches/child-reasoning-effort.patch`.

## 6. New risks / breaking changes in v0.17.0

Upstream delta: `git log --oneline v0.16.0..v0.17.0 | wc -l` = 254 commits; `git diff --stat v0.16.0 v0.17.0 | tail -1`
gives the full size. Start list: `git log --oneline v0.16.0..v0.17.0 | grep -iE 'break|!:|remove|retire|rename'`.

### 6.1 Database migrations

Since **v0.16.0** (`git diff --name-only --diff-filter=A v0.16.0 v0.17.0 -- omnigent/db/migrations/versions`): **1 new revision**.

| revision id | file | revises | what it does |
|---|---|---|---|
| `mm1a2b3c4d5e` | `mm1a2b3c4d5e_index_agents_by_owner_created.py` (#8777 `e7919ec7d`) | `ll1a2b3c4d5e` | creates `ix_agents_kind_owner_created` on `agents(workspace_id, kind, created_by, created_at, id)` for keyset-paged "my agents" listing (`designs/REUSABLE_USER_AGENTS.md`). PostgreSQL: `CREATE INDEX CONCURRENTLY` inside an autocommit block and drops an INVALID leftover index first; other dialects (SQLite): plain `op.create_index`. `downgrade()` = `op.drop_index`. No data change. `db_models.py` mirrors it (`Index("ix_agents_kind_owner_created", …)`). |

Since the **fork tip `318264335`** (`git diff --name-only --diff-filter=A 318264335 v0.17.0 -- omnigent/db/migrations/versions`;
`git merge-base 318264335 v0.17.0` = `b04e266e3`, i.e. the fork tip predates v0.16.0): **10 new revisions**, one linear chain
`gg1b2c3d4e5f` (already on the fork) → `gh1b…` → `hh2c…` → `hh1b…` → `ar1b…` → `hi1b…` → `ii1a…` → `jj1a…` → `kk1a…` → `ll1a…` → `mm1a…`:

| revision id | revises | what it does (read from the file) |
|---|---|---|
| `gh1b2c3d4e5f` | `gg1b2c3d4e5f` | adds nullable personal project-order column to `users` (MEDIUMBLOB on MySQL). |
| `hh2c3d4e5f6a` | `gh1b2c3d4e5f` | adds nullable JSON-text `files.source_metadata` (pre-downscale pixel size for the image resize notice). |
| `hh1b2c3d4e5f` | `hh2c3d4e5f6a` | adds nullable `files.blob_key` (artifact-store key; forked file rows share the source blob, no bytes copied). |
| `ar1b2c3d4e5f` | `hh1b2c3d4e5f` | account revocation: adds nullable `account_generation` (String 32) to `users`, `account_tokens`, `device_grants`, `scheduled_tasks`, `hosts` and nullable `users.deleted_at`; backfills a uuid generation for password accounts. |
| `hi1b2c3d4e5f` | `ar1b2c3d4e5f` | adds `inference_snapshot` (saved inference config) to `omnigent_conversation_metadata`; NULL for existing conversations. |
| `ii1a2b3c4d5e` | `hi1b2c3d4e5f` | adds nullable `agents.created_by` (String 128) so agent-code mutations are restricted to the creating user. |
| `jj1a2b3c4d5e` | `ii1a2b3c4d5e` | creates the `preferences` table and **moves** personal project ordering from `users` into it (data migration). |
| `kk1a2b3c4d5e` | `jj1a2b3c4d5e` | limits stored preference values to 65,535 bytes: **deletes** oversized preference rows (reads fall back to defaults); MySQL column narrowing. Downgrade cannot restore discarded rows. Docstring: stop old app instances before upgrading. |
| `ll1a2b3c4d5e` | `kk1a2b3c4d5e` | stores `inference_snapshot` as compressed BLOB/BYTEA: JSON is compressed, snapshots still over 65,535 bytes become **NULL** (saved inference profile lost). Online-only (raises on offline SQL). Docstring: run with readers/writers stopped. Present in v0.16.0 (the live install, on `trio-v0.16.0-fixes`, is already at this head unless its DB predates v0.16.0). |
| `mm1a2b3c4d5e` | `ll1a2b3c4d5e` | see above (the only revision new in v0.17.0). |

The fork added no migration of its own (`git diff --name-only v0.16.0 v16/trio-v0.16.0-fixes -- omnigent/db` and
`git diff --name-only --diff-filter=A v0.17.0 HEAD -- omnigent/db` are empty), so the live DB head after the upgrade is `mm1a2b3c4d5e`.

Consequences:
- The server runs migrations on start: `omnigent/db/utils.py::_initialize_or_verify_schema` — "Behind head" → warns "Omnigent database schema is out of date … attempting automatic migration" and calls `_run_migrations` (alembic `upgrade head`). A manual path exists: `omnigent debug db-upgrade sqlite:////abs/path/chat.db` (`omnigent/cli.py::debug_db_upgrade`, which warns "always take a backup").
- **Downgrade is not safe**: `_verify_db_revision_is_supported` raises `RuntimeError("Omnigent database schema is newer than this version of Omnigent … Upgrade Omnigent before using this database.")` when v0.16.0 (or older) code meets a DB stamped `mm1a2b3c4d5e`; there is no downgrade CLI (`grep -rn "command.downgrade" omnigent` finds none outside the migration files), and `kk`/`ll` data changes are destructive. Rollback must restore a pre-upgrade copy of the DB (§8).
- If the live DB is still at a pre-v0.16.0 head, the first start applies all 10 revisions in one go, including the destructive `kk`/`ll` steps.

### 6.2 Config / preference / API changes the fork or trio driver could hit

- **Switch-agent API retired (#8795, `1c0190294`, `feat(sessions)!:`)**: `POST /v1/sessions/{id}/switch-agent` is still registered (hidden from the schema) but **always returns 410** with fork guidance; the conversation-store method, request schema, switch-back label, runner-reset helper `_reset_runner_resources_after_switch(_impl)`, the web dialog and API client were removed. Anything that calls it (scripts, trio flows that switch an agent in place) must fork into another agent instead. The `session.agent_changed` event stays (MCP-server edits still publish it).
- **`_resolve_agent_spec` alias status**: v0.17.0 has no `_resolve_agent_spec` in `server/routes/_sessions/helpers.py` (the function is `_resolve_subagent_spec`; `git grep -n _resolve_agent_spec_from_server v0.17.0` is an unrelated runner helper). The fork keeps `_resolve_agent_spec = _resolve_subagent_spec` at `omnigent/server/routes/sessions/__init__.py:785` (`669e05bfd`) because `trioctl omnigent doctor` imports the old name (README of this branch). Follow-up: change doctor to import `_resolve_subagent_spec` and drop the alias. The ported `d4f6816bf` kept upstream's removal of the `_reset_runner_resources_after_switch_impl` re-export in the helpers import block.
- **Harnesses settings page (#8761 `ee3ca7cca`, plus #9013/#9017/#9019/#9021)** replaces the Customize settings section (`SettingsCustomizeSection.tsx` deleted, `SettingsHarnessesSection.tsx` / `HarnessCatalog.tsx` added). The feature flag was renamed: `Feature.CUSTOMIZE = "customize"` → `Feature.HARNESS_SETTINGS_UI = "harness_settings_ui"` (`omnigent/server/feature_flags.py`). `resolve_feature_flags` **fails startup on unknown names**, so an `OMNIGENT_FEATURES` that still contains `customize` makes the server refuse to start on v0.17.0 — check the live environment/service unit before restarting.
- **Preferences**: no v0.17.0 change to the preferences table (those are the `jj`/`kk` migrations that already shipped in v0.16.0): the 65,535-byte cap and the oversized-row deletion (see table) apply the first time an older DB is migrated. `git diff --name-only v0.16.0 v0.17.0 | grep -i preferen` only hits `web/electron/*` (managed/dev preferences, `just electron-mdm` #8811) and `web/src/lib/archiveWorktreePreferences.*`.
- **Module layout**: `omnigent/runner/app.py` was split (#8856 `614fdda1c`, native control handlers → `omnigent/runner/native_controls.py` 1961 lines; further new modules `app_support.py`, `mcp_routes.py`, `model_option_routes.py`, `resource_routes.py`, `session_history.py`, `subagent_work.py`, … `git diff --stat --diff-filter=A v0.16.0 v0.17.0 -- omnigent/runner`). Fork hunks that touched `runner/app.py` were re-homed: input fence handler → `native_controls.py` (`NativeControls.handle_cursor_native_input_fence`), Codex manual compact (`_handle_codex_native_compact`, `_await_codex_native_compact_completion`) → `native_controls.py`; the busy-check lines remain in `app.py` and `_codex_native_bridge_state_for_session` still lives in `app.py` (`v17-port-close.md`). Anything outside this repo that monkeypatches or imports those names from `omnigent.runner.app` must be re-checked.
- **Test layout moved** (#8788/#8789/#8805: 49 renames, e.g. `tests/test_claude_native*.py` → `tests/harnesses/claude_native/`, `tests/test_codex_native*.py` → `tests/harnesses/codex_native/`, `tests/e2e_ui/timings.py` → `tests/helpers/ui_timings.py`). The fork's moved test `test_codex_native_manual_compact.py` now lives in `tests/harnesses/codex_native/` (`604ab387b`); `auth_client` moved to `tests/server/conftest.py` (#8628). Any external script that runs old paths (e.g. `tests/test_claude_native_bridge.py`) fails with "file not found".
- Other removal/retire commits from the grep that touch behaviour: `da6036a0f` clear active markers when harnesses retire (#9120), `8fb8c5678` server-retired tunnel recycle (#8252), `808fdaccf` removes the E2E UI Required CI gate (#8538), `b77990a1c`/`bdf7d1ebf` codex attach-flag rename gate and its revert (#8828/#8857; net no change).
- **Cursor receipts under #8516**: markers now start with a leading blank line and every stop posts a `turn_outcome`; the fork's receipt layer was layered on (see §2). External readers of the legacy marker must skip blank lines.
- `uv.lock`/`pyproject.toml` changed upstream only by the 0.16.0 → 0.17.0 version bumps (`git diff v0.16.0 v0.17.0 -- pyproject.toml`; `uv.lock` 5+/5-), so `uv sync --frozen` does not need a re-lock.

## 7. Not verifiable without a live server (GOAL forbids starting/stopping the server)

- Real `cursor-agent` turns: completion receipts end to end, plugin-dir route with the real CLI
  (`tests/e2e/test_cursor_native_plugin_dir_cli_e2e.py`, `tests/e2e/test_cursor_native_cli_e2e.py`: gated by `OMNIGENT_E2E_CURSOR_NATIVE=1` + `cursor-agent login`; collect only).
- Real Codex app-server `thread/compact/start` against a live `codex` (the tests use a fake app-server);
  `tests/e2e_ui/sessions/test_codex_native_compact_takes_effect.py` needs the UI stack.
- Live Claude Code hook bridge over the Unix-socket MCP with a real `claude` binary; real hook TMPDIR differences.
- Kill escalation and pane reaping against real tmux panes of a live runner under load; viewer-attached busy rule with a human attached.
- Host-spawned runner env propagation (`OMNIGENT_CURSOR_PLUGIN_DIR`) through a live host.
- The Harnesses settings page and every other web UI change (#8761 …): no UI/browser run; `OMNIGENT_FEATURES` handling of the live service unit.
- The real migration of the user's `chat.db` (10 revisions from the fork-tip era, 1 from v0.16.0): only the Alembic code was read, no copy of the live DB was migrated.
- The `child-reasoning-effort` patch driving real Trio loops on a live server (only `git apply --check` + 60 unit tests ran).
- The skipped tests of the focused groups (dispatch 1, terminals 2, inner-proc 8 in §3) and gated e2e tests.
- `trioctl omnigent doctor` importing `_resolve_agent_spec` (alias is present in the tree, the import was not exercised from the trio side).

## 8. Install and rollback for the live editable install (nothing here was run — human steps)

The live Omnigent is the editable install of `/home/coder/omnigent` (installed with
`uv tool install --editable /home/coder/omnigent`), currently on branch `trio-v0.16.0-fixes`
(v0.16.0 + fork patches; the trio patch may be applied on top as an uncommitted diff). **Documentation only: none of the commands below were run by this loop**, and `/home/coder/omnigent` was not read or modified.

### 8.1 Where the DB lives (cite)

`omnigent/host/local_server.py::_local_data_dir()` (line ~80): `$OMNIGENT_DATA_DIR` if set, else
`~/.omnigent`. The server's default DB is `sqlite:///<data_dir>/chat.db`
(`omnigent/cli.py::_default_db_uri`, line ~1283; `docs/DATA_DIR_LAYOUT.md`: `chat.db (+ -shm, -wal)`
"Main SQLite runtime DB"; artifacts in `<data_dir>/artifacts/`). `--database-uri` / the config file
override it (`omnigent/cli.py`, `--database-uri` option help). Confirm the effective value before
backing up: `echo "${OMNIGENT_DATA_DIR:-$HOME/.omnigent}"`, and check the service unit / `ps -o args= -p <server pid>` for `--database-uri`.

### 8.2 Pre-flight (human, before stopping anything)

```sh
D="${OMNIGENT_DATA_DIR:-$HOME/.omnigent}"; TS=$(date +%Y%m%dT%H%M%S)
B="$HOME/omnigent-backups/pre-v0.17.0-$TS"; mkdir -p "$B"      # or any backup location of your choice
# 1. HUMAN ACTION: stop the Omnigent server/host/runner the way you normally stop it (this loop never stops it).
# 2. with the server stopped, copy the DB consistently (all three files) and the rest of the data dir:
sqlite3 "$D/chat.db" ".backup '$B/chat.db'"                    # consistent copy incl. WAL content
cp -a "$D/config.yaml" "$B/" 2>/dev/null; cp -a "$D/artifacts" "$B/artifacts"   # artifacts are not touched by migrations; optional
sqlite3 "$B/chat.db" "select version_num from alembic_version"  # expect ll1a2b3c4d5e (v0.16.0 head)
# 3. record the current checkout state
cd /home/coder/omnigent
git rev-parse HEAD > "$B/checkout-HEAD.txt"; git branch --show-current > "$B/checkout-branch.txt"   # expect trio-v0.16.0-fixes
git status --short                                           # a diff here = the trio patch applied; save it:
git diff > "$B/working-tree.diff"
git tag -f pre-v17-rollback HEAD
uv tool list > "$B/uv-tool-list.txt"; cat ~/.local/share/uv/tools/omnigent/uv-receipt.toml > "$B/uv-receipt.toml" 2>/dev/null   # note any extras / --with used
env | grep -E '^OMNIGENT_' > "$B/omnigent-env.txt"           # check OMNIGENT_FEATURES for `customize` (§6.2)
```

### 8.3 Install

```sh
cd /home/coder/omnigent
# reverse the v0.16 trio patch if it is applied (otherwise the switch fails on a dirty tree)
git apply --reverse patches/child-reasoning-effort.v0.16.0.patch 2>/dev/null || true
git status --short                                           # must be clean
git fetch /home/coder/omnigent-v17 trio-v0.17.0-fixes:trio-v0.17.0-fixes
git switch trio-v0.17.0-fixes                                # v0.17.0 + fork patches
git apply --check patches/child-reasoning-effort.v0.17.0.patch && git apply patches/child-reasoning-effort.v0.17.0.patch
uv tool install --editable /home/coder/omnigent --force      # re-resolve the tool env for 0.17.0; add the same extras as in $B/uv-receipt.toml
# HUMAN ACTION: start the server the way it is normally started. On start it migrates ll1a2b3c4d5e -> mm1a2b3c4d5e
# automatically (db/utils.py `_initialize_or_verify_schema`); to do it explicitly while the server is still stopped:
#   omnigent debug db-upgrade "sqlite:///$D/chat.db"
```

Verify:

```sh
sqlite3 "$D/chat.db" "select version_num from alembic_version"          # mm1a2b3c4d5e
sqlite3 "$D/chat.db" ".indexes agents" | grep ix_agents_kind_owner_created
omnigent --version                                                       # 0.17.0
cd /home/coder/omnigent && git rev-parse --abbrev-ref HEAD && git log --oneline -1   # trio-v0.17.0-fixes
git apply --check -R patches/child-reasoning-effort.v0.17.0.patch && echo "trio patch applied"
~/.local/share/trio-agent-loop/current/omnigent/smoke-test.sh           # the trio smoke test, if installed
```

Ship `patches/child-reasoning-effort.v0.17.0.patch` into the trio release's `omnigent/patches/` when that release is next updated.

### 8.4 Rollback (restore the DB — the migrations are not downgrade-safe, §6.1)

```sh
# HUMAN ACTION: stop the server first.
D="${OMNIGENT_DATA_DIR:-$HOME/.omnigent}"; B="$HOME/omnigent-backups/pre-v0.17.0-<TS>"   # the backup made in 8.2
mv "$D/chat.db" "$D/chat.db.v0.17.failed"; rm -f "$D/chat.db-wal" "$D/chat.db-shm"
cp -a "$B/chat.db" "$D/chat.db"                                         # restore the pre-upgrade DB (alembic head ll1a2b3c4d5e)
cd /home/coder/omnigent
git apply --reverse patches/child-reasoning-effort.v0.17.0.patch 2>/dev/null || true
git switch trio-v0.16.0-fixes                                           # or: git switch --detach pre-v17-rollback
git apply patches/child-reasoning-effort.v0.16.0.patch                  # if it was applied before (see $B/working-tree.diff)
uv tool install --editable /home/coder/omnigent --force
# HUMAN ACTION: restart the server; verify:
sqlite3 "$D/chat.db" "select version_num from alembic_version"          # ll1a2b3c4d5e
omnigent --version                                                      # 0.16.0
```

Do **not** try to roll back by only switching the branch: v0.16.0 code refuses a DB stamped
`mm1a2b3c4d5e` ("schema is newer than this version of Omnigent"), and artifacts/DB rows written
after the upgrade exist only in the failed DB copy kept as `chat.db.v0.17.failed`.
