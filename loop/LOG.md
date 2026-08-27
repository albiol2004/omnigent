- iter 0 | coordinator | mailbox initialized, investigation-only mission, baseline ead098caf
- iter 1 | lead | investigation-only: fork ~4MB replay confirmed; native live-delta skips rAF; close/SSE never kill CLI; no product diffs
- iter 1 | eval | ITERATE scope=local:loop/REPORT.md,loop/evidence/iter1/rc-render/ — cursor-native output→SSE→DOM unmeasured; user says it was slowest

- iter 1 | evaluator | ITERATE scope=local:loop/REPORT.md,loop/evidence/iter1/rc-render/ — cursor-native render path unmeasured (user reports it slowest)
- iter 1 | lead | repair: cursor-native render path measured (0–700 ms text poll; 1.203 ms capture-pane mean; generic rAF)
- iter 1 | eval | ITERATE (plain) — P1–P3 pass; P4 rc-freeze unmeasured (no evidence, no REPORT section)
- iter 1 | evaluator | ITERATE — problems 1-3 pass after repair 1 (cursor-native column verified); rc-freeze (problem 4) not yet investigated
- iter 2 | lead | rc-freeze: sqlite QueuePool 5+10 wait 30s×2 matches ~1 min; HTTP/1.1 SSE+WS can hit 6/host; no product diffs
