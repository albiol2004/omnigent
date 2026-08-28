# Builder brief — async-fork-preparing-ui

You are a Luna builder. Workspace: `/home/alex/omnigent-fixes`.
`cd /home/alex/omnigent-fixes` for every command. Web tests:
`cd web && npx vitest run` for the files you touch. Pre-commit:
`PATH=/home/alex/omnigent/.venv/bin:$PATH`.

Commit: `slice(async-fork-preparing-ui): …` with trailer
`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
Never amend/rebase/push/stash/reset/checkout. Never git in
`/home/alex/omnigent`. Never touch `:6767`. Leave mailbox uncommitted.
Do not edit GOAL.md or VERDICT.md. Do not full-read huge TS stores.

## UX contract (user verbatim)

The fork dialog is a modal that cannot be closed while POST /fork
runs. It should create the session immediately and block **only that
session** until available — never freeze the whole app.

## Code (grep/sed)

- `web/src/shell/ForkSessionDialog.tsx` ~447-515 `handleFork` awaits
  `forkSession` then `onClose()`+navigate. `submitting` disables Cancel
  (~869) and shows "Summarizing history…" ~847-857.
- `web/src/lib/sessionsApi.ts:527-572` `forkSession()`.
- `web/src/shell/ForkDialogContext.tsx` opener.
- ChatPage composer `disabled` ~5035, 5474 (grep `disabled`).
- Compaction SSE types already exist server-side
  (`response.compaction.in_progress/completed/failed`). Wire the fork
  session to those if the client already handles compaction events.

Server labels (do not change server in this slice):
`omnigent.fork.preparing=1` | `failed`, plus `preparing_reason`.

## Required UI

1. Dialog CLOSES as soon as POST returns 201 (unmount
   `fork-session-dialog`). Navigate to `/c/{fork.id}` immediately.
   Cancel stays enabled until 201 (or keep it enabled even while the
   short POST is in flight if that is simpler).
2. The NEW session view shows a non-blocking in-session banner
   "Preparing fork — summarizing history…" while `preparing=1`.
   Composer disabled until the label clears (SSE or refetch).
3. On `preparing=failed`, show the reason in-session and a retry
   affordance (e.g. re-POST compact or a documented retry endpoint —
   if no server retry endpoint exists yet, a button that refetches
   and/or tells the user to retry clone is OK; prefer calling a
   server retry if slice-server added one).
4. No modal may cover the app while the fork prepares.
5. Existing tests: dialog closes on 201 (assert unmounted).

Do not implement the server compact loop here. If labels are missing
in local fixtures, stub them on the session object.

## Tests

`web/src/shell/ForkSessionDialog.test.tsx` and composer tests:

- After 201, `fork-session-dialog` is unmounted; `navigate` called.
- Preparing session: banner visible, composer `disabled`.
- Failure label: reason + retry control visible.
- App shell remains interactive (dialog gone) while a fake preparing
  session is open.

```
cd /home/alex/omnigent-fixes/web && npx vitest run \
  src/shell/ForkSessionDialog.test.tsx \
  src/pages/ChatPage.composer.test.tsx
PATH=/home/alex/omnigent/.venv/bin:$PATH pre-commit run --files <changed>
```

Keep ChatPage edits minimal. Prefer a small helper/component under
`web/src/shell/` for the preparing banner rather than growing ChatPage.
