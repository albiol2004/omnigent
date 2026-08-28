# fork-compact-ui evidence

## Change

- Added an accessible `Summarizing history…` progress message while the fork
  request is submitting.
- Extended the fork dialog tests for deferred progress and the exact
  oversized-context error message.
- `sessionsApi.ts` was inspected and left unchanged because
  `readJsonOrThrow` already preserves the server error text.

The dialog does not currently receive source item-size or model metadata, so
the progress copy intentionally uses the permitted unknown-value fallback.
No source-session SSE subscription was added because this component does not
own one.

## Verification

### Vitest

Command:

```text
cd web && npx vitest run src/shell/ForkSessionDialog.test.tsx
```

Result: passed. 1 test file and 34 tests passed.

Output: `vitest-final.txt`

### Pre-commit

Command:

```text
pre-commit run --files web/src/shell/ForkSessionDialog.tsx \
  web/src/shell/ForkSessionDialog.test.tsx \
  web/src/lib/sessionsApi.ts
```

Result: could not start because `pre-commit` is not installed on `PATH`.

Output: `pre-commit.txt`

Repository fallback command:

```text
uv run pre-commit run --files web/src/shell/ForkSessionDialog.tsx \
  web/src/shell/ForkSessionDialog.test.tsx \
  web/src/lib/sessionsApi.ts
```

Result: exit 1 from the repository-wide `web-oxlint` hook. The rerun passed
Prettier and TypeScript; Oxlint still reports existing diagnostics across the
web tree, including the pre-existing `ForkSessionDialog.tsx` diagnostics at
lines 329 and 343. No diagnostic points at the new progress block.

Output: `pre-commit-uv.txt` and `pre-commit-uv-rerun.txt`
