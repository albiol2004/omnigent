# Probe decision

## Run

- Workspace: `/tmp/omnigent-cursor-stream-probe-1787919978-1841716`.
- T0: `2026-08-28T12:28:15.523+00:00`.
- Luna model id: `gpt-5.6-luna`.
- Pane model label: `GPT-5.6 Luna 272K Max`.
- Store:
  `/home/alex/.cursor/chats/a09d3066e00e78d72374f5fe8c6d9a1f/f0d89441-3224-42da-bd26-eb79fe2c6763/store.db`.
- Samples: 231 store and 231 pane samples.
- Cadence: 230 intervals; minimum 98.698 ms, median 100.001 ms,
  mean 99.994 ms, maximum 100.046 ms.
- Sampling window: 1.361 ms through 23000.054 ms after T0.

## Timings

- Time to first partial store: **not observed**.
- First assistant store observation: 21700.056 ms after T0, as rowid 11
  with a 21631-byte JSON blob and 6434 content-text characters. It was
  already a complete-looking assistant item on first observation.
- Time to first pane frame/text growth: 100.059 ms after T0. This was the
  submitted prompt plus the `Working` indicator, not assistant text.
- Time to first assistant-region growth: **16300.059 ms** after T0.
  Sample 162 had no assistant marker; sample 163 showed
  `🤖 A mechanical clock is`.
- The visible assistant region expanded from 25 characters at sample 163
  to 579 characters at sample 165 (16500.054 ms), while the store still
  reported rowid 4, a 222-byte newest blob, and no assistant role.

## Store behavior

- **Blobs did not grow incrementally before completion: no.**
- The assistant blob had zero sampled shorter lengths, zero same-row
  length-increase transitions, and one observed assistant-row appearance.
- Before the assistant appeared, the newest sampled row stayed at rowid 4
  and 222 bytes from 400.075 ms through 21600.082 ms.
- At 21700.056 ms, the newest row changed directly to rowid 11,
  21631 bytes, and 6434 content characters.
- At 21800.053 ms, a later metadata row became newest (rowid 13,
  567 bytes); rowid 11 remained 21631 bytes in the final read-only check.
- Row behavior is therefore **complete-only** for the assistant item:
  it appeared late as a new row at its full observed length, rather than
  appearing early and growing in place.

## Pane behavior

- **Yes, the assistant region grew before store completion.**
- Assistant text first appeared at 16300.059 ms and visibly expanded by
  16500.054 ms.
- The store had no assistant blob until 21700.056 ms, so the pane led the
  first assistant-store observation by 5399.997 ms.
- The pane continued showing the assistant response while the store still
  reported rowid 4. Later pane frames scrolled through the response while
  the `Working` indicator remained visible.

## Choice

**CHOICE: `pane-diff`**

The goal prefers `store.db` when partial assistant blobs exist, but this run
observed no partial assistant blobs. The pane was the only observed source
with assistant text during generation: it showed text at 16.300 seconds,
more text at 16.500 seconds, and continued changing before the complete
assistant row appeared at 21.700 seconds. A future implementation should
therefore use pane diffs for this observed Cursor version, with care for
viewport scrolling and ANSI removal.

## Limits and concerns

- A 100 ms sample cadence could miss a transient store write that exists
  for less than one interval. The conclusion is no partial blob observed
  or persisted across these samples, not proof that no sub-100 ms write can
  ever occur.
- Pane frame length also includes headers, prompt text, status, and spinner
  changes. The assistant-region timings above use the visible `🤖` marker
  and adjacent pane snapshots, not total frame length alone.
