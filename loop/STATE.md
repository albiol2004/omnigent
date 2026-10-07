schema: 1
iteration: 1
max_iterations: 10
status: shipped
mission: Re-port the user's Omnigent fork patches onto upstream stable v0.17.0 so the trio stack can run on 0.17.0 with every fork behaviour intact.

## Approaches tried and rejected
(append-only; the Lead adds one line per dead end, with why)

## Key decisions and rationale
(append-only)
- iter 1: 58 v16 product commits ported in 5 chained slices (original -x order); v16 docs commits ported as history (DECISION in PLAN.md).
- iter 1: all suite runs use TMPDIR=/var/tmp/pytest-of-coder (AF_UNIX 108-byte limit); targeted checks may --deselect only pristine-proven upstream failures.
target_ref: trio-v0.17.0-fixes
target_base: b52507b70a057cf7414465946813c52ec9508421
phase: shipped
evaluated_sha: c813e0b825b803b70350bad650cd024c7e2b121e
evaluator_attempt: 2c376deddaf84b97845c07adb216e236
