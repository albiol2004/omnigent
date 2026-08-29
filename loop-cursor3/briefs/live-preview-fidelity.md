# Builder brief — slice live-preview-fidelity

You are Trio Luna builder (`gpt-5.6-luna-max`). Workspace:
`/home/alex/omnigent-cursor3`. Mailbox `loop-cursor3/`. Iteration 1.

Do NOT touch `web/` (slice picker-ui-truth owns it). Do NOT touch
`cursor_native_bridge.py`. Do NOT use live cursor-agent. Commit:

```
slice(live-preview-fidelity): keep the live cursor preview a prefix of the final text

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
```

No amend/rebase/push/stash/reset/checkout.
`PATH=/home/alex/omnigent/.venv/bin:$PATH`

## Writes (only)

- `omnigent/cursor_native_stream.py`
- `tests/test_cursor_native_stream.py`

## Line ranges

- `suffix_after` 92–108 — on no overlap **returns the whole viewport**,
  which concatenates pane-diff fragments into a wrong preview.
- `CursorNativeStream.observe` 135–175 — `self.emitted += delta`.
- `extract_assistant_region` 61–84 — chrome strip (keep; improve if a
  chrome leak is why fragments contradict).

## Required behavior

Preferred trade-off (do this, do not blank the preview): treat each pane
as a **snapshot** of the assistant region. After observe, `emitted` must
be a prefix of the reconstructed region, or the region a prefix of
`emitted` (scrolled viewport). Never append a fragment that is not a
suffix of that consistent reconstruction.

If the new region is a redraw (no overlap): **replace** the reconstruction
with the new region and emit only the net new suffix relative to what was
already shown if it is still a prefix; if the already-emitted text would
become a lie, rewind is not available to the UI — so emit nothing further
until the region again extends `emitted` as a prefix, **or** start a
fresh message id only when `start_new_turn` / `reset` says so. Do not
silently concatenate.

Keep existing tests green (growing suffix, scroll overlap, wrap→spaces,
tool chrome, rewind, epochs). Add a test that feeds two non-overlapping
snapshots that share no prefix (the old `return viewport` bug) and
asserts joined `emitted` never contains a concatenation that is not a
substring/prefix of the later snapshot.

`OMNIGENT_CURSOR_STREAM=0` is in the forwarder; do not break that flag.

Commands:
`cd /home/alex/omnigent-cursor3 && PYTHONPATH=/home/alex/omnigent-cursor3 uv run pytest -q tests/test_cursor_native_stream.py`
