# Builder brief — slice picker-ui-truth

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent-cursor3`. Mailbox `loop-cursor3/`. Iteration 1.

Do NOT read `ChatPage.tsx` or `chatStore.ts` whole-file. Use grep/sed on
the ranges below. Do NOT touch Python picker code, `~/.cursor`, live
server :6767, or `/home/alex/omnigent` git. Do NOT run cursor-agent.
Commit only after tests pass:

```
slice(picker-ui-truth): revert the picker when a model PATCH is rejected

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

No amend/rebase/push/stash/reset/checkout.
`PATH=/home/alex/omnigent/.venv/bin:$PATH` for pre-commit.

## Writes (only these; stay inside web/)

- `web/src/store/chatStore.ts`
- `web/src/store/chatStore.test.ts`
- `web/src/pages/ChatPage.tsx`
- `web/src/pages/ChatPage.composer.test.tsx`

If ChatPage needs no code change after store rollback + existing
`.catch(setCommandError)`, still add a composer test that proves the
error names the attempted model and the displayed model stays the prior
one. Do not expand into unrelated ChatPage sections.

## Line ranges

- `setModel` `web/src/store/chatStore.ts:2089-2115` — optimistic
  `selectedModel` + `sessionModelOverride`, `updateSession` with **no**
  try/catch. Contrast `setCostControlMode` :2068-2160 which rolls back.
- SSE `session_model` :5318-5333 (authoritative when it arrives; do not
  treat it as a substitute for PATCH failure handling).
- Composer `/model` `ChatPage.tsx:4911-4939` — already `.catch`s into
  `setCommandError`, but store state stays on the rejected id.
- Picker save path ~6274 (`store.setModel(draftModelId)`).

## Required behavior

When PATCH fails (e.g. 503 `cursor_native_model_failed`):

1. Revert `sessionModelOverride` and `selectedModel` (and sticky pref if
   this pick wrote it) to the values from before the optimistic write.
2. Re-throw so ChatPage can `setCommandError` with a message that **names
   the attempted model**.
3. Never keep displaying the rejected selection.
4. Success path unchanged (canonical `session.modelOverride` still wins).

## Tests (component/store path)

- `chatStore.test.ts`: seed a session whose override is `cursor-grok-4.6-medium`;
  `setModel('glm-5.2-high')`; PATCH 503; expect override and sticky pick
  restored; expect the thrown/surfaced error to include `glm-5.2-high`.
- `ChatPage.composer.test.tsx`: `/model glm-5.2-high` on a cursor-native
  session; mocked `setModel` rejection; composer error names the model;
  status/picker still shows the prior model.

Commands:
`cd /home/alex/omnigent-cursor3/web && npx vitest run src/store/chatStore.test.ts src/pages/ChatPage.composer.test.tsx`

Then pre-commit on the touched files and commit.
