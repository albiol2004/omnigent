# Builder brief — slice cli-view

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent`. Mailbox `loop-stability/`. Iteration 1.

Do NOT commit. Do NOT edit Python runner/server files.

PATH: `PATH=/home/alex/omnigent/.venv/bin:$PATH`

Scout: CLI view picks a user shell as the agent terminal.

## Writes (only)

- `web/src/hooks/useTerminals.ts`
- `web/src/hooks/useTerminals.test.ts`
- `web/src/shell/AppShell.tsx` (only terminal-selection bits
  ~1411-1489)
- `web/src/shell/MainTerminalView.tsx` (~66-210)
- matching `*.test.ts*` you already touch

Line ranges: `useTerminals.ts` 30-93, 110-145, 430-540;
`AppShell.tsx` 1411-1432, 1461-1489;
`MainTerminalView.tsx` 66-125, 150-210.

Known-good pattern in git `90f476be3`: `findAgentTerminal()`,
availability from agent pane not list length, never substitute a
user shell. Backport that idea; do not wholesale revert unrelated
files.

Test-first: shell-only list must not count as agent CLI ready;
pending agent pane keeps reconciling. Add tests in
`useTerminals.test.ts` / `MainTerminalView.test.tsx`.

```
cd /home/alex/omnigent/web && npm test -- --run \
  src/hooks/useTerminals.test.ts \
  src/shell/MainTerminalView.test.tsx
```

Capture `loop-stability/evidence/iter1/cli-view/pytest.txt` (or
vitest log) and NOTES.md. Lines < 88 chars.
