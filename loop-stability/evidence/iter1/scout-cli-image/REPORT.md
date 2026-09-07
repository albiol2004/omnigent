# Scout CLI + image — captured from Luna scout (gpt-5.6-luna-max)

## CLI view
Root: user shell mistaken for agent CLI.
`web/src/hooks/useTerminals.ts` 30-93, 110-145, 430-540
`web/src/shell/AppShell.tsx` 1411-1432, 1461-1489
`web/src/shell/MainTerminalView.tsx` 66-125, 150-210
Backport pattern from commit `90f476be3` (`findAgentTerminal`).
Tests: `web/src/hooks/useTerminals.test.ts`, MainTerminalView.test.tsx

## Image attachment
Upload OK; download ignores stored MIME (`routes_resources.py`
1341-1400 line 1382 guess_type; 1388-1396 force attachment).
`helpers.py` 626-645, 680-705.
Serve vetted rasters inline; keep attachment for HTML/SVG/unknown.
