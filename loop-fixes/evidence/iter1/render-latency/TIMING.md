# Render-latency evidence

This slice uses adaptive polling instead of a single fixed quantum:

| Forwarder | Fast while output arrives | Idle backoff | Baseline quantum |
|---|---:|---:|---:|
| cursor-native | 0.150 s | 0.700 s | 0.700 s |
| claude-native | 0.100 s | 0.250 s | 0.250 s |

Compared with `loop/evidence/iter1/rc-render/TIMING.md`, the fast paths reduce
the known polling contribution from 0–700 ms to 0–150 ms for cursor and from
0–250 ms to 0–100 ms for Claude. Idle behavior keeps the previous quanta, so
quiet sessions do not increase polling load. The microbench in
`microbench.txt` measures only interval selection; no live TUI or server was
used.

Verification output is saved in `pytest.txt` and `vitest.txt`.
