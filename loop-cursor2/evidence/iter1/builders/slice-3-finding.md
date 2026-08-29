Hypothesis 5: `buildBubbles` with cache after a mid-array user splice
before a live preview (same live block object identity).

Result: PASS with no `renderItems.ts` change. `reusablePrefix`
reference equality (`blocks[j] !== cache.blocks[j]`) bails out of reuse
when the prefix region changes, so the splice rebuilds correctly.
