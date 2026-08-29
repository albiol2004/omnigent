# PLAN — iteration 1

status: complete
iteration: 1
mailbox: loop-cursor3

## Objective

Make every catalogued cursor-agent model selectable by exact variant
(including GLM 5.2 vs GLM 5.2 Max), make a rejected PATCH roll the web
picker back to the live model, and stop the mid-stream preview showing
text that contradicts the finished assistant item.

## Diagnosed mechanism (verified, not assumed)

`inject_model_command` (`omnigent/cursor_native_bridge.py:797-950`) only
inspects `_picker_highlighted_row` and, on mismatch, drives the Tab
effort editor (`_picker_set_variant` :1020-1055). It never sends Up/Down
to move the filtered **model** list to a non-highlighted row.

Live 41-column throwaway pane for query `GLM 5.2` (scratch HOME):

```
  → /model GLM 5.2
 Models matching "GLM 5.2" Max mode: OFF
 → GLM 5.2                  Hig(Tab to
                            h  modify)
```

`--list-models` id `glm-5.2-high` has displayName `GLM 5.2`, but the
picker row is `GLM 5.2 High`. Strict `_picker_row_matches_display`
(`:1110`) therefore rejects the correct highlight. Pre-fix inject on
that pane raised:

`cursor model 'glm-5.2-high' did not resolve to its exact picker row`

which matches the live 503. Footer stayed `Cursor Grok 4.6 Medium`.

Catalogue suffix shapes on this machine (204 models): high, low,
medium, (none), xhigh, fast, high-fast, max, low-fast, medium-fast,
xhigh-fast, none, extra-high, extra-high-fast. `_PICKER_QUERY_VARIANT_SUFFIXES`
and `_PICKER_EFFORT_INDEX` only know low/medium/high/xhigh(+fast).

Web: `setModel` (`web/src/store/chatStore.ts:2089-2115`) writes
optimistic `selectedModel` / `sessionModelOverride` and has **no**
catch; a 503 leaves the rejected id on the picker.

Preview: `suffix_after` (`omnigent/cursor_native_stream.py:92-108`)
appends a non-overlapping viewport as new text, so pane-diff fragments
concatenate into a gappy preview until `external_conversation_item`
replaces it.

## Slices

```yaml
slices:
  - id: picker-any-model
    repo: .
    writes: [omnigent/cursor_native_bridge.py, tests/test_cursor_native_bridge.py]
    reads: []
    gate: true
    status: complete
    iteration: 1
    accepts:
      - "glm-5.2-high selects GLM 5.2 exactly (not Max); glm-5.2-max selects Max"
      - "filtered-list navigation reaches a non-highlighted exact row"
      - "variant suffixes cover the live catalogue including max/none/fast"
      - "strict exact-variant matching is not loosened; bogus ids still fail"
      - "tests use the captured 41-col GLM pane (composer → and wrapped High)"
  - id: picker-ui-truth
    repo: .
    writes: [web/src/store/chatStore.ts, web/src/store/chatStore.test.ts, web/src/pages/ChatPage.tsx, web/src/pages/ChatPage.composer.test.tsx]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts:
      - "failed model PATCH reverts picker to the previously active model"
      - "error names the attempted model"
      - "proven through store and composer/component path, not a reducer island"
  - id: live-preview-fidelity
    repo: .
    writes: [omnigent/cursor_native_stream.py, tests/test_cursor_native_stream.py]
    reads: []
    gate: false
    status: complete
    iteration: 1
    accepts:
      - "joined live preview is a prefix/subset of the final assistant text"
      - "non-overlapping pane redraws do not concatenate contradictory fragments"
      - "OMNIGENT_CURSOR_STREAM=0 still disables streaming"
```

Wave 1: `picker-any-model` ∥ `picker-ui-truth` (disjoint writes).
Wave 2: `live-preview-fidelity` after wave 1 (stream-only; no web files).

### picker-any-model — done when

- Family query that matches several rows navigates to the exact row.
- Catalog display without an effort word still matches a picker row that
  shows that effort in the right-hand column (GLM 5.2 ↔ GLM 5.2 High).
- `max` / `none` / lone `fast` / `extra-high` ladders work; grok
  low/medium/high/xhigh(+fast) still works.
- Wrapped ~41-column rows still match; viewport-scrolled lists still
  match via navigation.
- Tests include the real captured GLM pane fixture.
- Commands:
  `cd /home/alex/omnigent-cursor3 && PYTHONPATH=/home/alex/omnigent-cursor3 uv run pytest -q tests/test_cursor_native_bridge.py`

### picker-ui-truth — done when

- `setModel` rolls back on PATCH failure (mirror `setCostControlMode`).
- Composer/picker still shows the active model; error names the attempt.
- Tests go through `setModel` + ChatPage `/model` path.
- Commands:
  `cd /home/alex/omnigent-cursor3/web && npx vitest run src/store/chatStore.test.ts src/pages/ChatPage.composer.test.tsx`

### live-preview-fidelity — done when

- `CursorNativeStream.observe` never emits a delta that makes `emitted`
  contradict the current assistant region (prefer: `emitted` is always a
  prefix of the reconstructed region, or the region is a prefix of
  `emitted` after a scroll).
- Trade-off recorded in the slice commit/report: reconstruction, not a
  blank preview.
- Commands:
  `cd /home/alex/omnigent-cursor3 && PYTHONPATH=/home/alex/omnigent-cursor3 uv run pytest -q tests/test_cursor_native_stream.py`

## Verification standard

mode: test-first

Evidence required:

1. Unit tests for slice 1 driven by the real captured panes in
   `loop-cursor3/evidence/iter1/glm-before/glm-5.2-query-pane.txt`
   (composer `→` line + wrapped `Hig`/`h  modify` row).
2. Web tests for slice 2 through store + composer, including 503 rollback.
3. Stream tests that concatenate successive observes and assert the
   joined preview is a prefix/subset of a final region (include a
   non-overlapping redraw case that used to append junk).
4. Lead-run live e2e (port ≥ 18900, scratch HOME + scratch
   OMNIGENT_DATA_DIR): switch away from the current footer to GLM 5.2,
   then a within-family effort switch, then a bogus id; then one >15 s
   streaming turn with SSE vs final item.

## Out of scope

- Changing `~/.cursor` or the user's default model.
- Live server :6767, `omni host`, `/home/alex/omnigent` git.
- Typing into / killing tmux session `main` or any pre-existing pane.
- Loosening exact-variant matching to make GLM pass.
- Redesigning the picker UX beyond truthfulness on reject.
- Claude-native / Codex streaming.

## Isolation for every live cursor-agent

Scratch `HOME` with copied `~/.cursor/cli-config.json` and
`~/.config/cursor/auth.json`; `XDG_CONFIG_HOME`/`XDG_CACHE_HOME`/
`XDG_DATA_HOME` under that scratch; unset `CURSOR_AGENT` and
`CURSOR_CONVERSATION_ID`. Private tmux socket. Kill only that server.
Record sha256 of `/home/alex/.cursor/cli-config.json` before and after.
Start-of-pass hash:
`f740d3d2b5623538d9c505dcde1be3d2ac0ecea377a2be66eb373051f53babba`
