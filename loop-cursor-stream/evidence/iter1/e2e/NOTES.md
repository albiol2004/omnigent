# Cursor stream e2e notes

- Slice: `cursor-stream-e2e`; iteration: 1.
- Command:
  `uv run python loop-cursor-stream/evidence/iter1/e2e/run_e2e.py`
- Throwaway server: `127.0.0.1:17201`, scratch
  `/tmp/cursor-stream-e2e-oy655atu`.
- Conversation: `7237030ec83841f9aa19d8abb39ef7e7`.
- Real `cursor-agent` via `omnigent cursor --server … -- --force --trust`.

## Repair 1 replay check

- Rerun: port **17200**, scratch
  `/tmp/cursor-stream-e2e-kmmrisji`, conversation
  `6c1e5743e96e4b639773f8c8065e0e37`.
- First turn: **17** deltas, **4979 / 4979** joined/complete lengths,
  `byte_equal: true`.
- The complete item was observed at **60.981 s**. The following
  **10.009 s** contained **0** deltas.
- The second prompt produced **1** delta with a fresh message ID ending in
  `-1`.
- `ss -ltnp | rg ':172'` was empty after teardown.

## Initial slice numbers (GOAL Acceptance 2)

The initial slice run recorded:

- `delta_count`: **26** (≥ 5)
- `joined_len` / `complete_len`: **4901 / 4901**
- `byte_equal`: **true**
- `ttfd_s` (inject → first delta): **71.005 s**
  This is Cursor's time-to-first-token after the prompt, not
  forwarder lag. First visible assistant text is the first delta.
- inject → complete: **76.881 s**
- stream span (first delta → complete item): **5.875 s**
- mean gap during stream: **~226 ms** (26 deltas / 5.875 s)
  which is under the 1.5 s "after generation starts" bound.

Earlier failing runs: workspace-trust (`-f` insufficient; need
`--force --trust`); conversation id is `/c/<32 hex>` not `conv_*`;
pane sampling had been gated on a bound store + a `Working` line.

## Isolation

Server torn down in `run_e2e.py` `finally`. `pkill -f cursor-stream-e2e`
only matches the throwaway prefix. Live `:6767` was not stopped.
