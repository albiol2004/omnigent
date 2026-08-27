# TIMING — CLI output → DOM

Live UI E2E was not run. Cursor's read-only pane measurement is saved in
`capture-pane-benchmark.txt`; all other values are source-derived or explicitly
unmeasured. The detailed cursor trace is in `CURSOR-NATIVE.md`.

| Stage | claude-native | claude-sdk | cursor-native |
|---|---|---|---|
| Hook | shell hook per chunk, unmeasured | N/A per delta | N/A for text; stop hook once/turn |
| Poll | **0–250 ms** | N/A | **0–700 ms** store; 0–200 ms tmux status only |
| Per-delta POST | 1 sequential POST/delta | N/A | 0/token; **1 POST/item**, RTT unmeasured |
| session_stream | local queue, 1024 overflow reconnect | same after runner relay | local queue; no fixed wait |
| SSE | one hop, per-event validation | runner SSE + server SSE | one hop, per-event validation |
| Store | **sync live delta per chunk** | rAF + 30-char coalesce | generic rAF; first content flushes sync |
| React | active bubble work per delta | ≤1 commit/frame after first token | ≤1 frame for later blocks; commit unmeasured |
| Markdown | 100 ms growing-text throttle | same | 0 ms initial complete item; 100 ms only if growing |
| Sidebar WS | 4 s, **not** token path | same | same, not token path |

Known cursor scheduling subtotal: **0–700 ms** to the first complete text item,
or **0–716.7 ms** for a later block at 60 Hz. This excludes unmeasured Cursor
store-write, HTTP/DB/SSE, and React commit time. The 200 ms tmux status quantum
and 300 ms permission poll are not text-path additions.

The cursor-native top known cause is the **700 ms transcript poll combined with
complete-item-only mirroring**. Claude-native still has the distinct
no-rAF live-delta path; SDK uses the generic rAF path. The prior Python analog
is in `scratch/microbench.txt` (poll quantum 250 ms; copy 0.417 ms).
