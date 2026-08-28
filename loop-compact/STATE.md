schema: 1
iteration: 1
max_iterations: 4
status: ship
mission: Make an oversize fork succeed by compacting the copied history with an LLM summary — using the source session's pinned model by default — so that the forked harness receives a transcript under `OMNIGENT_FORK_MAX_CONTEXT_BYTES`, while a fork that is already small stays byte-identical to today's behavior and the 413 remains only as the last resort.
verdict: SHIP
eval: pending Lead pass; evidence loop-compact/evidence/iter1/; commits 1c2a417e3 22793b2dd; throwaway 3937371→272 bytes mock-compact-model
last_run: 2026-08-28
